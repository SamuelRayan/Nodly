"""Nodly backend."""

import zoneinfo

__version__ = "0.1.0"

# All zone data comes from the pinned `tzdata` package, never the OS or conda copy, so Windows
# dev, CI and Linux prod agree on rules and on the zone lists (docs/DECISIONS.md).
zoneinfo.reset_tzpath(to=[])
