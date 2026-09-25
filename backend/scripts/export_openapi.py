"""Write backend/openapi.json for the mobile type generator (openapi-typescript).

    python scripts/export_openapi.py          # write the file
    python scripts/export_openapi.py --check  # exit 1 if the file is out of date

No database or Supabase connection is needed. /dev routes are never included.
"""

import argparse
import sys
from pathlib import Path

from nodly.api.openapi import render_openapi
from nodly.config import BACKEND_DIR

OUTPUT = BACKEND_DIR / "openapi.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if openapi.json is stale")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    document = render_openapi()
    current = args.output.read_text(encoding="utf-8") if args.output.exists() else None
    if args.check:
        if current != document:
            print(f"{args.output} is out of date: run python scripts/export_openapi.py")
            return 1
        print(f"{args.output} is up to date")
        return 0
    args.output.write_text(document, encoding="utf-8", newline="\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
