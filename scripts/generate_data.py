"""Generate the simulated BusBidder Spain dataset.

Run from the project root:  python scripts/generate_data.py

Everything is driven by a fixed random seed, so the three CSV files are byte-identical on
every run. The company rules below are the *assumptions* that make the five fictional
companies behave differently; the report discusses them as a limitation.

offers.csv ends with a block of deliberately broken rows (DIRTY_ROWS). They exist so that the
validation code has real problems to find and the report can show what happens to each one.
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 4207
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FIRST_DAY = datetime(2026, 7, 10)
DAYS = 7  # 10-16 July, so the default 12-14 July window really filters by date

COMPANIES = [
    ("SR", "SolRuta", "Low-cost daytime services"),
    ("CE", "Camino Express", "Fast direct connections between major cities"),
    ("CL", "CostaLink", "Strong coverage of coastal destinations"),
    ("VB", "VerdeBus", "Environment-focused services and modern vehicles"),
    ("NV", "NocheVia", "Overnight and late-evening services"),
]

# code, name, region, coastal, road distance from Madrid (km), major city?
DESTINATIONS = [
    ("BCN", "Barcelona", "Catalonia", True, 620, True),
    ("VLC", "Valencia", "Valencia", True, 355, True),
    ("SVQ", "Seville", "Andalusia", False, 530, True),
    ("AGP", "Malaga", "Andalusia", True, 530, True),
    ("GRX", "Granada", "Andalusia", False, 430, False),
    ("ODB", "Cordoba", "Andalusia", False, 400, False),
    ("BIO", "Bilbao", "Basque Country", False, 400, True),
    ("EAS", "San Sebastian", "Basque Country", True, 470, False),
    ("ZAZ", "Zaragoza", "Aragon", False, 320, True),
    ("ALC", "Alicante", "Valencia", True, 420, False),
    ("MJV", "Murcia", "Murcia", False, 400, False),
    ("SLM", "Salamanca", "Castile and Leon", False, 210, False),
    ("TOL", "Toledo", "Castile-La Mancha", False, 75, False),
    ("SCQ", "Santiago de Compostela", "Galicia", False, 620, False),
    ("CAD", "Cadiz", "Andalusia", True, 650, False),
]

# Fares: (tier digit, name, changeable, refundable, luggage kg)
FARES = {
    "SR": [(1, "Saver", False, False, 15), (2, "Plus", True, False, 20)],
    "CE": [(1, "Standard", True, False, 20), (2, "Premier", True, True, 30)],
    "CL": [(1, "Light", False, False, 15), (2, "Flex", True, True, 25)],
    "VB": [(1, "Green", True, False, 20), (2, "Green Flex", True, True, 25)],
    "NV": [(1, "Night", False, False, 15), (2, "Night Plus", True, False, 20)],
}
# Price multiplier of tier 2 over tier 1
TIER2_MULTIPLIER = {"SR": 1.18, "CE": 1.45, "CL": 1.30, "VB": 1.25, "NV": 1.20}
# Emission factor, kg CO2 per passenger-km (VerdeBus uses newer vehicles)
CO2_PER_KM = {"SR": 0.068, "CE": 0.060, "CL": 0.058, "VB": 0.036, "NV": 0.064}
CO2_MISSING = {"SR": 0.30, "CE": 0.04, "CL": 0.04, "VB": 0.0, "NV": 0.05}
RATING_MEAN = {"SR": 3.5, "CE": 4.4, "CL": 4.0, "VB": 4.3, "NV": 3.7}

HEADER = [
    "offer_id", "company_code", "destination", "departure", "arrival", "duration_min",
    "price_eur", "transfers", "luggage_kg", "fare_name", "changeable", "refundable",
    "seats_available", "rating", "co2_kg",
]


def route_profile(code: str, dest: tuple, rng: random.Random) -> list[dict]:
    """Return one dict per daily departure slot: time, speed, price/km, fixed fee, transfers."""
    _, _, _, coastal, km, major = dest
    if code == "SR":  # cheap, slow, daytime; long routes need a connection
        transfers = 0 if km < 450 else (1 if km < 600 else 2)
        return [dict(t=t, speed=66, per_km=0.058, fee=3.5, transfers=transfers) for t in ("07:30", "11:00", "15:30")]
    if code == "CE":  # fast and expensive; direct between major cities
        if major:
            return [dict(t=t, speed=96, per_km=0.098, fee=9.0, transfers=0) for t in ("06:45", "12:15", "18:30")]
        return [dict(t=t, speed=80, per_km=0.090, fee=8.0, transfers=1 if km > 350 else 0) for t in ("07:15", "16:00")]
    if code == "CL":
        if coastal:  # strong coastal network: two departures, cheap, direct
            return [dict(t=t, speed=84, per_km=0.052, fee=4.5, transfers=0) for t in ("09:30", "15:45")]
        return [dict(t="11:00", speed=70, per_km=0.074, fee=6.0, transfers=1 if km > 250 else 0)]
    if code == "VB":
        return [dict(t=t, speed=80, per_km=0.070, fee=6.0, transfers=0 if km < 500 else rng.choice([0, 0, 1]))
                for t in ("08:15", "14:45")]
    # NV: overnight and late evening, with a long rest stop
    return [dict(t=t, speed=73, per_km=0.057, fee=4.0, transfers=0 if km < 550 else 1) for t in ("21:30", "23:00")]


def offer_rows(rng: random.Random) -> list[list]:
    rows = []
    for code, _, _ in COMPANIES:
        for dest in DESTINATIONS:
            dcode, _, _, _, km, _ = dest
            for slot in route_profile(code, dest, rng):
                for day in range(DAYS):
                    date = FIRST_DAY + timedelta(days=day)
                    hh, mm = map(int, slot["t"].split(":"))
                    dep = date.replace(hour=hh, minute=mm)
                    # small jitter so no two companies depart at identical minutes
                    dep += timedelta(minutes=rng.choice([0, 0, 5, 10, 15]))
                    minutes = km / slot["speed"] * 60 + slot["transfers"] * 35
                    if code == "NV":
                        minutes += 45  # rest stop
                    minutes = int(round(minutes * rng.uniform(0.97, 1.05)))
                    arr = dep + timedelta(minutes=minutes)
                    weekend = 1.12 if dep.weekday() >= 4 else 1.0  # Fri-Sun are dearer
                    base = (slot["fee"] + km * slot["per_km"]) * weekend * rng.uniform(0.93, 1.08)
                    for tier, name, chg, ref, bag in FARES[code]:
                        price = round(base * (TIER2_MULTIPLIER[code] if tier == 2 else 1.0), 2)
                        seats = 0 if rng.random() < 0.05 else rng.randint(1, 48)
                        rating = "" if rng.random() < 0.06 else round(min(5, max(1, rng.gauss(RATING_MEAN[code], 0.35))), 1)
                        co2 = "" if rng.random() < CO2_MISSING[code] else round(km * CO2_PER_KM[code] * rng.uniform(0.95, 1.05), 1)
                        oid = f"{code}_{dcode}_{dep:%y%m%d}_{dep:%H%M}_{tier}"
                        rows.append([
                            oid, code, dest[1], f"{dep:%Y-%m-%d %H:%M}", f"{arr:%Y-%m-%d %H:%M}", minutes,
                            f"{price:.2f}", slot["transfers"], bag, name,
                            str(chg).lower(), str(ref).lower(), seats, rating, co2,
                        ])
    return rows


# Deliberately broken rows appended to offers.csv; the comment names the intended outcome.
DIRTY_ROWS = [
    # REJECT: negative price
    ["SR_AGP_260713_0731_1", "SR", "Malaga", "2026-07-13 07:31", "2026-07-13 15:20", 469, "-9.90", 1, 15, "Saver", "false", "false", 20, 3.4, 30.0],
    # REJECT: unknown destination
    ["SR_LIS_260713_0800_1", "SR", "Lisbon", "2026-07-13 08:00", "2026-07-13 16:00", 480, "40.00", 1, 15, "Saver", "false", "false", 20, 3.4, 30.0],
    # REJECT: impossible calendar date
    ["CL_VLC_260732_1000_1", "CL", "Valencia", "2026-07-32 10:00", "2026-07-32 15:00", 300, "30.00", 0, 15, "Light", "false", "false", 10, 4.0, 20.0],
    # REJECT: arrival before departure
    ["CE_BCN_260713_1100_2", "CE", "Barcelona", "2026-07-13 11:00", "2026-07-13 09:30", 390, "88.00", 0, 30, "Premier", "true", "true", 10, 4.5, 36.0],
    # REJECT: rating outside the 1-5 scale
    ["VB_SVQ_260713_1200_1", "VB", "Seville", "2026-07-13 12:00", "2026-07-13 20:30", 510, "45.00", 0, 20, "Green", "true", "false", 10, 8.2, 19.0],
    # REJECT: missing price
    ["NV_GRX_260713_2100_1", "NV", "Granada", "2026-07-13 21:00", "2026-07-14 05:00", 480, "", 0, 15, "Night", "false", "false", 10, 3.8, 27.0],
    # REJECT: malformed identifier
    ["SR-MLG-123", "SR", "Malaga", "2026-07-13 09:00", "2026-07-13 17:00", 480, "35.00", 1, 15, "Saver", "false", "false", 9, 3.5, 36.0],
    # REJECT: negative seat count
    ["CL_ALC_260713_1300_1", "CL", "Alicante", "2026-07-13 13:00", "2026-07-13 18:30", 330, "28.00", 0, 15, "Light", "false", "false", -3, 4.0, 24.0],
    # REJECT: identifier says Malaga but the row says Cordoba
    ["CE_AGP_260713_1400_1", "CE", "Cordoba", "2026-07-13 14:00", "2026-07-13 18:00", 240, "52.00", 0, 20, "Standard", "true", "false", 10, 4.2, 24.0],
    # REJECT: unknown company code
    ["XB_BCN_260713_1500_1", "XB", "Barcelona", "2026-07-13 15:00", "2026-07-13 23:00", 480, "40.00", 0, 15, "Saver", "false", "false", 10, 3.1, 30.0],
    # REJECT: transfers is not a number
    ["SR_ZAZ_260713_1600_1", "SR", "Zaragoza", "2026-07-13 16:00", "2026-07-13 22:00", 360, "29.00", "one", 15, "Saver", "false", "false", 10, 3.5, 21.0],
    # REJECT: journey longer than the 24 h plausibility limit
    ["NV_SCQ_260713_2200_1", "NV", "Santiago de Compostela", "2026-07-13 22:00", "2026-07-15 23:00", 2940, "50.00", 1, 15, "Night", "false", "false", 10, 3.7, 40.0],
    # REJECT: duplicate of an earlier offer id (copy of the first generated row)
    ["__DUPLICATE_OF_FIRST__"],
    # CORRECT: destination in wrong case and with spaces
    ["VB_VLC_260713_0937_1", "VB", "  valencia ", "2026-07-13 09:37", "2026-07-13 14:30", 293, "27.50", 0, 20, "Green", "true", "false", 12, 4.3, 13.0],
    # CORRECT: accented destination name
    ["CL_CAD_260713_0707_1", "CL", "Cádiz", "2026-07-13 07:07", "2026-07-13 17:30", 623, "39.00", 0, 15, "Light", "false", "false", 12, 4.0, 38.0],
    # CORRECT: stated duration disagrees with the timestamps (recomputed to 270)
    ["CE_BIO_260713_0807_1", "CE", "Bilbao", "2026-07-13 08:07", "2026-07-13 12:37", 999, "55.00", 0, 20, "Standard", "true", "false", 12, 4.4, 24.0],
]


def main() -> None:
    rng = random.Random(SEED)
    DATA_DIR.mkdir(exist_ok=True)

    with open(DATA_DIR / "companies.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "profile"])
        w.writerows(COMPANIES)

    with open(DATA_DIR / "destinations.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "region", "coastal", "distance_km"])
        for code, name, region, coastal, km, _ in DESTINATIONS:
            w.writerow([code, name, region, str(coastal).lower(), km])

    rows = offer_rows(rng)
    with open(DATA_DIR / "offers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
        for row in DIRTY_ROWS:
            w.writerow(rows[0] if row[0] == "__DUPLICATE_OF_FIRST__" else row)

    print(f"Wrote {len(rows)} generated offers + {len(DIRTY_ROWS)} deliberately broken rows to {DATA_DIR}")


if __name__ == "__main__":
    main()
