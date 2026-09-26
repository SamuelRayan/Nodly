"""Importing this package registers every job handler and periodic task. Add new modules here."""

from nodly.jobs.handlers import checkins, debug

__all__ = ["checkins", "debug"]
