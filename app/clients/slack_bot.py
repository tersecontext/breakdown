# app/clients/slack_bot.py
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import AsyncSessionLocal
from app.engine.notifier import post_error, post_research_result
from app.engine.queue import publish_approved_task
from app.engine.researcher import research
from app.models import Task, TaskLog, User
from app.routes.repos import _find_repos

logger = logging.getLogger(__name__)


class SlackBot:
    """Wraps a slack_bolt AsyncApp with message and action handlers."""

    def __init__(self, app_state, channel_id: str):
        from slack_bolt.async_app import AsyncApp
        from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler

        self.app_state = app_state
        self._channel_id = channel_id
        self._pending_messages: dict[str, str] = {}  # f"{channel}:{ts}" -> description
        self._handler_task: asyncio.Task | None = None

        self.bolt_app = AsyncApp(token=settings.slack_bot_token)
        self._handler = AsyncSocketModeHandler(self.bolt_app, settings.slack_app_token)
        self._register_handlers()

    def _register_handlers(self) -> None:
        @self.bolt_app.event("message")
        async def on_message(body, say, client):
            event = body.get("event", {})
            await self._handle_message(event, say)

        @self.bolt_app.action("select_repo")
        async def on_repo_select(ack, body, client):
            await self._handle_repo_select(ack, body, client)

        @self.bolt_app.action("approve_task")
        async def on_approve(ack, body, client):
            await self._handle_approve(ack, body, client)

        @self.bolt_app.action("reject_task")
        async def on_reject(ack, body, client):
            await self._handle_reject(ack, body, client)

    async def start(self) -> None:
        t = asyncio.create_task(self._handler.start_async())
        self.app_state.background_tasks.add(t)
        t.add_done_callback(self.app_state.background_tasks.discard)
        self._handler_task = t

    async def stop(self) -> None:
        await self._handler.close_async()

    # ── handlers ──────────────────────────────────────────────────────────

    async def _handle_message(self, message: dict, say) -> None:
        # Ignore bot messages and messages outside the configured channel
        if message.get("bot_id") or message.get("subtype") == "bot_message":
            return
        if message.get("channel") != self._channel_id:
            return

        text = message.get("text", "")
        ts = message.get("ts", "")
        channel = message.get("channel", "")

        # Cache message so action handler can retrieve the description
        self._pending_messages[f"{channel}:{ts}"] = text

        repos = _find_repos()
        if not repos:
            await say(text="No repos configured.", thread_ts=ts)
            return

        buttons = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": repo["name"]},
                "action_id": "select_repo",
                "value": json.dumps({"repo": repo["name"], "ts": ts}),
            }
            for repo in repos
        ]

        await say(
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Which repo is this for?"},
                },
                {"type": "actions", "elements": buttons},
            ],
            thread_ts=ts,
        )

    async def _resolve_username(self, client, slack_user_id: str) -> str:
        try:
            resp = await client.users_info(user=slack_user_id)
            profile = resp["user"]["profile"]
            return profile.get("display_name") or profile.get("real_name") or slack_user_id
        except Exception:
            logger.exception("Failed to resolve Slack username for %s", slack_user_id)
            return slack_user_id

    async def _get_or_create_user(self, session, username: str) -> User:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(username=username, role="member")
            session.add(user)
            await session.flush()  # populate user.id without committing
        return user

    async def _handle_repo_select(self, ack, body: dict, client) -> None:
        await ack()

        slack_user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]
        action = body["actions"][0]
        value = json.loads(action["value"])
        repo = value["repo"]
        original_ts = value["ts"]

        description = self._pending_messages.get(f"{channel_id}:{original_ts}", "")
        feature_name = description.split("\n")[0][:200] if description else "Untitled"

        username = await self._resolve_username(client, slack_user_id)

        async with AsyncSessionLocal() as session:
            user = await self._get_or_create_user(session, username)

            task = Task(
                feature_name=feature_name,
                description=description,
                repo=repo,
                submitter_id=user.id,
                state="submitted",
                source_channel="slack",
                slack_channel_id=channel_id,
                slack_thread_ts=original_ts,
            )
            session.add(task)
            session.add(TaskLog(task_id=task.id, event="task_created", actor_id=user.id))
            await session.commit()

        bolt_client = client

        async def notify(finished_task):
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Task)
                    .where(Task.id == finished_task.id)
                    .options(selectinload(Task.submitter))
                )
                fresh = result.scalar_one_or_none()
                if fresh is None:
                    return
                is_admin = fresh.submitter.role == "admin"
                if fresh.state == "researched":
                    await post_research_result(fresh, bolt_client, is_admin)
                else:
                    await post_error(fresh, bolt_client)

        t = asyncio.create_task(
            research(
                task.id,
                self.app_state.tc_client,
                self.app_state.llm_client,
                notify=notify,
            )
        )
        self.app_state.background_tasks.add(t)
        t.add_done_callback(self.app_state.background_tasks.discard)

        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=original_ts,
            text=f"Researching *{feature_name}* in `{repo}`...",
        )

    async def _handle_approve(self, ack, body: dict, client) -> None:
        await ack()

        slack_user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]
        task_id_str = body["actions"][0]["value"]

        username = await self._resolve_username(client, slack_user_id)

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()

            if user is None or user.role != "admin":
                await client.chat_postEphemeral(
                    channel=channel_id,
                    user=slack_user_id,
                    text="Only admins can approve tasks.",
                )
                return

            result = await session.execute(
                select(Task)
                .where(Task.id == uuid.UUID(task_id_str))
                .options(selectinload(Task.submitter), selectinload(Task.logs))
            )
            task = result.scalar_one_or_none()
            if task is None or task.state != "researched":
                await client.chat_postEphemeral(
                    channel=channel_id,
                    user=slack_user_id,
                    text="Task not found or not in 'researched' state.",
                )
                return

            task.state = "approved"
            task.approved_by_id = user.id
            task.approved_at = datetime.now(timezone.utc)
            session.add(TaskLog(task_id=task.id, event="task_approved", actor_id=user.id))

            try:
                await publish_approved_task(task, user, self.app_state.redis)
            except Exception:
                logger.exception("Redis publish failed for task %s", task_id_str)
                await client.chat_postEphemeral(
                    channel=channel_id,
                    user=slack_user_id,
                    text="Failed to publish task to queue.",
                )
                return

            session.add(TaskLog(task_id=task.id, event="task_queued", actor_id=user.id))
            await session.commit()
            thread_ts = task.slack_thread_ts or body.get("message", {}).get("ts")

        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Approved by {username}",
        )

    async def _handle_reject(self, ack, body: dict, client) -> None:
        await ack()

        slack_user_id = body["user"]["id"]
        channel_id = body["channel"]["id"]
        task_id_str = body["actions"][0]["value"]

        username = await self._resolve_username(client, slack_user_id)

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()

            if user is None or user.role != "admin":
                await client.chat_postEphemeral(
                    channel=channel_id,
                    user=slack_user_id,
                    text="Only admins can reject tasks.",
                )
                return

            result = await session.execute(
                select(Task).where(Task.id == uuid.UUID(task_id_str))
            )
            task = result.scalar_one_or_none()
            if task is None or task.state != "researched":
                await client.chat_postEphemeral(
                    channel=channel_id,
                    user=slack_user_id,
                    text="Task not found or not in 'researched' state.",
                )
                return

            task.state = "rejected"
            session.add(TaskLog(task_id=task.id, event="task_rejected", actor_id=user.id))
            await session.commit()
            thread_ts = task.slack_thread_ts or body.get("message", {}).get("ts")

        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Rejected by {username}",
        )
