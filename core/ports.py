from typing import Any, Protocol, TYPE_CHECKING

from core.schemas import Command
if TYPE_CHECKING:
    from core.review import ReviewSubmission
    from core.attribution import AttributionSubmission
    from core.analytics import AnalyticsSubmission


class DomainError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.message = message
        self.status = status


class ScoreStore(Protocol):
    def execute(self, match_id: str | None, command: Command, actor: str, *, prepared_review: "ReviewSubmission | None" = None,
                prepared_attribution: "AttributionSubmission | None" = None,
                prepared_analytics: "AnalyticsSubmission | None" = None) -> dict[str, Any]: ...

    def current(self) -> dict[str, Any] | None: ...

    def snapshot(self, match_id: str) -> dict[str, Any]: ...

    def export(self, match_id: str) -> dict[str, Any]: ...

    def integrity(self) -> dict[str, Any]: ...

    def close(self) -> None: ...
