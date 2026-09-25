"""The one place the backend asks for the current time.

Code passes this value into SQL instead of using the database's now(), so tests can freeze
time with time-machine and get the same answer from Python and from queries.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
