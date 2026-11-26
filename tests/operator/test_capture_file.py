import hashlib
from types import SimpleNamespace

import pytest

from core.ports import DomainError
from modules.capture.manager import CaptureManager


def test_registered_capture_download_rejects_pending_escape_and_changed_bytes(tmp_path):
    root = tmp_path / "clips"
    root.mkdir()
    target = root / "owned.mjpeg"
    target.write_bytes(b"test-bytes")
    record = dict(status="ready", recording=dict(path="owned.mjpeg", sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    manager = CaptureManager.__new__(CaptureManager)
    manager.clips = SimpleNamespace(root=root, status=lambda _: record)
    assert manager.clip_file("registered") == target
    record["status"] = "writing"
    with pytest.raises(DomainError) as error:
        manager.clip_file("registered")
    assert error.value.status == 409
    record["status"] = "ready"
    record["recording"]["path"] = "../outside.mjpeg"
    with pytest.raises(DomainError) as error:
        manager.clip_file("registered")
    assert error.value.status == 422
    record["recording"]["path"] = "owned.mjpeg"
    target.write_bytes(b"changed")
    with pytest.raises(DomainError) as error:
        manager.clip_file("registered")
    assert error.value.status == 410
