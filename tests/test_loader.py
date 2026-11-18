"""Loading and validation: normal, invalid, missing-data and boundary cases."""

import csv
from pathlib import Path

import pytest

from bbspain.errors import DataFileError, InvalidRequestError
from bbspain.loader import (
    OFFER_COLUMNS, OFFER_ID, load_catalogue, load_destinations,
    normalise_name, validate_offer, write_rejected
)

GOOD = dict(offer_id="SR_AGP_260713_0900_1", company_code="SR", destination="Malaga",
            departure="2026-07-13 09:00", arrival="2026-07-13 16:00", duration_min="420", price_eur="40.00",
            transfers="0", luggage_kg="20", fare_name="Saver", changeable="false", refundable="false",
            seats_available="10", rating="4.0", co2_kg="30.0")


@pytest.fixture
def refs(project):
    cat = load_catalogue(project / "data")
    return cat.companies, cat.destinations


def check(refs, **changes):
    companies, destinations = refs
    row = {**GOOD, **changes}
    corrections = []
    offer, problems = validate_offer(row, 2, companies, destinations, set(), corrections)
    return offer, problems, corrections


def write_data(tmp_path, rows, header=OFFER_COLUMNS):
    """Write a minimal data folder whose offers.csv holds `rows`."""
    (tmp_path / "companies.csv").write_text("code,name,profile\nSR,SolRuta,cheap\n")
    (tmp_path / "destinations.csv").write_text("code,name,region,coastal,distance_km\nAGP,Malaga,Andalusia,true,530\n")
    with open(tmp_path / "offers.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return tmp_path


# real dataset

def test_real_dataset_covers_all_75_combinations(project):
    cat = load_catalogue(project / "data")
    assert len(cat.companies) == 5 and len(cat.destinations) == 15
    assert len({(o.company.code, o.destination.code) for o in cat.offers}) == 75


def test_real_dataset_rejects_13_corrects_3(project):
    cat = load_catalogue(project / "data")
    assert len(cat.rejected) == 13
    assert len(cat.corrections) == 3
    assert cat.rows_read == len(cat.offers) + len(cat.rejected)


def test_load_is_deterministic(project):
    a = load_catalogue(project / "data")
    b = load_catalogue(project / "data")
    assert [o.offer_id for o in a.offers] == [o.offer_id for o in b.offers]


# valid row

def test_valid_row_is_accepted(refs):
    offer, problems, corrections = check(refs)
    assert problems == [] and corrections == []
    assert offer.duration_min == 420 and offer.price_eur == 40.0


def test_missing_optional_values_are_kept_as_none(refs):
    offer, problems, _ = check(refs, rating="", co2_kg="")
    assert problems == [] and offer.rating is None and offer.co2_kg is None


def test_zero_seats_is_valid_data(refs):
    offer, problems, _ = check(refs, seats_available="0")
    assert problems == [] and offer.seats_available == 0


# rejections

@pytest.mark.parametrize("field,value,fragment", [
    ("price_eur", "-5", "price_eur"),
    ("price_eur", "0", "price_eur"),
    ("price_eur", "501", "price_eur"),
    ("price_eur", "", "missing"),
    ("price_eur", "cheap", "not a number"),
    ("destination", "Lisbon", "unknown destination"),
    ("company_code", "ZZ", "unknown company"),
    ("departure", "2026-07-32 10:00", "not a valid date"),
    ("departure", "13/07/2026", "not a valid date"),
    ("rating", "5.1", "rating"),
    ("rating", "0.9", "rating"),
    ("seats_available", "-1", "seats_available"),
    ("seats_available", "ten", "whole number"),
    ("transfers", "-1", "transfers"),
    ("transfers", "6", "transfers"),
    ("transfers", "one", "whole number"),
    ("changeable", "maybe", "changeable"),
    ("co2_kg", "-3", "co2_kg"),
    ("fare_name", "", "fare_name"),
])
def test_invalid_field_is_rejected(refs, field, value, fragment):
    offer, problems, _ = check(refs, **{field: value})
    assert offer is None
    assert any(fragment in p for p in problems), problems


@pytest.mark.parametrize("rating", ["1", "5", "1.0", "5.0"])
def test_rating_boundaries_are_accepted(refs, rating):
    assert check(refs, rating=rating)[0] is not None


def test_price_boundary_500_accepted(refs):
    assert check(refs, price_eur="500")[0] is not None


def test_arrival_before_departure_rejected(refs):
    offer, problems, _ = check(refs, arrival="2026-07-13 08:00")
    assert offer is None and any("not after departure" in p for p in problems)


def test_arrival_equal_to_departure_rejected(refs):
    assert check(refs, arrival="2026-07-13 09:00")[0] is None


def test_journey_over_24_hours_rejected(refs):
    offer, problems, _ = check(refs, arrival="2026-07-14 09:01")
    assert offer is None and any("plausibility" in p for p in problems)


def test_journey_of_exactly_24_hours_accepted(refs):
    assert check(refs, arrival="2026-07-14 09:00", duration_min="1440")[0] is not None


def test_all_reasons_are_reported_together(refs):
    offer, problems, _ = check(refs, price_eur="-1", rating="9", seats_available="-2")
    assert offer is None and len(problems) == 3


# regex-validated identifiers

@pytest.mark.parametrize("text", ["SR_AGP_260713_0900_1", "CE_BCN_261231_2359_2"])
def test_offer_id_pattern_matches_valid(text):
    assert OFFER_ID.match(text)


@pytest.mark.parametrize("text", ["", "SR-AGP-260713-0900-1", "sr_agp_260713_0900_1", "SR_AGP_260713_900_1",
                                  "SR_AGP_2607_0900_1", "SR_AGP_260713_0900_0", "SR_AGP_260713_0900_1_X"])
def test_offer_id_pattern_rejects_invalid(text):
    assert not OFFER_ID.match(text)


@pytest.mark.parametrize("changes", [
    dict(offer_id="CE_AGP_260713_0900_1"),     # company disagrees
    dict(offer_id="SR_VLC_260713_0900_1"),     # destination disagrees
    dict(offer_id="SR_AGP_260714_0900_1"),     # date disagrees
    dict(offer_id="SR_AGP_260713_0915_1"),     # time disagrees
])
def test_id_must_agree_with_row_fields(refs, changes):
    offer, problems, _ = check(refs, **changes)
    assert offer is None and any("disagrees" in p for p in problems)


def test_duplicate_id_rejected(project):
    cat = load_catalogue(project / "data")
    assert any("duplicate" in r.reasons[0] for r in cat.rejected)


# corrections

def test_destination_is_normalised_and_logged(refs):
    offer, problems, corrections = check(refs, destination="  malaga ")
    assert problems == [] and offer.destination.name == "Malaga"
    assert any("normalised" in c.message for c in corrections)


def test_wrong_duration_is_recomputed(refs):
    offer, _, corrections = check(refs, duration_min="999")
    assert offer.duration_min == 420
    assert any("recomputed" in c.message for c in corrections)


def test_duration_off_by_one_minute_is_not_corrected(refs):
    _, _, corrections = check(refs, duration_min="421")
    assert corrections == []


def test_normalise_name_handles_accents_and_spaces():
    assert normalise_name("  Cádiz ") == "cadiz"
    assert normalise_name("SAN   Sebastián") == "san sebastian"


# fatal errors

def test_missing_file_is_fatal(tmp_path):
    with pytest.raises(DataFileError, match="not found"):
        load_catalogue(tmp_path)


def test_missing_column_is_fatal(tmp_path):
    write_data(tmp_path, [GOOD], header=[c for c in OFFER_COLUMNS if c != "price_eur"])
    with pytest.raises(DataFileError, match="price_eur"):
        load_catalogue(tmp_path)


def test_empty_offer_file_is_fatal(tmp_path):
    write_data(tmp_path, [])
    with pytest.raises(DataFileError, match="no data rows"):
        load_catalogue(tmp_path)


def test_bad_company_code_is_fatal(tmp_path):
    write_data(tmp_path, [GOOD])
    (tmp_path / "companies.csv").write_text("code,name,profile\nsolruta,SolRuta,cheap\n")
    with pytest.raises(DataFileError, match="company code"):
        load_catalogue(tmp_path)


def test_minimal_valid_folder_loads(tmp_path):
    write_data(tmp_path, [GOOD])
    cat = load_catalogue(tmp_path)
    assert len(cat.offers) == 1 and not cat.rejected


def test_destination_lookup_by_name_and_code(project):
    cat = load_catalogue(project / "data")
    assert cat.destination_by_name("  MÁLAGA".replace("Á", "A")).code == "AGP"
    assert cat.destination_by_name("agp").name == "Malaga"
    with pytest.raises(InvalidRequestError, match="Unknown destination"):
        cat.destination_by_name("Atlantis")


def test_rejected_rows_are_written_for_review(project, tmp_path):
    cat = load_catalogue(project / "data")
    out = tmp_path / "out" / "rejected.csv"
    write_rejected(cat.rejected, out)
    rows = list(csv.reader(open(out, encoding="utf-8")))
    assert rows[0][:3] == ["line", "offer_id", "reasons"] and len(rows) == 14

@pytest.mark.parametrize("distance", ["-10", "0"])
def test_invalid_destination_distance(tmp_path, distance):
    path = tmp_path / "destinations.csv"

    path.write_text(
        "code,name,region,coastal,distance_km\n"
        f"AGP,Malaga,Andalusia,true,{distance}\n",
        encoding="utf-8",
    )

    with pytest.raises(DataFileError, match="distance_km must be positive"):
        load_destinations(path)