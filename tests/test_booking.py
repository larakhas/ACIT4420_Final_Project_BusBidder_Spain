"""Bookings: references, capacity, persistence, cancellation."""

import json
import random
from datetime import datetime

import pytest

from bbspain.booking import (ALPHABET, REFERENCE, BookingStore, check_char, parse_reference, validate_name)
from bbspain.errors import (BookingError, BookingNotFoundError, DataFileError, InvalidReferenceError,
                            SeatsUnavailableError)
from bbspain.models import BookingStatus
from tests.conftest import make_offer

NOW = datetime(2026, 7, 5, 10, 30, 15)


@pytest.fixture
def store(tmp_path):
    return BookingStore(tmp_path / "bookings.json", rng=random.Random(1), clock=lambda: NOW)


# references

def test_reference_has_expected_format_and_valid_check(store):
    b = store.book(make_offer(), "Rodrigo Vidal")
    assert REFERENCE.match(b.reference)
    assert parse_reference(b.reference) == b.reference


def test_references_are_unique(store):
    refs = {store.book(make_offer(seats=50), "Rodrigo Vidal").reference for _ in range(40)}
    assert len(refs) == 40


def test_reference_alphabet_has_no_lookalikes():
    assert not set("IO01") & set(ALPHABET)


def test_reference_lookup_ignores_case_and_spaces(store):
    b = store.book(make_offer(), "Rodrigo Vidal")
    assert store.get("  " + b.reference.lower() + " ").reference == b.reference


@pytest.mark.parametrize("text", ["", "BB-260705-ABCDEF", "XX-260705-K7Q2XM", "BB-26070-K7Q2XM",
                                  "BB-260705-K7Q2X", "BB-260705-K7Q2XM1", "BB-260705-K7Q2IS"])
def test_malformed_reference_rejected(text):
    with pytest.raises(InvalidReferenceError):
        parse_reference(text)


def test_mistyped_reference_fails_check_character(store):
    ref = store.book(make_offer(), "Rodrigo Vidal").reference
    body = ref[10:15]
    wrong = ref[:10] + ("A" if body[0] != "A" else "B") + body[1:] + ref[-1]
    with pytest.raises(InvalidReferenceError, match="check character"):
        parse_reference(wrong)


def test_well_formed_unknown_reference_not_found(store):
    date_part, body = "260705", "ABCDE"
    ref = f"BB-{date_part}-{body}{check_char(date_part, body)}"
    with pytest.raises(BookingNotFoundError):
        store.get(ref)


# passenger

@pytest.mark.parametrize("name", ["Rodrigo Vidal", "Iñaki Muñoz", "D'Angelo", "Maria-Jose Castro", "Øyvind Sæther"])
def test_valid_names(name):
    assert validate_name(name)


@pytest.mark.parametrize("name", ["", "   ", "R2D2", "Rodrigo_Vidal", "Rodrigo; DROP TABLE", "x" * 61, "--", "Rodrigo  3"])
def test_invalid_names(name):
    with pytest.raises(BookingError):
        validate_name(name)


def test_name_whitespace_is_normalised():
    assert validate_name("  Rodrigo    Vidal ") == "Rodrigo Vidal"


# capacity

def test_booking_reduces_capacity_and_stores_fare(store):
    offer = make_offer(seats=5, changeable=True, refundable=True, price=40.0)
    b = store.book(offer, "Rodrigo Vidal", 2)
    assert store.seats_left(offer) == 3
    assert b.total_price_eur == 80.0 and b.fare.refundable and b.fare.changeable
    assert b.payment_status.startswith("SIMULATED")


def test_catalogue_offer_is_not_mutated(store):
    offer = make_offer(seats=5)
    store.book(offer, "Rodrigo Vidal", 2)
    assert offer.seats_available == 5


def test_cannot_book_more_than_remaining(store):
    offer = make_offer(seats=3)
    store.book(offer, "Rodrigo Vidal", 2)
    with pytest.raises(SeatsUnavailableError, match="1 seat"):
        store.book(offer, "Diego Ramos", 2)
    assert store.seats_left(offer) == 1


def test_can_book_exactly_the_last_seats(store):
    offer = make_offer(seats=2)
    store.book(offer, "Rodrigo Vidal", 2)
    assert store.seats_left(offer) == 0
    with pytest.raises(SeatsUnavailableError):
        store.book(offer, "Diego Ramos", 1)


def test_sold_out_offer_cannot_be_booked(store):
    with pytest.raises(SeatsUnavailableError):
        store.book(make_offer(seats=0), "Rodrigo Vidal")


@pytest.mark.parametrize("n", [0, -1, 10])
def test_passenger_count_limits(store, n):
    with pytest.raises(BookingError):
        store.book(make_offer(seats=50), "Rodrigo Vidal", n)


def test_apply_inventory_subtracts_only_confirmed_seats(store):
    offer = make_offer(seats=5)
    b = store.book(offer, "Rodrigo Vidal", 2)
    assert store.apply_inventory([offer])[0].seats_available == 3
    store.cancel(b.reference)
    assert store.apply_inventory([offer])[0].seats_available == 5


# persistence

def test_bookings_survive_reload(tmp_path):
    path = tmp_path / "b.json"
    offer = make_offer(seats=5, changeable=True)
    first = BookingStore(path, rng=random.Random(2), clock=lambda: NOW)
    b = first.book(offer, "Rodrigo Vidal", 2, profile="business")
    second = BookingStore(path)
    assert second.get(b.reference) == b
    assert second.seats_left(offer) == 3


def test_failed_booking_writes_nothing(store, tmp_path):
    with pytest.raises(SeatsUnavailableError):
        store.book(make_offer(seats=0), "Rodrigo Vidal")
    assert not (tmp_path / "bookings.json").exists()


def test_corrupt_booking_file_is_a_clear_error(tmp_path):
    path = tmp_path / "b.json"
    path.write_text("{not json")
    with pytest.raises(DataFileError, match="corrupt"):
        BookingStore(path)


def test_booking_file_with_wrong_shape_is_a_clear_error(tmp_path):
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"bookings": [{"reference": "x"}]}))
    with pytest.raises(DataFileError):
        BookingStore(path)


def test_no_temporary_file_left_behind(store, tmp_path):
    store.book(make_offer(), "Rodrigo Vidal")
    assert [p.name for p in tmp_path.iterdir()] == ["bookings.json"]


# cancellation

def test_cancel_refundable_returns_price_minus_fee(store):
    offer = make_offer(seats=5, refundable=True, price=50.0)
    b = store.book(offer, "Rodrigo Vidal", 2)
    c = store.cancel(b.reference)
    assert c.status is BookingStatus.CANCELLED and c.refund_eur == 90.0
    assert store.seats_left(offer) == 5


def test_cancel_non_refundable_returns_nothing(store):
    offer = make_offer(seats=5, refundable=False)
    c = store.cancel(store.book(offer, "Rodrigo Vidal").reference)
    assert c.refund_eur == 0.0 and c.payment_status == "SIMULATED_PAID_NO_REFUND"


def test_cannot_cancel_twice(store):
    ref = store.book(make_offer(), "Rodrigo Vidal").reference
    store.cancel(ref)
    with pytest.raises(BookingError, match="already cancelled"):
        store.cancel(ref)


def test_cancel_unknown_reference(store):
    with pytest.raises(BookingNotFoundError):
        store.cancel("BB-260705-" + "AAAAA" + check_char("260705", "AAAAA"))


def test_seat_freed_by_cancellation_can_be_rebooked(store):
    offer = make_offer(seats=1)
    ref = store.book(offer, "Rodrigo Vidal").reference
    store.cancel(ref)
    assert store.book(offer, "Diego Ramos").status is BookingStatus.CONFIRMED


def test_all_lists_in_creation_order(store):
    times = iter(datetime(2026, 7, 5, 10, i) for i in range(5))
    s = BookingStore(store.path, rng=random.Random(3), clock=lambda: next(times))
    refs = [s.book(make_offer(seats=9), "Rodrigo Vidal").reference for _ in range(3)]
    assert [b.reference for b in s.all()] == refs
    
def test_check_character_catches_every_single_character_typo():
    date_part, body = "260705", "K7Q2X"
    good = check_char(date_part, body)
    text = date_part + body
    for i, original in enumerate(text):
        for other in ("0123456789" if i < 6 else ALPHABET):
            if other == original:
                continue
            typo = text[:i] + other + text[i + 1:]
            assert check_char(typo[:6], typo[6:]) != good, f"typo {typo} not detected"


def test_documented_example_reference_is_valid():
    assert parse_reference("BB-260705-K7Q2XZ") == "BB-260705-K7Q2XZ"


def test_cannot_book_a_bus_that_has_left(tmp_path):
    after = datetime(2026, 7, 13, 9, 1)
    s = BookingStore(tmp_path / "b.json", clock=lambda: NOW, travel_clock=lambda: after)
    with pytest.raises(BookingError, match="departed"):
        s.book(make_offer(), "Rodrigo Vidal")
    assert s.all() == []


def test_departure_exactly_now_is_too_late(tmp_path):
    at = datetime(2026, 7, 13, 9, 0)
    s = BookingStore(tmp_path / "b.json", clock=lambda: NOW, travel_clock=lambda: at)
    with pytest.raises(BookingError, match="departed"):
        s.book(make_offer(), "Rodrigo Vidal")


def test_can_book_one_minute_before_departure(tmp_path):
    before = datetime(2026, 7, 13, 8, 59)
    s = BookingStore(tmp_path / "b.json", clock=lambda: NOW, travel_clock=lambda: before)
    assert s.book(make_offer(), "Rodrigo Vidal").status is BookingStatus.CONFIRMED

def test_cannot_cancel_after_departure(tmp_path):
    travel_time = [datetime(2026, 7, 5, 10, 30)]

    store = BookingStore(
        tmp_path / "bookings.json",
        clock=lambda: NOW,
        travel_clock=lambda: travel_time[0],
    )

    offer = make_offer(seats=2, refundable=True)
    booking = store.book(offer, "Rodrigo Vidal")

    # Move the simulated time to the departure
    travel_time[0] = offer.departure

    with pytest.raises(BookingError, match="already departed"):
        store.cancel(booking.reference)

    # The booking must remain confirmed
    assert store.get(booking.reference).status is BookingStatus.CONFIRMED
    assert store.seats_left(offer) == 1