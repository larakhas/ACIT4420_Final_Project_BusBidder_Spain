"""Domain objects of the marketplace.

All of them are frozen dataclasses: once an offer has been validated nothing can change it by
accident. Seat counts in particular are never edited in place; see booking.py.
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
        f = d["fare"]
        return cls(
            reference=d["reference"], offer_id=d["offer_id"], company=d["company"],
            destination=d["destination"], departure=datetime.fromisoformat(d["departure"]),
            arrival=datetime.fromisoformat(d["arrival"]), passenger_name=d["passenger_name"],
            passengers=int(d["passengers"]), unit_price_eur=float(d["unit_price_eur"]),
            total_price_eur=float(d["total_price_eur"]),
            fare=FareConditions(f["name"], bool(f["changeable"]), bool(f["refundable"]), int(f["luggage_kg"])),
            created_at=datetime.fromisoformat(d["created_at"]), profile=d.get("profile"),
            status=BookingStatus(d["status"]), payment_status=d.get("payment_status", "SIMULATED_PAID"),
            refund_eur=float(d.get("refund_eur", 0.0)),
            cancelled_at=datetime.fromisoformat(d["cancelled_at"]) if d.get("cancelled_at") else None,
        )
