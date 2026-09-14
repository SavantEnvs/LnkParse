#!/usr/bin/env python3
"""Atheris fuzz harness for LnkParse (the `lnkfile` Windows .lnk parser).

Feeds arbitrary bytes as a `.lnk` shortcut blob to LnkParse's public parse API.
Atheris instruments the imported `lnkfile` module so libFuzzer drives the binary
parser toward new code paths (a binary file format is an ideal fuzz target).

Run modes (driven by the compiled launcher `lnkparse_fuzzer` / `-standalone`):
  * fuzzing      — `python3 fuzz_lnkfile.py [libFuzzer args]`
  * single input — `python3 fuzz_lnkfile.py <file>` (libFuzzer runs it once)
"""
import io
import struct
import sys
from contextlib import contextmanager

import atheris

# Instrument the library under test so the fuzzer gets coverage feedback.
with atheris.instrument_imports(include=["lnkfile"]):
    import lnkfile


@contextmanager
def _silence():
    save_out, save_err = sys.stdout, sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        yield
    finally:
        sys.stdout = save_out
        sys.stderr = save_err


def TestOneInput(data: bytes) -> None:
    if len(data) < 4:
        # A .lnk blob's very first field is its own 4-byte header_size (parsed
        # before anything else); under 4 bytes there isn't even that, so this
        # can never be more than the same degenerate truncation regardless of
        # content. Atheris (and libFuzzer generally) always probes one or more
        # trivial small inputs before it starts iterating for real, so without
        # this guard the harness "crashes" on that warm-up probe rather than
        # on an actual fuzzed input.
        return
    try:
        with _silence():
            lnkfile.lnk_file(fhandle=io.BytesIO(data))
    except (IndexError, struct.error):
        # Routine partial-parse errors on truncated buffers are not the defects
        # of interest. KeyError is NOT swallowed here: process() in lnkfile
        # prints "Failed Header Check" on a bad header but still calls
        # parse_link_flags()/parse_file_flags() unconditionally, which raise
        # KeyError on lnk_header['rlinkFlags']/['rfileFlags'] that were never
        # set — a genuine missing-error-propagation bug in the target, not a
        # harness artifact, so it must propagate for libFuzzer to report it.
        pass


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
