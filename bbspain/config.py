"""Settings read from config/settings.json (with safe defaults for every value)."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path

from bbspain.errors import ConfigError


@dataclass(frozen=True)
class Settings:
    normaliser: str = "guarded_minmax"      # guarded_minmax | minmax | ratio
    min_span_fraction: float = 0.20         # guarded_minmax: smallest spread, as a fraction of the best value
    departure_tolerance_min: int = 180      # minutes outside the window at which the departure score hits 0
    neutral_score: float = 50.0             # score given to a missing optional value
    dominance_warning: float = 0.50         # warn when one weight exceeds this share
    cancellation_fee_pct: float = 10.0      # fee kept on a refundable cancellation
    default_date_from: str = "2026-07-12"
    default_date_to: str = "2026-07-14"
    data_dir: str = "data"
    output_dir: str = "output"
    log_file: str = "logs/busbidder.log"
    profiles_file: str = "config/profiles.json"


def load_settings(path: Path | None) -> Settings:
    """Read a settings file; with no path the defaults are used. Unknown keys are an error."""
    if path is None:
        return Settings()
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"Settings file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Could not read settings file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    known = {f.name for f in fields(Settings)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"Unknown setting(s) in {path}: {', '.join(unknown)}")
    settings = Settings(**raw)
    _check(settings)
    return settings


def _check(s: Settings) -> None:
    from bbspain.scoring import NORMALISERS
    if s.normaliser not in NORMALISERS:
        raise ConfigError(f"Unknown normaliser '{s.normaliser}'. Available: {', '.join(sorted(NORMALISERS))}")
    if not 0 < s.min_span_fraction <= 1:
        raise ConfigError("min_span_fraction must be in (0, 1]")
    if s.departure_tolerance_min <= 0:
        raise ConfigError("departure_tolerance_min must be positive")
    if not 0 <= s.neutral_score <= 100:
        raise ConfigError("neutral_score must be between 0 and 100")
    if not 0 < s.dominance_warning <= 1:
        raise ConfigError("dominance_warning must be in (0, 1]")
    if not 0 <= s.cancellation_fee_pct <= 100:
        raise ConfigError("cancellation_fee_pct must be between 0 and 100")
