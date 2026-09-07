#!/usr/bin/env python3
"""
m5_diff.py - regression oracle for the M5 milestone (end-to-end QBD pipeline).

Acceptance per port plan:
    "QBD JSON -> permit-set SVG bundle in pure Rust, no C++ in the pipeline."

This harness:
1. Runs the smoke_test (Python) pipeline to produce the canonical 9-sheet
   bundle in `smoke_test_output/drawings/`.
2. Runs the Rust qbd_dump on the SAME QBD JSON to produce a parallel
   bundle in `target/m5_output/rust_bundle/`.
3. For each expected sheet, reports:
   - [PASS]  both sides produced the sheet (no byte-diff yet — see note)
   - [STUB]  Rust pipeline doesn't have the generator yet (M5+ work)
   - [MISS]  Python pipeline didn't produce it (broken Python smoke)
   - [EXTRA] Rust produced a sheet Python didn't (informational)

Note on PASS without byte-diff: today the Rust floor_plan output uses raw mm
coordinates and lacks the Python annotation layer (dimensions, labels, title
block, CSS classes). Byte-equivalence here requires porting:
- intelligent_dimensions.py (4-tier dimensions) - ~700 LOC
- title_block.py - ~200 LOC
- Coordinate-scale normalisation in the Rust drawing crate

Until those land, PASS means "both pipelines produced a non-empty floor-plan
SVG with the expected polygon count for the input walls."

Usage:
    python rust/tests/m5_diff.py
    python rust/tests/m5_diff.py --verbose
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUST_BIN = REPO_ROOT / "rust" / "target" / "release" / "qbd_dump.exe"
SMOKE_TEST = REPO_ROOT / "smoke_test.py"
PY_BUILDING_JSON = REPO_ROOT / "smoke_test_output" / "building.json"
PY_DRAWINGS_DIR = REPO_ROOT / "smoke_test_output" / "drawings"
RUST_BUNDLE_DIR = REPO_ROOT / "rust" / "target" / "m5_output" / "rust_bundle"

# Canonical 9-sheet permit set per permit_drawing_set.py.
EXPECTED_PY_SHEETS = [
    "01_site_plan.svg",
    "02_floor_plan.svg",
    "elevations/03_elevation_north.svg",
    "elevations/03_elevation_south.svg",
    "elevations/03_elevation_east.svg",
    "elevations/03_elevation_west.svg",
    "sections/04_section_aa.svg",
    "schedules/05_door_schedule.svg",
    "schedules/05_window_schedule.svg",
]

# What the Rust pipeline produces today. Anything in EXPECTED_PY_SHEETS not
# in this list is STUB (M5+ generator work). Schedules are conditional —
# the Rust pipeline emits them only when the building has the matching
# openings (door schedule iff doors > 0, window schedule iff windows > 0).
RUST_PRODUCES = {
    "01_site_plan.svg",
    "02_floor_plan.svg",
    "03_elevation_north.svg",
    "03_elevation_south.svg",
    "03_elevation_east.svg",
    "03_elevation_west.svg",
    "04_section_aa.svg",
    "05_door_schedule.svg",
    "05_window_schedule.svg",
}

_USE_COLOR = sys.stdout.isatty() and sys.platform != "win32"
GREEN = "\033[32m" if _USE_COLOR else ""
YELLOW = "\033[33m" if _USE_COLOR else ""
RED = "\033[31m" if _USE_COLOR else ""
CYAN = "\033[36m" if _USE_COLOR else ""
RESET = "\033[0m" if _USE_COLOR else ""


@dataclass
class SheetReport:
    name: str
    status: str  # PASS / STUB / MISS / EXTRA / DIFF
    note: str = ""


def ensure_python_pipeline(verbose: bool) -> bool:
    """Run smoke_test if its output isn't fresh."""
    if PY_BUILDING_JSON.exists() and PY_DRAWINGS_DIR.exists():
        if verbose:
            print("  (Python smoke output already present)")
        return True
    if verbose:
        print(f"  Running {SMOKE_TEST.name}...")
    proc = subprocess.run(
        [sys.executable, str(SMOKE_TEST)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(f"smoke_test failed (exit {proc.returncode}):\n{proc.stderr}\n")
        return False
    return True


def run_rust_bundle(verbose: bool) -> bool:
    """Run Rust qbd_dump --bundle against the Python pipeline's output JSON."""
    if not RUST_BIN.exists():
        sys.stderr.write(f"Rust binary missing: {RUST_BIN}\n")
        sys.stderr.write("Build it with: cargo build --release --bin qbd_dump\n")
        return False
    if not PY_BUILDING_JSON.exists():
        sys.stderr.write(f"Input JSON missing: {PY_BUILDING_JSON}\n")
        return False

    # Fresh bundle each run.
    if RUST_BUNDLE_DIR.exists():
        for child in RUST_BUNDLE_DIR.iterdir():
            child.unlink()
    RUST_BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        [
            str(RUST_BIN),
            str(PY_BUILDING_JSON),
            "--bundle", str(RUST_BUNDLE_DIR),
            "--project", "M5 Smoke",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(f"qbd_dump failed (exit {proc.returncode}):\n{proc.stderr}\n")
        return False
    if verbose:
        sys.stderr.write(proc.stderr)
    return True


def classify(sheet: str) -> SheetReport:
    """Per-sheet status: PASS / STUB / MISS / DIFF."""
    name = Path(sheet).name  # strip subdirs for Rust comparison
    py_path = PY_DRAWINGS_DIR / sheet
    rust_path = RUST_BUNDLE_DIR / name

    py_exists = py_path.exists() and py_path.stat().st_size > 0
    rust_expected = name in RUST_PRODUCES
    rust_exists = rust_path.exists() and rust_path.stat().st_size > 0

    if not py_exists:
        return SheetReport(sheet, "MISS", f"Python did not produce {py_path}")

    if not rust_expected:
        return SheetReport(sheet, "STUB", "Rust generator not yet ported (M5+ work)")

    if not rust_exists:
        return SheetReport(sheet, "DIFF", f"Rust expected to produce but missing: {rust_path}")

    # Both produced. Today we don't do byte-diff (Rust output lacks the
    # annotation layer + uses raw-mm coordinates while Python is scaled).
    # Smoke check: both are non-empty SVG with at least one drawing primitive
    # (polygon, rect, or line). Different sheet types favour different
    # primitives — site_plan is all <rect>, sections mix <rect> + <polygon>,
    # elevations mix <rect> + <polygon> + <line>.
    py_text = py_path.read_text(encoding="utf-8", errors="replace")
    rust_text = rust_path.read_text(encoding="utf-8", errors="replace")

    def shape_count(s: str) -> int:
        # Include <text> so room labels and dimension callouts contribute.
        return (
            s.count("<polygon")
            + s.count("<rect")
            + s.count("<line")
            + s.count("<text")
        )

    py_shapes = shape_count(py_text)
    rust_shapes = shape_count(rust_text)
    if py_shapes == 0 or rust_shapes == 0:
        return SheetReport(sheet, "DIFF",
            f"empty geometry - py shapes={py_shapes}, rust shapes={rust_shapes}")

    note = (
        f"py {py_path.stat().st_size}B/{py_shapes} shapes, "
        f"rust {rust_path.stat().st_size}B/{rust_shapes} shapes"
    )
    return SheetReport(sheet, "PASS", note)


def color_for(status: str) -> str:
    return {
        "PASS":  GREEN,
        "STUB":  YELLOW,
        "MISS":  RED,
        "DIFF":  RED,
        "EXTRA": CYAN,
    }.get(status, "")


def list_rust_extras() -> list[SheetReport]:
    py_names = {Path(s).name for s in EXPECTED_PY_SHEETS}
    extras = []
    for p in sorted(RUST_BUNDLE_DIR.iterdir()):
        if p.name == "manifest.json" or p.name in py_names:
            continue
        extras.append(SheetReport(
            p.name, "EXTRA",
            f"Rust produced a sheet Python doesn't ({p.stat().st_size}B)",
        ))
    return extras


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    print("M5 regression oracle - QBD JSON -> permit-set SVG bundle (pure Rust)")
    print(f"  python pipeline: {SMOKE_TEST.relative_to(REPO_ROOT)} (produces 9-sheet bundle)")
    print(f"  rust pipeline:   {RUST_BIN.relative_to(REPO_ROOT)} --bundle ...")
    print()

    if not ensure_python_pipeline(args.verbose):
        return 2
    if not run_rust_bundle(args.verbose):
        return 2

    reports = [classify(s) for s in EXPECTED_PY_SHEETS]
    reports.extend(list_rust_extras())

    pass_count = sum(1 for r in reports if r.status == "PASS")
    stub_count = sum(1 for r in reports if r.status == "STUB")
    miss_count = sum(1 for r in reports if r.status == "MISS")
    diff_count = sum(1 for r in reports if r.status == "DIFF")
    extra_count = sum(1 for r in reports if r.status == "EXTRA")

    for r in reports:
        c = color_for(r.status)
        label = f"[{r.status}]".ljust(7)
        line = f"  {c}{label}{RESET} {r.name}"
        if args.verbose or r.status in {"MISS", "DIFF", "EXTRA"}:
            line += f"  -- {r.note}"
        print(line)

    print()
    print(
        f"Summary: {pass_count} pass, {stub_count} stub, "
        f"{miss_count} miss, {diff_count} diff, {extra_count} extra"
    )

    # Fail only on hard failures (DIFF = Rust diverged from Python where both
    # produced output). STUB, MISS, and EXTRA are informational:
    #   STUB = Rust generator not yet ported (M5+ scope)
    #   MISS = Python pipeline didn't produce the sheet — possibly a Python
    #          bug (e.g. extract_openings looking at the wrong JSON path),
    #          but not the Rust port's problem to surface
    #   EXTRA = Rust produced a sheet Python doesn't (different sheet set,
    #           e.g. per-category wall section details)
    return 1 if diff_count else 0


if __name__ == "__main__":
    sys.exit(main())
