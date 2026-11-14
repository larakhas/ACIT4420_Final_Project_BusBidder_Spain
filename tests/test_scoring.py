"""Normalisers, criteria, weights, ranking order and the generated explanation."""

from dataclasses import replace
from datetime import datetime

import pytest

from bbspain.config import Settings
from bbspain.errors import WeightError
from bbspain.explain import explain
from bbspain.request import DepartureWindow
from bbspain.scoring import CRITERIA, NORMALISERS, Ranker, Weights, criterion
from tests.conftest import make_offer, make_request

CORE = Weights.from_mapping({"price": 40, "duration": 25, "departure": 15, "flexibility": 20})
EQUAL = Weights.from_mapping({"price": 25, "duration": 25, "departure": 25, "flexibility": 25})


def rank(offers, weights=CORE, settings=None, **req):
    return Ranker(settings or Settings()).rank(offers, make_request(**req), weights)


# normalisers

def test_at_least_four_criteria_are_registered():
    assert {"price", "duration", "departure", "flexibility"} <= set(CRITERIA)
    assert len(CRITERIA) >= 4


@pytest.mark.parametrize("name", sorted(NORMALISERS))
def test_every_normaliser_gives_best_100_and_stays_in_range(name, settings):
    scores = NORMALISERS[name]([30.0, 45.0, 60.0, 90.0], True, settings)
    assert scores[0] == 100.0
    assert all(0.0 <= s <= 100.0 for s in scores)
    assert scores == sorted(scores, reverse=True)       # cheaper never scores lower


@pytest.mark.parametrize("name", sorted(NORMALISERS))
def test_higher_is_better_direction(name, settings):
    scores = NORMALISERS[name]([1.0, 2.0, 4.0], False, settings)
    assert scores[2] == 100.0 and scores == sorted(scores)


@pytest.mark.parametrize("name", sorted(NORMALISERS))
def test_equal_values_all_score_100(name, settings):
    assert NORMALISERS[name]([40.0, 40.0, 40.0], True, settings) == [100.0] * 3


@pytest.mark.parametrize("name", sorted(NORMALISERS))
def test_single_value_scores_100(name, settings):
    assert NORMALISERS[name]([55.0], True, settings) == [100.0]


def test_plain_minmax_blows_up_a_one_euro_gap(settings):
    assert NORMALISERS["minmax"]([30.0, 31.0], True, settings) == [100.0, 0.0]


def test_guarded_minmax_keeps_a_small_gap_small(settings):
    low, high = NORMALISERS["guarded_minmax"]([30.0, 31.0], True, settings)
    assert low == 100.0 and high > 80.0


def test_guarded_minmax_still_spreads_large_gaps(settings):
    scores = NORMALISERS["guarded_minmax"]([30.0, 60.0], True, settings)
    assert scores == [100.0, 0.0]


def test_ratio_halves_the_score_at_double_the_price(settings):
    assert NORMALISERS["ratio"]([20.0, 40.0], True, settings) == [100.0, 50.0]


def test_one_extreme_outlier_does_not_collapse_the_others(settings):
    scores = NORMALISERS["ratio"]([30.0, 32.0, 34.0, 400.0], True, settings)
    assert scores[0] == 100.0 and scores[1] > 90.0 and scores[2] > 85.0      # ratio: 400 does not squash 30-34
    mm = NORMALISERS["minmax"]([30.0, 32.0, 34.0, 400.0], True, settings)
    assert mm[2] > 98.0                                                      # min-max squashes them together


# weights

def test_percent_and_fraction_weights_are_equivalent():
    a = Weights.from_mapping({"price": 60, "duration": 40})
    b = Weights.from_mapping({"price": 0.6, "duration": 0.4})
    assert a.values == pytest.approx(b.values)


@pytest.mark.parametrize("mapping,fragment", [
    ({"price": 40, "duration": 25, "departure": 15, "flexibility": 10}, "total"),
    ({"price": 60, "duration": 50}, "total"),
    ({"price": -10, "duration": 110}, "negative"),
    ({"price": 50, "colour": 50}, "Unknown"),
    ({"price": 100}, "At least two"),
    ({}, "No weights"),
    ({"price": "half", "duration": 50}, "number"),
])
def test_invalid_weights_are_rejected(mapping, fragment):
    with pytest.raises(WeightError, match=fragment):
        Weights.from_mapping(mapping)


def test_weights_parse_from_text():
    w = Weights.parse("price=40, duration=25,departure=15,flexibility=20")
    assert w.percent("price") == 40 and w.percent("rating") == 0


@pytest.mark.parametrize("text", ["price:40,duration:60", "price=40,price=60", "price=abc,duration=60"])
def test_bad_weight_text_is_rejected(text):
    with pytest.raises(WeightError):
        Weights.parse(text)


def test_shifted_weights_still_total_one():
    s = CORE.shifted("price", +10)
    assert sum(s.values.values()) == pytest.approx(1.0)
    assert s.values["price"] == pytest.approx(0.5)


def test_shift_outside_0_to_100_is_impossible():
    assert CORE.shifted("price", +70) is None and CORE.shifted("price", -50) is None


# criteria and totals

def test_total_is_weighted_sum_of_criterion_scores():
    offers = [make_offer("a", price=40, minutes=300, changeable=True, refundable=True),
              make_offer("b", price=60, minutes=420)]
    res = rank(offers)
    for s in res.ranked:
        expected = sum(CORE.values[k] * s.scores[k] for k in CORE.used())
        assert s.total == pytest.approx(expected, abs=0.006)


def test_cheaper_faster_more_flexible_offer_wins():
    good = make_offer("good", price=35, minutes=300, changeable=True, refundable=True)
    bad = make_offer("bad", price=60, minutes=500)
    res = rank([bad, good])
    assert [s.offer.offer_id for s in res.ranked] == ["good", "bad"]
    assert res.ranked[0].rank == 1


def test_flexibility_scores():
    f = CRITERIA["flexibility"]
    req = make_request()
    vals = [f.raw(make_offer(changeable=c, refundable=r), req) for c in (True, False) for r in (True, False)]
    assert vals == [100.0, 60.0, 40.0, 0.0]


def test_departure_score_100_inside_and_0_at_tolerance():
    req = make_request(preferred_departure=DepartureWindow.parse("morning"))
    c, s = CRITERIA["departure"], Settings()
    inside = make_offer(departure=datetime(2026, 7, 13, 9, 0))
    at_tol = make_offer(departure=datetime(2026, 7, 13, 15, 0))          # 3 h after 12:00
    far = make_offer(departure=datetime(2026, 7, 13, 21, 0))
    assert c.score_all([inside, at_tol, far], req, s) == [100.0, 0.0, 0.0]


def test_no_departure_preference_means_everyone_scores_100():
    res = rank([make_offer("a", departure=datetime(2026, 7, 13, 3, 0)), make_offer("b")])
    assert all(s.scores["departure"] == 100.0 for s in res.ranked)


def test_transfers_and_rating_scales():
    req = make_request()
    t, r = CRITERIA["transfers"], CRITERIA["rating"]
    s = Settings()
    assert t.score_all([make_offer(transfers=n) for n in (0, 1, 2, 3, 5)], req, s) == [100.0, 60.0, 20.0, 0.0, 0.0]
    assert r.score_all([make_offer(rating=x) for x in (1.0, 3.0, 5.0)], req, s) == [0.0, 50.0, 100.0]


def test_unused_criteria_do_not_change_the_total():
    a = make_offer("a", rating=1.0)
    b = make_offer("b", rating=5.0)
    res = rank([a, b])               # rating weight is 0
    assert res.ranked[0].total == res.ranked[1].total


# missing values and ties

def test_missing_value_gets_neutral_score_and_is_flagged():
    w = Weights.from_mapping({"price": 50, "rating": 50})
    res = rank([make_offer("a", rating=None), make_offer("b", rating=5.0)], w)
    a = next(s for s in res.ranked if s.offer.offer_id == "a")
    assert a.scores["rating"] == 50.0 and a.missing == {"rating"}
    assert any("missing value" in m for m in res.warnings)


def test_missing_does_not_count_as_best_or_worst():
    w = Weights.from_mapping({"price": 50, "rating": 50})
    offers = [make_offer("low", rating=1.0), make_offer("none", rating=None), make_offer("high", rating=5.0)]
    order = [s.offer.offer_id for s in rank(offers, w).ranked]
    assert order == ["high", "none", "low"]


def test_missing_emissions_handled_by_relative_criterion():
    w = Weights.from_mapping({"price": 50, "emissions": 50})
    res = rank([make_offer("a", co2=None), make_offer("b", co2=20.0), make_offer("c", co2=40.0)], w)
    assert next(s for s in res.ranked if s.offer.offer_id == "a").scores["emissions"] == 50.0


def test_all_values_missing_for_a_criterion_is_safe():
    w = Weights.from_mapping({"price": 50, "emissions": 50})
    res = rank([make_offer("a", co2=None), make_offer("b", co2=None)], w)
    assert len(res.ranked) == 2


def test_ties_are_broken_by_price_then_departure_then_id_and_marked():
    a = make_offer("b_id", price=40)
    b = make_offer("a_id", price=40)
    res = rank([a, b], Weights.from_mapping({"departure": 50, "flexibility": 50}))
    assert [s.offer.offer_id for s in res.ranked] == ["a_id", "b_id"]
    assert all(s.tied for s in res.ranked)


def test_ranking_is_reproducible_regardless_of_input_order():
    offers = [make_offer(f"o{i}", price=30 + i % 4, minutes=300 + 10 * (i % 5)) for i in range(12)]
    first = [s.offer.offer_id for s in rank(offers).ranked]
    second = [s.offer.offer_id for s in rank(list(reversed(offers))).ranked]
    assert first == second


def test_no_acceptable_offer_gives_empty_ranking():
    res = rank([make_offer(price=90)], max_price=50)
    assert res.ranked == [] and res.best is None and explain(res) == []


def test_single_acceptable_offer():
    res = rank([make_offer()])
    assert len(res.ranked) == 1 and res.best.rank == 1


def test_dominating_weight_triggers_warning():
    res = rank([make_offer()], Weights.from_mapping({"price": 70, "duration": 30}))
    assert any("dominate" in w for w in res.warnings)
    assert not rank([make_offer()]).warnings or all("dominate" not in w for w in rank([make_offer()]).warnings)


def test_scoring_uses_only_offers_that_passed_the_filter():
    cheap_but_banned = make_offer("cheap", price=10, transfers=3)
    ok_a, ok_b = make_offer("a", price=40), make_offer("b", price=50)
    res = rank([cheap_but_banned, ok_a, ok_b], max_transfers=1)
    assert next(s for s in res.ranked if s.offer.offer_id == "a").scores["price"] == 100.0


def test_normaliser_setting_changes_scores_not_the_pipeline():
    offers = [make_offer("a", price=30), make_offer("b", price=31)]
    w = Weights.from_mapping({"price": 60, "duration": 40})
    mm = Ranker(replace(Settings(), normaliser="minmax")).rank(offers, make_request(), w)
    gm = Ranker(Settings()).rank(offers, make_request(), w)
    assert mm.ranked[1].scores["price"] == 0.0 and gm.ranked[1].scores["price"] > 80


def test_registering_duplicate_criterion_fails():
    with pytest.raises(ValueError, match="already registered"):
        criterion(key="price", label="x", header="x", kind="absolute", scale=lambda v, r, s: v,
                  show=lambda o, r: "", describe=lambda o, r, c: "")(lambda o, r: 1.0)


# explanation

def test_explanation_names_strengths_and_disadvantages():
    best = make_offer("best", price=48, minutes=300, changeable=True, refundable=True)
    other = make_offer("other", price=30, minutes=420)
    res = rank([best, other], max_transfers=1)
    text = "\n".join(explain(res))
    assert res.best.offer.offer_id == "best"
    assert "+ Flexibility" in text
    assert "- Price" in text
    assert "not an objectively best ticket" in text


def test_explanation_mentions_lead_over_runner_up():
    res = rank([make_offer("a", price=40), make_offer("b", price=45)])
    assert any(line.startswith("Lead over #2") for line in explain(res))


def test_explanation_flags_a_narrow_margin():
    res = rank([make_offer("a", price=40.0), make_offer("b", price=40.1)])
    assert any("margin is small" in line for line in explain(res))


def test_explanation_flags_missing_data():
    w = Weights.from_mapping({"price": 50, "rating": 50})
    res = rank([make_offer("a", rating=None, price=30)], w)
    assert any(line.startswith("?") for line in explain(res))


# later refinements (found while reviewing output)

def test_explanation_does_not_praise_departure_when_no_preference_was_set():
    res = rank([make_offer("a", price=30)])             # CORE weights include departure, request has no window
    assert not any("Departure time" in line for line in explain(res))


def test_departure_weight_without_preference_triggers_warning():
    res = rank([make_offer("a"), make_offer("b", price=50)])
    assert any("no effect" in w for w in res.warnings)
    with_pref = rank([make_offer("a")], preferred_departure=DepartureWindow.parse("morning"))
    assert not any("no effect" in w for w in with_pref.warnings)


def test_acronym_labels_keep_their_case():
    from bbspain.scoring import lower_label
    assert lower_label("emissions") == "CO2 emissions" and lower_label("price") == "price"


def test_registering_duplicate_normaliser_fails():
    from bbspain.scoring import normaliser
    with pytest.raises(ValueError, match="already registered"):
        normaliser("ratio")(lambda values, lower, settings: values)


def test_weights_parse_ignores_capitalisation():
    w = Weights.parse("Price=40, DURATION=25,departure=15,Flexibility=20")
    assert w.percent("price") == 40 and w.percent("duration") == 25
