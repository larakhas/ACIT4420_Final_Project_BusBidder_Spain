"""Rank offers using the traveller's weights.

I give each criterion a score from 0 to 100, with 100 as the best score.
This puts values like price in euros and travel time in minutes on the same
scale. For each offer, I multiply each score by its weight and add up the
results to get the total score.

For price, travel time and emissions, I use the selected normaliser to compare
each offer with the others that meet the traveller's requirements. These scores
can change when a different set of offers qualifies.

For departure time, flexibility, transfers and rating, I use fixed scales.
For example, the departure score depends on how well the offer matches the
traveller's preferred time. Adding or removing other offers won't change it.

I register each normaliser and criterion by name using decorators. The settings,
profiles, weight validator and CLI can then look them up without having to
maintain separate lists.
"""
from __future__ import annotations
import math

from dataclasses import dataclass, field
from typing import Callable, Sequence

from bbspain.config import Settings
from bbspain.constraints import FilterResult, apply_hard_constraints
from bbspain.errors import WeightError
from bbspain.models import Offer
from bbspain.request import TravelRequest

# normalisers

Normaliser = Callable[[Sequence[float], bool, Settings], "list[float]"]
NORMALISERS: dict[str, Normaliser] = {}


def normaliser(name: str):
    def register(func: Normaliser) -> Normaliser:
        if name in NORMALISERS:
            raise ValueError(f"normaliser '{name}' is already registered")
        NORMALISERS[name] = func
        return func
    return register


@normaliser("minmax")
def minmax(values, lower_is_better, settings):
    """Best = 100, worst = 0. Equal values all score 100 (nothing to tell them apart)."""
    low, high = min(values), max(values)
    if high == low:
        return [100.0] * len(values)
    if lower_is_better:
        return [100.0 * (high - v) / (high - low) for v in values]
    return [100.0 * (v - low) / (high - low) for v in values]


@normaliser("guarded_minmax")
def guarded_minmax(values, lower_is_better, settings):
    """Min-max, but the spread is never smaller than `min_span_fraction` of the best value.

    Plain min-max turns any difference, however small, into a 0-100 gap: EUR 30 vs EUR 31 would
    score 100 vs 0. Here a gap smaller than 20 % of the best value cannot use the full scale, so
    a trivial difference cannot dominate the ranking, while large differences still spread out.
    """
    best = min(values) if lower_is_better else max(values)
    worst = max(values) if lower_is_better else min(values)
    span = max(abs(worst - best), settings.min_span_fraction * abs(best))
    if span == 0:
        return [100.0] * len(values)
    return [max(0.0, 100.0 * (1 - abs(v - best) / span)) for v in values]


@normaliser("ratio")
def ratio(values, lower_is_better, settings):
    """Score proportional to the best value: twice the best price scores 50."""
    best = min(values) if lower_is_better else max(values)
    if best <= 0:
        return minmax(values, lower_is_better, settings)
    return [100.0 * best / v if lower_is_better else 100.0 * v / best for v in values]


# criteria

def lower_label(key: str) -> str:
    """'Price' -> 'price', but keep acronyms: 'CO2 emissions' stays as it is."""
    label = CRITERIA[key].label
    return label if label.split()[0].isupper() else label.lower()


def hm(minutes: float) -> str:
    h, m = divmod(int(round(minutes)), 60)
    return f"{h}h{m:02d}"


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    header: str                                              # short table heading
    kind: str                                                # "relative" | "absolute"
    raw: Callable[[Offer, TravelRequest], float | None]      # None = value missing
    show: Callable[[Offer, TravelRequest], str]
    describe: Callable[[Offer, TravelRequest, Sequence[Offer]], str]
    lower_is_better: bool = True                             # relative criteria only
    scale: Callable[[float, TravelRequest, Settings], float] | None = None   # absolute criteria only

    def score_all(self, offers: Sequence[Offer], request: TravelRequest, settings: Settings) -> list[float | None]:
        raws = [self.raw(o, request) for o in offers]
        present = [r for r in raws if r is not None]
        if self.kind == "relative":
            scored = iter(NORMALISERS[settings.normaliser](present, self.lower_is_better, settings) if present else [])
        else:
            scored = iter([self.scale(r, request, settings) for r in present])
        return [None if r is None else next(scored) for r in raws]


CRITERIA: dict[str, Criterion] = {}
CORE_CRITERIA = ("price", "duration", "departure", "flexibility")


def criterion(**spec):
    """Decorator: the decorated function is the criterion's raw-value extractor."""
    def register(raw_func):
        c = Criterion(raw=raw_func, **spec)
        if c.key in CRITERIA:
            raise ValueError(f"criterion '{c.key}' is already registered")
        CRITERIA[c.key] = c
        return raw_func
    return register


def _cheapest(c): return min(o.price_eur for o in c)


@criterion(key="price", label="Price", header="Price", kind="relative",
           show=lambda o, r: f"{o.price_eur:.2f}",
           describe=lambda o, r, c: ("the cheapest acceptable fare" if o.price_eur <= _cheapest(c) + 0.005 else
                                     f"EUR {o.price_eur - _cheapest(c):.2f} dearer than the cheapest acceptable offer "
                                     f"(EUR {_cheapest(c):.2f})"))
def price(offer, request):
    return offer.price_eur


@criterion(key="duration", label="Duration", header="Durat", kind="relative",
           show=lambda o, r: hm(o.duration_min),
           describe=lambda o, r, c: ("the fastest acceptable journey" if o.duration_min <= min(x.duration_min for x in c)
                                     else f"{hm(o.duration_min)}, {int(o.duration_min - min(x.duration_min for x in c))} min "
                                          f"slower than the fastest acceptable option"))
def duration(offer, request):
    return float(offer.duration_min)


def _departure_scale(gap, request, settings):
    return max(0.0, 100.0 * (1 - gap / settings.departure_tolerance_min))


def _departure_describe(o, r, c):
    w = r.preferred_departure
    if w is None:
        return f"departs {o.departure:%H:%M} (no departure preference set)"
    gap = w.gap_min(o.departure.time())
    return (f"departs {o.departure:%H:%M}, inside your {w.label} window" if gap == 0
            else f"departs {o.departure:%H:%M}, {gap} min outside your {w.label} window")


@criterion(key="departure", label="Departure time", header="Depart", kind="absolute", scale=_departure_scale,
           show=lambda o, r: f"{o.departure:%H:%M}", describe=_departure_describe)
def departure(offer, request):
    """Gap in minutes to the preferred window (0 inside it, or when there is no preference)."""
    return 0.0 if request.preferred_departure is None else float(request.preferred_departure.gap_min(offer.departure.time()))


# Changing a ticket is worth a little more than a refund: a shifted plan is the more common
# need, and a change keeps the trip. These two numbers are judgement calls (see the report).
CHANGE_VALUE, REFUND_VALUE = 60.0, 40.0


@criterion(key="flexibility", label="Flexibility", header="Flex", kind="absolute",
           scale=lambda v, r, s: v, show=lambda o, r: o.fare.flags,
           describe=lambda o, r, c: f"'{o.fare.name}' fare is {o.fare.summary}")
def flexibility(offer, request):
    return CHANGE_VALUE * offer.fare.changeable + REFUND_VALUE * offer.fare.refundable


@criterion(key="transfers", label="Transfers", header="Trnsf", kind="absolute",
           scale=lambda v, r, s: max(0.0, 100.0 - 40.0 * v), show=lambda o, r: str(o.transfers),
           describe=lambda o, r, c: "a direct journey" if o.transfers == 0 else f"{o.transfers} transfer(s) on the way")
def transfers(offer, request):
    return float(offer.transfers)


@criterion(key="rating", label="Rating", header="Rating", kind="absolute",
           scale=lambda v, r, s: (v - 1.0) / 4.0 * 100.0,
           show=lambda o, r: "n/a" if o.rating is None else f"{o.rating:.1f}",
           describe=lambda o, r, c: "no customer rating available" if o.rating is None else f"customer rating {o.rating:.1f}/5")
def rating(offer, request):
    return offer.rating


@criterion(key="emissions", label="CO2 emissions", header="CO2", kind="relative",
           show=lambda o, r: "n/a" if o.co2_kg is None else f"{o.co2_kg:.1f}",
           describe=lambda o, r, c: ("no emissions figure reported" if o.co2_kg is None else
                                     f"{o.co2_kg:.1f} kg CO2 per passenger"))
def emissions(offer, request):
    return offer.co2_kg


#  weights

@dataclass(frozen=True)
class Weights:
    """Importance of each criterion. Stored as fractions that sum to 1."""

    values: dict[str, float]

    @classmethod
    def from_mapping(cls, mapping: dict[str, float]) -> "Weights":
        """Validate and build. Accepts percentages (total 100) or fractions (total 1.0).

        An incorrect total is rejected rather than silently rescaled: 40+25+15+10 = 90 is more
        likely a typing mistake than an intention, and the traveller should see that.
        """
        if not mapping:
            raise WeightError("No weights given")
        unknown = sorted(set(mapping) - set(CRITERIA))
        if unknown:
            raise WeightError(f"Unknown criterion/criteria: {', '.join(unknown)}. Available: {', '.join(CRITERIA)}")
        for key, w in mapping.items():
            if isinstance(w, bool) or not isinstance(w, (int, float)):
                raise WeightError(f"Weight for {key} must be a number (got {w!r})")
            if not math.isfinite(w):
                raise WeightError(f"Weight for {key} must be finite")

            if w < 0:
                raise WeightError(f"Weight for {key} cannot be negative (got {w})")
        total = sum(mapping.values())
        if abs(total - 100) <= 1e-6:
            scale = 100.0
        elif abs(total - 1) <= 1e-6:
            scale = 1.0
        else:
            raise WeightError(f"Weights must total 100% (or 1.0); they total {total:g}")
        values = {k: mapping.get(k, 0) / scale for k in CRITERIA}
        used = [k for k, v in values.items() if v > 0]
        if len(used) < 2:
            raise WeightError("At least two criteria need a weight above zero")
        return cls(values)

    @classmethod
    def parse(cls, text: str) -> "Weights":
        """Read weights written as criterion=percent."""
        import re

        mapping = {}

        for part in text.split(","):
            m = re.fullmatch(
                r"\s*([a-z_]+)\s*=\s*(-?\d+(?:\.\d+)?)\s*",
                part.casefold(),
            )

            if not m:
                raise WeightError(
                    f"'{part.strip()}' is not in the form criterion=percent"
                )

            if m[1] in mapping:
                raise WeightError(f"Criterion '{m[1]}' is given twice")

            mapping[m[1]] = float(m[2])

        weights = cls.from_mapping(mapping)
        weights.require_core()
        return weights
    
    def percent(self, key: str) -> float:
        return round(self.values[key] * 100, 1)

    def used(self) -> list[str]:
        return [k for k, v in self.values.items() if v > 0]
    
    def require_core(self) -> None:
        missing = [
            key for key in CORE_CRITERIA
            if self.values.get(key, 0) <= 0
        ]

        if missing:
            raise WeightError(
                "Price, duration, departure and flexibility must all have "
                "positive weights. Missing or zero: " + ", ".join(missing)
            )

    def describe(self) -> str:
        return ", ".join(f"{lower_label(k)} {self.values[k] * 100:g}%" for k in self.used())

    def shifted(self, key: str, delta_points: float) -> "Weights | None":
        """Move one weight by delta_points, rescaling the others proportionally. None if impossible."""
        new = self.values[key] + delta_points / 100
        if new < 0 or new > 1:
            return None
        others = {k: v for k, v in self.values.items() if k != key}
        rest = sum(others.values())
        if rest == 0:
            return None
        scale = (1 - new) / rest
        values = {k: v * scale for k, v in others.items()}
        values[key] = new
        return Weights(values)


# ranking

@dataclass
class ScoredOffer:
    offer: Offer
    scores: dict[str, float]            # criterion -> 0-100 (neutral value if it was missing)
    missing: frozenset[str]
    total: float
    rank: int = 0
    tied: bool = False

    def contribution(self, key: str, weights: Weights) -> float:
        return weights.values[key] * self.scores[key]


@dataclass
class RankingResult:
    request: TravelRequest
    weights: Weights
    settings: Settings
    filtered: FilterResult
    ranked: list[ScoredOffer] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def best(self) -> ScoredOffer | None:
        return self.ranked[0] if self.ranked else None


class Ranker:
    def __init__(self, settings: Settings):
        self.settings = settings

    def rank(self, offers: Sequence[Offer], request: TravelRequest, weights: Weights) -> RankingResult:
        filtered = apply_hard_constraints(list(offers), request)
        result = RankingResult(request, weights, self.settings, filtered)
        for key in weights.used():
            if weights.values[key] > self.settings.dominance_warning:
                result.warnings.append(
                    f"{CRITERIA[key].label} carries {weights.values[key] * 100:g}% of the weight and may dominate the result.")
        if weights.values["departure"] > 0 and request.preferred_departure is None:
            result.warnings.append("Departure time has a weight but no preferred departure was set, so it scores "
                                   "every offer 100 and has no effect.")
        candidates = filtered.accepted
        if not candidates:
            return result

        per_criterion = {k: CRITERIA[k].score_all(candidates, request, self.settings) for k in weights.used()}
        neutral = self.settings.neutral_score
        scored = []
        for i, offer in enumerate(candidates):
            scores, missing = {}, set()
            for key in CRITERIA:
                if key not in per_criterion:
                    scores[key] = 0.0       # unused criterion: weight 0, so it has no effect on the total
                    continue
                value = per_criterion[key][i]
                if value is None:
                    missing.add(key)
                    value = neutral
                scores[key] = value
            total = round(sum(weights.values[k] * scores[k] for k in weights.used()), 2)
            scored.append(ScoredOffer(offer, scores, frozenset(missing), total))

        # deterministic order: higher total, then cheaper, then earlier departure, then id
        scored.sort(key=lambda s: (-s.total, s.offer.price_eur, s.offer.departure, s.offer.offer_id))
        for i, s in enumerate(scored, start=1):
            s.rank = i
        for a, b in zip(scored, scored[1:]):
            if a.total == b.total:
                a.tied = b.tied = True
        result.ranked = scored

        n_missing = sum(1 for s in scored if s.missing)
        if n_missing:
            result.warnings.append(
                f"{n_missing} of {len(scored)} acceptable offers have a missing value; a neutral score of "
                f"{neutral:g} was used (marked * in the table).")
        return result
