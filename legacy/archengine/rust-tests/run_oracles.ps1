# run_oracles.ps1 - regression net for the Rust port.
#
# Runs every guarantee in order, fails fast on the first regression:
#   1. cargo test --workspace                  (unit + integration tests)
#   2. m1_diff.py                              (schema parse + generators)
#   3. m4_diff.py                              (drawing pipeline)
#   4. m5_cpp_diff.py                          (C++ qbd_interface byte-identical)
#   5. m5_diff.py                              (Python pipeline equivalence)
#
# Build dependencies are checked up front: missing C++ binaries
# downgrade the C++ oracles to SKIP (not FAIL), since the rest of the
# net is still meaningful.
#
# Usage:
#   pwsh rust/tests/run_oracles.ps1
#   pwsh rust/tests/run_oracles.ps1 -SkipPython   # cargo + cpp only
#   pwsh rust/tests/run_oracles.ps1 -Verbose

[CmdletBinding()]
param(
    [switch]$SkipPython,
    [switch]$KeepGoing  # don't stop on first FAIL
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$RustRoot = Join-Path $RepoRoot 'rust'
$KernelBuild = 'F:\Software\ArchEngine_Suite_Kernel\ArchEngine_kernel\build\Release'

# Track results as [ordered] hashtable so the summary preserves order.
$Results = [ordered]@{}

function Step {
    param(
        [string]$Name,
        [scriptblock]$Check,
        [scriptblock]$Body
    )
    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan

    if ($Check) {
        $skipReason = & $Check
        if ($skipReason) {
            Write-Host "  SKIP: $skipReason" -ForegroundColor Yellow
            $Results[$Name] = 'SKIP'
            return
        }
    }

    $start = [DateTime]::Now
    try {
        & $Body
        $elapsed = ([DateTime]::Now - $start).TotalSeconds
        Write-Host ("  PASS ({0:N1}s)" -f $elapsed) -ForegroundColor Green
        $Results[$Name] = 'PASS'
    } catch {
        $elapsed = ([DateTime]::Now - $start).TotalSeconds
        Write-Host ("  FAIL ({0:N1}s): {1}" -f $elapsed, $_) -ForegroundColor Red
        $Results[$Name] = 'FAIL'
        if (-not $KeepGoing) {
            Write-Host ""
            Print-Summary
            exit 1
        }
    }
}

function Print-Summary {
    Write-Host ""
    Write-Host "===== Summary =====" -ForegroundColor Cyan
    foreach ($k in $Results.Keys) {
        $v = $Results[$k]
        $color = switch ($v) { 'PASS' { 'Green' } 'FAIL' { 'Red' } default { 'Yellow' } }
        Write-Host ("  {0,-6} {1}" -f $v, $k) -ForegroundColor $color
    }
    $pass = ($Results.Values | Where-Object { $_ -eq 'PASS' }).Count
    $fail = ($Results.Values | Where-Object { $_ -eq 'FAIL' }).Count
    $skip = ($Results.Values | Where-Object { $_ -eq 'SKIP' }).Count
    Write-Host ""
    Write-Host ("Total: {0} pass, {1} fail, {2} skip" -f $pass, $fail, $skip)
}

function Run {
    param([string]$Cmd, [string[]]$ArgList)
    # PS 5.1 wraps native-command stderr in ErrorRecords when
    # ErrorActionPreference=Stop, which would turn cargo warnings into
    # script-level errors. Use Continue for the native call only and rely
    # on $LASTEXITCODE for the real pass/fail signal.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Cmd @ArgList
    } finally {
        $ErrorActionPreference = $prev
    }
    if ($LASTEXITCODE -ne 0) {
        throw "$Cmd exited $LASTEXITCODE"
    }
}

# ----------------------------------------------------------------------
# 1. cargo test --workspace
# ----------------------------------------------------------------------
Step 'cargo test --workspace' $null {
    Push-Location $RustRoot
    try {
        Run 'cargo' @('test', '--workspace', '--quiet')
    } finally {
        Pop-Location
    }
}

# ----------------------------------------------------------------------
# 2. M1 oracle (schema parse + generators)
# ----------------------------------------------------------------------
Step 'm1_diff.py (schema + generators byte-identical)' {
    $cppPath = Join-Path $RepoRoot 'Shared\ArchGeometry\build\tools\Release\archgeometry_dump.exe'
    if (-not (Test-Path $cppPath)) {
        return "missing $cppPath"
    }
    $rustPath = Join-Path $RustRoot 'target\release\archgeometry_dump.exe'
    if (-not (Test-Path $rustPath)) {
        return "missing $rustPath (build: cargo build --release --bin archgeometry_dump)"
    }
    return $null
} {
    Run 'python' @((Join-Path $RustRoot 'tests\m1_diff.py'))
}

# ----------------------------------------------------------------------
# 3. M4 oracle (drawing pipeline)
# ----------------------------------------------------------------------
Step 'm4_diff.py (drawing pipeline byte-identical)' {
    if (-not (Test-Path (Join-Path $KernelBuild 'drawing_dump.exe'))) {
        return "missing $KernelBuild\drawing_dump.exe"
    }
    return $null
} {
    Run 'python' @((Join-Path $RustRoot 'tests\m4_diff.py'))
}

# ----------------------------------------------------------------------
# 4. M5 C++ oracle (qbd_interface byte-identical)
# ----------------------------------------------------------------------
Step 'm5_cpp_diff.py (C++ QBDInterface byte-identical)' {
    if (-not (Test-Path (Join-Path $KernelBuild 'qbd_dump.exe'))) {
        return "missing $KernelBuild\qbd_dump.exe (build: cmake --build . --target qbd_dump --config Release)"
    }
    if (-not (Test-Path (Join-Path $RustRoot 'target\release\qbd_dump.exe'))) {
        return "missing rust release qbd_dump (build: cargo build --release --bin qbd_dump)"
    }
    return $null
} {
    Run 'python' @((Join-Path $RustRoot 'tests\m5_cpp_diff.py'))
}

# ----------------------------------------------------------------------
# 5. M5 Python equivalence (rust vs permit_drawing_set.py)
# ----------------------------------------------------------------------
if (-not $SkipPython) {
    Step 'm5_diff.py (Python pipeline equivalence)' {
        if (-not (Test-Path (Join-Path $RustRoot 'target\release\qbd_dump.exe'))) {
            return 'missing rust release qbd_dump'
        }
        return $null
    } {
        Run 'python' @((Join-Path $RustRoot 'tests\m5_diff.py'))
    }
}

Print-Summary

# Exit 1 if any FAIL.
if ($Results.Values -contains 'FAIL') {
    exit 1
}
exit 0
