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
    try:
        with _silence():
            lnkfile.lnk_file(fhandle=io.BytesIO(data))
    except (KeyError, IndexError, struct.error):
        # Routine partial-parse errors on malformed/truncated headers are not
        # the defects of interest; anything else propagates so libFuzzer reports it.
        pass


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
