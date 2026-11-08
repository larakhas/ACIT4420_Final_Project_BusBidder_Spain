"""Read the three CSV files, convert values to the right types and check each offer.

If a file is missing, can't be opened or is missing a required column, I raise
DataFileError and stop. If an offer contains impossible or conflicting values,
I set it aside and record every reason I find. The CLI writes these offers and
their reasons to output/rejected_offers.csv so they can be reviewed.

I fix and log differences in capitalisation, accents and spacing in destination
names. If the stated duration doesn't match the departure and arrival times,
I use those times to calculate the duration and log the correction.

I keep missing ratings and CO2 values as None so the scoring model can handle
them. An offer with zero seats is still valid. The seat constraint filters it
out later.

The README and report also explain these rules.
"""


from __future__ import annotations

import csv
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from bbspain.errors import DataFileError
from bbspain.models import Company, Destination, FareConditions, Offer

log = logging.getLogger(__name__)

# Offer ids are structured:  SR_AGP_260713_0831_2
#   company code _ destination code _ YYMMDD _ HHMM _ fare tier (1 basic, 2 flexible)
OFFER_ID = re.compile(r"^(?P<co>[A-Z]{2})_(?P<dest>[A-Z]{3})_(?P<date>\d{6})_(?P<time>\d{4})_(?P<tier>[1-9])$")

OFFER_COLUMNS = ["offer_id", "company_code", "destination", "departure", "arrival", "duration_min",
                 "price_eur", "transfers", "luggage_kg", "fare_name", "changeable", "refundable",
                 "seats_available", "rating", "co2_kg"]
COMPANY_COLUMNS = ["code", "name", "profile"]
DESTINATION_COLUMNS = ["code", "name", "region", "coastal", "distance_km"]

TIME_FORMAT = "%Y-%m-%d %H:%M"
MAX_PRICE_EUR = 500.0
MAX_DURATION_MIN = 24 * 60
MAX_TRANSFERS = 5
RATING_MIN, RATING_MAX = 1.0, 5.0
TRUE_WORDS = {"true", "1", "yes", "y"}
FALSE_WORDS = {"false", "0", "no", "n"}


@dataclass
class Rejected:
    line: int
    offer_id: str
    reasons: list[str]
    raw: dict


@dataclass
class Correction:
    line: int
    offer_id: str
    message: str


@dataclass
class Catalogue:
    companies: dict[str, Company]
    destinations: dict[str, Destination]
    offers: list[Offer]
    rejected: list[Rejected] = field(default_factory=list)
    corrections: list[Correction] = field(default_factory=list)
    rows_read: int = 0

    def destination_by_name(self, text: str) -> Destination:
        """Find a destination by name or code, ignoring case, accents and extra spaces."""
        from bbspain.errors import InvalidRequestError
        key = normalise_name(text)
        for d in self.destinations.values():
            if key in (normalise_name(d.name), d.code.casefold()):
                return d
        raise InvalidRequestError(
            f"Unknown destination '{text}'. Choose one of: {', '.join(sorted(d.name for d in self.destinations.values()))}")

    @property
    def sold_out(self) -> int:
        return sum(1 for o in self.offers if o.seats_available == 0)


def normalise_name(text: str) -> str:
    """'  Cádiz ' -> 'cadiz'. Used to recognise destinations typed in a slightly different way."""
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(stripped.split()).casefold()


# ----------------------------------------------------------------------------- file helpers

def _read_csv(path: Path, required: list[str]) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        raise DataFileError(f"Data file not found: {path}")
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            missing = [c for c in required if c not in (reader.fieldnames or [])]
            if missing:
                raise DataFileError(f"{path.name} is missing required column(s): {', '.join(missing)}")
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise DataFileError(f"Could not read {path}: {exc}") from exc
    if not rows:
        raise DataFileError(f"{path.name} contains no data rows")
    return rows


def _to_bool(text: str) -> bool:
    word = text.strip().casefold()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise ValueError(f"'{text}' is not true/false")


def load_companies(path: Path) -> dict[str, Company]:
    companies = {}
    for row in _read_csv(path, COMPANY_COLUMNS):
        code = row["code"].strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", code):
            raise DataFileError(f"companies.csv: bad company code '{row['code']}'")
        companies[code] = Company(code, row["name"].strip(), row["profile"].strip())
    return companies


def load_destinations(path: Path) -> dict[str, Destination]:
    destinations = {}
    for row in _read_csv(path, DESTINATION_COLUMNS):
        code = row["code"].strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise DataFileError(f"destinations.csv: bad destination code '{row['code']}'")
        try:
            destinations[code] = Destination(code, row["name"].strip(), row["region"].strip(),
                                             _to_bool(row["coastal"]), int(row["distance_km"]))
        except ValueError as exc:
            raise DataFileError(f"destinations.csv: bad value in row for {code}: {exc}") from exc
    return destinations


# ------------------------------------------------------------------------ offer validation

def _parse_time(text: str, label: str, problems: list[str]) -> datetime | None:
    try:
        return datetime.strptime(text.strip(), TIME_FORMAT)
    except ValueError:
        problems.append(f"{label}: '{text}' is not a valid date and time (YYYY-MM-DD HH:MM)")
        return None


def _parse_number(text: str, label: str, problems: list[str], *, integer: bool = False,
                  optional: bool = False):
    text = (text or "").strip()
    if not text:
        if not optional:
            problems.append(f"{label}: missing value")
        return None
    try:
        return int(text) if integer else float(text)
    except ValueError:
        kind = "a whole number" if integer else "a number"
        problems.append(f"{label}: '{text}' is not {kind}")
        return None


def validate_offer(row: dict, line: int, companies: dict[str, Company],
                   destinations: dict[str, Destination], seen_ids: set[str],
                   corrections: list[Correction]) -> tuple[Offer | None, list[str]]:
    """Return (offer, []) if the row is usable, otherwise (None, every reason it is not)."""
    problems: list[str] = []
    offer_id = (row.get("offer_id") or "").strip()

    id_match = OFFER_ID.match(offer_id)
    if not id_match:
        problems.append(f"offer_id: '{offer_id}' does not match the pattern XX_XXX_YYMMDD_HHMM_T")
    elif offer_id in seen_ids:
        problems.append(f"offer_id: duplicate of an offer already loaded")

    company = companies.get((row.get("company_code") or "").strip().upper())
    if company is None:
        problems.append(f"company_code: unknown company '{row.get('company_code')}'")

    wanted = normalise_name(row.get("destination") or "")
    destination = next((d for d in destinations.values() if normalise_name(d.name) == wanted), None)
    if destination is None:
        problems.append(f"destination: unknown destination '{(row.get('destination') or '').strip()}'")

    departure = _parse_time(row.get("departure") or "", "departure", problems)
    arrival = _parse_time(row.get("arrival") or "", "arrival", problems)
    if departure and arrival and arrival <= departure:
        problems.append(f"arrival: {arrival:%Y-%m-%d %H:%M} is not after departure {departure:%Y-%m-%d %H:%M}")

    price = _parse_number(row.get("price_eur"), "price_eur", problems)
    if price is not None and not 0 < price <= MAX_PRICE_EUR:
        problems.append(f"price_eur: must be above 0 and at most {MAX_PRICE_EUR:.0f} (got {price})")
        price = None
    transfers = _parse_number(row.get("transfers"), "transfers", problems, integer=True)
    if transfers is not None and not 0 <= transfers <= MAX_TRANSFERS:
        problems.append(f"transfers: must be 0-{MAX_TRANSFERS} (got {transfers})")
    luggage = _parse_number(row.get("luggage_kg"), "luggage_kg", problems, integer=True)
    if luggage is not None and luggage < 0:
        problems.append(f"luggage_kg: cannot be negative (got {luggage})")
    seats = _parse_number(row.get("seats_available"), "seats_available", problems, integer=True)
    if seats is not None and seats < 0:
        problems.append(f"seats_available: cannot be negative (got {seats})")
    rating = _parse_number(row.get("rating"), "rating", problems, optional=True)
    if rating is not None and not RATING_MIN <= rating <= RATING_MAX:
        problems.append(f"rating: must be between {RATING_MIN:g} and {RATING_MAX:g} (got {rating})")
    co2 = _parse_number(row.get("co2_kg"), "co2_kg", problems, optional=True)
    if co2 is not None and co2 <= 0:
        problems.append(f"co2_kg: must be positive when given (got {co2})")

    flags = {}
    for key in ("changeable", "refundable"):
        try:
            flags[key] = _to_bool(row.get(key) or "")
        except ValueError as exc:
            problems.append(f"{key}: {exc}")
    if not (row.get("fare_name") or "").strip():
        problems.append("fare_name: missing value")

    # the structured id must agree with the row's own fields
    if id_match and company and destination and departure:
        if id_match["co"] != company.code:
            problems.append(f"offer_id: identifier disagrees with company ({company.code})")
        if id_match["dest"] != destination.code:
            problems.append(f"offer_id: identifier disagrees with destination ({destination.code})")
        if id_match["date"] != f"{departure:%y%m%d}" or id_match["time"] != f"{departure:%H%M}":
            problems.append("offer_id: identifier disagrees with the departure date/time")

    if departure and arrival and arrival > departure:
        computed = int((arrival - departure).total_seconds() // 60)
        if computed > MAX_DURATION_MIN:
            problems.append(f"arrival: journey of {computed} min exceeds the {MAX_DURATION_MIN} min plausibility limit")
        stated = _parse_number(row.get("duration_min"), "duration_min", [], integer=True, optional=True)
        if not problems and stated is not None and abs(stated - computed) > 1:
            corrections.append(Correction(line, offer_id,
                                          f"duration_min {stated} -> {computed} (recomputed from timestamps)"))
        if destination and row.get("destination", "").strip() != destination.name and not problems:
            corrections.append(Correction(line, offer_id,
                                          f"destination '{row['destination']}' -> '{destination.name}' (normalised)"))

    if problems:
        return None, problems

    return Offer(
        offer_id=offer_id, company=company, destination=destination, departure=departure, arrival=arrival,
        price_eur=round(price, 2), transfers=transfers,
        fare=FareConditions(row["fare_name"].strip(), flags["changeable"], flags["refundable"], luggage),
        seats_available=seats, rating=rating, co2_kg=co2,
    ), []


def load_catalogue(data_dir: Path) -> Catalogue:
    """Load and validate everything in `data_dir`. Raises DataFileError for fatal problems."""
    data_dir = Path(data_dir)
    companies = load_companies(data_dir / "companies.csv")
    destinations = load_destinations(data_dir / "destinations.csv")
    rows = _read_csv(data_dir / "offers.csv", OFFER_COLUMNS)

    catalogue = Catalogue(companies, destinations, [], rows_read=len(rows))
    seen: set[str] = set()
    for line, row in enumerate(rows, start=2):  # line 1 is the header
        offer, problems = validate_offer(row, line, companies, destinations, seen, catalogue.corrections)
        if offer is None:
            catalogue.rejected.append(Rejected(line, (row.get("offer_id") or "").strip(), problems, row))
            log.warning("Rejected line %d (%s): %s", line, row.get("offer_id"), "; ".join(problems))
            continue
        seen.add(offer.offer_id)
        catalogue.offers.append(offer)

    for c in catalogue.corrections:
        log.info("Corrected line %d (%s): %s", c.line, c.offer_id, c.message)
    log.info("Loaded %d offers (%d rejected, %d corrected) from %s", len(catalogue.offers),
             len(catalogue.rejected), len(catalogue.corrections), data_dir)
    return catalogue


def write_rejected(rejected: list[Rejected], path: Path) -> None:
    """Save the quarantined rows, with their reasons, for human review."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["line", "offer_id", "reasons"] + OFFER_COLUMNS)
        for r in rejected:
            writer.writerow([r.line, r.offer_id, " | ".join(r.reasons)] + [r.raw.get(c, "") for c in OFFER_COLUMNS])
