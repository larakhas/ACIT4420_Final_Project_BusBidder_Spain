"""Profiles, sensitivity analysis, settings and the command-line interface."""

import json
import re

import pytest

from bbspain.cli import cmd_interactive, main
from bbspain.config import load_settings
from bbspain.errors import BookingError, ConfigError
from bbspain.loader import load_catalogue
from bbspain.marketplace import Marketplace
from bbspain.profiles import load_profiles
from bbspain.scoring import Weights
from bbspain.sensitivity import normaliser_comparison, weight_sensitivity
from tests.conftest import make_offer, make_request


@pytest.fixture
def mk(project):
    return Marketplace.open(load_settings(project / "config" / "settings.json"), project)


def run(project, capsys, *argv):
    code = main(["--root", str(project), *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


# ---------------------------------------------------------------------------------- profiles

def test_at_least_three_profiles_with_valid_weights(mk):
    assert len(mk.profiles) >= 3
    for p in mk.profiles.values():
        assert sum(p.weights.values.values()) == pytest.approx(1.0)


def test_brief_profile_matches_the_assignment_example(mk):
    p = mk.profile("brief")
    assert [p.weights.percent(k) for k in ("price", "duration", "departure", "flexibility")] == [40, 25, 15, 20]
    assert p.limits["max_price"] == 50 and p.limits["max_transfers"] == 1 and p.limits["require_changeable"]


def test_profile_request_applies_limits_and_overrides(mk):
    dest = mk.catalogue.destination_by_name("Malaga")
    d1, d2 = mk.default_dates()
    req = mk.profile("brief").make_request(dest, d1, d2, 2, max_price=30)
    assert req.max_price == 30 and req.max_transfers == 1 and req.passengers == 2


def test_different_profiles_can_recommend_different_offers(mk):
    winners = {}
    for key, p in mk.profiles.items():
        req = p.make_request(mk.catalogue.destination_by_name("Malaga"), *mk.default_dates())
        winners[key] = mk.search(req, p.weights).best.offer.offer_id
    assert len(set(winners.values())) >= 3


def test_unknown_profile_is_a_config_error(mk):
    with pytest.raises(ConfigError, match="Unknown profile"):
        mk.profile("nobody")


def test_profile_file_with_bad_weights_rejected(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"x": {"name": "X", "description": "d", "weights": {"price": 50, "duration": 10}}}))
    with pytest.raises(ConfigError, match="profile 'x'"):
        load_profiles(f)


def test_profile_file_with_unknown_limit_rejected(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"x": {"name": "X", "description": "d", "weights": {"price": 50, "duration": 50},
                                   "limits": {"max_pricee": 1}}}))
    with pytest.raises(ConfigError, match="unknown limit"):
        load_profiles(f)


def test_profile_file_missing_field_rejected(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"x": {"weights": {"price": 50, "duration": 50}}}))
    with pytest.raises(ConfigError, match="lacks"):
        load_profiles(f)


def test_missing_and_malformed_profile_files(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_profiles(tmp_path / "none.json")
    (tmp_path / "bad.json").write_text("[1,2")
    with pytest.raises(ConfigError, match="Could not read"):
        load_profiles(tmp_path / "bad.json")


# ------------------------------------------------------------------------------- settings

def test_default_settings_without_a_file():
    assert load_settings(None).normaliser == "guarded_minmax"


def test_unknown_setting_rejected(tmp_path):
    f = tmp_path / "s.json"
    f.write_text('{"normalizer": "ratio"}')
    with pytest.raises(ConfigError, match="Unknown setting"):
        load_settings(f)


@pytest.mark.parametrize("body", ['{"normaliser": "magic"}', '{"min_span_fraction": 0}',
                                  '{"departure_tolerance_min": -1}', '{"neutral_score": 120}',
                                  '{"cancellation_fee_pct": 101}', '[]', 'nonsense'])
def test_bad_settings_rejected(tmp_path, body):
    f = tmp_path / "s.json"
    f.write_text(body)
    with pytest.raises(ConfigError):
        load_settings(f)


def test_missing_settings_file_rejected(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "none.json")


# ----------------------------------------------------------------------------- sensitivity

def test_sensitivity_runs_every_used_criterion_in_both_directions(mk, settings):
    p = mk.profile("brief")
    req = p.make_request(mk.catalogue.destination_by_name("Malaga"), *mk.default_dates())
    base, scenarios = weight_sensitivity(mk.current_offers(), req, p.weights, settings)
    assert base and len(scenarios) == 8
    assert all(s.changed == (s.winner_id != base) for s in scenarios)


def test_sensitivity_detects_a_flip(settings):
    cheap = make_offer("cheap", price=30, minutes=480)
    fast = make_offer("fast", price=45, minutes=300)
    w = Weights.from_mapping({"price": 50, "duration": 50})
    base, scenarios = weight_sensitivity([cheap, fast], make_request(), w, settings, step=40)
    assert any(s.changed for s in scenarios)


def test_sensitivity_with_nothing_acceptable(settings):
    base, scenarios = weight_sensitivity([], make_request(), Weights.from_mapping({"price": 50, "duration": 50}), settings)
    assert base is None and all(not s.changed for s in scenarios)


def test_normaliser_comparison_lists_every_method(settings):
    out = normaliser_comparison([make_offer("a"), make_offer("b", price=50)], make_request(),
                                Weights.from_mapping({"price": 50, "duration": 50}), settings)
    assert set(out) == {"guarded_minmax", "minmax", "ratio"}


# --------------------------------------------------------------------------------- CLI

def test_rank_command_shows_constraints_ranking_and_explanation(project, capsys):
    code, out, _ = run(project, capsys, "rank")
    assert code == 0
    assert "Hard constraints" in out and "Soft preferences" in out
    assert "ranks first" in out and "not an objectively best ticket" in out


def test_rank_is_reproducible(project, capsys):
    a = run(project, capsys, "rank", "--top", "0")[1]
    b = run(project, capsys, "rank", "--top", "0")[1]
    assert a == b


def test_override_hard_constraint_changes_result(project, capsys):
    _, loose, _ = run(project, capsys, "rank", "-p", "budget", "--top", "0")
    _, tight, _ = run(project, capsys, "rank", "-p", "budget", "--top", "0", "--max-price", "35")
    count = lambda s: int(re.search(r"(\d+) meet every hard constraint", s).group(1))
    assert count(tight) < count(loose)


def test_custom_weights_option(project, capsys):
    code, out, _ = run(project, capsys, "rank", "--weights", "price=25,duration=25,departure=25,flexibility=25")
    assert code == 0 and "price 25%" in out


@pytest.mark.parametrize("argv,fragment", [
    (["rank", "-d", "Atlantis"], "Unknown destination"),
    (["rank", "-p", "nobody"], "Unknown profile"),
    (["rank", "--weights", "price=40,duration=25"], "total"),
    (["rank", "--departure", "teatime"], "Departure preference"),
    (["rank", "--max-price", "-5"], "max_price"),
    (["rank", "-n", "0"], "passengers"),
    (["show", "BB-bad"], "not a booking reference"),
])
def test_user_errors_exit_with_status_2_and_message(project, capsys, argv, fragment):
    code, _, err = run(project, capsys, *argv)
    assert code == 2 and err.startswith("Error:") and fragment in err


def test_invalid_date_is_a_parser_error(project, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--root", str(project), "rank", "--from", "2026-13-40"])
    assert exc.value.code == 2


def test_missing_data_folder_is_a_clear_error(tmp_path, capsys):
    code = main(["--root", str(tmp_path), "validate"])
    assert code == 2 and "not found" in capsys.readouterr().err


def test_no_acceptable_offers_message(project, capsys):
    code, out, _ = run(project, capsys, "rank", "--max-price", "1")
    assert code == 0 and "No acceptable offers" in out


def test_compare_lists_every_profile(project, capsys, mk):
    _, out, _ = run(project, capsys, "compare", "-d", "Barcelona")
    for p in mk.profiles.values():
        assert p.name in out


def test_validate_and_rejected_file_written(project, capsys):
    _, out, _ = run(project, capsys, "validate")
    assert "Rejected        : 13" in out
    assert (project / "output" / "rejected_offers.csv").is_file()
    assert (project / "logs" / "busbidder.log").read_text().count("Rejected line") == 13


def test_book_show_cancel_flow(project, capsys):
    _, out, _ = run(project, capsys, "rank", "--top", "1")
    offer_id = re.search(r"^\s*1\s+([A-Z]{2}_\w+)", out, re.M).group(1)
    code, out, _ = run(project, capsys, "book", "--offer", offer_id, "--name", "Ana Lopez", "-n", "2")
    assert code == 0 and "Booking confirmation" in out and "SIMULATED" in out
    ref = re.search(r"Reference\s+(BB-\S+)", out).group(1)
    assert ref in run(project, capsys, "bookings")[1]
    assert "CONFIRMED" in run(project, capsys, "show", ref)[1]
    assert "Booking cancelled" in run(project, capsys, "cancel", ref)[1]
    assert "already cancelled" in run(project, capsys, "cancel", ref)[2]


def test_booking_reduces_seats_in_next_search(project, capsys):
    _, out, _ = run(project, capsys, "rank", "--top", "1")
    row = re.search(r"^\s*1\s+([A-Z]{2}_\w+).*?\s(\d+)\s+\|", out, re.M)
    offer_id, seats_before = row.group(1), int(row.group(2))
    run(project, capsys, "book", "--offer", offer_id, "--name", "Ana Lopez", "-n", "3")
    _, out2, _ = run(project, capsys, "rank", "--top", "0")
    row2 = re.search(rf"{offer_id}.*?\s(\d+)\s+\|", out2)
    assert int(row2.group(1)) == seats_before - 3


def test_overbooking_is_refused(project, capsys):
    offer_id = next(o.offer_id for o in load_catalogue(project / "data").offers if o.seats_available == 2)
    assert run(project, capsys, "book", "--offer", offer_id, "--name", "Ana Lopez", "-n", "2")[0] == 0
    code, _, err = run(project, capsys, "book", "--offer", offer_id, "--name", "Bo Berg")
    assert code == 2 and "0 seat" in err


def test_unknown_offer_cannot_be_booked(project, capsys):
    code, _, err = run(project, capsys, "book", "--offer", "SR_AGP_260713_0000_1", "--name", "Ana Lopez")
    assert code == 2 and "No such offer" in err


def test_alternative_config_changes_normalisation(project, capsys):
    code, out, _ = run(project, capsys, "--normaliser", "minmax", "rank")
    assert code == 0 and "[normalisation: minmax]" in out
    assert "[normalisation: guarded_minmax]" in run(project, capsys, "rank")[1]


def test_interactive_flow_books_an_offer(mk):
    answers = iter(["Malaga", "1", "1", "1", "Ana Lopez"])
    lines = []
    cmd_interactive(mk, None, ask=lambda prompt: next(answers), out=lines.append)
    text = "\n".join(lines)
    assert "Booking confirmation" in text and len(mk.bookings.all()) == 1


def test_interactive_recovers_from_bad_input(mk):
    answers = iter(["Atlantis", "Malaga", "9", "1", "x", "1", ""])
    lines = []
    cmd_interactive(mk, None, ask=lambda prompt: next(answers), out=lines.append)
    text = "\n".join(lines)
    assert "Unknown destination" in text and "Please enter a number" in text and "Invalid passenger count" in text
    assert mk.bookings.all() == []
    
def test_interactive_ends_cleanly_when_input_runs_out(project, monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert main(["--root", str(project)]) == 0
    assert "Traceback" not in capsys.readouterr().err


def test_simulated_now_must_be_a_date_and_time(tmp_path):
    f = tmp_path / "s.json"
    f.write_text('{"simulated_now": "next tuesday"}', encoding="utf-8")
    with pytest.raises(ConfigError, match="simulated_now"):
        load_settings(f)


def test_real_clock_refuses_the_july_2026_dataset(project):
    from dataclasses import replace
    settings = replace(load_settings(project / "config" / "settings.json"), simulated_now=None)
    market = Marketplace.open(settings, project)
    with pytest.raises(BookingError, match="departed"):
        market.book(market.catalogue.offers[0].offer_id, "Ana Lopez", 1)
