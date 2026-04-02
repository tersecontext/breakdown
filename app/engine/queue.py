import re

from app.clients.redis import RedisQueue
from app.models import Task, User

_REGISTRY_LINE = re.compile(
    r"^(?:fn|cls|file):\d+\s+.*?\[([^\]]+)\]",
    re.MULTILINE,
)


def parse_tc_file_paths(tc_context: str) -> list[str]:
    """Extract unique file paths from TerseContext Layer 3 registry lines.

    Registry lines look like:
        fn:1  authenticate(user: str, pwd: str) -> bool  [auth/service.py:34]

    Returns de-duplicated file paths (without line numbers), preserving order.
    """
    seen: set[str] = set()
    paths: list[str] = []
    for match in _REGISTRY_LINE.finditer(tc_context):
        raw = match.group(1).strip()
        # Strip trailing :line_number
        path = raw.rsplit(":", 1)[0] if ":" in raw else raw
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


async def publish_approved_task(task: Task, user: User, redis: RedisQueue) -> None:
    tc_context = task.tc_context or ""
    file_paths = parse_tc_file_paths(tc_context)

    bundle = {
        "task_id": str(task.id),
        "feature_name": task.feature_name,
        "description": task.description,
        "repo": task.repo,
        "branch_from": task.branch_from,
        "submitter": task.submitter.username,
        "approved_by": user.username,
        "approved_at": task.approved_at.isoformat(),
        "tc_context": tc_context,
        "research": task.research,
        "additional_context": task.additional_context,
        "optional_answers": task.optional_answers,
        "file_paths": file_paths,
    }
    await redis.push_approved(bundle)
