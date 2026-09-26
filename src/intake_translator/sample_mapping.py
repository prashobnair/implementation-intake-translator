"""Map documented fictional source shapes into the intake contract.

This is a sample configuration exercise, not an official vendor connector.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from .core import IntakeError, analyze_intake

FIELD_KEYS = ("customer_name", "launch_date", "seat_count", "region")


def map_sample_sources(raw: Mapping[str, object], config: Mapping[str, object]) -> dict[str, object]:
    """Extract configured keys, rejecting missing required mapping inputs.

    Form fields are key/answer pairs, CRM properties a flat object, notes
    topic/value pairs. All source records are synthetic and non-vendor-specific.
    """
    if not isinstance(raw, Mapping) or not isinstance(config, Mapping):
        raise IntakeError("invalid_mapping", "source and config must be objects")
    event_id = config.get("event_id")
    mapping = config.get("mapping")
    if not isinstance(mapping, Mapping) or set(mapping) != {"form", "crm", "notes"}:
        raise IntakeError("invalid_mapping", "mapping must define form, crm and notes")
    source_keys = {"form": ("form_submission", "fields", "key", "answer"),
                   "crm": ("crm_deal_record", "properties", None, None),
                   "notes": ("meeting_notes", "decisions", "topic", "value")}
    mapped = {}
    for name, (record_key, values_key, key_field, value_field) in source_keys.items():
        record = raw.get(record_key)
        if not isinstance(record, Mapping):
            raise IntakeError("invalid_mapping", f"{record_key} must be an object")
        values = record.get(values_key)
        if key_field is None:
            if not isinstance(values, Mapping):
                raise IntakeError("invalid_mapping", f"{record_key}.{values_key} must be an object")
            lookup = values
        else:
            if not isinstance(values, list) or any(not isinstance(row, Mapping) for row in values):
                raise IntakeError("invalid_mapping", f"{record_key}.{values_key} must be a list of objects")
            lookup = {}
            for row in values:
                key = row.get(key_field)
                if not isinstance(key, str) or key in lookup:
                    raise IntakeError("invalid_mapping", f"{record_key} has missing or duplicate keys")
                lookup[key] = row.get(value_field)
        choices = mapping[name]
        if not isinstance(choices, Mapping) or any(field not in FIELD_KEYS or not isinstance(key, str) for field, key in choices.items()):
            raise IntakeError("invalid_mapping", f"{name} mapping contains an unknown field or non-text key")
        missing = [key for key in choices.values() if key not in lookup]
        if missing:
            raise IntakeError("invalid_mapping", f"{name} is missing configured keys: {', '.join(sorted(missing))}")
        mapped[name] = {field: lookup[key] for field, key in choices.items()}
    event = {"schema_version": "1", "event_id": event_id, "sources": mapped}
    analyze_intake(event)  # validate the assembled contract before emitting it
    return event


def main() -> int:
    parser = argparse.ArgumentParser(description="Map fictional sample records; no vendor API is called")
    parser.add_argument("records")
    parser.add_argument("configuration")
    args = parser.parse_args()
    try:
        with open(args.records, encoding="utf-8") as source, open(args.configuration, encoding="utf-8") as cfg:
            event = map_sample_sources(json.load(source), json.load(cfg))
    except (OSError, json.JSONDecodeError, IntakeError) as exc:
        print(f"sample mapping error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(event, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
