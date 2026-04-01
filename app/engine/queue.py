from app.clients.redis import RedisQueue
from app.models import Task, User


async def publish_approved_task(task: Task, user: User, redis: RedisQueue) -> None:
    bundle = {
        "task_id": str(task.id),
        "feature_name": task.feature_name,
        "description": task.description,
        "repo": task.repo,
        "branch_from": task.branch_from,
        "submitter": task.submitter.username,
        "approved_by": user.username,
        "approved_at": task.approved_at.isoformat(),
        "tc_context": task.tc_context or "",
        "research": task.research,
        "additional_context": task.additional_context,
        "optional_answers": task.optional_answers,
    }
    await redis.push_approved(bundle)
