#!/usr/bin/env python3
"""
m5_cpp_diff.py - byte-identical oracle: C++ QBDInterface vs Rust ls-qbd.

Runs `qbd_dump.exe` (C++, built from ArchEngine_kernel/tools/qbd_dump.cpp)
and the Rust `qbd_dump` (built from rust/crates/qbd/src/bin/dump.rs) on the
same QBD-format JSON fixture, then byte-compares the floor-plan SVGs.

Sibling to m5_diff.py:
- m5_diff.py:     Rust vs Python smoke_test (architectural-pipeline equivalence)
- m5_cpp_diff.py: Rust vs C++ qbd_interface (port fidelity, byte-identical)

Both `printf` log noise on stderr and Windows CRLF in the C++ output are
stripped before comparison.

Usage:
    python rust/tests/m5_cpp_diff.py
    python rust/tests/m5_cpp_diff.py --fixture path/to/building.json
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUST_BIN = REPO_ROOT / "rust" / "target" / "release" / "qbd_dump.exe"

# The C++ qbd_dump lives in the sibling kernel repo. Hard-coded for now;
# could become an env var if the layout ever changes.
KERNEL_ROOT = Path("F:/Software/ArchEngine_Suite_Kernel/ArchEngine_kernel")
CPP_BIN = KERNEL_ROOT / "build" / "Release" / "qbd_dump.exe"

DEFAULT_FIXTURE = KERNEL_ROOT / "test_building_qbd.json"


def normalise(text: str) -> str:
    """Strip CRLF (C++ on Windows) and drop QBDInterface's `[QBD] ...`
    diagnostic lines that arch::qbd::QBDInterface::loadFromFile prints to
    stdout. The Rust side has no such log."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(
        line for line in text.split("\n") if not line.startswith("[QBD]")
    )


def run(binary: Path, fixture: Path, extra_args: list[str] | None = None) -> str:
    if not binary.exists():
        sys.stderr.write(f"missing binary: {binary}\n")
        sys.exit(2)
    cmd = [str(binary), str(fixture)] + (extra_args or [])
    # stdout = SVG, stderr = log noise we discard.
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(
            f"{binary.name} failed (exit {proc.returncode}):\n{proc.stderr}\n"
        )
        sys.exit(2)
    return normalise(proc.stdout)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    p.add_argument("--write-artifacts", action="store_true",
                   help="Write cpp.svg and rust.svg to repo root for inspection.")
    args = p.parse_args()

    if not args.fixture.exists():
        sys.stderr.write(f"fixture not found: {args.fixture}\n")
        return 2

    print(f"M5 C++ <-> Rust byte-identical oracle")
    print(f"  fixture: {args.fixture}")
    print(f"  cpp:     {CPP_BIN.relative_to(KERNEL_ROOT.parent)}")
    print(f"  rust:    {RUST_BIN.relative_to(REPO_ROOT)}")
    print()

    # C++ QBDInterface emits raw slicer SVG (no annotations).
    # Rust qbd_dump --bare matches: it skips the dimension / title-block /
    # room-label overlay that generate_documentation adds on top.
    cpp_svg = run(CPP_BIN, args.fixture)
    rust_svg = run(RUST_BIN, args.fixture, ["--bare"])

    if args.write_artifacts:
        (REPO_ROOT / "cpp.svg").write_text(cpp_svg, encoding="utf-8", newline="\n")
        (REPO_ROOT / "rust.svg").write_text(rust_svg, encoding="utf-8", newline="\n")
        print("  wrote cpp.svg / rust.svg")

    if cpp_svg == rust_svg:
        print(f"PASS  byte-identical ({len(rust_svg)} chars)")
        return 0

    # Diff report.
    cpp_lines = cpp_svg.splitlines()
    rust_lines = rust_svg.splitlines()
    print(f"FAIL  cpp={len(cpp_svg)} chars / {len(cpp_lines)} lines, "
          f"rust={len(rust_svg)} chars / {len(rust_lines)} lines")
    print()
    n = max(len(cpp_lines), len(rust_lines))
    diff_lines = 0
    for i in range(n):
        c = cpp_lines[i] if i < len(cpp_lines) else "<EOF>"
        r = rust_lines[i] if i < len(rust_lines) else "<EOF>"
        if c != r:
            diff_lines += 1
            if diff_lines <= 5:
                print(f"  line {i + 1}:")
                print(f"    cpp:  {c}")
                print(f"    rust: {r}")
    if diff_lines > 5:
        print(f"  ... and {diff_lines - 5} more differing lines")
    return 1


if __name__ == "__main__":
    sys.exit(main())
