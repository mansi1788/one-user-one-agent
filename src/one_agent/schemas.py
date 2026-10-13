from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Literal

IST = timezone(timedelta(hours=5, minutes=30))

def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timezone required")
    return result.astimezone(timezone.utc)

@dataclass(frozen=True)
class Fact:
    name: str
    value: Any
    status: Literal["known", "unknown"]
    sources: tuple[str, ...] = ()
    observed_at: str | None = None
    reason: str = ""
    conflicts: tuple[dict, ...] = ()

    def to_dict(self):
        return asdict(self)

@dataclass(frozen=True)
class Eligibility:
    goal_id: str
    status: Literal["eligible", "ineligible", "unknown"]
    reason: str
    evidence: tuple[str, ...] = ()
    disabled: bool = False
    context: dict = field(default_factory=dict)
