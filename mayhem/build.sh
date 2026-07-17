#!/usr/bin/env bash
#
# mayhem/build.sh — build the LnkParse (lnkfile) Atheris fuzz harness + its standalone
# reproducer, and prepare the project's pytest oracle. Runs inside the commit image
# (mayhem/Dockerfile) as `mayhem` in /mayhem. Python adaptation of the C/C++ template.
#
# Idempotent + air-gapped on re-run (SPEC §6.2 item 9 / §6.5):
#   1. Populate / reuse an in-image wheelhouse under /opt/toolchains/python (HOME-independent),
#      then install atheris + pytest OFFLINE from that wheelhouse into a fixed site dir on
#      PYTHONPATH. The first (CI, online) build fills the wheelhouse; the air-gapped PATCH
#      re-run resolves entirely from it (pip --no-index --find-links).
#   2. Compile launcher.c -> the ELF Mayhem target `lnkparse_fuzzer` (Atheris is a Python
#      script; Mayhem needs an ELF cmd, and the gate needs DWARF < 4 — hence a compiled wrapper).
#   3. Build the same launcher as the standalone (run-once) reproducer `lnkparse_fuzzer-standalone`.
#   4. Compile run_tests.c -> the ELF pytest wrapper (so the sabotage check bites the oracle).
#
# lnkfile is a single-module package at the REPO ROOT (no src/ layout), so we expose the repo
# root itself on PYTHONPATH; the package stays an editable source tree (a PATCH agent's edits
# under ./lnkfile take effect with no reinstall).
#
# The base image exports the build contract (CC, SANITIZER_FLAGS, DEBUG_FLAGS, ...). The Mayhem
# target here is a thin C exec wrapper, so we apply $DEBUG_FLAGS (DWARF < 4) to it but NOT
# $SANITIZER_FLAGS: sanitizing the wrapper would instrument the launcher, not the fuzzed Python —
# Atheris instruments the `lnkfile` library itself at import time, which is where coverage + bug
# detection happen. ($SANITIZER_FLAGS stays available for any future native extension.)
set -euo pipefail

[ -n "${SOURCE_DATE_EPOCH:-}" ] || unset SOURCE_DATE_EPOCH

: "${DEBUG_FLAGS:=-g -gdwarf-3}"
: "${CC:=clang}"
: "${MAYHEM_JOBS:=$(nproc)}"
export DEBUG_FLAGS CC MAYHEM_JOBS

SRC="${SRC:-/mayhem}"
cd "$SRC"

# ── Python toolchain caches at a FIXED, $HOME-independent prefix (SPEC §6.2 item 8) ──
PY_PREFIX=/opt/toolchains/python
WHEELHOUSE="$PY_PREFIX/wheelhouse"
SITE="$PY_PREFIX/site"
mkdir -p "$WHEELHOUSE" "$SITE"

PY="$(command -v python3)"

# 1) Wheelhouse: download runtime/test deps ONCE (online). atheris ships a prebuilt manylinux
#    wheel for this CPython; pytest runs the KAT oracle. lnkfile itself has NO third-party
#    runtime deps (pure stdlib), so it is NOT installed from the wheelhouse — it stays editable.
PKGS=(atheris pytest)
need_download=0
"$PY" -c "import os,glob,sys; sys.exit(0 if glob.glob(os.path.join('$WHEELHOUSE','atheris-*.whl')) else 1)" || need_download=1
if [ "$need_download" -eq 1 ]; then
  echo ">> populating wheelhouse (online) at $WHEELHOUSE"
  "$PY" -m pip download --dest "$WHEELHOUSE" "${PKGS[@]}"
else
  echo ">> wheelhouse already populated — reusing $WHEELHOUSE (air-gapped re-run path)"
fi

# 2) Install the deps into the fixed site dir, OFFLINE from the wheelhouse. Guarded to be
#    idempotent: once atheris+pytest are present we SKIP the reinstall.
if "$PY" -c "import os,glob,sys; sys.exit(0 if (glob.glob(os.path.join('$SITE','atheris*')) and glob.glob(os.path.join('$SITE','pytest*'))) else 1)"; then
  echo ">> deps already installed in $SITE — skipping (idempotent re-run)"
else
  echo ">> installing deps (offline) into $SITE"
  "$PY" -m pip install --no-index --find-links="$WHEELHOUSE" --target "$SITE" "${PKGS[@]}"
fi

# lnkfile lives at the repo root, so the repo root goes on PYTHONPATH (editable source tree).
PYRUN="$SITE:$SRC"

# Record the site dir + interpreter for test.sh / the launcher to consume.
cat > "$PY_PREFIX/env.sh" <<EOF2
export PYTHONPATH="$PYRUN\${PYTHONPATH:+:\$PYTHONPATH}"
export PYTHON_BIN="$PY"
EOF2

# Sanity: the harness imports must resolve offline now.
PYTHONPATH="$PYRUN" "$PY" -c 'import atheris, lnkfile, pytest; print("imports OK: lnkfile", lnkfile.__version__)'

# 3) Compile the ELF launcher target + the standalone reproducer (DWARF < 4 via $DEBUG_FLAGS).
HARNESS="$SRC/mayhem/fuzz_lnkfile.py"
# The harness MUST be executable: atheris built-in libFuzzer fork mode (how Mayhem drives the
# run) relaunches each child via the shell using argv[0] (this .py path). Without the +x bit the
# shell cannot honor the shebang, every child dies with 'Permission denied' (exit 126), and the
# Mayhem run records 0 edges. The tracked git mode is 100755; this is belt-and-suspenders in case
# the file is ever copied without its mode bit.
chmod +x "$HARNESS"
echo ">> compiling lnkparse_fuzzer (+ standalone) with DEBUG_FLAGS=$DEBUG_FLAGS"
$CC $DEBUG_FLAGS -DPYTHON="\"$PY\"" -DHARNESS="\"$HARNESS\"" \
    "$SRC/mayhem/launcher.c" -o "$SRC/lnkparse_fuzzer"
$CC $DEBUG_FLAGS -DPYTHON="\"$PY\"" -DHARNESS="\"$HARNESS\"" \
    "$SRC/mayhem/launcher.c" -o "$SRC/lnkparse_fuzzer-standalone"

# 4) The pytest oracle runs through a compiled NON-system ELF wrapper so the gate's
#    anti-reward-hack sabotage check (neuters non-system binaries to exit(0)) bites the suite.
$CC $DEBUG_FLAGS -DPYTHON="\"$PY\"" "$SRC/mayhem/run_tests.c" -o "$SRC/lnkparse_run_tests"

echo ">> build.sh complete"
ls -la "$SRC/lnkparse_fuzzer" "$SRC/lnkparse_fuzzer-standalone" "$SRC/lnkparse_run_tests"
