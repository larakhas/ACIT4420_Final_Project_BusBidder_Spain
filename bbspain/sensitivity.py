"""How stable is the recommendation? Move each weight by +/-10 points and re-rank."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from bbspain.config import Settings
from bbspain.models import Offer
from bbspain.request import TravelRequest
from bbspain.scoring import CRITERIA, NORMALISERS, Ranker, Weights


@dataclass
class Scenario:
    description: str
    winner_id: str | None
    changed: bool


def weight_sensitivity(offers: Sequence[Offer], request: TravelRequest, weights: Weights, settings: Settings,
                       step: float = 10.0) -> tuple[str | None, list[Scenario]]:
    """Return the baseline winner and, for every used criterion and direction, the new winner.

    When one weight moves, the others are rescaled proportionally so the total stays 100 %.
    """
    ranker = Ranker(settings)
    base = ranker.rank(offers, request, weights).best
    base_id = base.offer.offer_id if base else None
    scenarios = []
    for key in weights.used():
        for delta in (-step, +step):
            shifted = weights.shifted(key, delta)
            if shifted is None:
                continue
            best = ranker.rank(offers, request, shifted).best
            wid = best.offer.offer_id if best else None
            scenarios.append(Scenario(f"{CRITERIA[key].label} {delta:+g} points", wid, wid != base_id))
    return base_id, scenarios


def normaliser_comparison(offers: Sequence[Offer], request: TravelRequest, weights: Weights,
                          settings: Settings) -> dict[str, str | None]:
    """Winner under each registered normaliser: does the scaling choice alone change the answer?"""
    out = {}
    for name in sorted(NORMALISERS):
        best = Ranker(replace(settings, normaliser=name)).rank(offers, request, weights).best
        out[name] = best.offer.offer_id if best else None
    return out
