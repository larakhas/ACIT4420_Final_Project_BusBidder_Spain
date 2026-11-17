
"""Define the data classes used in the marketplace.

I use frozen dataclasses to prevent accidental changes to an offer after
validation. Each offer keeps its original seat count. The code in booking.py
uses confirmed bookings to work out how many seats are still available.
"""



from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum


@dataclass(frozen=True)
class Company:
    code: str
    name: str
    profile: str


@dataclass(frozen=True)
class Destination:
    code: str
    name: str
    region: str
    coastal: bool
    distance_km: int


@dataclass(frozen=True)
class FareConditions:
    """What the ticket allows. Stored in full on every booking."""

    name: str
    changeable: bool
    refundable: bool
    luggage_kg: int

    @property
    def flags(self) -> str:
        parts = ("C" if self.changeable else "-") + ("R" if self.refundable else "-")
        return parts

    @property
    def summary(self) -> str:
        if self.changeable and self.refundable:
            return "changeable and refundable"
        if self.changeable:
            return "changeable, not refundable"
        if self.refundable:
            return "refundable, not changeable"
        return "neither changeable nor refundable"


@dataclass(frozen=True)
class Offer:
    offer_id: str
    company: Company
    destination: Destination
    departure: datetime
    arrival: datetime
    price_eur: float
    transfers: int
    fare: FareConditions
    seats_available: int
    rating: float | None = None
    co2_kg: float | None = None

    @property
    def duration_min(self) -> int:
        return int((self.arrival - self.departure).total_seconds() // 60)

    @property
    def luggage_kg(self) -> int:
        return self.fare.luggage_kg

    def with_seats(self, seats: int) -> "Offer":
        return replace(self, seats_available=seats)


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Booking:
    reference: str
    offer_id: str
    company: str
    destination: str
    departure: datetime
    arrival: datetime
    passenger_name: str
    passengers: int
    unit_price_eur: float
    total_price_eur: float
    fare: FareConditions
    created_at: datetime
    profile: str | None = None
    status: BookingStatus = BookingStatus.CONFIRMED
    payment_status: str = "SIMULATED_PAID"
    refund_eur: float = 0.0
    cancelled_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "reference": self.reference, "offer_id": self.offer_id, "company": self.company,
            "destination": self.destination, "departure": self.departure.isoformat(timespec="minutes"),
            "arrival": self.arrival.isoformat(timespec="minutes"), "passenger_name": self.passenger_name,
            "passengers": self.passengers, "unit_price_eur": self.unit_price_eur,
            "total_price_eur": self.total_price_eur,
            "fare": {"name": self.fare.name, "changeable": self.fare.changeable,
                     "refundable": self.fare.refundable, "luggage_kg": self.fare.luggage_kg},
            "created_at": self.created_at.isoformat(timespec="seconds"), "profile": self.profile,
            "status": self.status.value, "payment_status": self.payment_status,
            "refund_eur": self.refund_eur,
            "cancelled_at": self.cancelled_at.isoformat(timespec="seconds") if self.cancelled_at else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Booking":
        import math

        from bbspain.request import MAX_PASSENGERS

        def required_text(value, field):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be non-empty text")
            return value

        def whole_number(value, field, minimum, maximum=None):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field} must be a whole number")
            if value < minimum or (
                maximum is not None and value > maximum
            ):
                raise ValueError(f"{field} is outside the allowed range")
            return value

        def amount(value, field, *, positive=False):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{field} must be a number")
            if not math.isfinite(value):
                raise ValueError(f"{field} must be finite")
            if value < 0 or (positive and value == 0):
                raise ValueError(f"{field} has an invalid amount")
            return float(value)

        def boolean(value, field):
            if not isinstance(value, bool):
                raise ValueError(f"{field} must be true or false")
            return value

        def timestamp(value, field):
            return datetime.fromisoformat(required_text(value, field))

        if not isinstance(d, dict):
            raise ValueError("Booking must be a JSON object")

        fare = d["fare"]
        if not isinstance(fare, dict):
            raise ValueError("fare must be a JSON object")

        passengers = whole_number(
            d["passengers"], "passengers", 1, MAX_PASSENGERS
        )
        unit_price = amount(
            d["unit_price_eur"], "unit_price_eur", positive=True
        )
        total_price = amount(
            d["total_price_eur"], "total_price_eur", positive=True
        )

        expected_total = round(unit_price * passengers, 2)
        if not math.isclose(
            total_price, expected_total, rel_tol=0.0, abs_tol=1e-6
        ):
            raise ValueError(
                "total_price_eur does not match unit_price_eur "
                "multiplied by passengers"
            )

        departure = timestamp(d["departure"], "departure")
        arrival = timestamp(d["arrival"], "arrival")
        created_at = timestamp(d["created_at"], "created_at")
        cancelled_at = (
            timestamp(d["cancelled_at"], "cancelled_at")
            if d.get("cancelled_at") is not None
            else None
        )

        try:
            if arrival <= departure:
                raise ValueError("arrival must be after departure")
            if cancelled_at is not None and cancelled_at < created_at:
                raise ValueError("cancelled_at cannot precede created_at")
        except TypeError as exc:
            raise ValueError("Booking timestamps use incompatible time zones") from exc

        status = BookingStatus(d["status"])
        refund = amount(d.get("refund_eur", 0.0), "refund_eur")

        if refund > total_price:
            raise ValueError("refund_eur cannot exceed total_price_eur")
        if status is BookingStatus.CONFIRMED:
            if cancelled_at is not None or refund != 0:
                raise ValueError(
                    "A confirmed booking cannot have a cancellation or refund"
                )
        elif status is BookingStatus.CANCELLED and cancelled_at is None:
            raise ValueError("A cancelled booking must have cancelled_at")

        refundable = boolean(fare["refundable"], "fare.refundable")
        if refund > 0 and not refundable:
            raise ValueError("A non-refundable fare cannot have a refund")

        profile = d.get("profile")
        if profile is not None:
            required_text(profile, "profile")

        return cls(
            reference=required_text(d["reference"], "reference"),
            offer_id=required_text(d["offer_id"], "offer_id"),
            company=required_text(d["company"], "company"),
            destination=required_text(d["destination"], "destination"),
            departure=departure,
            arrival=arrival,
            passenger_name=required_text(d["passenger_name"], "passenger_name"),
            passengers=passengers,
            unit_price_eur=unit_price,
            total_price_eur=total_price,
            fare=FareConditions(
                required_text(fare["name"], "fare.name"),
                boolean(fare["changeable"], "fare.changeable"),
                refundable,
                whole_number(fare["luggage_kg"], "fare.luggage_kg", 0),
            ),
            created_at=created_at,
            profile=profile,
            status=status,
            payment_status=required_text(
                d.get("payment_status", "SIMULATED_PAID"),
                "payment_status",
            ),
            refund_eur=refund,
            cancelled_at=cancelled_at,
        )