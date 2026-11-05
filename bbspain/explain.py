"""Generate a short explanation of the top-ranked offer from the data itself.

The text names strengths (criteria where the offer scores well), remaining disadvantages
(criteria where it scores poorly), and how narrow or wide its lead over the runner-up is. It
never calls the offer "the best": only the best under this traveller's constraints, weights and
scoring assumptions.
"""

from __future__ import annotations

from bbspain.scoring import CRITERIA, RankingResult, lower_label

STRONG, WEAK = 80.0, 60.0


def explain(result: RankingResult) -> list[str]:
    best = result.best
    if best is None:
        return []
    req, w = result.request, result.weights
    pool = [s.offer for s in result.ranked]
    lines = []

    used = [k for k in w.used() if k not in best.missing
            and not (k == "departure" and req.preferred_departure is None)]   # no preference: nothing to praise
    # most influential first, so the explanation leads with what mattered to this traveller
    used.sort(key=lambda k: -w.values[k])
    strengths = [k for k in used if best.scores[k] >= STRONG]
    weaknesses = [k for k in used if best.scores[k] < WEAK]
    for k in strengths:
        lines.append(f"+ {CRITERIA[k].label} {best.scores[k]:.0f}/100: {CRITERIA[k].describe(best.offer, req, pool)}")
    for k in weaknesses:
        lines.append(f"- {CRITERIA[k].label} {best.scores[k]:.0f}/100: {CRITERIA[k].describe(best.offer, req, pool)}")
    for k in sorted(best.missing):
        lines.append(f"? {CRITERIA[k].label}: {CRITERIA[k].describe(best.offer, req, pool)} (a neutral score was used)")
    if not strengths and not weaknesses:
        lines.append("= No criterion stands out; the offer is a balanced compromise.")

    if len(result.ranked) > 1:
        second = result.ranked[1]
        gap = best.total - second.total
        diffs = sorted(((best.contribution(k, w) - second.contribution(k, w), k) for k in w.used()), reverse=True)
        gains = [f"{lower_label(k)} ({d:+.1f})" for d, k in diffs if d > 0.05][:2]
        losses = [f"{lower_label(k)} ({d:+.1f})" for d, k in reversed(diffs) if d < -0.05][:1]
        narrow = "a very narrow" if gap < 2 else "a clear"
        text = f"Lead over #2 ({second.offer.offer_id}, {second.offer.company.name}): {gap:.2f} points, {narrow} margin."
        if gains:
            text += " Gains most on " + ", ".join(gains) + "."
        if losses:
            text += " Loses most on " + ", ".join(losses) + "."
        lines.append(text)
        if gap < 2:
            lines.append("Because the margin is small, small changes in weights could change the winner "
                         "(see the `sensitivity` command).")
    lines.append(f"This is the best match under your hard constraints and these weights ({w.describe()}), "
                 "not an objectively best ticket.")
    return lines
