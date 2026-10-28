from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(str, Enum):
    SAFE = "safe"
    CAUTION = "caution"
    DESTRUCTIVE = "destructive"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    reasons: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        return self.level is RiskLevel.BLOCKED


@dataclass
class ExecutionResult:
    output: str
    exit_code: int
    timed_out: bool = False
    blocked: bool = False


@dataclass
class PlanStep:
    id: str
    command: str
    purpose: str
    expected_result: str
    file_effects: list[str] = field(default_factory=list)
    reversible: bool = False


@dataclass
class CommandPlan:
    goal: str
    steps: list[PlanStep]


@dataclass(frozen=True)
class VerificationResult:
    success: bool
    summary: str
    action: str = "continue"


@dataclass(frozen=True)
class FileChange:
    path: str
    kind: str
    diff: str = ""


@dataclass
class SessionTurn:
    user_query: str
    commands: list[str]
    output: str
    exit_code: int
    cwd: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
