"""Independent identity contracts, source drift guards, and exact ROM image checks."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import unittest

from audit_bootrom import audit


# Keep these expectations independent of the auditor's contract definitions.
ROM_SIZE = 131072
WORD_COUNT = 32768
FIRMWARE = Path(__file__).resolve().parent
ANSI_SOURCE_TOKENS = (
    ("bootrom.c", b"Valence Bootrom V0.2 | verified downloads auto-boot\r\n\0"),
    ("boot_tui.h", b"n/1  Network download + boot (TFTP)\0"),
    ("boot_tui.h", b"d/2  UART download + boot (VLD1)\0"),
    ("boot_tui.h", b"c/C/5  CoreMark formal (measured >10 seconds, all CRCs)\0"),
    ("monitor_diag.c", b"EXTERNAL STATE LOCKED; BOARD RESET REQUIRED\r\n\0"),
)
PROFILE_TOKENS = {
    "minimal": (b"Valence Bootrom V0.1\r\n\0", b"download mode (UART)\r\n\0"),
    "menu": (b"Valence Bootrom V0.1\r\n\0", b"monitor> \0", b"locked> \0",
             b"EXTERNAL STATE LOCKED; BOARD RESET REQUIRED\r\n\0"),
    "ansi-menu": tuple(token for _, token in ANSI_SOURCE_TOKENS),
}
DCP_BYTES = b"test fixture, not a real FPGA checkpoint"


def profile_data(profile):
    # Separators ensure deleting a NUL cannot accidentally borrow the next token's.
    return b"\x13\x01\x02\x03" + b"\xa5".join(PROFILE_TOKENS[profile]) + b"\xfe\x01"


def mif_text(data):
    # Encode through struct, independently of the auditor's int/to_bytes decoder.
    padded = data + bytes(ROM_SIZE - len(data))
    return "".join(f"{word:032b}\n" for (word,) in struct.iter_unpack("<I", padded))


def source_strings(path):
    # Lex strings and comments together so commented-out identities cannot pass.
    parts = re.findall(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/',
                       path.read_text(encoding="utf-8"))
    return [ast.literal_eval(part).encode("ascii") + b"\0"
            for part in parts if part.startswith('"')]


class AuditBootromTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def fixture(self, profile="minimal", data=None):
        if data is None:
            data = profile_data(profile)
        binary, mif, dcp = (self.directory / name
                            for name in ("bootrom.bin", "bootrom.mif", "bootrom.dcp"))
        binary.write_bytes(data)
        mif.write_text(mif_text(data), encoding="ascii")
        dcp.write_bytes(DCP_BYTES)
        self.mark_checkpoint_current(mif, dcp)
        return binary, mif, dcp

    def mark_checkpoint_current(self, mif, dcp):
        # Explicit nanosecond times make checkpoint ordering deterministic.
        os.utime(mif, ns=(1_700_000_000_000_000_000,) * 2)
        os.utime(dcp, ns=(1_700_000_001_000_000_000,) * 2)

    def run_cli(self, files, *arguments):
        binary, mif, dcp = files
        manifest = self.directory / "manifest.json"
        result = subprocess.run(
            [sys.executable, "-B", str(FIRMWARE / "audit_bootrom.py"),
             "--bin", str(binary), "--mif", str(mif), "--dcp", str(dcp),
             "--manifest", str(manifest), *arguments],
            capture_output=True, text=True, check=False,
        )
        return result, manifest

    def test_minimal_default_and_manifest(self):
        binary, mif, dcp = self.fixture()
        result = audit(binary, mif, dcp)
        self.assertEqual(result["profile"], "minimal")
        self.assertEqual(result["binary"], str(binary.resolve()))
        self.assertEqual(result["binaryBytes"], len(profile_data("minimal")))
        self.assertEqual(result["binarySha256"], hashlib.sha256(binary.read_bytes()).hexdigest())
        self.assertEqual(result["mif"], str(mif.resolve()))
        self.assertEqual(result["mifWordsMatched"], WORD_COUNT)
        self.assertEqual(result["romDcp"], str(dcp.resolve()))
        self.assertEqual(result["romDcpSha256"], hashlib.sha256(DCP_BYTES).hexdigest())

    def test_explicit_profiles(self):
        for profile in PROFILE_TOKENS:
            with self.subTest(profile=profile):
                result = audit(*self.fixture(profile), profile=profile)
                self.assertEqual(result["profile"], profile)
                self.assertEqual(result["mifWordsMatched"], WORD_COUNT)

    def test_ansi_source_tokens_have_not_drifted(self):
        for filename, token in ANSI_SOURCE_TOKENS:
            with self.subTest(source=filename, token=token):
                self.assertIn(token, source_strings(FIRMWARE / filename))
        for filename in {name for name, _ in ANSI_SOURCE_TOKENS}:
            with self.subTest(source=filename):
                self.assertFalse(any(b"Run verified RAM image" in token
                                     for token in source_strings(FIRMWARE / filename)))

    def test_ansi_missing_each_required_token(self):
        for _, token in ANSI_SOURCE_TOKENS:
            with self.subTest(token=token):
                data = profile_data("ansi-menu").replace(token, b"", 1)
                with self.assertRaisesRegex(ValueError, "ansi-menu.*V0.2.*missing"):
                    audit(*self.fixture(data=data), profile="ansi-menu")

    def test_ansi_corrupted_each_required_token(self):
        for _, token in ANSI_SOURCE_TOKENS:
            with self.subTest(token=token):
                data = profile_data("ansi-menu").replace(token, b"?" + token[1:], 1)
                with self.assertRaisesRegex(ValueError, "ansi-menu.*missing"):
                    audit(*self.fixture(data=data), profile="ansi-menu")

    def test_ansi_each_token_requires_nul_termination(self):
        for _, token in ANSI_SOURCE_TOKENS:
            with self.subTest(token=token):
                data = profile_data("ansi-menu").replace(token, token[:-1] + b"!", 1)
                with self.assertRaisesRegex(ValueError, "ansi-menu.*missing"):
                    audit(*self.fixture(data=data), profile="ansi-menu")

    def test_ansi_line_endings_are_exact(self):
        for _, token in ANSI_SOURCE_TOKENS:
            if b"\r\n" not in token:
                continue
            with self.subTest(token=token):
                data = profile_data("ansi-menu").replace(token, token.replace(b"\r\n", b"\n"), 1)
                with self.assertRaisesRegex(ValueError, "ansi-menu.*missing"):
                    audit(*self.fixture(data=data), profile="ansi-menu")

    def test_ansi_rejects_retired_manual_launch(self):
        for retired in (b"Run verified RAM image\0", b"r/4  Run verified RAM image (old)\0"):
            with self.subTest(retired=retired):
                data = profile_data("ansi-menu") + retired
                with self.assertRaisesRegex(ValueError, "retired manual-launch"):
                    audit(*self.fixture(data=data), profile="ansi-menu")

    def test_legacy_profiles_keep_manual_launch_compatibility(self):
        for profile in ("minimal", "menu"):
            with self.subTest(profile=profile):
                data = profile_data(profile) + b"Run verified RAM image\0"
                self.assertEqual(audit(*self.fixture(data=data), profile=profile)["profile"], profile)

    def test_legacy_profiles_require_all_original_tokens(self):
        for profile in ("minimal", "menu"):
            for token in PROFILE_TOKENS[profile]:
                with self.subTest(profile=profile, token=token):
                    data = profile_data(profile).replace(token, b"", 1)
                    with self.assertRaisesRegex(ValueError, profile + ".*V0.1.*missing"):
                        audit(*self.fixture(data=data), profile=profile)

    def test_retired_diagnostics_rejected_in_every_profile(self):
        for profile in PROFILE_TOKENS:
            for token in (b"r:RAM", b"CPU OK"):
                with self.subTest(profile=profile, token=token):
                    with self.assertRaisesRegex(ValueError, "retired ROM diagnostics"):
                        audit(*self.fixture(data=profile_data(profile) + token), profile=profile)

    def test_every_wrong_profile_rejected(self):
        for image_profile in PROFILE_TOKENS:
            files = self.fixture(image_profile)
            for requested in PROFILE_TOKENS:
                if image_profile == requested:
                    continue
                with self.subTest(image=image_profile, requested=requested):
                    with self.assertRaisesRegex(ValueError, requested + ".*missing"):
                        audit(*files, profile=requested)

    def test_unknown_profile_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown BootROM profile"):
            audit(*self.fixture(), profile="anything")

    def test_empty_rom_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid BootROM binary size"):
            audit(*self.fixture(data=b""))

    def test_oversize_rom_rejected(self):
        binary, mif, dcp = self.fixture("ansi-menu")
        binary.write_bytes(profile_data("ansi-menu").ljust(ROM_SIZE + 1, b"\xa5"))
        with self.assertRaisesRegex(ValueError, "invalid BootROM binary size"):
            audit(binary, mif, dcp, profile="ansi-menu")

    def test_full_capacity_rom_accepted(self):
        data = profile_data("ansi-menu").ljust(ROM_SIZE, b"\xa5")
        result = audit(*self.fixture(data=data), profile="ansi-menu")
        self.assertEqual(result["binaryBytes"], ROM_SIZE)
        self.assertEqual(result["mifWordsMatched"], WORD_COUNT)

    def test_non_word_aligned_rom_accepted(self):
        data = profile_data("ansi-menu")
        data += b"\xfe" * ((1 - len(data)) % 4)
        self.assertEqual(len(data) % 4, 1)
        self.assertEqual(audit(*self.fixture(data=data), profile="ansi-menu")["binaryBytes"], len(data))

    def test_malformed_mif_word_rejected(self):
        for word in ("0" * 31, "0" * 33, "0" * 31 + "2", "0" * 31 + " ", ""):
            with self.subTest(word=word):
                binary, mif, dcp = self.fixture("ansi-menu")
                words = mif.read_text(encoding="ascii").splitlines()
                words[12345] = word
                mif.write_text("\n".join(words) + "\n", encoding="ascii")
                with self.assertRaisesRegex(ValueError, "expected 32768 binary MIF words"):
                    audit(binary, mif, dcp, profile="ansi-menu")

    def test_truncated_mif_rejected(self):
        binary, mif, dcp = self.fixture("ansi-menu")
        mif.write_bytes(mif.read_bytes()[:-33])
        with self.assertRaisesRegex(ValueError, "expected 32768 binary MIF words"):
            audit(binary, mif, dcp, profile="ansi-menu")

    def test_extra_mif_word_rejected(self):
        binary, mif, dcp = self.fixture("ansi-menu")
        mif.write_bytes(mif.read_bytes() + b"0" * 32 + b"\n")
        with self.assertRaisesRegex(ValueError, "expected 32768 binary MIF words"):
            audit(binary, mif, dcp, profile="ansi-menu")

    def test_non_ascii_mif_rejected(self):
        binary, mif, dcp = self.fixture("ansi-menu")
        mif.write_bytes(b"\xff" + mif.read_bytes()[1:])
        with self.assertRaises(UnicodeDecodeError):
            audit(binary, mif, dcp, profile="ansi-menu")

    def test_changed_mif_payload_words_rejected(self):
        data = profile_data("ansi-menu").ljust(ROM_SIZE, b"\xa5")
        for index in (0, 12345, WORD_COUNT - 1):
            with self.subTest(word=index):
                binary, mif, dcp = self.fixture(data=data)
                changed = bytearray(data)
                changed[index * 4] ^= 1
                mif.write_text(mif_text(changed), encoding="ascii")
                self.mark_checkpoint_current(mif, dcp)
                with self.assertRaisesRegex(ValueError, "MIF differs"):
                    audit(binary, mif, dcp, profile="ansi-menu")

    def test_changed_padding_bytes_rejected(self):
        data = profile_data("ansi-menu")
        for offset in (len(data), ROM_SIZE // 2, ROM_SIZE - 1):
            with self.subTest(byte=offset):
                binary, mif, dcp = self.fixture(data=data)
                changed = bytearray(data.ljust(ROM_SIZE, b"\0"))
                changed[offset] = 1
                mif.write_text(mif_text(changed), encoding="ascii")
                self.mark_checkpoint_current(mif, dcp)
                with self.assertRaisesRegex(ValueError, "MIF differs"):
                    audit(binary, mif, dcp, profile="ansi-menu")

    def test_big_endian_mif_rejected(self):
        data = profile_data("ansi-menu")
        binary, mif, dcp = self.fixture(data=data)
        words = struct.iter_unpack(">I", data.ljust(ROM_SIZE, b"\0"))
        mif.write_text("".join(f"{word:032b}\n" for (word,) in words), encoding="ascii")
        self.mark_checkpoint_current(mif, dcp)
        with self.assertRaisesRegex(ValueError, "MIF differs"):
            audit(binary, mif, dcp, profile="ansi-menu")

    def test_missing_checkpoint_rejected(self):
        binary, mif, dcp = self.fixture("ansi-menu")
        dcp.unlink()
        with self.assertRaisesRegex(ValueError, "missing ROM IP checkpoint"):
            audit(binary, mif, dcp, profile="ansi-menu")

    def test_empty_checkpoint_rejected(self):
        binary, mif, dcp = self.fixture("ansi-menu")
        dcp.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "missing ROM IP checkpoint"):
            audit(binary, mif, dcp, profile="ansi-menu")

    def test_directory_checkpoint_rejected(self):
        binary, mif, dcp = self.fixture("ansi-menu")
        with self.assertRaisesRegex(ValueError, "missing ROM IP checkpoint"):
            audit(binary, mif, self.directory, profile="ansi-menu")

    def test_stale_checkpoint_rejected(self):
        binary, mif, dcp = self.fixture("ansi-menu")
        os.utime(dcp, ns=(mif.stat().st_mtime_ns - 1,) * 2)
        with self.assertRaisesRegex(ValueError, "ROM DCP predates its MIF"):
            audit(binary, mif, dcp, profile="ansi-menu")

    def test_equal_checkpoint_timestamp_accepted(self):
        binary, mif, dcp = self.fixture("ansi-menu")
        os.utime(dcp, ns=(mif.stat().st_mtime_ns,) * 2)
        self.assertEqual(audit(binary, mif, dcp, profile="ansi-menu")["profile"], "ansi-menu")

    def test_cli_default_remains_minimal(self):
        result, manifest = self.run_cli(self.fixture())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BOOTROM_IMAGE: PASS", result.stdout)
        self.assertEqual(json.loads(manifest.read_text())["profile"], "minimal")

    def test_cli_explicit_profiles(self):
        for profile in PROFILE_TOKENS:
            with self.subTest(profile=profile):
                result, manifest = self.run_cli(self.fixture(profile), "--profile", profile)
                self.assertEqual(result.returncode, 0, result.stderr)
                parsed = json.loads(manifest.read_text())
                self.assertEqual(parsed["profile"], profile)
                self.assertEqual(parsed["mifWordsMatched"], WORD_COUNT)
                self.assertEqual(parsed["binarySha256"], hashlib.sha256(profile_data(profile)).hexdigest())

    def test_cli_default_rejects_ansi_image(self):
        result, manifest = self.run_cli(self.fixture("ansi-menu"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("minimal Bootrom V0.1 identity/contract missing", result.stderr)
        self.assertFalse(manifest.exists())

    def test_cli_unknown_profile_rejected(self):
        result, manifest = self.run_cli(self.fixture(), "--profile", "anything")
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)
        self.assertFalse(manifest.exists())

    def test_cli_rejects_ansi_contract_drift(self):
        data = profile_data("ansi-menu").replace(b"all CRCs", b"one CRCs")
        result, manifest = self.run_cli(self.fixture(data=data), "--profile", "ansi-menu")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ansi-menu Bootrom V0.2 identity/contract missing", result.stderr)
        self.assertFalse(manifest.exists())


if __name__ == "__main__":
    unittest.main()
