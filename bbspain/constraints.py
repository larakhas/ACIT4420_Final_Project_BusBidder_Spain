"""Check which offers meet the requirements before ranking them.

I use a small function for each rule and register it with @hard_constraint.
The decorator records when the rule applies and how to describe it. An offer
has to pass every rule that applies to the request before it can be ranked.

To add a new rule, I just write another function with the same decorator.
The filter then uses the rule automatically, and the CLI shows which rules
were applied and how many offers each one removed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from bbspain.models import Offer
from bbspain.request import TravelRequest


@dataclass(frozen=True)
class HardConstraint:
    name: str
    label: str
    check: Callable[[Offer, TravelRequest], bool]      # True = the offer satisfies it
    applies: Callable[[TravelRequest], bool]           # is it active for this request?
    describe: Callable[[TravelRequest], str]
    scope: bool = False                                # True for route/date: they define the search


CONSTRAINTS: dict[str, HardConstraint] = {}


def hard_constraint(name: str, label: str, *, describe: Callable[[TravelRequest], str],
                    applies: Callable[[TravelRequest], bool] = lambda r: True, scope: bool = False):
    """Register a check function as a hard constraint."""
    def register(func: Callable[[Offer, TravelRequest], bool]):
        if name in CONSTRAINTS:
            raise ValueError(f"hard constraint '{name}' is already registered")
        CONSTRAINTS[name] = HardConstraint(name, label, func, applies, describe, scope)
        return func
    return register


@hard_constraint("route", "route", scope=True,
                 describe=lambda r: f"route Madrid -> {r.destination.name}")
def _route(offer, req):
    return offer.destination.code == req.destination.code


@hard_constraint("dates", "travel window", scope=True,
                 describe=lambda r: f"departs between {r.date_from:%d %b} and {r.date_to:%d %b %Y}")
def _dates(offer, req):
    return req.date_from <= offer.departure.date() <= req.date_to


@hard_constraint("seats", "seat availability",
                 describe=lambda r: f"at least {r.passengers} free seat(s)")
def _seats(offer, req):
    return offer.seats_available >= req.passengers


@hard_constraint("budget", "budget", applies=lambda r: r.max_price is not None,
                 describe=lambda r: f"price at most EUR {r.max_price:.2f} per ticket")
def _budget(offer, req):
    return offer.price_eur <= req.max_price


@hard_constraint("transfers", "maximum transfers", applies=lambda r: r.max_transfers is not None,
                 describe=lambda r: f"at most {r.max_transfers} transfer(s)")
def _transfers(offer, req):
    return offer.transfers <= req.max_transfers


@hard_constraint("duration", "maximum duration", applies=lambda r: r.max_duration_min is not None,
                 describe=lambda r: f"journey of at most {r.max_duration_min // 60}h{r.max_duration_min % 60:02d}")
def _duration(offer, req):
    return offer.duration_min <= req.max_duration_min


@hard_constraint("luggage", "luggage allowance", applies=lambda r: r.min_luggage_kg is not None,
                 describe=lambda r: f"luggage allowance of at least {r.min_luggage_kg} kg")
def _luggage(offer, req):
    return offer.luggage_kg >= req.min_luggage_kg


@hard_constraint("changeable", "changeable ticket", applies=lambda r: r.require_changeable,
                 describe=lambda r: "ticket must be changeable")
def _changeable(offer, req):
    return offer.fare.changeable


@hard_constraint("refundable", "refundable ticket", applies=lambda r: r.require_refundable,
                 describe=lambda r: "ticket must be refundable")
def _refundable(offer, req):
    return offer.fare.refundable


@dataclass
class FilterResult:
    request: TravelRequest
    searched: int
    in_scope: int                                   # offers matching route and dates
    accepted: list[Offer]
    excluded: list[tuple[Offer, list[str]]] = field(default_factory=list)
    removed_by: dict[str, int] = field(default_factory=dict)   # constraint label -> offers it removed

    @property
    def active(self) -> list[HardConstraint]:
        return active_constraints(self.request)


def active_constraints(request: TravelRequest) -> list[HardConstraint]:
    return [c for c in CONSTRAINTS.values() if c.applies(request)]


def apply_hard_constraints(offers: list[Offer], request: TravelRequest) -> FilterResult:
    """Split offers into those satisfying every active constraint and the rest (with reasons).

    Offers outside the route/dates are simply not part of this search; they are counted in
    `searched` but not reported as "excluded". Everything else that fails is reported with
    every constraint it breaks, because an offer can fail several at once.
    """
    active = active_constraints(request)
    scope = [c for c in active if c.scope]
    rules = [c for c in active if not c.scope]
    accepted, excluded = [], []
    removed_by: dict[str, int] = {}
    in_scope = 0
    for offer in offers:
        if not all(c.check(offer, request) for c in scope):
            continue
        in_scope += 1
        broken = [c for c in rules if not c.check(offer, request)]
        if broken:
            excluded.append((offer, [c.label for c in broken]))
            for c in broken:
                removed_by[c.label] = removed_by.get(c.label, 0) + 1
        else:
            accepted.append(offer)
    return FilterResult(request, len(offers), in_scope, accepted, excluded, removed_by)
