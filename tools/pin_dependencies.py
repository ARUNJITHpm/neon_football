"""Capture the tested runtime's transitive dependency versions, not its secrets.

Run only when intentionally refreshing the lock, then validate a clean install.
Environment markers preserve Python/OS-specific runtime requirements.
"""
from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def collect(roots):
    locked = {}
    def visit(name):
        canonical = canonicalize_name(name)
        if canonical in locked:
            return
        package = distribution(name)
        locked[canonical] = package.version
        for text in package.requires or []:
            requirement = Requirement(text)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                visit(requirement.name)
    for root in roots:
        visit(root)
    return locked


if __name__ == "__main__":
    runtime = collect(["fastapi", "uvicorn", "pydantic", "PyYAML", "websockets"])
    testing = collect(["pytest", "httpx"])
    for name, content in (("requirements.lock", runtime), ("requirements-test.lock", {**runtime, **testing})):
        header = "# Tested on Python 3.12.4 / Windows; regenerate with tools/pin_dependencies.py.\n"
        lines = [f"{key}=={value}" for key, value in sorted(content.items())]
        Path(name).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
