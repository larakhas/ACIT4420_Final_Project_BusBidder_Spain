"""Error categories for BusBidder Spain.

Every failure the program raises on purpose is a BusBidderError, so the command-line layer can
catch one base class, print a clear message and exit with a non-zero status, while real bugs
still show a traceback.
"""


class BusBidderError(Exception):
    """Base class for all expected, user-facing failures."""


class DataFileError(BusBidderError):
    """A data file is missing, unreadable, empty or lacks required columns (fatal)."""


class ConfigError(BusBidderError):
    """Settings or profile files are missing, malformed or hold impossible values."""


class WeightError(ConfigError):
    """Criterion weights are unknown, negative or do not total 100 %."""


class InvalidRequestError(BusBidderError):
    """The traveller's request contains an impossible or unknown value."""


class BookingError(BusBidderError):
    """A booking could not be created, read or changed."""


class SeatsUnavailableError(BookingError):
    """Fewer seats remain than the booking needs."""


class InvalidReferenceError(BookingError):
    """A booking reference is malformed or fails its check character."""


class BookingNotFoundError(BookingError):
    """No booking exists with the given reference."""
