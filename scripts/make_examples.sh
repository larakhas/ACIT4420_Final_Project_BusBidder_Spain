#!/bin/sh
# Regenerate everything in examples/ (the evidence quoted in the report).
# Run from the project root:   sh scripts/make_examples.sh      (PYTHON=python if python3 is not on PATH)
set -e
PY="${PYTHON:-python3}"
OUT=examples
mkdir -p "$OUT" output logs
rm -f output/bookings.json "$OUT"/*.txt

run() { name="$1"; shift; "$PY" -m bbspain "$@" > "$OUT/$name.txt" 2>&1 || true; echo "wrote $OUT/$name.txt"; }

run 01_validation_report            validate
cp output/rejected_offers.csv "$OUT/rejected_offers.csv"
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
    echo "\$ bbspain $args"; "$PY" -m bbspain $args 2>&1 || echo "(exit status $?)"; echo; done; } > "$OUT/17_errors.txt" 2>&1
echo "wrote $OUT/17_errors.txt"

# booking demo: book the top offer, list, show, cancel; the reference is random on every run
TOP=$("$PY" -m bbspain rank --top 1 | awk '/^ *1 +[A-Z][A-Z]_/ {print $2; exit}')
{
  echo "\$ rank (top offer: $TOP)"; "$PY" -m bbspain rank --top 1 | sed -n '/^ *#/,/^Showing/p'
  echo; echo "\$ book --offer $TOP --name \"Ana Lopez\" --passengers 2"
  BOOK=$("$PY" -m bbspain book --offer "$TOP" --name "Ana Lopez" --passengers 2); echo "$BOOK"
  REF=$(echo "$BOOK" | awk '/Reference/ {print $2}')
  echo; echo "\$ rank (same search again: the booked seats are gone from the top offer)"
  "$PY" -m bbspain rank --top 1 | sed -n '/^ *#/,/^Showing/p'
  echo; echo "\$ bookings"; "$PY" -m bbspain bookings
  echo; echo "\$ cancel $REF"; "$PY" -m bbspain cancel "$REF"
  echo; echo "\$ rank (seats restored)"; "$PY" -m bbspain rank --top 1 | sed -n '/^ *#/,/^Showing/p'
} > "$OUT/18_booking_demo.txt" 2>&1
echo "wrote $OUT/18_booking_demo.txt"

"$PY" scripts/evaluate.py > "$OUT/20_evaluation.txt" 2>&1
echo "wrote $OUT/20_evaluation.txt"

grep -E "Rejected line|Corrected line|Loaded" logs/busbidder.log | tail -20 | sed 's/^[0-9-]* [0-9:,]* //' > "$OUT/19_log_excerpt.txt"
rm -f output/bookings.json
