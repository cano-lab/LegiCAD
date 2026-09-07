"""
schema_diff.py - Reconcile actual qbd_layout_generator output vs qbd_output.schema.json.

Loads the canonical schema and a sample building dict; reports:
- Required fields the schema demands that the building lacks
- Fields the building has that the schema doesn't define
- Type/shape mismatches on shared fields
- Per collection (walls_batch[0], doors[0], windows[0], rooms[any]), same diff

Output is the input to deciding: fix the schema, fix the generator, or both.
Pure stdlib.
"""
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).parent
SCHEMA_PATH = REPO / "Shared" / "Schemas" / "qbd_output.schema.json"
BUILDING_PATH = REPO / "smoke_test_output" / "building.json"


def jtype(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def schema_type(node: dict) -> str:
    t = node.get("type")
    if isinstance(t, list):
        return "/".join(t)
    return t or "?"


def diff_object(label: str, schema: dict, sample: dict, definitions: dict, out: list):
    """Compare a sample dict against a schema object node."""
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref.startswith("#/definitions/"):
            name = ref.split("/")[-1]
            if name in definitions:
                schema = definitions[name]
            else:
                out.append(f"  [WARN] {label}: schema $ref to {ref} not found")
                return

    schema_props = schema.get("properties", {})
    schema_required = set(schema.get("required", []))
    sample_keys = set(sample.keys()) if isinstance(sample, dict) else set()

    if not isinstance(sample, dict):
        out.append(f"  [TYPE] {label}: schema=object, actual={jtype(sample)}")
        return

    missing_required = schema_required - sample_keys
    for k in sorted(missing_required):
        prop = schema_props.get(k, {})
        out.append(f"  [MISSING] {label}.{k}: schema requires (type={schema_type(prop)})")

    extra = sample_keys - set(schema_props.keys())
    for k in sorted(extra):
        out.append(f"  [EXTRA]   {label}.{k}: building has it, schema doesn't define (actual={jtype(sample[k])})")

    for k in sorted(sample_keys & set(schema_props.keys())):
        prop = schema_props[k]
        actual = sample[k]
        expected_type = schema_type(prop)
        actual_type = jtype(actual)
        type_ok = (
            expected_type == "?" or
            actual_type == expected_type or
            (expected_type == "number" and actual_type == "integer") or
            (expected_type in expected_type.split("/"))
        )
        if not type_ok:
            out.append(f"  [TYPE]    {label}.{k}: schema={expected_type}, actual={actual_type}")


def diff_array_item(label: str, schema_items: dict, sample_item, definitions: dict, out: list):
    if "$ref" in schema_items:
        ref = schema_items["$ref"]
        if ref.startswith("#/definitions/"):
            name = ref.split("/")[-1]
            if name in definitions:
                diff_object(label, definitions[name], sample_item, definitions, out)
                return
    diff_object(label, schema_items, sample_item, definitions, out)


def main():
    schema = json.loads(SCHEMA_PATH.read_text())
    building = json.loads(BUILDING_PATH.read_text())
    definitions = schema.get("definitions", {})

    print("=" * 70)
    print("SCHEMA vs ACTUAL BUILDING DIFF")
    print(f"Schema:   {SCHEMA_PATH}")
    print(f"Building: {BUILDING_PATH}")
    print("=" * 70)

    out = []
    print("\n--- Top-level fields ---")
    diff_object("$root", schema, building, definitions, out)
    for line in out:
        print(line)

    collections = {
        "walls_batch": "wall",
        "doors": "door",
        "windows": "window",
        "levels": "level",
        "dimensions": "dimension",
        "roofs": "roof",
        "stairs": "stair",
    }
    for field, def_name in collections.items():
        items = building.get(field, [])
        if not isinstance(items, list) or len(items) == 0:
            print(f"\n--- {field}: {jtype(items)} of length {len(items) if hasattr(items, '__len__') else '?'} ---")
            continue
        print(f"\n--- {field}[0] ({len(items)} items total) ---")
        out = []
        if def_name in definitions:
            diff_object(f"{field}[0]", definitions[def_name], items[0], definitions, out)
        else:
            out.append(f"  [WARN] no schema definition '{def_name}' to validate against")
        if not out:
            print("  (matches schema)")
        for line in out:
            print(line)

    rooms = building.get("rooms", {})
    if isinstance(rooms, dict) and rooms:
        first_key = next(iter(rooms))
        print(f"\n--- rooms[{first_key!r}] ({len(rooms)} rooms total, dict-keyed) ---")
        out = []
        if "room" in definitions:
            diff_object(f"rooms.{first_key}", definitions["room"], rooms[first_key], definitions, out)
        else:
            out.append("  [WARN] no schema definition 'room'")
        if not out:
            print("  (matches schema)")
        for line in out:
            print(line)
    elif isinstance(rooms, list):
        print(f"\n--- rooms (list of length {len(rooms)}) ---")
        print("  [TYPE] rooms: schema is object map (room_id -> room), actual is list")

    print("\n" + "=" * 70)
    print("Done.")


if __name__ == "__main__":
    main()
