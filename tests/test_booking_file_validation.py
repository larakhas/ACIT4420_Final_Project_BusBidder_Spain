import json
from datetime import datetime

import pytest

from bbspain.booking import BookingStore
from bbspain.errors import DataFileError
from tests.conftest import make_offer


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"bookings": {}},
        {"bookings": [None]},
    ],
)
def test_invalid_booking_structure(tmp_path, payload):
    path = tmp_path / "bookings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DataFileError, match="corrupt"):
        BookingStore(path)


def test_duplicate_references_are_rejected(tmp_path):
    path = tmp_path / "bookings.json"

    def travel_clock():
        return datetime(2026, 7, 5)

    store = BookingStore(path, travel_clock=travel_clock)
    booking = store.book(make_offer(), "Alice Smith")
    record = booking.to_dict()

    path.write_text(
        json.dumps({"bookings": [record, record]}),
        encoding="utf-8",
    )

    with pytest.raises(DataFileError, match="Duplicate booking reference"):
        BookingStore(path)