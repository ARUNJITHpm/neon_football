"""Explicit closed-session media retention; audit/metadata and held sessions survive."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path

from core.capture import RecordingManifest, SegmentRecord
from core.operations import RetentionPolicy


def checksum(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def owned(root, session, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Retention path must be relative without parent traversal")
    target = session / relative
    for entry in (target, *target.parents):
        if entry == root:
            break
        if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
            raise ValueError("Retention never follows links/junctions")
    resolved = target.resolve()
    if not resolved.is_relative_to(session) or not session.is_relative_to(root) or session == root:
        raise ValueError("Retention target escapes owned session")
    return resolved


def plan_retention(root, policy: RetentionPolicy, now=None):
    root = Path(root).resolve(strict=True)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Retention time must include timezone")
    files, skipped = [], []
    for session in sorted(root.iterdir()):
        if not session.is_dir() or session.is_symlink() or (hasattr(session, "is_junction") and session.is_junction()):
            continue
        manifest_path = session / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            continue
        if manifest_path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Retention manifest capacity exceeded")
        manifest = RecordingManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if manifest.session_id in policy.holds:
            skipped.append(dict(session_id=manifest.session_id, reason="held", detail=policy.holds[manifest.session_id])); continue
        if manifest.status != "closed" or not manifest.ended_at or manifest.ended_at > now:
            skipped.append(dict(session_id=manifest.session_id, reason="not_closed")); continue
        records = []
        if manifest.ended_at <= now - timedelta(days=policy.raw_days):
            records += [("raw", segment) for camera in manifest.cameras for segment in camera.segments]
        if manifest.ended_at <= now - timedelta(days=policy.clip_days):
            clip_root = session / "clips"
            if clip_root.exists() and (clip_root.is_symlink() or (hasattr(clip_root, "is_junction") and clip_root.is_junction())):
                raise ValueError("Clip directory must be owned")
            for clip in sorted(clip_root.glob("*.json")):
                if clip.is_symlink() or clip.stat().st_size > 1024 * 1024:
                    raise ValueError("Invalid clip metadata")
                record = json.loads(clip.read_text(encoding="utf-8"))
                if record.get("status") == "ready":
                    records.append(("clip", SegmentRecord.model_validate(record["recording"])))
        for kind, segment in records:
            for relative, digest, suffix in ((segment.path, segment.sha256, ".mjpeg"), (segment.index_path, segment.index_sha256, ".jsonl")):
                target = owned(root, session, relative)
                if target.suffix != suffix:
                    raise ValueError("Retention accepts registered MJPEG/index files only")
                if not target.exists():
                    continue  # A previous audited retention run may have removed it.
                if not target.is_file() or checksum(target) != digest:
                    raise ValueError("Retention file changed from registered checksum")
                files.append(dict(path=target.relative_to(root).as_posix(), sha256=digest,
                                  bytes=target.stat().st_size, session_id=manifest.session_id, kind=kind))
                if len(files) > 100000:
                    raise ValueError("Retention plan capacity exceeded")
    unique = {item["path"]: item for item in files}
    return dict(schema_version=1, root=str(root), policy=policy.model_dump(), files=list(unique.values()), skipped=skipped,
                bytes=sum(item["bytes"] for item in unique.values()), audit_logs_deleted=False)


def apply_retention(plan):
    policy = RetentionPolicy.model_validate(plan["policy"])
    if not policy.enabled:
        raise ValueError("Retention policy is disabled; review policy before applying")
    root = Path(plan["root"]).resolve(strict=True)
    # Replan against current manifests, holds and bytes, before any deletion.
    fresh = plan_retention(root, policy)
    if fresh["files"] != plan["files"] or fresh["skipped"] != plan["skipped"]:
        raise ValueError("Retention inputs changed; generate a new plan")
    journal = root / "retention-events.jsonl"
    if journal.is_symlink() or (journal.exists() and not journal.is_file()):
        raise ValueError("Retention journal must be an owned regular file")
    removed = []
    with journal.open("a", encoding="utf-8") as audit:
        def record(event):
            audit.write(json.dumps(event, sort_keys=True) + "\n"); audit.flush(); os.fsync(audit.fileno())
        for item in fresh["files"]:
            relative = Path(item["path"])
            session = root / relative.parts[0]
            target = owned(root, session, Path(*relative.parts[1:]))
            if checksum(target) != item["sha256"]:
                raise ValueError("Retention bytes changed before deletion")
            event = dict(recorded_at=datetime.now(timezone.utc).isoformat(), file=item)
            record(dict(**event, action="delete_intent"))
            target.unlink()  # Only the checked registered file, never recursive deletion.
            removed.append(item["path"])
            record(dict(**event, action="deleted"))
    return dict(removed=removed, bytes=fresh["bytes"], audit_logs_deleted=False)
