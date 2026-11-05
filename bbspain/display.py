"""Plain-text rendering. Nothing here makes decisions; it only formats results."""

from __future__ import annotations

from typing import Sequence

from bbspain.constraints import active_constraints
from bbspain.explain import explain
from bbspain.loader import Catalogue
from bbspain.models import Booking
from bbspain.scoring import CRITERIA, RankingResult, hm


def table(headers: Sequence[str], rows: Sequence[Sequence[str]], align_right: Sequence[int] = ()) -> str:
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(str(h)) for i, h in enumerate(headers)]

    def fmt(cells):
        return "  ".join(str(c).rjust(widths[i]) if i in align_right else str(c).ljust(widths[i])
                         for i, c in enumerate(cells)).rstrip()
    return "\n".join([fmt(headers), fmt(["-" * w for w in widths]), *[fmt(r) for r in rows]])


def render_validation(cat: Catalogue) -> str:
    lines = ["Data validation report", "=" * 22,
             f"Companies: {len(cat.companies)}   Destinations: {len(cat.destinations)}   "
             f"Company-destination combinations covered: {len({(o.company.code, o.destination.code) for o in cat.offers})}"
             f"/{len(cat.companies) * len(cat.destinations)}",
             f"Offer rows read : {cat.rows_read}",
             f"Accepted        : {len(cat.offers)}",
             f"Rejected        : {len(cat.rejected)}  (set aside for review in output/rejected_offers.csv)",
             f"Corrected       : {len(cat.corrections)}",
             f"Sold out        : {cat.sold_out}  (valid data; removed later by the seat constraint)",
             f"Missing rating  : {sum(o.rating is None for o in cat.offers)}",
             f"Missing CO2     : {sum(o.co2_kg is None for o in cat.offers)}", ""]
    if cat.rejected:
        lines.append("Rejected rows:")
        for r in cat.rejected:
            lines.append(f"  line {r.line:>4}  {r.offer_id or '(no id)'}: " + "; ".join(r.reasons))
        lines.append("")
    if cat.corrections:
        lines.append("Corrections:")
        for c in cat.corrections:
            lines.append(f"  line {c.line:>4}  {c.offer_id}: {c.message}")
    return "\n".join(lines)


def render_request(result: RankingResult, profile_name: str | None = None) -> str:
    req, w = result.request, result.weights
    title = f"Ranking for {profile_name}" if profile_name else "Ranking"
    lines = [title, "=" * len(title),
             f"Trip: Madrid -> {req.destination.name}, {req.date_from:%d %b} to {req.date_to:%d %b %Y}, "
             f"{req.passengers} passenger(s)",
             "Hard constraints (an offer that breaks any of these is removed BEFORE ranking):"]
    lines += [f"  * {c.describe(req)}" for c in active_constraints(req)]
    lines.append("Soft preferences (scored and weighted; they never remove an offer):")
    if req.preferred_departure:
        lines.append(f"  * preferred departure: {req.preferred_departure.label}")
    lines.append(f"  * weights: {w.describe()}   [normalisation: {result.settings.normaliser}]")
    f = result.filtered
    lines.append("")
    lines.append(f"Searched {f.searched} offers: {f.in_scope} match route and dates, "
                 f"{len(f.accepted)} meet every hard constraint.")
    if f.removed_by:
        lines.append("Removed by: " + ", ".join(f"{k} {v}" for k, v in sorted(f.removed_by.items(), key=lambda kv: -kv[1]))
                     + " (an offer can break several).")
    return "\n".join(lines)


def render_ranking(result: RankingResult, top: int = 10) -> str:
    if not result.ranked:
        return "No acceptable offers: every offer on this route broke at least one hard constraint."
    used = result.weights.used()
    headers = ["#", "Offer ID", "Company", "Date", "Dep", "Arr", "Length", "EUR", "Tr", "Fare", "Seats", "|"] + \
              [CRITERIA[k].header for k in used] + ["Total"]
    rows = []
    shown = result.ranked if top <= 0 else result.ranked[:top]
    for s in shown:
        o = s.offer
        arr = f"{o.arrival:%H:%M}" + (f"+{(o.arrival.date() - o.departure.date()).days}" if o.arrival.date() != o.departure.date() else "")
        cells = [f"{s.rank}{'=' if s.tied else ''}", o.offer_id, o.company.name, f"{o.departure:%d %b}",
                 f"{o.departure:%H:%M}", arr, hm(o.duration_min), f"{o.price_eur:.2f}", str(o.transfers),
                 f"{o.fare.name} {o.fare.flags}", str(o.seats_available), "|"]
        cells += [f"{s.scores[k]:.1f}" + ("*" if k in s.missing else "") for k in used]
        cells.append(f"{s.total:.2f}")
        rows.append(cells)
    numeric = [0, 7, 8, 10] + list(range(12, len(headers)))
    out = [table(headers, rows, align_right=numeric),
           "Scores are 0-100 (100 = best). Total = sum of weight x score. Fare: C = changeable, R = refundable. "
           "* = missing value, neutral score used. = after a rank means a tie.",
           f"Showing {len(shown)} of {len(result.ranked)} acceptable offers (use --top 0 for all)."]
    return "\n".join(out)


def render_explanation(result: RankingResult, profile_name: str | None = None) -> str:
    best = result.best
    if best is None:
        return ""
    who = f" for the {profile_name}" if profile_name else ""
    head = f"Why {best.offer.offer_id} ({best.offer.company.name}, {best.offer.departure:%a %d %b %H:%M}) ranks first{who}:"
    return "\n".join([head, *[f"  {line}" for line in explain(result)]])


def render_warnings(result: RankingResult) -> str:
    return "\n".join(f"Warning: {w}" for w in result.warnings)


def render_excluded(result: RankingResult, limit: int = 15) -> str:
    ex = result.filtered.excluded
    if not ex:
        return "No offers were excluded by hard constraints."
    lines = [f"Excluded offers ({len(ex)}; first {min(limit, len(ex))} shown):"]
    for offer, reasons in ex[:limit]:
        lines.append(f"  {offer.offer_id:<24} EUR {offer.price_eur:>6.2f}  broke: {', '.join(reasons)}")
    return "\n".join(lines)


def render_booking(b: Booking, heading: str = "Booking confirmation") -> str:
    rows = [("Reference", b.reference), ("Status", b.status.value), ("Passenger", f"{b.passenger_name} (x{b.passengers})"),
            ("Journey", f"Madrid -> {b.destination} with {b.company}"),
            ("Departure", f"{b.departure:%a %d %b %Y %H:%M}"), ("Arrival", f"{b.arrival:%a %d %b %Y %H:%M}"),
            ("Fare", f"{b.fare.name}: {b.fare.summary}, {b.fare.luggage_kg} kg luggage"),
            ("Price", f"EUR {b.unit_price_eur:.2f} x {b.passengers} = EUR {b.total_price_eur:.2f}"),
            ("Payment", f"{b.payment_status} (simulated, no real payment)")]
    if b.status.value == "CANCELLED":
        rows.append(("Refund", f"EUR {b.refund_eur:.2f}"))
    w = max(len(k) for k, _ in rows)
    return "\n".join([heading, "=" * len(heading), *[f"  {k:<{w}}  {v}" for k, v in rows]])


def render_bookings(bookings: Sequence[Booking]) -> str:
    if not bookings:
        return "No bookings yet."
    rows = [[b.reference, b.status.value, b.company, b.destination, f"{b.departure:%d %b %H:%M}",
             str(b.passengers), f"{b.total_price_eur:.2f}", b.passenger_name] for b in bookings]
    return table(["Reference", "Status", "Company", "Destination", "Departs", "Pax", "EUR", "Name"], rows, align_right=[5, 6])
