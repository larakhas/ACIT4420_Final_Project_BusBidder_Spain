"""Evaluation experiments used in the report (run from the project root):

    python scripts/evaluate.py > examples/20_evaluation.txt

1. Who wins? For every profile x destination (5 x 15 = 75 searches), which company's offer is
   ranked first. Shows whether some company is systematically favoured or never recommended.
2. Does the normalisation method matter? Re-runs the 75 searches under each normaliser and
   counts the searches whose winner changes.
3. How stable are the winners? Moves each weight by +/-10 points in every search and counts how
   often the winner changes.
4. Missing data: how often is a top-ranked offer one with a missing value?
"""

import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bbspain.config import load_settings  # noqa: E402
from bbspain.logging_setup import configure_logging  # noqa: E402
from bbspain.marketplace import Marketplace  # noqa: E402
from bbspain.scoring import NORMALISERS, Ranker  # noqa: E402
from bbspain.sensitivity import weight_sensitivity  # noqa: E402


def main() -> None:
    root = Path.cwd()
    settings = load_settings(root / "config" / "settings.json")
    configure_logging(root / settings.log_file)      # keep warnings out of the printed report
    mk = Marketplace.open(settings, root)
    offers = mk.catalogue.offers
    d_from, d_to = mk.default_dates()
    cases = [(p, d) for p in mk.profiles.values() for d in sorted(mk.catalogue.destinations.values(), key=lambda x: x.name)]

    print("1. Winning company per profile (15 destinations each)")
    print("-" * 60)
    totals = Counter()
    empty = 0
    for p in mk.profiles.values():
        c = Counter()
        for d in sorted(mk.catalogue.destinations.values(), key=lambda x: x.name):
            best = Ranker(settings).rank(offers, p.make_request(d, d_from, d_to), p.weights).best
            if best is None:
                empty += 1
                continue
            c[best.offer.company.name] += 1
        totals.update(c)
        print(f"  {p.name:<32} " + ", ".join(f"{k} {v}" for k, v in c.most_common()))
    print(f"  {'ALL (75 searches)':<32} " + ", ".join(f"{k} {v}" for k, v in totals.most_common()))
    never = [c.name for c in mk.catalogue.companies.values() if c.name not in totals]
    print(f"  Searches with no acceptable offer: {empty}.  Companies never recommended: {', '.join(never) or 'none'}")

    print("\n2. Winner under each normalisation method (75 searches)")
    print("-" * 60)
    winners = {}
    for name in sorted(NORMALISERS):
        s = replace(settings, normaliser=name)
        winners[name] = [getattr(Ranker(s).rank(offers, p.make_request(d, d_from, d_to), p.weights).best, "offer", None) for p, d in cases]
        winners[name] = [w.offer_id if w else None for w in winners[name]]
    base = winners[settings.normaliser]
    for name, ids in winners.items():
        diff = sum(a != b for a, b in zip(base, ids))
        print(f"  {name:<15} winner differs from {settings.normaliser} in {diff} of {len(cases)} searches")

    print("\n3. Weight sensitivity (+/-10 points on each used weight, 75 searches)")
    print("-" * 60)
    total = changed = fragile = 0
    for p, d in cases:
        req = p.make_request(d, d_from, d_to)
        base_id, scenarios = weight_sensitivity(offers, req, p.weights, settings)
        if base_id is None:
            continue
        total += len(scenarios)
        n = sum(s.changed for s in scenarios)
        changed += n
        fragile += n > 0
    print(f"  {changed} of {total} weight shifts change the winner ({100 * changed / total:.1f}%)")
    print(f"  {fragile} of {len(cases) - empty} searches have at least one shift that changes the winner")

    print("\n4. Missing data among winners")
    print("-" * 60)
    flagged = n_win = 0
    for p, d in cases:
        best = Ranker(settings).rank(offers, p.make_request(d, d_from, d_to), p.weights).best
        if best:
            n_win += 1
            flagged += bool(best.missing)
    print(f"  {flagged} of {n_win} winning offers rely on a neutral score for a missing value")
    print("  Missing CO2 by company: " + ", ".join(
        f"{c.name} {sum(o.co2_kg is None for o in offers if o.company.code == c.code) / sum(o.company.code == c.code for o in offers):.0%}"
        for c in mk.catalogue.companies.values()))


if __name__ == "__main__":
    main()
