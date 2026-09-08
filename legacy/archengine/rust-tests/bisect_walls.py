"""Bisect which wall in the smoke fixture causes the C++/Rust hash divergence.

For each N in 1..=14, builds a fixture with the first N walls + their doors,
runs both dumpers, and reports whether the WALLS hashes match.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "smoke_test_output" / "building.json"
TMP = ROOT / "rust" / "test-data" / "_bisect_tmp.json"
CPP = ROOT / "Shared" / "ArchGeometry" / "build" / "tools" / "Release" / "archgeometry_dump.exe"
RUST = ROOT / "rust" / "target" / "release" / "archgeometry_dump.exe"

HASH_RE = re.compile(r"WALLS\s+count=\d+ vertices=\d+ triangles=\d+ hash=(0x[0-9a-f]+)")


def walls_hash(out: str) -> str | None:
    for line in out.splitlines():
        m = HASH_RE.search(line)
        if m:
            return m.group(1)
    return None


def run(binary: Path, path: Path) -> str:
    r = subprocess.run([str(binary), str(path)], capture_output=True, text=True, check=False)
    return r.stdout


def main() -> int:
    doc = json.loads(SRC.read_text())
    walls = doc["walls_batch"]
    doors = doc.get("doors", [])

    print(f"Full fixture: {len(walls)} walls, {len(doors)} doors")
    print()
    print(f"{'N':>3}  {'C++ WALLS hash':>20}  {'Rust WALLS hash':>20}  match")

    last_match_n = 0
    for n in range(1, len(walls) + 1):
        sub_walls = walls[:n]
        sub_doors = [d for d in doors if d.get("wall_index", -1) < n]
        sub = {
            "success": True,
            "building_id": f"bisect-{n}",
            "unit": "mm",
            "width": doc.get("width", 0),
            "depth": doc.get("depth", 0),
            "walls_batch": sub_walls,
            "doors": sub_doors,
            "floors_batch": [],
            "windows": [],
            "roofs": [],
            "rooms": [],
        }
        TMP.write_text(json.dumps(sub))
        cpp_h = walls_hash(run(CPP, TMP))
        rust_h = walls_hash(run(RUST, TMP))
        ok = cpp_h == rust_h
        if ok:
            last_match_n = n
        flag = "OK" if ok else "**DIVERGE**"
        print(f"{n:>3}  {cpp_h or '-':>20}  {rust_h or '-':>20}  {flag}")
        if not ok and last_match_n + 1 == n:
            print()
            print(f"First divergence at wall index {n - 1}")
            # Print that wall and its doors for inspection.
            print("Wall:", json.dumps(walls[n - 1], indent=2))
            wall_doors = [d for d in doors if d.get("wall_index") == n - 1]
            print("Doors on that wall:")
            for d in wall_doors:
                print(" ", json.dumps(d))
            return 1

    if last_match_n == len(walls):
        print()
        print("All walls match. The divergence must be in a non-wall category.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
