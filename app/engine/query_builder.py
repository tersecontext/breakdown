from app.models import Task

_OPTIONAL_KEYS = [
    ("scope_notes", "Scope"),
    ("architecture_notes", "Architecture"),
    ("constraints", "Constraints"),
    ("testing_notes", "Testing"),
]

MAX_QUERY_LENGTH = 500


def build_query(task: Task) -> str:
    parts = [task.description]
    for key, label in _OPTIONAL_KEYS:
        value = task.optional_answers.get(key, "")
        if value and isinstance(value, str):
            parts.append(f"\n{label}: {value}")
    return "".join(parts)[:MAX_QUERY_LENGTH]
