import pytest

from core.fusion import FusionCamera, FusionCommand, FusionEvidence, FusionSettings
from core.sensors import SensorImpact
from core.vision import VisionCandidate
from modules.goal_engine.engine import GoalEngine


def settings():
    return FusionSettings(cameras={f"camera-{end}": FusionCamera(goal_end=end, calibration_version="cal-v1",
        model_version="injected-v1", configuration_version="vision-v1") for end in ("goal_a", "goal_b")},
        devices={1:"goal_a", 2:"goal_b"})


def engine():
    return GoalEngine(settings(), session_id="session", match_id="match", clock_domain="host")


def command(e, action, now=0, candidate=None, **overrides):
    return e.command(FusionCommand(command_id=f"cmd-{e.revision}-{action}", match_id=e.match_id,
        expected_revision=e.revision, action=action, candidate_id=candidate, actor="operator", **overrides), now)


def vision(event="v1", t=1, end="goal_a", quality="observed_crossing", track="ball1", **changes):
    values = dict(event_id=event, session_id="session", match_id="match", camera_id=f"camera-{end}",
        goal_end=end, track_id=track, occurred_seconds=t, emitted_seconds=t+.02, timing_uncertainty_seconds=.002,
        calibration_version="cal-v1", model_version="injected-v1", configuration_version="vision-v1",
        quality=quality, evidence="synthetic", reasons=["injected geometry"], flags=[],
        supporting_sequences=[1,2], crossing_interval_seconds=(t-.005,t+.005))
    values.update(changes)
    return VisionCandidate(**values)


def sensor(event="s1", t=1.01, end="goal_a", classification="net_impact", **changes):
    values = dict(event_id=event, goal_end=end, device_id=1 if end=="goal_a" else 2, boot_id=1,
        occurred_device_seconds=t, occurred_seconds=t, emitted_seconds=t+.12, timing_uncertainty_seconds=.003,
        host_clock_domain="host", evidence="synthetic", classification=classification,
        features={"net_peak_g":2.}, flags=[], configuration_version="impact-rules-v1")
    values.update(changes)
    return SensorImpact(**values)


def ingest(e, observation, now=None, **envelope):
    values = dict(session_id=e.session_id, match_id=e.match_id, clock_domain=e.clock_domain,
        play_epoch=e.play_epoch, observation=observation)
    values.update(envelope)
    return e.ingest(FusionEvidence(**values), observation.emitted_seconds if now is None else now)


@pytest.fixture
def live():
    e = engine()
    command(e,"start")
    return e
