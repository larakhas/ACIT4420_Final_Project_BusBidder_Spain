#!/bin/sh
# Regenerate everything in examples/ (the evidence quoted in the report).
# Run from the project root:   sh scripts/make_examples.sh      (PYTHON=python if python3 is not on PATH)
#
# The commands run against a temporary copy of config/ and data/, so your own
# output/bookings.json and logs/ are never touched. The copy is removed at the end.
set -e
PY="${PYTHON:-python3}"
OUT=examples
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cp -r config data "$WORK"/
mkdir -p "$OUT"


bb() { "$PY" -m bbspain --root "$WORK" "$@"; }
run() {
    name="$1"
    shift

    if ! bb "$@" > "$OUT/$name.txt" 2>&1; then
        echo "Failed while creating $OUT/$name.txt" >&2
        cat "$OUT/$name.txt" >&2
        exit 1
    fi

    echo "wrote $OUT/$name.txt"
}
run 01_validation_report            validate
cp "$WORK/output/rejected_offers.csv" "$OUT/rejected_offers.csv"
run 02_profiles                     profiles
run 03_rank_brief_malaga            rank
run 04_rank_budget_malaga           rank -p budget
run 05_rank_business_malaga         rank -p business
run 06_rank_tourist_malaga          rank -p tourist
run 07_rank_eco_malaga              rank -p eco
run 08_compare_malaga               compare -d Malaga
run 09_compare_barcelona            compare -d Barcelona
run 10_compare_seville              compare -d Seville
run 11_compare_santiago             compare -d "Santiago de Compostela"
run 12_sensitivity_brief_malaga     sensitivity -p brief
run 13_sensitivity_business_malaga  sensitivity -p business
run 14_rank_brief_minmax            --normaliser minmax rank
run 15_rank_excluded                rank -p brief --show-excluded --top 3
run 16_rank_custom_weights          rank -d Barcelona --weights price=25,duration=25,departure=25,flexibility=25 --departure evening
{ for args in "rank -d Atlantis" "rank --weights price=40,duration=25,departure=15,flexibility=10" "rank --departure teatime" "show BB-123"; do
    echo "\$ bbspain $args"; bb $args 2>&1 || echo "(exit status $?)"; echo; done; } > "$OUT/17_errors.txt" 2>&1
echo "wrote $OUT/17_errors.txt"

# booking demo: book the top offer, list, show, cancel; the reference is random on every run
TOP=$(bb rank --top 1 | awk '/^ *1 +[A-Z][A-Z]_/ {print $2; exit}')
{
  echo "\$ rank (top offer: $TOP)"; bb rank --top 1 | sed -n '/^ *#/,/^Showing/p'
  echo; echo "\$ book --offer $TOP --name \"Rodrigo Vidal\" --passengers 2"
  BOOK=$(bb book --offer "$TOP" --name "Rodrigo Vidal" --passengers 2); echo "$BOOK"
  REF=$(echo "$BOOK" | awk '/Reference/ {print $2}')
  echo; echo "\$ rank (same search again: the booked seats are gone from the top offer)"
  bb rank --top 1 | sed -n '/^ *#/,/^Showing/p'
  echo; echo "\$ bookings"; bb bookings
  echo; echo "\$ cancel $REF"; bb cancel "$REF"
  echo; echo "\$ rank (seats restored)"; bb rank --top 1 | sed -n '/^ *#/,/^Showing/p'
} > "$OUT/18_booking_demo.txt" 2>&1
echo "wrote $OUT/18_booking_demo.txt"

HERE=$(pwd)
( cd "$WORK" && "$PY" "$HERE/scripts/evaluate.py" ) > "$OUT/20_evaluation.txt" 2>&1
echo "wrote $OUT/20_evaluation.txt"

grep -E "Rejected line|Corrected line|Loaded" "$WORK/logs/busbidder.log" | tail -20 | sed 's/^[0-9-]* [0-9:,]* //' > "$OUT/19_log_excerpt.txt"
echo "wrote $OUT/19_log_excerpt.txt"

run 21_seville_afternoon rank -p budget -d Seville --top 3
run 22_seville_any rank -p budget -d Seville --departure any --top 3
