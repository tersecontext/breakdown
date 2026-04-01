# app/engine/notifier.py
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _build_research_blocks(task, is_admin: bool) -> list[dict[str, Any]]:
    research = task.research or {}
    affected = research.get("affected_code", [])
    complexity = research.get("complexity", {})
    metrics = research.get("metrics", {})

    affected_text = "\n".join(
        f"• `{f['file']}` ({f['change_type']})" for f in affected
    ) or "None"

    risk_areas = metrics.get("risk_areas") or []
    risk_text = ", ".join(risk_areas) if risk_areas else "None"

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Research complete: {task.feature_name}*\n"
                    f"{research.get('summary', '')}"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Affected Files:*\n{affected_text}"},
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"*Complexity:* {complexity.get('score')}/10"
                        f" ({complexity.get('label')})"
                    ),
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Estimated Effort:* {complexity.get('estimated_effort')}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Files Affected:* {metrics.get('files_affected')}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Risk Areas:* {risk_text}",
                },
            ],
        },
    ]

    task_id_str = str(task.id)

    if is_admin:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": "approve_task",
                    "value": task_id_str,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "style": "danger",
                    "action_id": "reject_task",
                    "value": task_id_str,
                },
            ],
        })
    else:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "_Waiting for admin approval_",
            },
        })

    return blocks


async def post_research_result(task, client, is_admin: bool) -> None:
    """Post research summary to the task's Slack thread."""
    if task.source_channel != "slack" or not task.slack_channel_id or not task.slack_thread_ts:
        return
    blocks = _build_research_blocks(task, is_admin)
    try:
        await client.chat_postMessage(
            channel=task.slack_channel_id,
            thread_ts=task.slack_thread_ts,
            blocks=blocks,
            text=f"Research complete: {task.feature_name}",
        )
    except Exception:
        logger.exception("Failed to post research result for task %s", task.id)


async def post_error(task, client) -> None:
    """Post research failure message to the task's Slack thread."""
    if task.source_channel != "slack" or not task.slack_channel_id or not task.slack_thread_ts:
        return
    try:
        await client.chat_postMessage(
            channel=task.slack_channel_id,
            thread_ts=task.slack_thread_ts,
            text=f":x: Research failed for *{task.feature_name}*: {task.error_message or 'unknown error'}",
        )
    except Exception:
        logger.exception("Failed to post error for task %s", task.id)
