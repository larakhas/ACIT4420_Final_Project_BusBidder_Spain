"""Command-line interface: subcommands for scripting and an interactive guided mode."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Callable

from bbspain import display
from bbspain.config import load_settings
from bbspain.errors import BookingError, BusBidderError, InvalidRequestError
from bbspain.logging_setup import configure_logging
from bbspain.marketplace import Marketplace
from bbspain.request import DepartureWindow
from bbspain.scoring import CRITERIA, NORMALISERS, Weights
from bbspain.sensitivity import normaliser_comparison, weight_sensitivity

EXIT_USER_ERROR = 2


def iso_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a valid date (use YYYY-MM-DD)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bbspain", description="BusBidder Spain: filter and rank bus offers from Madrid.")
    p.add_argument("--root", type=Path, default=Path.cwd(), help="project folder holding config/ and data/ (default: cwd)")
    p.add_argument("--config", type=Path, help="settings file (default: <root>/config/settings.json)")
    p.add_argument("--normaliser", choices=sorted(NORMALISERS), help="override the normalisation method")
    p.add_argument("--verbose", action="store_true", help="also print log messages to the terminal")
    sub = p.add_subparsers(dest="command")

    def search_options(sp, with_profile=True):
        sp.add_argument("-d", "--destination", default="Malaga", help="name or code (default: Malaga)")
        sp.add_argument("--from", dest="date_from", type=iso_date, help="first travel date YYYY-MM-DD")
        sp.add_argument("--to", dest="date_to", type=iso_date, help="last travel date YYYY-MM-DD")
        sp.add_argument("-n", "--passengers", type=int, default=1)
        if with_profile:
            sp.add_argument("-p", "--profile", default="brief", help="traveller profile (see `profiles`)")
        g = sp.add_argument_group("hard constraints (override the profile)")
        g.add_argument("--max-price", type=float, help="EUR per ticket")
        g.add_argument("--max-transfers", type=int)
        g.add_argument("--max-duration-min", type=int, help="journey length in minutes")
        g.add_argument("--min-luggage-kg", type=int)
        g.add_argument("--require-changeable", action="store_true", default=None)
        g.add_argument("--require-refundable", action="store_true", default=None)
        s = sp.add_argument_group("soft preferences (scored, never remove offers)")
        s.add_argument("--departure", help="morning|afternoon|evening|night|HH:MM-HH:MM|any")
        s.add_argument("--weights", help="percentages, e.g. price=40,duration=25,departure=15,flexibility=20")

    r = sub.add_parser("rank", help="filter and rank offers, explain the top one")
    search_options(r)
    r.add_argument("--top", type=int, default=10, help="rows to show (0 = all)")
    r.add_argument("--show-excluded", action="store_true", help="list offers removed by hard constraints")

    c = sub.add_parser("compare", help="same offers, every profile side by side")
    search_options(c, with_profile=False)

    s = sub.add_parser("sensitivity", help="does the winner survive +/-10 point weight changes?")
    search_options(s)

    sub.add_parser("profiles", help="list traveller profiles")
    sub.add_parser("validate", help="data validation report")

    b = sub.add_parser("book", help="book an offer")
    b.add_argument("--offer", required=True, help="offer id")
    b.add_argument("--name", required=True, help="passenger name")
    b.add_argument("-n", "--passengers", type=int, default=1)
    b.add_argument("-p", "--profile", help="profile used to find the offer (stored with the booking)")
    sub.add_parser("bookings", help="list bookings")
    sh = sub.add_parser("show", help="show one booking")
    sh.add_argument("reference")
    cn = sub.add_parser("cancel", help="cancel a booking")
    cn.add_argument("reference")
    sub.add_parser("interactive", help="guided search, ranking and booking")
    return p


# -------------------------------------------------------------------------------- helpers

def request_and_weights(mk: Marketplace, args, profile_key: str):
    prof = mk.profile(profile_key)
    d_from, d_to = mk.default_dates()
    destination = mk.catalogue.destination_by_name(args.destination)
    overrides = {k: getattr(args, k, None) for k in ("max_price", "max_transfers", "max_duration_min",
                                                      "min_luggage_kg", "require_changeable", "require_refundable")}
    if getattr(args, "departure", None) is not None:
        DepartureWindow.parse(args.departure)           # fail early with a clear message
        overrides["departure"] = args.departure
    request = prof.make_request(destination, args.date_from or d_from, args.date_to or d_to,
                                args.passengers, **overrides)
    weights = Weights.parse(args.weights) if getattr(args, "weights", None) else prof.weights
    return prof, request, weights


def print_result(mk, prof, request, weights, top, show_excluded=False, out=print, label=None):
    label = label or prof.name
    result = mk.search(request, weights)
    out(display.render_request(result, label))
    out("")
    out(display.render_ranking(result, top))
    if result.warnings:
        out("")
        out(display.render_warnings(result))
    if result.best:
        out("")
        out(display.render_explanation(result, label))
    if show_excluded:
        out("")
        out(display.render_excluded(result))
    return result


# ------------------------------------------------------------------------------- commands

def cmd_rank(mk, args):
    prof, request, weights = request_and_weights(mk, args, args.profile)
    label = prof.name + (" (custom weights)" if args.weights else "")
    print_result(mk, prof, request, weights, args.top, args.show_excluded, label=label)


def cmd_compare(mk, args):
    args.profile = None
    d_from, d_to = mk.default_dates()
    destination = mk.catalogue.destination_by_name(args.destination)
    rows, details = [], []
    scope = None
    for key, prof in mk.profiles.items():
        _, request, weights = request_and_weights(mk, args, key)
        result = mk.search(request, weights)
        scope = result.filtered.in_scope
        b = result.best
        if b is None:
            rows.append([prof.name, "0", "(none)", "", "", "", "", "", ""])
            continue
        o = b.offer
        rows.append([prof.name, str(len(result.ranked)), o.offer_id, o.company.name, f"{o.price_eur:.2f}",
                     display.hm(o.duration_min), f"{o.departure:%a %H:%M}", f"{o.fare.name} {o.fare.flags}",
                     f"{b.total:.2f}"])
    print(f"Profile comparison: Madrid -> {destination.name}, {(args.date_from or d_from):%d %b} to "
          f"{(args.date_to or d_to):%d %b %Y}")
    print(f"Every profile starts from the same {scope} offers on this route and dates.\n")
    print(display.table(["Profile", "Acceptable", "Recommended", "Company", "EUR", "Length", "Departs", "Fare", "Score"],
                        rows, align_right=[1, 4, 8]))


def cmd_sensitivity(mk, args):
    prof, request, weights = request_and_weights(mk, args, args.profile)
    offers = mk.current_offers()
    base, scenarios = weight_sensitivity(offers, request, weights, mk.settings)
    print(f"Weight sensitivity for {prof.name}: Madrid -> {request.destination.name}")
    print(f"Baseline winner: {base}   weights: {weights.describe()}\n")
    rows = [[s.description, s.winner_id or "(none)", "CHANGED" if s.changed else "same"] for s in scenarios]
    print(display.table(["Scenario", "Winner", "Result"], rows))
    same = sum(not s.changed for s in scenarios)
    print(f"\nThe winner is unchanged in {same} of {len(scenarios)} scenarios.")
    print("\nWinner under each normalisation method (weights unchanged):")
    for name, wid in normaliser_comparison(offers, request, weights, mk.settings).items():
        print(f"  {name:<15} {wid}")


def cmd_profiles(mk, args):
    for p in mk.profiles.values():
        print(f"{p.key:<9} {p.name}\n          {p.description}\n          weights: {p.weights.describe()}")
        if p.limits:
            print("          hard limits: " + ", ".join(f"{k}={v}" for k, v in p.limits.items()))
        print()


def cmd_validate(mk, args):
    print(display.render_validation(mk.catalogue))


def cmd_book(mk, args):
    booking = mk.book(args.offer, args.name, args.passengers, args.profile)
    print(display.render_booking(booking))


def cmd_bookings(mk, args):
    print(display.render_bookings(mk.bookings.all()))


def cmd_show(mk, args):
    print(display.render_booking(mk.bookings.get(args.reference), "Booking"))


def cmd_cancel(mk, args):
    print(display.render_booking(mk.bookings.cancel(args.reference), "Booking cancelled"))


def cmd_interactive(mk, args, ask: Callable[[str], str] = input, out=print):
    """Guided flow: pick destination and profile, see the ranking, optionally book."""
    out("BusBidder Spain: find and book a bus from Madrid. (Ctrl+C to quit)\n")
    names = sorted(d.name for d in mk.catalogue.destinations.values())
    out("Destinations: " + ", ".join(names))
    while True:
        try:
            destination = mk.catalogue.destination_by_name(ask("Destination: "))
            break
        except InvalidRequestError as exc:
            out(f"  {exc}")
    keys = list(mk.profiles)
    for i, k in enumerate(keys, 1):
        out(f"  {i}. {mk.profiles[k].name}: {mk.profiles[k].description}")
    while True:
        choice = ask(f"Profile [1-{len(keys)}] (Enter = 1): ").strip() or "1"
        if choice.isdigit() and 1 <= int(choice) <= len(keys):
            break
        out("  Please enter a number from the list.")
    prof = mk.profiles[keys[int(choice) - 1]]
    d_from, d_to = mk.default_dates()
    while True:
        try:
            n = int(ask("Passengers (Enter = 1): ").strip() or "1")
            request = prof.make_request(destination, d_from, d_to, n)
            break
        except (ValueError, InvalidRequestError) as exc:
            out(f"  Invalid passenger count: {exc}")
    result = print_result(mk, prof, request, prof.weights, top=5, out=out)
    if not result.best:
        return
    pick = ask("\nBook one? Enter its rank (1-5) or press Enter to quit: ").strip()
    if not pick:
        return
    if not (pick.isdigit() and 1 <= int(pick) <= min(5, len(result.ranked))):
        out("  Not a rank in the list; nothing booked.")
        return
    chosen = result.ranked[int(pick) - 1].offer
    name = ask("Passenger name: ")
    try:
        booking = mk.book(chosen.offer_id, name, n, prof.key)
    except BookingError as exc:
        out(f"  Booking failed: {exc}")
        return
    out("\n" + display.render_booking(booking))


COMMANDS = {"rank": cmd_rank, "compare": cmd_compare, "sensitivity": cmd_sensitivity, "profiles": cmd_profiles,
            "validate": cmd_validate, "book": cmd_book, "bookings": cmd_bookings, "show": cmd_show,
            "cancel": cmd_cancel, "interactive": cmd_interactive}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "interactive"
    try:
        config_path = args.config or (args.root / "config" / "settings.json")
        settings = load_settings(config_path if config_path.exists() or args.config else None)
        if args.normaliser:
            settings = replace(settings, normaliser=args.normaliser)
        configure_logging(args.root / settings.log_file, args.verbose)
        mk = Marketplace.open(settings, args.root)
        if command == "interactive" and not hasattr(args, "passengers"):
            args.passengers = 1
        COMMANDS[command](mk, args)
        return 0
    except BusBidderError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USER_ERROR
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
