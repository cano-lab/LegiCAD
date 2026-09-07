#!/usr/bin/env python3
"""
m4_diff.py — regression oracle for the M4 milestone (drawing module).

Runs both the C++ kernel `drawing_dump` and the Rust `drawing_dump` against
every fixture under `rust/test-data/drawing_fixtures/`, normalizes line
endings (the C++ tool emits CRLF on Windows), and diffs the SVG outputs
line by line.

Exit codes:
    0 — every fixture matches byte-for-byte after line-ending normalization
    1 — at least one fixture has a real diff
    2 — bad invocation / missing binaries / missing fixtures

Usage:
    python rust/tests/m4_diff.py
    python rust/tests/m4_diff.py --verbose
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CPP_DUMPER = (
    Path("F:/Software/ArchEngine_Suite_Kernel/ArchEngine_kernel/build/Release/drawing_dump.exe")
)
RUST_DUMPER = REPO_ROOT / "rust" / "target" / "release" / "drawing_dump.exe"
FIXTURES_DIR = REPO_ROOT / "rust" / "test-data" / "drawing_fixtures"

_USE_COLOR = sys.stdout.isatty() and sys.platform != "win32"
GREEN = "\033[32m" if _USE_COLOR else ""
RED = "\033[31m" if _USE_COLOR else ""
RESET = "\033[0m" if _USE_COLOR else ""


@dataclass
class FixtureResult:
    name: str
    matched_lines: int = 0
    diffs: list[tuple[int, str, str]] = field(default_factory=list)
    cpp_only: list[str] = field(default_factory=list)
    rust_only: list[str] = field(default_factory=list)

    @property
    def is_pass(self) -> bool:
        return not (self.diffs or self.cpp_only or self.rust_only)


def run(binary: Path, fixture: Path) -> list[str]:
    if not binary.exists():
        sys.exit(f"error: dumper binary missing: {binary}")
    proc = subprocess.run(
        [str(binary), str(fixture)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(
            f"  [{binary.name}] exit={proc.returncode}: {proc.stderr.strip()}\n"
        )
    # Normalize line endings (the C++ tool emits CRLF on Windows).
    return proc.stdout.replace("\r\n", "\n").splitlines()


def diff_one(fixture: Path, verbose: bool) -> FixtureResult:
    name = fixture.relative_to(REPO_ROOT).as_posix()
    cpp_lines = run(CPP_DUMPER, fixture)
    rust_lines = run(RUST_DUMPER, fixture)
    res = FixtureResult(name=name)

    n = max(len(cpp_lines), len(rust_lines))
    for i in range(n):
        cpp = cpp_lines[i] if i < len(cpp_lines) else None
        rust = rust_lines[i] if i < len(rust_lines) else None
        if cpp is None:
            res.rust_only.append(rust or "")
        elif rust is None:
            res.cpp_only.append(cpp)
        elif cpp == rust:
            res.matched_lines += 1
        else:
            res.diffs.append((i + 1, cpp, rust))

    if verbose:
        for ln, cpp, rust in res.diffs[:10]:
            print(f"      diff @ line {ln}:")
            print(f"        C++ : {cpp}")
            print(f"        Rust: {rust}")
        if len(res.diffs) > 10:
            print(f"      … and {len(res.diffs) - 10} more diffs")
        for line in res.cpp_only:
            print(f"      C++-only: {line}")
        for line in res.rust_only:
            print(f"      Rust-only: {line}")

    return res


def status_line(res: FixtureResult) -> str:
    if res.is_pass:
        return f"{GREEN}[PASS]{RESET} {res.name}: {res.matched_lines} lines identical"
    parts = [f"{len(res.diffs)} diffs"]
    if res.cpp_only:
        parts.append(f"{len(res.cpp_only)} C++-only")
    if res.rust_only:
        parts.append(f"{len(res.rust_only)} Rust-only")
    return f"{RED}[FAIL]{RESET} {res.name}: " + ", ".join(parts)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--verbose", action="store_true", help="show diff content for mismatches")
    args = p.parse_args()

    if not FIXTURES_DIR.exists():
        sys.stderr.write(f"error: fixtures dir missing: {FIXTURES_DIR}\n")
        return 2

    fixtures = sorted(FIXTURES_DIR.glob("*.json"))
    if not fixtures:
        sys.stderr.write(f"error: no fixtures found in {FIXTURES_DIR}\n")
        return 2

    print("M4 regression oracle - drawing C++ vs Rust")
    print(f"  cpp:  {CPP_DUMPER}")
    print(f"  rust: {RUST_DUMPER.relative_to(REPO_ROOT)}")
    print()

    fail = 0
    for fixture in fixtures:
        res = diff_one(fixture, args.verbose)
        print("  " + status_line(res))
        if not res.is_pass:
            fail += 1

    print()
    print(f"Summary: {len(fixtures) - fail} pass, {fail} fail")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
