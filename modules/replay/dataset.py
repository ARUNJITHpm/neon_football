import hashlib
from pathlib import Path

from core.dataset import AnnotationSet, DatasetManifest, ReplayEvent


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def asset_path(root, relative):
    target = (Path(root) / relative).resolve()
    if not target.is_relative_to(Path(root).resolve()):
        raise ValueError("Asset escaped media root (including symlinks)")
    return target


def select(manifest: DatasetManifest, split, allow_blind_test=False):
    if split == "blind_test" and not allow_blind_test:
        raise ValueError("Blind-test access requires explicit --allow-blind-test after freezing the evaluator/model")
    sessions = sorted((s for s in manifest.sessions if s.split == split), key=lambda s: s.session_id)
    if not sessions:
        raise ValueError("No sessions assigned to requested split")
    return sessions


def read_events(session, root, max_events=250000):
    for asset in session.assets:
        if digest(asset_path(root, asset.path)) != asset.sha256:
            raise ValueError(f"Asset checksum mismatch: {asset.path}")
    asset = next(a for a in session.assets if a.kind == "replay_events")
    events = []
    ids, sequences = set(), set()
    with asset_path(root, asset.path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            event = ReplayEvent.model_validate_json(line)
            if len(events) >= max_events:
                raise ValueError("Replay event capacity reached; partition sessions or set an explicit larger --max-events")
            if event.session_id != session.session_id or event.event_id in ids or event.sequence in sequences:
                raise ValueError("Replay session mismatch or duplicate event ID/sequence")
            if event.delivered_seconds > session.duration_seconds:
                raise ValueError("Event delivery exceeds recording duration")
            if event.clip_path is not None and not any(a.path == event.clip_path and a.kind in ("video", "clip") for a in session.assets):
                raise ValueError("Replay clip reference is not a declared media asset")
            if event.source_timing is not None and event.source_timing.host_clock_domain != session.host_clock_domain:
                raise ValueError("Replay source timing belongs to another host clock domain")
            match = next((m for m in session.matches if m.match_id == event.match_id), None)
            if match is None or not (match.start_seconds <= event.occurred_seconds < match.end_seconds):
                raise ValueError("Replay occurrence lies outside its scheduled match")
            ids.add(event.event_id)
            sequences.add(event.sequence)
            events.append(event)
    return events


def validate_annotations(manifest: DatasetManifest, annotations: AnnotationSet, sessions):
    if annotations.dataset_id != manifest.dataset_id or annotations.annotation_policy_version != manifest.annotation_policy_version:
        raise ValueError("Annotation dataset/policy does not match manifest")
    if any(s.split != annotations.split for s in sessions):
        raise ValueError("Annotation split differs from selected replay split")
    permitted = {s.session_id for s in sessions}
    all_sessions = {s.session_id: s for s in manifest.sessions}
    for audit in annotations.audits:
        if audit.session_id not in permitted:
            raise ValueError("Audit refers to an unknown session")
    for label in annotations.labels:
        session = all_sessions.get(label.session_id)
        if session is None or label.session_id not in permitted:
            raise ValueError("Label refers to an unknown session")
        match = next((m for m in session.matches if m.match_id == label.match_id), None)
        if match is None or not (match.start_seconds <= label.crossing_start_seconds <= label.crossing_end_seconds < match.end_seconds):
            raise ValueError("Annotation crossing interval lies outside its scheduled match")
        if label.clip_path is not None and not any(a.path == label.clip_path and a.kind in ("video", "clip") for a in session.assets):
            raise ValueError("Annotation clip reference is not a declared media asset")
    return [l for l in annotations.labels if l.session_id in {s.session_id for s in sessions}]
