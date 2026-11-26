"""Private review submissions from composition, never automatic scoring authority."""
from typing import Literal, Protocol
from pathlib import Path

from pydantic import Field, model_validator

from core.capture import CaptureContract
from core.dataset import Digest
from core.fusion import FusedCandidate, FusionEvidence


class ReviewClip(CaptureContract):
    status: Literal["ready", "missing", "pending", "failed"]
    kind: Literal["generated_pattern"] = "generated_pattern"
    media_id: Literal["dummy-review-pattern-v1"] | None = None
    sha256: Digest | None = None
    bytes: int | None = Field(default=None, ge=1, le=4*1024*1024)
    detail: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def available(self):
        if self.status == "ready" and any(v is None for v in (self.media_id, self.sha256, self.bytes)):
            raise ValueError("Ready clip needs registered identity, checksum and size")
        return self


class ReviewSubmission(CaptureContract):
    candidate: FusedCandidate
    evidence: list[FusionEvidence] = Field(min_length=1, max_length=16)
    clips: list[ReviewClip] = Field(max_length=2)
    review_seconds: float = Field(default=15, gt=0, le=300)
    origin: Literal["dummy_fusion"] = "dummy_fusion"

    @model_validator(mode="after")
    def provenance(self):
        c = self.candidate
        if {e.observation.event_id for e in self.evidence} != set(c.evidence_ids) or len(c.evidence_ids)!=len(self.evidence):
            raise ValueError("Candidate/evidence identity mismatch")
        if any((e.session_id,e.match_id,e.play_epoch,e.observation.goal_end)!=(c.session_id,c.match_id,c.play_epoch,c.goal_end)
               or e.observation.evidence!="synthetic" for e in self.evidence):
            raise ValueError("Dummy review identity/provenance mismatch")
        return self


class ReviewService(Protocol):
    def prepare(self, match_id, command, snapshot) -> ReviewSubmission: ...
    def clip_file(self, candidate: dict) -> Path: ...


class DisplayService(Protocol):
    def open(self) -> str: ...
    def sent(self, connection_id: str, snapshot: dict | None) -> None: ...
    def acknowledge(self, connection_id: str, message: dict) -> None: ...
    def close(self, connection_id: str) -> None: ...
    def status(self) -> dict: ...
