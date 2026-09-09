#!/usr/bin/env bash
# LegiCAD build script — archengine Rust workspace (Vulkan viewer + path tracer).
#
# Targets:
#   - macOS Apple Silicon: Vulkan via MoltenVK (brew install molten-vk),
#     optional OIDN denoise via Homebrew (brew install open-image-denoise)
#   - Linux: system Vulkan driver, optional OIDN via pkg-config
#
# Usage:
#   ./build.sh                # release build: archrender + archview (windowed + egui)
#   ./build.sh --debug        # debug profile (faster compile)
#   ./build.sh --test         # also run the workspace test suite
#   ./build.sh --clean        # cargo clean first
#   ./build.sh --with-oidn    # force OIDN denoise feature (fails if not found)
#   ./build.sh --no-oidn      # force the CPU 3x3 fallback filter
#
# Artifacts: target/{release,debug}/archrender and .../archview

set -euo pipefail
cd "$(dirname "$0")"

PROFILE=release
RUN_TESTS=0
CLEAN=0
OIDN=auto

for arg in "$@"; do
    case "$arg" in
        --debug)     PROFILE=debug ;;
        --release)   PROFILE=release ;;
        --test)      RUN_TESTS=1 ;;
        --clean)     CLEAN=1 ;;
        --with-oidn) OIDN=on ;;
        --no-oidn)   OIDN=off ;;
        -h|--help)
            sed -n '2,17p' "$0"
            exit 0
            ;;
        *)
            echo "unknown option: $arg (try --help)" >&2
            exit 2
            ;;
    esac
done

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

OS="$(uname -s)"

# ── Prerequisites ────────────────────────────────────────────────────────
command -v cargo >/dev/null || die "cargo not found — install Rust via https://rustup.rs"
command -v cmake >/dev/null || die "cmake not found — needed to build shaderc (macOS: brew install cmake)"

if [ "$OS" = "Darwin" ]; then
    if command -v brew >/dev/null; then
        brew list --versions molten-vk >/dev/null 2>&1 \
            || warn "molten-vk not installed — the viewer needs Vulkan on Metal: brew install molten-vk"
    else
        warn "Homebrew not found — install molten-vk and cmake manually"
    fi
fi

# ── OIDN detection ───────────────────────────────────────────────────────
# The `oidn` crate links OpenImageDenoise via pkg-config (or OIDN_DIR).
if [ "$OS" = "Darwin" ] && command -v brew >/dev/null; then
    if OIDN_PREFIX="$(brew --prefix open-image-denoise 2>/dev/null)"; then
        export PKG_CONFIG_PATH="${OIDN_PREFIX}/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
    fi
fi

oidn_available() {
    command -v pkg-config >/dev/null && pkg-config --exists OpenImageDenoise 2>/dev/null
}

FEATURES=""
case "$OIDN" in
    on)
        oidn_available || die "--with-oidn given but OpenImageDenoise not found (macOS: brew install open-image-denoise)"
        FEATURES="denoise-oidn"
        ;;
    off) ;;
    auto)
        if oidn_available; then
            FEATURES="denoise-oidn"
            info "OpenImageDenoise found — building with OIDN denoise"
        else
            info "OpenImageDenoise not found — path tracer will use the CPU 3x3 fallback filter"
        fi
        ;;
esac

# ── Build ────────────────────────────────────────────────────────────────
[ "$CLEAN" = "1" ] && { info "cargo clean"; cargo clean; }

PROFILE_ARGS=()
[ "$PROFILE" = "debug" ] || PROFILE_ARGS+=(--release)
FEATURE_ARGS=()
[ -n "$FEATURES" ] && FEATURE_ARGS+=(--features "$FEATURES")

info "cargo build ($PROFILE) — archrender + archview${FEATURES:+ [$FEATURES]}"
cargo build "${PROFILE_ARGS[@]}" -p archengine-viewer --bins "${FEATURE_ARGS[@]}"

if [ "$RUN_TESTS" = "1" ]; then
    info "cargo test --workspace"
    cargo test --workspace
fi

# ── Runtime hints (macOS / MoltenVK) ─────────────────────────────────────
BIN_DIR="target/$PROFILE"
echo
info "built: $BIN_DIR/archrender  $BIN_DIR/archview"

if [ "$OS" = "Darwin" ]; then
    # Point the Vulkan loader at MoltenVK's ICD if the user hasn't already.
    if [ -z "${VK_ICD_FILENAMES:-}" ] && command -v brew >/dev/null; then
        MVK_PREFIX="$(brew --prefix molten-vk 2>/dev/null || true)"
        for icd in \
            "$MVK_PREFIX/share/vulkan/icd.d/MoltenVK_icd.json" \
            "$MVK_PREFIX/etc/molten-vk/icd.d/MoltenVK_icd.json"; do
            if [ -n "$MVK_PREFIX" ] && [ -f "$icd" ]; then
                echo
                echo "  MoltenVK ICD found. If archview fails to create a Vulkan instance, run:"
                echo "      export VK_ICD_FILENAMES=\"$icd\""
                break
            fi
        done
    fi
    echo
    echo "  Try it:  $BIN_DIR/archview test-data/wall10_only.json"
    echo "  Render:  $BIN_DIR/archrender test-data/test_building_qbd.json out.png"
    echo "  (in the viewer: F1 toggles the UI, WASD + mouse to fly)"
fi
