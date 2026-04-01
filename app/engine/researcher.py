import json
import logging
from uuid import UUID

from sqlalchemy import select

from app.clients.anthropic import AnthropicClient
from app.clients.tersecontext import TerseContextClient
from app.db import AsyncSessionLocal
from app.engine.query_builder import build_query
from app.models import Task, TaskLog
from app.schemas import ResearchOutput

logger = logging.getLogger(__name__)

RESEARCH_SYSTEM_PROMPT = """You are analyzing a feature request against a codebase. You have been given the feature description, optional context from the requester, and relevant code context retrieved from the codebase.

Produce a JSON object with:

- "summary": 2-3 sentence plain English overview of what this feature involves and how it relates to the existing code

- "affected_code": array of objects, each with:
  - "file": file path
  - "change_type": "create" | "modify" | "delete"
  - "description": what changes in this file and why

- "complexity": object with:
  - "score": integer 1-10
  - "label": "low" (1-3), "medium" (4-6), or "high" (7-10)
  - "estimated_effort": human-readable estimate (e.g. "2-4 hours", "1-2 days")
  - "reasoning": why this complexity rating

- "metrics": object with:
  - "files_affected": total count
  - "files_created": count of new files
  - "files_modified": count of modified files
  - "services_affected": count of distinct services touched
  - "contract_changes": boolean
  - "new_dependencies": array of new packages/libraries needed
  - "risk_areas": array of strings describing potential risks

Respond with ONLY the JSON object, no other text."""


async def research(
    task_id: UUID,
    tc_client: TerseContextClient,
    llm_client: AnthropicClient,
) -> None:
    async with AsyncSessionLocal() as session:
        task = None
        error_message = None
        try:
            result = await session.execute(select(Task).where(Task.id == task_id))
            task = result.scalar_one_or_none()
            if task is None:
                logger.error("research: task %s not found", task_id)
                return

            task.state = "researching"
            session.add(TaskLog(task_id=task.id, event="research_started"))
            await session.commit()

            query_text = build_query(task)
            tc_context = await tc_client.query(query_text, repo=task.repo)
            task.tc_context = tc_context
            await session.commit()

            optional_parts = []
            for k, v in (task.optional_answers or {}).items():
                if v and isinstance(v, str):
                    optional_parts.append(f"{k}: {v}")

            context_parts = [f"Context: {c}" for c in (task.additional_context or [])]

            user_message = "\n".join(filter(None, [
                f"Feature: {task.feature_name}",
                f"Description: {task.description}",
                "\n".join(optional_parts),
                "\n".join(context_parts),
                "",
                "Code context:",
                tc_context,
            ]))

            response = await llm_client.chat(
                system=RESEARCH_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )

            try:
                parsed = json.loads(response.content)
            except json.JSONDecodeError:
                response = await llm_client.chat(
                    system=RESEARCH_SYSTEM_PROMPT,
                    messages=[
                        {"role": "user", "content": user_message},
                        {"role": "assistant", "content": response.content},
                        {"role": "user", "content": "Your previous response was not valid JSON. Respond with only the JSON object, no other text."},
                    ],
                )
                parsed = json.loads(response.content)

            ResearchOutput(**parsed)  # validate structure; raises ValidationError if invalid

            task.research = parsed
            task.state = "researched"
            session.add(TaskLog(task_id=task.id, event="research_completed"))
            await session.commit()

        except Exception as e:
            error_message = str(e)
            logger.exception("research failed for task %s", task_id)
            if task is not None:
                task.state = "failed"
                task.error_message = error_message
                session.add(TaskLog(
                    task_id=task.id,
                    event="research_failed",
                    detail={"error": error_message},
                ))
                try:
                    await session.commit()
                except Exception:
                    logger.exception("failed to commit error state for task %s", task_id)
                    await session.rollback()
