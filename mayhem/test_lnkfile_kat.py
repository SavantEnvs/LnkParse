#!/usr/bin/env python3
"""Known-answer behavioral test for LnkParse (the `lnkfile` parser).

This is an ADDITIVE oracle (it lives under mayhem/, never touches upstream). It
parses the sample shortcut shipped in upstream `tests/microsoft_example.lnk` via
LnkParse's public API (`lnkfile.lnk_file`) and asserts field values that were
derived BY HAND from the raw bytes of that file cross-referenced against the
[MS-SHLLINK] Shell Link Binary File Format spec — NOT by running LnkParse and
recording whatever it returned.

Ground truth (independently decoded; offsets are into the raw file):
  * ShellLinkHeader @0x00:
      - HeaderSize  @0x00 (LE u32) = 4c 00 00 00            -> 0x4C = 76   (spec: MUST be 0x4C)
      - LinkCLSID   @0x04 (16 bytes)= 01 14 02 00 00 00 00 00 c0 00 00 00 00 00 00 46
                                       -> hex "0114020000000000c000000000000046"
                                          (the standard ShellLink CLSID 00021401-0000-0000-C000-000000000046)
      - LinkFlags   @0x14 (LE u32) = 9b 00 08 00            -> 0x0008009B
            bits set: 0 HasTargetIDList, 1 HasLinkInfo, 3 HasRelativePath,
                      4 HasWorkingDir, 7 IsUnicode, 19 EnableTargetMetadata
      - FileAttrs   @0x18 (LE u32) = 20 00 00 00            -> 0x20 (FILE_ATTRIBUTE_ARCHIVE)
      - FileSize    @0x34 (LE u32) = 00 00 00 00            -> 0
      - ShowCommand @0x3C (LE u32) = 01 00 00 00            -> 1 (SW_SHOWNORMAL / SW_NORMAL)
  * TargetIDList size @0x4C (LE u16) = bd 00 -> 0xBD=189; LinkInfo begins at 0x4E+189 = 0x10B.
  * LinkInfo @0x10B: LinkInfoSize=60, LinkInfoHeaderSize=28, LinkInfoFlags=1
      (VolumeIDAndLocalBasePath); LocalBasePathOffset @0x11B = 45 -> LocalBasePath
      at 0x10B+45 = 0x138: ascii "C:\\test\\a.txt".
  * StringData @0x167 (LinkInfo end), IsUnicode so each entry is u16 CountChars + UTF-16LE:
      - RelativePath  : CountChars 7, ".\\a.txt"
      - WorkingDir    : CountChars 7, "C:\\test"

These literals come from the bytes + spec, so a parser that returns the WRONG
value (or empty, e.g. when neutered) fails the assertions.
"""
import io
import os

import pytest

import lnkfile

SAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests",
    "microsoft_example.lnk",
)


@pytest.fixture(scope="module")
def parsed():
    with open(SAMPLE, "rb") as fh:
        return lnkfile.lnk_file(fhandle=io.BytesIO(fh.read()))


def test_header_size_is_0x4c(parsed):
    # Spec: ShellLinkHeader.HeaderSize MUST be 0x0000004C.
    assert parsed.lnk_header["header_size"] == 76


def test_link_clsid(parsed):
    # Spec: the well-known Shell Link CLSID 00021401-0000-0000-C000-000000000046.
    assert parsed.lnk_header["guid"] == "0114020000000000c000000000000046"


def test_raw_link_flags(parsed):
    assert parsed.lnk_header["rlinkFlags"] == 0x0008009B


def test_decoded_link_flags(parsed):
    flags = set(parsed.lnk_header["linkFlags"])
    assert flags == {
        "HasTargetIDList",
        "HasLinkInfo",
        "HasRelativePath",
        "HasWorkingDir",
        "IsUnicode",
        "EnableTargetMetadata",
    }
    # Flags whose bits are CLEAR must not appear.
    assert "HasName" not in flags
    assert "HasArguments" not in flags


def test_file_size_field(parsed):
    assert parsed.lnk_header["file_size"] == 0


def test_local_base_path(parsed):
    assert parsed.loc_information["LocalBasePath"] == "C:\\test\\a.txt"


def test_relative_path(parsed):
    assert parsed.data["relativePath"] == ".\\a.txt"


def test_working_directory(parsed):
    assert parsed.data["workingDirectory"] == "C:\\test"
