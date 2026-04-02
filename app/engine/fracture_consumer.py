"""fracture_consumer.py — Consumes stream:fracture-results and updates task state."""
import asyncio
import logging
from uuid import UUID

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.engine.notifier import post_error
from app.models import Task, TaskLog

logger = logging.getLogger(__name__)


async def consume_fracture_results(app_state) -> None:
    """Long-running loop. Reads stream:fracture-results and updates task state.

    Spawned as an asyncio.Task in lifespan. Exits cleanly on CancelledError.
    """
    logger.info("Fracture results consumer started")
    while True:
        try:
            async for msg_id, fields in app_state.redis.read_fracture_results():
                await _handle_message(msg_id, fields, app_state)
        except asyncio.CancelledError:
            logger.info("Fracture results consumer cancelled")
            raise
        except Exception:
            logger.exception("Unexpected error in fracture results consumer")
            raise


async def _handle_message(msg_id, fields: dict, app_state) -> None:
    """Process one message from stream:fracture-results.

    Always acks (in finally) to prevent poison-pill loops.
    """
    task_id_str = fields.get("task_id", "")
    status = fields.get("status", "")

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Task).where(Task.id == UUID(task_id_str))
            )
            task = await result.scalar_one_or_none()

            if task is None:
                logger.warning(
                    "fracture_consumer: task %s not found — skipping", task_id_str
                )
                return

            if status == "ok":
                task.state = "decomposed"
                session.add(TaskLog(task_id=task.id, event="decomposed"))
                await session.commit()

            elif status == "error":
                error_text = fields.get("error", "unknown error")
                task.state = "failed"
                task.error_message = error_text
                session.add(TaskLog(
                    task_id=task.id,
                    event="fracture_failed",
                    detail={"error": error_text},
                ))
                await session.commit()
                if app_state.slack_web_client is not None:
                    try:
                        await post_error(task, app_state.slack_web_client)
                    except Exception:
                        logger.exception(
                            "fracture_consumer: post_error failed for task %s", task_id_str
                        )

            else:
                logger.warning(
                    "fracture_consumer: unknown status %r for task %s", status, task_id_str
                )

    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "fracture_consumer: error handling message for task %s", task_id_str
        )
    finally:
        await app_state.redis.ack_fracture_result(msg_id)
