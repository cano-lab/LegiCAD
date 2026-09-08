#!/usr/bin/env python3
"""
m1_diff.py — regression oracle for the M1 milestone of the Rust port.

Runs both the C++ and the Rust `archgeometry_dump` binaries against a corpus
of building JSON fixtures, diffs the outputs line by line, and reports per
fixture / per category whether the Rust port matches the C++ canonical output.

Lines containing `UNIMPLEMENTED` on the Rust side are treated as "not yet
ported" rather than failure — they're expected during the port and disappear
as crate modules land.

Exit codes:
    0 — all fixtures either match or are cleanly unimplemented (yellow)
    1 — at least one fixture has a real diff (red)
    2 — bad invocation / missing binaries / missing fixtures

Usage:
    python rust/tests/m1_diff.py
    python rust/tests/m1_diff.py --verbose
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CPP_DUMPER = REPO_ROOT / "Shared" / "ArchGeometry" / "build" / "tools" / "Release" / "archgeometry_dump.exe"
RUST_DUMPER = REPO_ROOT / "rust" / "target" / "release" / "archgeometry_dump.exe"

# Fixtures to diff. Add more as they're created; keep the list short and
# representative so the oracle runs in <5s.
FIXTURES = [
    REPO_ROOT / "smoke_test_output" / "building.json",  # live qbd_layout_generator output
    # REPO_ROOT / "Shared" / "test_building_simple.json",  # legacy format, currently rejected by C++
]

_USE_COLOR = sys.stdout.isatty() and sys.platform != "win32"
GREEN = "\033[32m" if _USE_COLOR else ""
YELLOW = "\033[33m" if _USE_COLOR else ""
RED = "\033[31m" if _USE_COLOR else ""
RESET = "\033[0m" if _USE_COLOR else ""


@dataclass
class FixtureResult:
    name: str
    matched: list[str]
    unimplemented: list[str]
    mismatched: list[tuple[str, str, str]]  # (line_label, cpp_line, rust_line)
    cpp_only: list[str]
    rust_only: list[str]

    @property
    def has_mismatch(self) -> bool:
        return bool(self.mismatched or self.cpp_only or self.rust_only)


def run(binary: Path, fixture: Path) -> tuple[int, list[str]]:
    if not binary.exists():
        sys.exit(f"error: dumper binary missing: {binary}")
    proc = subprocess.run(
        [str(binary), str(fixture)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(f"  [{binary.name}] exit={proc.returncode}: {proc.stderr.strip()}\n")
    return proc.returncode, proc.stdout.splitlines()


def diff_one(fixture: Path, verbose: bool) -> FixtureResult:
    name = fixture.relative_to(REPO_ROOT).as_posix()
    _, cpp_out = run(CPP_DUMPER, fixture)
    _, rust_out = run(RUST_DUMPER, fixture)

    res = FixtureResult(name=name, matched=[], unimplemented=[], mismatched=[], cpp_only=[], rust_only=[])

    # Line-by-line — both dumpers emit the same fixed-shape header + categories.
    n = max(len(cpp_out), len(rust_out))
    for i in range(n):
        cpp_line = cpp_out[i] if i < len(cpp_out) else None
        rust_line = rust_out[i] if i < len(rust_out) else None
        label = (cpp_line or rust_line or "").split(" ", 1)[0] or f"line{i}"
        if cpp_line is None:
            res.rust_only.append(rust_line or "")
        elif rust_line is None:
            res.cpp_only.append(cpp_line)
        elif "UNIMPLEMENTED" in rust_line:
            res.unimplemented.append(label)
        elif cpp_line == rust_line:
            res.matched.append(label)
        else:
            res.mismatched.append((label, cpp_line, rust_line))

    if verbose:
        for label, cpp, rust in res.mismatched:
            print(f"      diff @ {label}:")
            print(f"        C++ : {cpp}")
            print(f"        Rust: {rust}")
        for line in res.cpp_only:
            print(f"      C++-only: {line}")
        for line in res.rust_only:
            print(f"      Rust-only: {line}")

    return res


def status_line(res: FixtureResult) -> str:
    if res.has_mismatch:
        return f"{RED}[FAIL]{RESET} {res.name}: {len(res.mismatched)} mismatched"
    if res.unimplemented:
        unimp = ",".join(res.unimplemented)
        return f"{YELLOW}[STUB]{RESET} {res.name}: {len(res.matched)} match, unimplemented=[{unimp}]"
    return f"{GREEN}[PASS]{RESET} {res.name}: {len(res.matched)} lines identical"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--verbose", action="store_true", help="show diff content for mismatches")
    args = p.parse_args()

    print(f"M1 regression oracle - archgeometry C++ vs Rust\n  cpp:  {CPP_DUMPER.relative_to(REPO_ROOT)}\n  rust: {RUST_DUMPER.relative_to(REPO_ROOT)}\n")

    fail = 0
    stub = 0
    for fixture in FIXTURES:
        if not fixture.exists():
            print(f"{RED}[MISS]{RESET} fixture not found: {fixture}")
            fail += 1
            continue
        res = diff_one(fixture, args.verbose)
        print("  " + status_line(res))
        if res.has_mismatch:
            fail += 1
        elif res.unimplemented:
            stub += 1

    print()
    print(f"Summary: {len(FIXTURES) - fail - stub} pass, {stub} stub, {fail} fail")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
