import os
from pathlib import Path
import secrets

from pydantic import BaseModel, ConfigDict, Field
import yaml
from core.capture import CameraConfig, CaptureSettings
from core.operations import OperationsSettings


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    venue_name: str = "Neon Football"
    database_path: Path = Path("data/neon-score.sqlite3")
    operator_key_path: Path = Path("data/operator.key")
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    default_duration_seconds: int = Field(default=1200, ge=60, le=14400)
    automatic_scoring_enabled: bool = False
    demo_review_enabled: bool = True
    pitch: dict = Field(default_factory=dict)
    cameras: list[CameraConfig] = Field(default_factory=list)
    capture: CaptureSettings = Field(default_factory=CaptureSettings)
    sensors: list = Field(default_factory=list)
    operations: OperationsSettings = Field(default_factory=OperationsSettings)

    def operator_key(self) -> str:
        configured = os.environ.get("NEON_OPERATOR_KEY")
        if configured:
            if len(configured) < 16:
                raise ValueError("NEON_OPERATOR_KEY must contain at least 16 characters")
            return configured
        self.operator_key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.operator_key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            key = self.operator_key_path.read_text(encoding="utf-8").strip()
        else:
            key = secrets.token_urlsafe(32)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(key + "\n")
        if len(key) < 16:
            raise ValueError("Operator key file is invalid; supply NEON_OPERATOR_KEY or replace the file")
        return key


def load_settings(path: Path | None = None) -> Settings:
    path = path or Path(os.environ.get("NEON_CONFIG", Path(__file__).parent / "config/cage.example.yaml"))
    settings = Settings.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if settings.schema_version != 1:
        raise ValueError("Unsupported configuration schema")
    if settings.automatic_scoring_enabled:
        raise ValueError("This milestone supports manual scoring only")
    return settings
