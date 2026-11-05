"""Shared fixtures and small factories so each test states only what it cares about."""

import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bbspain.config import Settings  # noqa: E402
from bbspain.models import Company, Destination, FareConditions, Offer  # noqa: E402
from bbspain.request import TravelRequest  # noqa: E402

COMPANY = Company("SR", "SolRuta", "test")
MALAGA = Destination("AGP", "Malaga", "Andalusia", True, 530)
VALENCIA = Destination("VLC", "Valencia", "Valencia", True, 355)


def make_offer(offer_id="SR_AGP_260713_0900_1", *, company=COMPANY, destination=MALAGA, departure=None,
               minutes=420, price=40.0, transfers=0, changeable=False, refundable=False, luggage=20,
               seats=10, rating=4.0, co2=30.0, fare_name="Basic") -> Offer:
    departure = departure or datetime(2026, 7, 13, 9, 0)
    return Offer(offer_id, company, destination, departure, departure + timedelta(minutes=minutes), price,
                 transfers, FareConditions(fare_name, changeable, refundable, luggage), seats, rating, co2)


def make_request(destination=MALAGA, **kw) -> TravelRequest:
    kw.setdefault("date_from", date(2026, 7, 12))
    kw.setdefault("date_to", date(2026, 7, 14))
    return TravelRequest(destination, kw.pop("date_from"), kw.pop("date_to"), **kw)


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def project(tmp_path):
    """A private copy of config/ and data/ so CLI tests never touch the real output folders."""
    for name in ("config", "data"):
        shutil.copytree(ROOT / name, tmp_path / name)
    return tmp_path
