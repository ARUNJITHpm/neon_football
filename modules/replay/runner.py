"""Replay timestamped observations/decisions with stable ordering and virtual time."""
import hashlib
import json
from pathlib import Path

from core.clock import VirtualClock
from core.dataset import DatasetManifest, ReplayOutput
from .dataset import digest, read_events, select


def replay(manifest_path, *, media_root=None, split="validation", allow_blind_test=False, max_events=250000):
    if not 1 <= max_events <= 2000000:
        raise ValueError("Replay event limit must be between 1 and 2000000")
    manifest_path = Path(manifest_path)
    manifest = DatasetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    sessions = select(manifest, split, allow_blind_test)
    root = Path(media_root) if media_root is not None else manifest_path.parent
    clock, decisions, trace = VirtualClock(), [], []
    fingerprints = []
    # Session clocks are local. Replay sessions sequentially in stable identity order.
    for session in sessions:
        events = sorted(read_events(session, root, max_events-len(trace)), key=lambda e: (e.delivered_seconds, e.sequence, e.event_id))
        fingerprint = [(a.path, a.sha256) for a in sorted(session.assets, key=lambda a: a.path)]
        fingerprints.append([session.session_id, fingerprint])
        offset = clock.monotonic()
        for event in events:
            target = offset + event.delivered_seconds
            clock.advance(target - clock.monotonic())
            trace.append(dict(session_id=session.session_id, event_id=event.event_id, sequence=event.sequence,
                              virtual_seconds=clock.monotonic(), occurred_seconds=event.occurred_seconds,
                              delivered_seconds=event.delivered_seconds, kind=event.kind))
            if event.kind == "decision":
                decisions.append(event)
        clock.advance(offset + session.duration_seconds - clock.monotonic())
    return ReplayOutput(dataset_id=manifest.dataset_id, event_limit=max_events, split=split, manifest_sha256=digest(manifest_path),
                        input_fingerprint=hashlib.sha256(json.dumps(fingerprints, separators=(",", ":")).encode()).hexdigest(),
                        sessions=[s.session_id for s in sessions],
                        configuration_versions={s.session_id: s.configuration_version for s in sessions},
                        model_versions={s.session_id: s.model_version for s in sessions}, trace=trace, decisions=decisions,
                        final_virtual_seconds=clock.monotonic())
