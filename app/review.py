"""Compose controlled dummy evidence with the Part 06 engine and durable review writer."""
import hashlib
from pathlib import Path

from core.fusion import FusedCandidate, FusionCamera, FusionCommand, FusionEvidence, FusionSettings
from core.ports import DomainError
from core.review import ReviewClip, ReviewSubmission
from core.schemas import DemoIncident
from core.sensors import SensorImpact
from core.vision import VisionCandidate
from modules.goal_engine.engine import GoalEngine


MEDIA=Path(__file__).parent/"fixtures/review-pattern.mp4"


class DummyReview:
    def __init__(self, enabled=True, media_path=MEDIA):
        self.enabled, self.media_path = enabled, Path(media_path)

    def prepare(self, match_id, command, snapshot):
        if not self.enabled:
            raise DomainError("Dummy review is disabled in server configuration",422)
        requested=DemoIncident.model_validate(command.payload)
        end=requested.goal_end
        sid="demo:"+hashlib.sha256(f"{match_id}:{command.command_id}".encode()).hexdigest()[:24]
        domain="dummy-virtual-clock"
        settings=FusionSettings(cameras={"dummy-camera":FusionCamera(goal_end=end,calibration_version="dummy-cal-v1",
            model_version="injected-no-detector-v1",configuration_version="dummy-vision-v1")},devices={1:end})
        engine=GoalEngine(settings,session_id=sid,match_id=match_id,clock_domain=domain,
            goal_a_defending=snapshot["goal_mapping"]["goal_a"])
        engine.command(FusionCommand(command_id="dummy-start",match_id=match_id,expected_revision=0,action="start",actor="dummy"),0)
        quality={"partial":"boundary_uncertain","net_contact":"net_motion_only"}.get(requested.scenario,"observed_crossing")
        visual=VisionCandidate(event_id=f"{sid}:vision",session_id=sid,match_id=match_id,camera_id="dummy-camera",
            goal_end=end,track_id="dummy-ball",occurred_seconds=1,emitted_seconds=1.02,timing_uncertainty_seconds=.002,
            calibration_version="dummy-cal-v1",model_version="injected-no-detector-v1",configuration_version="dummy-vision-v1",
            quality=quality,evidence="synthetic",reasons=["Explicitly generated numerical evidence; no camera detection"],flags=[],
            supporting_sequences=[1,2],crossing_interval_seconds=(.995,1.005))
        sensor=SensorImpact(event_id=f"{sid}:sensor",goal_end=end,device_id=1,boot_id=1,occurred_device_seconds=1.01,
            occurred_seconds=1.01,emitted_seconds=1.13,timing_uncertainty_seconds=.003,host_clock_domain=domain,
            evidence="synthetic",classification="slow_impact" if requested.scenario=="net_contact" else "mixed_impact",
            features={"net_peak_g":2.,"frame_peak_g":1.2},flags=[],configuration_version="impact-rules-v1")
        evidence=[FusionEvidence(session_id=sid,match_id=match_id,clock_domain=domain,play_epoch=1,observation=o) for o in (visual,sensor)]
        for record in evidence:
            engine.ingest(record,record.observation.emitted_seconds)
        engine.advance(1.4,snapshot=False)
        candidate=FusedCandidate.model_validate(engine.snapshot()["candidates"][0])
        # The virtual engine's epoch is retained in source provenance. Official epoch is stored separately.
        clip_status={"missing_clip":"missing","pending_clip":"pending","failed_clip":"failed"}.get(requested.scenario,"ready")
        details={"missing":"No clip was supplied for this dummy incident.","pending":"Simulated clip still encoding; scoring remains available.",
                 "failed":"Simulated encoding failure; scoring remains available."}
        if clip_status=="ready":
            try:
                raw=self.media_path.read_bytes()
                if not 0<len(raw)<=4*1024*1024:
                    raise ValueError("Clip fixture capacity")
            except (OSError,ValueError):
                clip=ReviewClip(status="failed",detail="Generated clip fixture is unavailable.")
            else:
                clip=ReviewClip(status="ready",media_id="dummy-review-pattern-v1",sha256=hashlib.sha256(raw).hexdigest(),
                    bytes=len(raw),detail="Generated test pattern; it does not show the numerical incident or a real goal.")
        else:
            clip=ReviewClip(status=clip_status,detail=details[clip_status])
        return ReviewSubmission(candidate=candidate,evidence=evidence,clips=[clip])

    def clip_file(self,candidate):
        review=candidate.get("review")
        if not review or not review["clips"] or review["clips"][0]["status"]!="ready":
            raise DomainError("This incident has no ready clip",404)
        clip=ReviewClip.model_validate(review["clips"][0])
        try:
            raw=self.media_path.read_bytes()
        except OSError as exc:
            raise DomainError("Clip file unavailable",410) from exc
        if len(raw)!=clip.bytes or hashlib.sha256(raw).hexdigest()!=clip.sha256:
            raise DomainError("Clip checksum changed; review media is unavailable",410)
        return self.media_path
