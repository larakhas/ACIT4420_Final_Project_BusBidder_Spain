"""Facade that wires catalogue, profiles, ranker and bookings together for the CLI."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from bbspain.booking import BookingStore
from bbspain.config import Settings
from bbspain.errors import ConfigError
from bbspain.loader import Catalogue, load_catalogue, write_rejected
from bbspain.models import Booking, Offer
from bbspain.profiles import TravellerProfile, load_profiles
from bbspain.request import TravelRequest
from bbspain.scoring import Ranker, RankingResult, Weights

log = logging.getLogger(__name__)


@dataclass
class Marketplace:
    settings: Settings
    catalogue: Catalogue
    profiles: dict[str, TravellerProfile]
    bookings: BookingStore
    root: Path = field(default_factory=Path.cwd)

    @classmethod
    def open(cls, settings: Settings, root: Path) -> "Marketplace":
        root = Path(root)
        catalogue = load_catalogue(root / settings.data_dir)
        if catalogue.rejected:
            write_rejected(catalogue.rejected, root / settings.output_dir / "rejected_offers.csv")
        profiles = load_profiles(root / settings.profiles_file)
        store = BookingStore(root / settings.output_dir / "bookings.json",
                             cancellation_fee_pct=settings.cancellation_fee_pct)
        return cls(settings, catalogue, profiles, store, root)

    def profile(self, key: str) -> TravellerProfile:
        try:
            return self.profiles[key]
        except KeyError:
            raise ConfigError(f"Unknown profile '{key}'. Available: {', '.join(self.profiles)}") from None

    def current_offers(self) -> list[Offer]:
        """Catalogue offers with seats already booked taken off."""
        return self.bookings.apply_inventory(self.catalogue.offers)

    def search(self, request: TravelRequest, weights: Weights) -> RankingResult:
        result = Ranker(self.settings).rank(self.current_offers(), request, weights)
        log.info("Search %r: %d in scope, %d acceptable, winner %s", request, result.filtered.in_scope,
                 len(result.ranked), result.best.offer.offer_id if result.best else None)
        return result

    def original_offer(self, offer_id: str) -> Offer:
        """The catalogue offer with its original seat count (what BookingStore.book expects)."""
        for o in self.catalogue.offers:
            if o.offer_id == offer_id:
                return o
        from bbspain.errors import BookingError
        raise BookingError(f"No such offer: {offer_id}")

    def book(self, offer_id: str, name: str, passengers: int, profile: str | None = None) -> Booking:
        return self.bookings.book(self.original_offer(offer_id), name, passengers, profile)

    def default_dates(self) -> tuple[date, date]:
        return date.fromisoformat(self.settings.default_date_from), date.fromisoformat(self.settings.default_date_to)
