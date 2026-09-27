"""Local demonstrator: reads synthetic JSON and writes a review packet to stdout."""

import argparse
import json
import sys
from .core import IntakeError
from .store import process_once


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event", help="JSON intake event path")
    parser.add_argument("--db", default="intake-events.sqlite3", help="local idempotency database")
    args = parser.parse_args()
    try:
        with open(args.event, encoding="utf-8") as source:
            event = json.load(source)
        packet, replayed = process_once(args.db, event)
    except (OSError, json.JSONDecodeError, IntakeError) as exc:
        print(f"intake error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({**packet, "replayed": replayed}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
