"""Log important events (loading, rejections, searches, bookings) to a file."""

from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(log_file: Path, verbose: bool = False) -> None:
    root = logging.getLogger("bbspain")
    root.setLevel(logging.DEBUG)
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        root.addHandler(handler)
    except OSError as exc:      # logging must never stop the program
        print(f"Warning: cannot write log file {log_file}: {exc}")
    if verbose:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        root.addHandler(console)
    root.propagate = False
