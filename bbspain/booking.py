"""Store simulated bookings in a JSON file.

I keep the original seat count for each offer in offers.csv. To find out how many
seats are free, I subtract the number of seats in CONFIRMED bookings from that
count. If someone cancels, their seats become available again. That way, I only
have one seat count to maintain. Payment status is simulated, and I don't
collect any payment details.

A booking reference looks like BB-260705-K7Q2XZ. After the date, there are six
characters. I leave out I, O, 0 and 1 because they're easy to mix up. The last
character is calculated from the others, so I can check for typos before looking
up the booking.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence
from functools import wraps

from bbspain.errors import (BookingError, BookingNotFoundError, DataFileError, InvalidReferenceError,
                            SeatsUnavailableError)
from bbspain.models import Booking, BookingStatus, Offer
from bbspain.request import MAX_PASSENGERS

log = logging.getLogger(__name__)

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"            # 32 symbols
REFERENCE = re.compile(rf"^BB-(?P<date>\d{{6}})-(?P<body>[{ALPHABET}]{{5}})(?P<check>[{ALPHABET}])$")
NAME = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$")     # letters in any language, joined by space/-/'
MAX_NAME_LENGTH = 60
LOCK_TIMEOUT_SECONDS = 30


def check_char(date_part: str, body: str) -> str:
    """Weighted sum of the symbols, modulo 32, with odd weights so every single typo is caught."""
    text = date_part + body
    total = sum((2 * i + 1) * (ALPHABET.index(c) if c in ALPHABET else int(c)) for i, c in enumerate(text))
    return ALPHABET[total % 32]

def parse_reference(text: str) -> str:
    ref = text.strip().upper()
    m = REFERENCE.match(ref)
    if not m:
        raise InvalidReferenceError(f"'{text}' is not a booking reference (expected e.g. BB-260705-K7Q2XZ)")
    if check_char(m["date"], m["body"]) != m["check"]:
        raise InvalidReferenceError(f"'{text}' has a wrong check character; was it mistyped?")
    return ref


def validate_name(text: str) -> str:
    """Validate and normalise the passenger name."""
    if not isinstance(text, str):
        raise BookingError("Passenger name must be text")

    cleaned_name = " ".join(text.split())

    if cleaned_name == "":
        raise BookingError("Passenger name is required")

    correct_length = len(cleaned_name) <= MAX_NAME_LENGTH
    correct_format = NAME.fullmatch(cleaned_name) is not None

    if not correct_length or not correct_format:
        raise BookingError(
            f"'{text}' is not a valid passenger name "
            "(letters, spaces, hyphens, apostrophes)"
        )

    return cleaned_name

def clear_stale_lock(lock: Path) -> None:
    """Remove a lock left behind by a run that was interrupted before it could clean up."""
    try:
        age = time.time() - lock.stat().st_mtime
        if age > LOCK_TIMEOUT_SECONDS:
            lock.rmdir()
    except OSError:
        pass   # there is no lock, or another process removed it first

def booking_write(func):
    """Protect booking changes and reload the latest saved bookings."""
    @wraps(func)
    def wrapped(self, *args, **kwargs):
        lock = self.path.with_suffix(self.path.suffix + ".lock")

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            clear_stale_lock(lock)
            lock.mkdir()
        except FileExistsError:
            raise BookingError(
                "Booking file is busy. Please try again."
            ) from None
        except OSError as exc:
            raise BookingError(
                f"Could not lock booking file: {exc}"
            ) from exc

        try:
            self._bookings = self._load()
            return func(self, *args, **kwargs)
        finally:
            lock.rmdir()

    return wrapped

class BookingStore:
    def __init__(self, path: Path, *, cancellation_fee_pct: float = 10.0, rng: random.Random | None = None,
                clock: Callable[[], datetime] = datetime.now,
                travel_clock: Callable[[], datetime] | None = None):
        self.path = Path(path)
        self.fee_pct = cancellation_fee_pct
        self._rng = rng or random.SystemRandom()
        self._clock = clock
        self._travel_clock = travel_clock
        self._bookings: dict[str, Booking] = self._load()

    # file handling

    def _load(self) -> dict[str, Booking]:
        if not self.path.exists():
            return {}

        try:
            text = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise DataFileError(
                f"Could not read booking file {self.path}: {exc}"
            ) from exc

        try:
            payload = json.loads(text)
            return self._decode_bookings(payload)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError,
                InvalidReferenceError) as exc:
            raise DataFileError(
                f"Booking file {self.path} is corrupt: {exc}"
            ) from exc

    @staticmethod
    def _decode_bookings(payload: object) -> dict[str, Booking]:
        """Validate stored records before indexing them by reference."""
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")

        records = payload.get("bookings")
        if not isinstance(records, list):
            raise ValueError("The bookings field must be a list")

        bookings = {}

        for position, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                raise ValueError(f"Booking {position} must be an object")

            if not isinstance(record.get("fare"), dict):
                raise ValueError(
                    f"Booking {position} must contain fare conditions"
                )

            reference = record.get("reference")
            if not isinstance(reference, str):
                raise ValueError(
                    f"Booking {position} must have a reference"
                )

            if parse_reference(reference) != reference:
                raise ValueError(
                    f"Booking {position} has a non-canonical reference"
                )

            if reference in bookings:
                raise ValueError(
                    f"Duplicate booking reference: {reference}"
                )

            bookings[reference] = Booking.from_dict(record)

        return bookings

    def _save(self, bookings: dict[str, Booking]) -> None:
        """Write a temporary file and swap it in, so a crash cannot leave a half-written file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps({"bookings": [b.to_dict() for b in bookings.values()]},
                                      indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            raise BookingError(f"Could not save bookings to {self.path}: {exc}") from exc

    #capacity
    def _reserved_capacity(self) -> Counter:
        """Count reserved seats for each offer from confirmed bookings."""
        reserved = Counter()

        for booking in self._bookings.values():
            if booking.status is BookingStatus.CONFIRMED:
                reserved[booking.offer_id] += booking.passengers

        return reserved

    def seats_booked(self, offer_id: str) -> int:
        reserved = self._reserved_capacity()
        return reserved[offer_id]

    def seats_left(self, offer: Offer) -> int:
        """`offer` must carry the original seat count from the data file."""
        return max(0, offer.seats_available - self.seats_booked(offer.offer_id))

    def apply_inventory(self, offers: Sequence[Offer]) -> list[Offer]:
        """Return offers with capacity adjusted for saved bookings."""
        self._bookings = self._load()
        reserved = self._reserved_capacity()
        available_offers = []

        for offer in offers:
            reserved_seats = reserved[offer.offer_id]

            if reserved_seats == 0:
                available_offers.append(offer)
                continue

            remaining_seats = max(
                0,
                offer.seats_available - reserved_seats,
            )
            available_offers.append(offer.with_seats(remaining_seats))

        return available_offers

    # operations

    def _new_reference(self, when: datetime) -> str:
        date_part = f"{when:%y%m%d}"
        for _ in range(200):
            body = "".join(self._rng.choice(ALPHABET) for _ in range(5))
            ref = f"BB-{date_part}-{body}{check_char(date_part, body)}"
            if ref not in self._bookings:
                return ref
        raise BookingError("Could not generate a unique booking reference")
    
    @booking_write
    def book(self, offer: Offer, passenger_name: str, passengers: int = 1, profile: str | None = None) -> Booking:
        """`offer` must be the original catalogue offer (not one already reduced by apply_inventory)."""
        name = validate_name(passenger_name)
        if not 1 <= passengers <= MAX_PASSENGERS:
            raise BookingError(f"Passengers must be between 1 and {MAX_PASSENGERS}")
        now = self._clock()
        if offer.departure <= (self._travel_clock() if self._travel_clock else now):
            raise BookingError(f"{offer.offer_id} departed on {offer.departure:%d %b %Y at %H:%M} "
                               "and can no longer be booked")
        left = self.seats_left(offer)
        if left < passengers:          # confirm seats again at the moment of booking
            raise SeatsUnavailableError(f"{offer.offer_id} has {left} seat(s) left; {passengers} requested")
        
        booking = Booking(
            reference=self._new_reference(now), offer_id=offer.offer_id, company=offer.company.name,
            destination=offer.destination.name, departure=offer.departure, arrival=offer.arrival,
            passenger_name=name, passengers=passengers, unit_price_eur=offer.price_eur,
            total_price_eur=round(offer.price_eur * passengers, 2), fare=offer.fare,
            created_at=now.replace(microsecond=0), profile=profile)
        updated = {**self._bookings, booking.reference: booking}
        self._save(updated)            # persist first; only then change in-memory state
        self._bookings = updated
        log.info("Booked %s: %s x%d on %s for EUR %.2f (%d seat(s) left)", booking.reference, name, passengers,
                 offer.offer_id, booking.total_price_eur, left - passengers)
        return booking

    def get(self, reference: str) -> Booking:
        self._bookings = self._load()
        ref = parse_reference(reference)
        try:
            return self._bookings[ref]
        except KeyError:
            raise BookingNotFoundError(f"No booking with reference {ref}") from None
        
    @booking_write
    def cancel(self, reference: str) -> Booking:
        """Cancel a booking. Refundable fares get the price back minus the cancellation fee."""
        from dataclasses import replace
        booking = self.get(reference)
        if booking.status is BookingStatus.CANCELLED:
            raise BookingError(f"Booking {booking.reference} is already cancelled")
        refund = round(booking.total_price_eur * (1 - self.fee_pct / 100), 2) if booking.fare.refundable else 0.0
        cancelled = replace(booking, status=BookingStatus.CANCELLED, refund_eur=refund,
                            cancelled_at=self._clock().replace(microsecond=0),
                            payment_status="SIMULATED_REFUNDED" if refund else "SIMULATED_PAID_NO_REFUND")
        updated = {**self._bookings, booking.reference: cancelled}
        self._save(updated)
        self._bookings = updated
        log.info("Cancelled %s (%s); refund EUR %.2f", cancelled.reference, cancelled.offer_id, refund)
        return cancelled

    def all(self) -> list[Booking]:
        self._bookings = self._load()
        return sorted(self._bookings.values(), key=lambda b: b.created_at)
