import json
from datetime import datetime

import pytest

from bbspain.booking import BookingStore
from bbspain.config import load_settings
from bbspain.errors import ConfigError, SeatsUnavailableError, WeightError
from bbspain.scoring import Weights
from tests.conftest import make_offer


@pytest.mark.parametrize("value", ["abc", float("nan"), float("inf")])
def test_invalid_numeric_settings(tmp_path, value):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"departure_tolerance_min": value}))

    with pytest.raises(ConfigError):
        load_settings(path)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_weights(value):
    with pytest.raises(WeightError):
        Weights.from_mapping({
            "price": value,
            "duration": 25,
            "departure": 25,
            "flexibility": 25,
        })


def test_two_instances_preserve_bookings_and_capacity(tmp_path):
    path = tmp_path / "bookings.json"

    def travel_clock():
        return datetime(2026, 7, 5)

    first = BookingStore(path, travel_clock=travel_clock)
    second = BookingStore(path, travel_clock=travel_clock)
    offer = make_offer(seats=2)

    booking_a = first.book(offer, "Alice Smith")
    booking_b = second.book(offer, "Bob Smith")

    references = {booking.reference for booking in first.all()}
    assert references == {booking_a.reference, booking_b.reference}
    assert first.apply_inventory([offer])[0].seats_available == 0

    with pytest.raises(SeatsUnavailableError):
        first.book(offer, "Charlie Smith")
        

@pytest.mark.parametrize("value", [None, 123, [], {}])
def test_passenger_name_requires_text(value):
    from bbspain.booking import validate_name
    from bbspain.errors import BookingError

    with pytest.raises(BookingError, match="must be text"):
        validate_name(value)
        
def test_fresh_lock_blocks_a_booking(tmp_path):
    from bbspain.errors import BookingError
    path = tmp_path / "bookings.json"
    (tmp_path / "bookings.json.lock").mkdir()
    store = BookingStore(path, travel_clock=lambda: datetime(2026, 7, 5, 12, 0))
    with pytest.raises(BookingError, match="busy"):
        store.book(make_offer(), "Rodrigo Vidal")


def test_stale_lock_is_removed(tmp_path):
    import os
    import time
    from bbspain.booking import LOCK_TIMEOUT_SECONDS
    path = tmp_path / "bookings.json"
    lock = tmp_path / "bookings.json.lock"
    lock.mkdir()
    old = time.time() - LOCK_TIMEOUT_SECONDS - 5
    os.utime(lock, (old, old))
    store = BookingStore(path, travel_clock=lambda: datetime(2026, 7, 5, 12, 0))
    booking = store.book(make_offer(), "Rodrigo Vidal")
    assert store.get(booking.reference).passenger_name == "Rodrigo Vidal"
    assert not lock.exists()
        