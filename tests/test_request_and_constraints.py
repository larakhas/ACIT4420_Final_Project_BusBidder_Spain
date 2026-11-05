"""The request object (descriptor validation, departure windows) and the hard constraints."""

from datetime import datetime, time

import pytest

from bbspain.constraints import CONSTRAINTS, active_constraints, apply_hard_constraints, hard_constraint
from bbspain.errors import InvalidRequestError
from bbspain.request import DepartureWindow
from tests.conftest import MALAGA, VALENCIA, make_offer, make_request


# ------------------------------------------------------------------------------- request

@pytest.mark.parametrize("field,value", [("passengers", 0), ("passengers", 10), ("passengers", 1.5),
                                         ("max_price", -5), ("max_price", 0), ("max_transfers", -1),
                                         ("max_transfers", 2.5), ("max_duration_min", 10),
                                         ("min_luggage_kg", -1), ("passengers", "2"), ("max_price", True)])
def test_descriptor_rejects_impossible_values(field, value):
    with pytest.raises(InvalidRequestError):
        make_request(**{field: value})


def test_descriptor_also_validates_later_assignment():
    req = make_request()
    with pytest.raises(InvalidRequestError):
        req.max_price = -1
    req.max_price = 30
    assert req.max_price == 30


def test_optional_limits_default_to_none():
    req = make_request()
    assert req.max_price is None and req.max_transfers is None


def test_window_ending_before_start_rejected():
    from datetime import date
    with pytest.raises(InvalidRequestError, match="before it starts"):
        make_request(date_from=date(2026, 7, 14), date_to=date(2026, 7, 12))


def test_single_day_window_allowed():
    from datetime import date
    assert make_request(date_from=date(2026, 7, 12), date_to=date(2026, 7, 12))


# --------------------------------------------------------------------- departure windows

def test_named_windows_parse():
    assert DepartureWindow.parse("morning").start == 360
    assert DepartureWindow.parse("Evening").end == 22 * 60


def test_any_means_no_preference():
    assert DepartureWindow.parse("any") is None and DepartureWindow.parse("") is None


def test_custom_window_parses():
    w = DepartureWindow.parse("07:00-09:30")
    assert (w.start, w.end) == (420, 570)


@pytest.mark.parametrize("text", ["lunchtime", "7-9", "25:00-26:00", "07:00-07:00", "07:60-08:00"])
def test_bad_windows_rejected(text):
    with pytest.raises(InvalidRequestError):
        DepartureWindow.parse(text)


def test_gap_is_zero_inside_and_grows_outside():
    w = DepartureWindow.parse("morning")
    assert w.gap_min(time(9, 0)) == 0
    assert w.gap_min(time(6, 0)) == 0          # start is inside
    assert w.gap_min(time(13, 0)) == 60
    assert w.gap_min(time(5, 0)) == 60


def test_window_end_is_exclusive_but_has_no_gap():
    w = DepartureWindow.parse("morning")
    assert not w.contains(12 * 60)             # 12:00 is already outside the window...
    assert w.gap_min(time(12, 0)) == 0         # ...but only zero minutes away from it
    assert w.gap_min(time(12, 1)) == 1


def test_night_window_wraps_midnight():
    w = DepartureWindow.parse("night")           # 22:00-04:00
    assert w.gap_min(time(23, 30)) == 0
    assert w.gap_min(time(2, 0)) == 0
    assert w.gap_min(time(5, 0)) == 60
    assert w.gap_min(time(20, 0)) == 120


# ------------------------------------------------------------------------- constraints

def kept(offers, **req):
    return apply_hard_constraints(offers, make_request(**req)).accepted


def test_route_and_dates_scope_offers():
    inside = make_offer("SR_AGP_260713_0900_1")
    wrong_dest = make_offer("SR_VLC_260713_0900_1", destination=VALENCIA)
    wrong_date = make_offer("SR_AGP_260720_0900_1", departure=datetime(2026, 7, 20, 9, 0))
    result = apply_hard_constraints([inside, wrong_dest, wrong_date], make_request())
    assert result.accepted == [inside] and result.in_scope == 1 and result.searched == 3
    assert result.excluded == []             # out-of-scope offers are not "excluded", just not searched


def test_date_window_edges_are_inclusive():
    first = make_offer("a", departure=datetime(2026, 7, 12, 0, 0))
    last = make_offer("b", departure=datetime(2026, 7, 14, 23, 59))
    before = make_offer("c", departure=datetime(2026, 7, 11, 23, 59))
    after = make_offer("d", departure=datetime(2026, 7, 15, 0, 0))
    assert kept([first, last, before, after]) == [first, last]


def test_seat_availability_boundary():
    assert kept([make_offer(seats=2)], passengers=2)
    assert not kept([make_offer(seats=1)], passengers=2)
    assert not kept([make_offer(seats=0)])


def test_budget_boundary_is_inclusive():
    assert kept([make_offer(price=50.0)], max_price=50)
    assert not kept([make_offer(price=50.01)], max_price=50)


def test_max_transfers():
    offers = [make_offer("a", transfers=0), make_offer("b", transfers=1), make_offer("c", transfers=2)]
    assert [o.offer_id for o in kept(offers, max_transfers=1)] == ["a", "b"]
    assert [o.offer_id for o in kept(offers, max_transfers=0)] == ["a"]


def test_max_duration_boundary():
    assert kept([make_offer(minutes=300)], max_duration_min=300)
    assert not kept([make_offer(minutes=301)], max_duration_min=300)


def test_min_luggage():
    assert kept([make_offer(luggage=20)], min_luggage_kg=20)
    assert not kept([make_offer(luggage=19)], min_luggage_kg=20)


def test_changeable_and_refundable_required():
    plain = make_offer("p")
    chg = make_offer("c", changeable=True)
    both = make_offer("b", changeable=True, refundable=True)
    assert [o.offer_id for o in kept([plain, chg, both], require_changeable=True)] == ["c", "b"]
    assert [o.offer_id for o in kept([plain, chg, both], require_refundable=True)] == ["b"]


def test_without_optional_limits_nothing_extra_is_removed():
    worst = make_offer(price=400, transfers=5, minutes=1400, luggage=0)
    assert kept([worst]) == [worst]


def test_excluded_offer_lists_every_broken_constraint():
    bad = make_offer(price=90, transfers=3)
    result = apply_hard_constraints([bad], make_request(max_price=50, max_transfers=1))
    assert result.excluded[0][1] == ["budget", "maximum transfers"]
    assert result.removed_by == {"budget": 1, "maximum transfers": 1}


def test_active_constraints_follow_the_request():
    names = {c.name for c in active_constraints(make_request())}
    assert names == {"route", "dates", "seats"}
    names = {c.name for c in active_constraints(make_request(max_price=40, require_changeable=True))}
    assert {"budget", "changeable"} <= names


def test_registering_duplicate_constraint_name_fails():
    with pytest.raises(ValueError, match="already registered"):
        hard_constraint("budget", "x", describe=lambda r: "")(lambda o, r: True)


def test_new_constraint_is_picked_up_without_other_changes():
    @hard_constraint("test_only_even_price", "even price", describe=lambda r: "price is whole",
                     applies=lambda r: getattr(r, "wants_whole_price", False))
    def _whole(offer, req):
        return offer.price_eur == int(offer.price_eur)
    try:
        req = make_request()
        req.wants_whole_price = True
        res = apply_hard_constraints([make_offer("a", price=40.0), make_offer("b", price=40.5)], req)
        assert [o.offer_id for o in res.accepted] == ["a"]
    finally:
        del CONSTRAINTS["test_only_even_price"]
