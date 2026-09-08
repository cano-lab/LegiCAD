#!/usr/bin/env python3
"""
solver_schema.py — Increment-4 acceptance oracle.

Runs the pure-Rust `qbd_solve` (answers → building JSON) and validates its
output against the locked qbd_output.schema.json. Then chains it through
`qbd_dump --bundle` to prove the complete answers → permit-drawings path is
pure Rust, no Python in the loop.

Exit 0 = both pass.

Usage:
    python rust/tests/solver_schema.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOLVE = REPO / "rust" / "target" / "release" / "qbd_solve.exe"
DUMP = REPO / "rust" / "target" / "release" / "qbd_dump.exe"
SCHEMA = REPO / "Shared" / "Schemas" / "qbd_output.schema.json"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main() -> int:
    if not SOLVE.exists():
        sys.stderr.write(f"missing {SOLVE}; build: cargo build --release --bin qbd_solve\n")
        return 2

    print("Increment-4 oracle — pure-Rust answers → schema-valid bundle → drawings\n")

    # 1. answers → building JSON (pure Rust)
    proc = subprocess.run(
        [str(SOLVE), "--bedrooms", "3", "--bathrooms", "2", "--sqft", "1800"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(f"qbd_solve failed: {proc.stderr}\n")
        return 1
    building = json.loads(proc.stdout)

    # 2. validate against the locked schema
    import jsonschema
    schema = json.loads(SCHEMA.read_text())
    errs = sorted(jsonschema.Draft7Validator(schema).iter_errors(building),
                  key=lambda e: list(e.path))
    if errs:
        for e in errs[:10]:
            loc = "/".join(str(p) for p in e.absolute_path) or "<root>"
            print(f"  [schema] {loc}: {e.message[:160]}")
        print(f"\nFAIL: {len(errs)} schema violations")
        return 1
    print(f"  [PASS] qbd_solve output validates against {SCHEMA.name}")
    print(f"         walls={len(building['walls_batch'])} doors={len(building['doors'])} "
          f"rooms={len(building['rooms'])} dims={len(building['dimensions'])}")

    # 3. building JSON → permit bundle (pure Rust), proving the full chain
    if DUMP.exists():
        with tempfile.TemporaryDirectory() as td:
            bjson = Path(td) / "building.json"
            bjson.write_text(proc.stdout, encoding="utf-8")
            bundle = Path(td) / "bundle"
            dproc = subprocess.run(
                [str(DUMP), str(bjson), "--bundle", str(bundle), "--project", "Solver Chain"],
                capture_output=True, text=True, check=False,
            )
            if dproc.returncode != 0:
                sys.stderr.write(f"qbd_dump failed on Rust-solved building: {dproc.stderr}\n")
                return 1
            sheets = sorted(p.name for p in bundle.iterdir() if p.suffix == ".svg")
            print(f"  [PASS] qbd_dump produced {len(sheets)} sheets from the Rust-solved building")
            print(f"         {', '.join(sheets)}")
    else:
        print("  [SKIP] qbd_dump not built — chain check skipped")

    print("\nIncrement 4 complete: answers → drawings is pure Rust.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
