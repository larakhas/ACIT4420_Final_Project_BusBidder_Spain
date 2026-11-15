# BusBidder Spain

Final project for ACIT4420 Problem-solving with scripting (OsloMet, Fall 2026).

BusBidder Spain is a fictional marketplace for bus journeys from Madrid to fifteen Spanish
destinations. A traveller describes a trip, five simulated companies return offers, and the
program removes the offers that break a mandatory requirement and ranks the rest with a
weighted scoring model. It explains why the top offer ranks first and lets the traveller make
a simulated booking.

## Quick reference

| | |
|---|---|
| Python version | 3.10 or newer |
| Required libraries | None for the application (standard library only); `pytest` 7.0 or newer for the tests |
| Program entry point | `bbspain/__main__.py` |
| Run the application | `python -m bbspain` |
| Run the tests | `python -m pytest` |
| Input files | `data/companies.csv`, `data/destinations.csv`, `data/offers.csv` |
| Configuration files | `config/settings.json`, `config/profiles.json` |

All commands are run from the project folder (the one that contains this file).

## Requirements

- Python 3.10 or newer
- The application itself uses only the Python standard library
- `pytest` 7.0 or newer is needed to run the tests

## Setup

Run these commands from the project folder (the one that contains this file):

```
python -m venv .venv
.venv\Scripts\activate          (Windows)
source .venv/bin/activate       (macOS / Linux)
pip install -r requirements.txt
```

## Running the program

The entry point is `bbspain/__main__.py`. Run it as a module from the project folder:

```
python -m bbspain
```

With no command, the program starts in interactive mode: it asks for a destination, a
traveller profile and the number of passengers, shows the ranking and offers to book one of
the top five.

The same functions are available as commands:

| Command | What it does |
|---|---|
| `python -m bbspain validate` | Data validation report: accepted, rejected and corrected rows |
| `python -m bbspain profiles` | List the traveller profiles with their weights and hard limits |
| `python -m bbspain rank` | Filter and rank offers, and explain the top one |
| `python -m bbspain compare -d Malaga` | Recommended offer for every profile on the same route |
| `python -m bbspain sensitivity -p brief` | Does the winner change when a weight moves by 10 points? |
| `python -m bbspain book --offer <offer id> --name "Rodrigo Vidal"` | Book an offer |
| `python -m bbspain bookings` | List all bookings |
| `python -m bbspain show <reference>` | Show one booking |
| `python -m bbspain cancel <reference>` | Cancel a booking |

Examples:

```
python -m bbspain rank
python -m bbspain rank -p business -d Barcelona
python -m bbspain rank -d Seville --from 2026-07-12 --to 2026-07-13 -n 2
python -m bbspain rank --max-price 45 --max-transfers 0 --show-excluded
python -m bbspain rank --weights price=25,duration=25,departure=25,flexibility=25 --departure evening
python -m bbspain --normaliser minmax rank
python -m bbspain book --offer CL_AGP_260714_0930_2 --name "Rodrigo Vidal" -n 2
```

`rank` uses the destination Malaga, the dates 12-14 July 2026 and the profile `brief` unless
other values are given. `python -m bbspain rank -h` lists every option.

Options that apply to all commands are written before the command: `--root <folder>`,
`--config <file>`, `--normaliser <name>` and `--verbose`.

## Running the tests

```
python -m pytest
```

There are 280 tests. They cover normal use, invalid input, missing data and boundary values.

## Where the files are

| Path | Content |
|---|---|
| `bbspain/` | The application (one module per responsibility, see `docs/architecture.md`) |
| `data/companies.csv` | The five companies |
| `data/destinations.csv` | The fifteen destinations |
| `data/offers.csv` | 2284 offer rows for 10-16 July 2026 |
| `config/settings.json` | Settings for scoring, booking and file locations |
| `config/profiles.json` | The five traveller profiles |
| `tests/` | Automated tests |
| `scripts/generate_data.py` | Creates the three data files from a fixed random seed |
| `scripts/evaluate.py` | Runs the experiments used in the report |
| `scripts/make_examples.sh` | Regenerates everything in `examples/` |
| `examples/` | Saved output used as evidence in the report |
| `docs/` | Architecture description and diagrams |

The program creates these files when it runs. They are not in the repository:

| Path | Content |
|---|---|
| `output/rejected_offers.csv` | Offer rows that failed validation, with every reason |
| `output/bookings.json` | Simulated bookings |
| `logs/busbidder.log` | Log of loading, rejections, searches and bookings |

## Data validation

The program checks every row in `data/offers.csv` when it starts.

- **Fatal errors.** If a data file is missing, cannot be read, is empty or lacks a required
  column, the program stops with an error message.
- **Rejected rows.** A row with an impossible or inconsistent value is set aside and written
  to `output/rejected_offers.csv` together with every reason. Examples are a negative price,
  an unknown company or destination, an invalid date, arrival before departure, a rating
  outside 1-5, a negative seat count, a duplicate offer id and an offer id that does not
  match the row.
- **Corrected rows.** Differences in capitalisation, accents and spacing in destination names
  are fixed. If the stated duration does not match the departure and arrival times, the
  duration is recalculated from the times. Every correction is logged.
- **Missing optional values.** A missing rating or CO2 value is kept as missing. The scoring
  model gives it a neutral score of 50 and marks it with `*` in the ranking.
- **Sold-out offers.** An offer with zero seats is valid data. The seat constraint removes it
  during filtering.

The dataset contains 13 broken rows and 3 rows that need correction on purpose, so that the
validation has real problems to find. `python -m bbspain validate` shows the result.

## Hard constraints and soft preferences

Hard constraints remove an offer before ranking: route, travel dates, free seats and, when the
traveller sets them, maximum price, maximum transfers, maximum duration, minimum luggage
allowance, changeable ticket and refundable ticket.

Soft preferences are scored from 0 to 100 and weighted: price, duration, departure time,
flexibility, transfers, rating and CO2 emissions. Weights must total 100 %. The output of
`rank` lists both groups above the ranking.

## Settings

`config/settings.json` holds the values the program reads at start:

| Setting | Meaning |
|---|---|
| `normaliser` | `guarded_minmax` (default), `minmax` or `ratio` |
| `min_span_fraction` | Smallest spread used by `guarded_minmax`, as a fraction of the best value |
| `departure_tolerance_min` | Minutes outside the preferred window at which the departure score reaches 0 |
| `neutral_score` | Score given to a missing rating or CO2 value |
| `dominance_warning` | The program warns when one weight is above this share |
| `cancellation_fee_pct` | Fee kept when a refundable booking is cancelled |
| `simulated_now` | The date and time the program treats as "now" when it checks whether a bus has left |
| `default_date_from`, `default_date_to` | Travel window used when no dates are given |
| `data_dir`, `output_dir`, `log_file`, `profiles_file` | File locations |

The dataset is fixed in July 2026, so `simulated_now` is set to `2026-07-05 12:00`. With the
value `null` the program uses the real clock, and offers that have already departed cannot be
booked.

## Reproducing the examples

The files in `examples/` are created by one script. On Windows, run it in Git Bash:

```
sh scripts/make_examples.sh
```

If `python3` is not available, use `PYTHON=python sh scripts/make_examples.sh`.

The script works on a temporary copy of `config/` and `data/`, so it never changes your own
bookings or log file.

The ranking results are the same on every run because the dataset comes from a fixed random
seed and ties are sorted in a fixed order. Only the booking reference in
`examples/18_booking_demo.txt` changes, because it is random and contains the current date.

To recreate the dataset itself:

```
python scripts/generate_data.py
```

## Ranking requirements

Custom search weights and traveller profiles must assign positive weights to
price, duration, departure-time convenience and ticket flexibility. Additional
criteria are optional. All weights must total 100% or 1.0.

## Booking storage and locking

Booking and cancellation operations acquire an exclusive local lock before
reloading the booking file, checking the relevant conditions and saving changes.
Other writers receive a clear message asking them to retry.

With the default settings, the lock directory is output/bookings.json.lock.
An interrupted process may leave this directory behind. Remove it manually
only after confirming that no booking process is running.

The booking loader checks the stored structure and rejects duplicate references.
Confirmed bookings are used to calculate reserved capacity in one shared method.