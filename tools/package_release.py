"""Build a checksummed offline source candidate; dependencies/hardware are not bundled."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "neon-score-0.1.0-part10-prototype"


def release_files(root=ROOT):
    paths = []
    for folder in ("app", "core", "modules", "tools", "firmware"):
        for path in (root / folder).rglob("*"):
            relative = path.relative_to(root).as_posix()
            if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts:
                if path.suffix in (".py", ".ino") or relative.startswith("modules/api/static/") or relative in (
                    "app/config/cage.example.yaml", "app/config/retention.example.json", "app/fixtures/review-pattern.mp4", "app/fixtures/review-pattern.json", "firmware/esp32/README.md"):
                    paths.append(path)
    for name in ("README.md", "IMPLEMENTATION_PLAN.md", "PRODUCT.md", "DESIGN.md", "pyproject.toml", "requirements.lock", "requirements-test.lock", "requirements-vision.lock",
                 "docs/runbook.md", "docs/release-evaluation.md", "docs/api.md", "docs/operator-review.md", "docs/data-policy.md"):
        path = root / name
        if path.is_file():
            paths.append(path)
    paths += list((root / "docs/schemas").glob("*.json"))
    # Include the established guides/results referenced by the README. These are
    # public generated prototype docs, not arbitrary future venue exports.
    for name in ("capture", "annotation-guide", "baseline-results", "vision", "vision-baseline", "sensor-protocol",
                 "sensor-baseline", "fusion", "fusion-baseline", "operator-baseline", "operator-ui-review",
                 "implementation-progress", "requirements", "venue-survey", "hardware", "recovery-baseline", "attribution", "attribution-baseline", "analytics", "analytics-baseline"):
        path = root / "docs" / f"{name}.md"
        if path.is_file():
            paths.append(path)
    for name in ("baseline-results", "vision-baseline", "vision-benchmark", "vision-hd-benchmark", "vision-calibration-check",
                 "sensor-baseline", "sensor-throughput", "sensor-timing-results", "fusion-baseline", "operator-baseline",
                 "recovery-baseline", "release-evaluation", "attribution-baseline", "analytics-baseline"):
        path = root / "docs" / f"{name}.json"
        if path.is_file():
            paths.append(path)
    return sorted(set(paths))


def build(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    paths = release_files()
    contents = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in paths}
    if "docs/runbook.md" not in contents or "docs/release-evaluation.md" not in contents:
        raise ValueError("Recovery/release documents must exist before packaging")
    manifest = dict(schema_version=1, candidate=VERSION, application_version="0.1.0", database_schema=1,
                    tested_python=platform.python_version(), platform=platform.system(), automatic_scoring_enabled=False,
                    field_qualified=False, dependencies_bundled=False, clean_install_verified=False,
                    media_included="generated_review_pattern_only", secrets_included=False,
                    files={name:dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest()) for name,data in contents.items()})
    encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    archive = destination / f"{VERSION}.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in {**contents, "candidate-manifest.json": encoded}.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, data)
    (destination / "candidate-manifest.json").write_bytes(encoded)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / "archive.sha256").write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    return dict(candidate=VERSION, files=len(contents), archive=archive.name, sha256=checksum,
                automatic_scoring_enabled=False, field_qualified=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="New directory only")
    args = parser.parse_args()
    print(json.dumps(build(args.destination), sort_keys=True))
