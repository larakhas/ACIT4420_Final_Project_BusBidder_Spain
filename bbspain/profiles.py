"""Traveller profiles: named bundles of weights, hard limits and a departure preference."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from bbspain.errors import ConfigError, WeightError
from bbspain.models import Destination
from bbspain.request import DepartureWindow, TravelRequest
from bbspain.scoring import Weights

_ALLOWED_LIMITS = {"max_price", "max_transfers", "max_duration_min", "min_luggage_kg",
                   "require_changeable", "require_refundable"}


@dataclass(frozen=True)
class TravellerProfile:
    key: str
    name: str
    description: str
    weights: Weights
    departure: str = "any"
    limits: dict = field(default_factory=dict)

    def make_request(self, destination: Destination, date_from: date, date_to: date, passengers: int = 1,
                     **overrides) -> TravelRequest:
        """Build a request from the profile; explicit overrides (not None) win over profile limits."""
        merged = {**self.limits, **{k: v for k, v in overrides.items() if v is not None}}
        window = DepartureWindow.parse(merged.pop("departure", self.departure))
        return TravelRequest(destination, date_from, date_to, passengers=passengers,
                             preferred_departure=window, **merged)


def load_profiles(path: Path) -> dict[str, TravellerProfile]:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"Profiles file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Could not read profiles file {path}: {exc}") from exc
    if not isinstance(raw, dict) or not raw:
        raise ConfigError(f"{path} must hold a non-empty JSON object of profiles")

    profiles = {}
    for key, entry in raw.items():
        try:
            weights = Weights.from_mapping(entry["weights"])
            limits = dict(entry.get("limits", {}))
            bad = sorted(set(limits) - _ALLOWED_LIMITS)
            if bad:
                raise ConfigError(f"profile '{key}': unknown limit(s) {', '.join(bad)}")
            DepartureWindow.parse(entry.get("departure", "any"))     # fail early on a bad preference
            profiles[key] = TravellerProfile(key, entry["name"], entry["description"], weights,
                                             entry.get("departure", "any"), limits)
        except KeyError as exc:
            raise ConfigError(f"profile '{key}' lacks the field {exc}") from exc
        except WeightError as exc:
            raise ConfigError(f"profile '{key}': {exc}") from exc
    return profiles
