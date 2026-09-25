"""Importing this package registers every job handler. Add new handler modules here."""

from nodly.jobs.handlers import debug

__all__ = ["debug"]
