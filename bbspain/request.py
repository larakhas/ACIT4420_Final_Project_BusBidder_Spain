"""Store where and when the traveller wants to travel, their limits and their preferences.

I use a descriptor called Limit to check numeric limits whenever they're set.
For example, if any part of the program tries to set a negative budget,
Limit rejects it right away.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time

from bbspain.errors import InvalidRequestError
from bbspain.models import Destination

MAX_PASSENGERS = 9
WINDOW_PATTERN = re.compile(r"^(?P<a>[01]\d|2[0-3]):(?P<am>[0-5]\d)\s*-\s*(?P<b>[01]\d|2[0-3]):(?P<bm>[0-5]\d)$")
MINUTES_PER_DAY = 24 * 60


class Limit:
    """Descriptor: a number that must lie in [low, high]; None is allowed when optional."""

    def __init__(self, low: float, high: float, *, optional: bool = False, integer: bool = False):
        self.low, self.high, self.optional, self.integer = low, high, optional, integer

    def __set_name__(self, owner, name):
        self.public = name
        self.private = "_" + name

    def __get__(self, obj, objtype=None):
        return self if obj is None else getattr(obj, self.private, None)

    def __set__(self, obj, value):
        if value is None:
            if self.optional:
                setattr(obj, self.private, None)
                return
            raise InvalidRequestError(f"{self.public} is required")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidRequestError(f"{self.public} must be a number (got {value!r})")
        if self.integer and int(value) != value:
            raise InvalidRequestError(f"{self.public} must be a whole number (got {value})")
        if not self.low <= value <= self.high:
            raise InvalidRequestError(f"{self.public} must be between {self.low:g} and {self.high:g} (got {value:g})")
        setattr(obj, self.private, int(value) if self.integer else value)


@dataclass(frozen=True)
class DepartureWindow:
    """A preferred departure window in minutes after midnight; end < start means it wraps midnight."""

    start: int
    end: int
    label: str

    NAMED = {"morning": (6 * 60, 12 * 60), "afternoon": (12 * 60, 18 * 60),
             "evening": (18 * 60, 22 * 60), "night": (22 * 60, 4 * 60)}

    @classmethod
    def parse(cls, text: str) -> "DepartureWindow | None":
        """'morning', '07:00-09:30' or 'any' (-> None, meaning no preference)."""
        word = text.strip().casefold()
        if word in ("any", "none", ""):
            return None
        if word in cls.NAMED:
            start, end = cls.NAMED[word]
            return cls(start, end, f"{word} ({start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d})")
        m = WINDOW_PATTERN.match(word)
        if not m:
            raise InvalidRequestError(
                f"Departure preference '{text}' is not morning/afternoon/evening/night/any or HH:MM-HH:MM")
        start = int(m["a"]) * 60 + int(m["am"])
        end = int(m["b"]) * 60 + int(m["bm"])
        if start == end:
            raise InvalidRequestError("Departure window must not be empty")
        return cls(start, end, f"{m['a']}:{m['am']}-{m['b']}:{m['bm']}")

    def contains(self, minute: int) -> bool:
        if self.start < self.end:
            return self.start <= minute < self.end
        return minute >= self.start or minute < self.end

    def gap_min(self, at: time) -> int:
        """Minutes between a departure time and the window; 0 when inside it. Wraps midnight."""
        minute = at.hour * 60 + at.minute
        if self.contains(minute):
            return 0
        to_start = (self.start - minute) % MINUTES_PER_DAY
        from_end = (minute - self.end) % MINUTES_PER_DAY
        return min(to_start, from_end)


class TravelRequest:
    """Hard constraints (destination, dates, seats, optional limits) plus soft preferences."""

    passengers = Limit(1, MAX_PASSENGERS, integer=True)
    max_price = Limit(0.01, 5000, optional=True)
    max_transfers = Limit(0, 5, optional=True, integer=True)
    max_duration_min = Limit(30, MINUTES_PER_DAY, optional=True, integer=True)
    min_luggage_kg = Limit(0, 100, optional=True, integer=True)

    def __init__(self, destination: Destination, date_from: date, date_to: date, *, passengers: int = 1,
                 max_price: float | None = None, max_transfers: int | None = None,
                 max_duration_min: int | None = None, min_luggage_kg: int | None = None,
                 require_changeable: bool = False, require_refundable: bool = False,
                 preferred_departure: DepartureWindow | None = None):
        if date_to < date_from:
            raise InvalidRequestError(f"Travel window ends ({date_to}) before it starts ({date_from})")
        self.destination = destination
        self.date_from, self.date_to = date_from, date_to
        self.passengers = passengers
        self.max_price = max_price
        self.max_transfers = max_transfers
        self.max_duration_min = max_duration_min
        self.min_luggage_kg = min_luggage_kg
        self.require_changeable = require_changeable
        self.require_refundable = require_refundable
        self.preferred_departure = preferred_departure

    def __repr__(self) -> str:
        return f"TravelRequest(Madrid->{self.destination.name}, {self.date_from}..{self.date_to}, n={self.passengers})"
