"""Evaluate the actual CPU report commands with Tcl stubs, never FPGA tools."""
from pathlib import Path
import shutil
import subprocess
import unittest


SOURCE = Path(__file__).with_name("build_native_board.tcl")
EXPECTED = {
    "cpu_paths.rpt": "min_max",
    "cpu_setup_paths.rpt": "max",
    "cpu_hold_paths.rpt": "min",
}
MOCKS = r'''
proc get_pins {args} {
    if {$args ne {u_soc/clock}} {error "wrong CPU clock pin"}
    return cpu_pin_fixture
}
proc get_clocks {args} {
    if {$args ne {-of_objects cpu_pin_fixture}} {error "wrong clock query"}
    return cpu_clock_fixture
}
proc report_timing {args} {puts $args}
'''


def report_block(text):
    start = "set cpuClock "
    end = "# Query every physical lane independently:"
    if text.count(start) != 1 or text.count(end) != 1:
        raise AssertionError("review the changed CPU report section")
    return start + text.split(start, 1)[1].split(end, 1)[0]


def check_commands(block):
    # No other board script is evaluated. Unknown commands fail in plain Tcl.
    script = MOCKS + '\nif {[catch {\n' + block + '\n} message]} {\nputs stderr $message\nexit 1\n}\n'
    result = subprocess.run([shutil.which("tclsh") or "tclsh"], input=script,
                            text=True, capture_output=True, check=False)
    if result.returncode:
        raise AssertionError(result.stderr)
    records = [line.split() for line in result.stdout.splitlines() if line.strip()]
    if len(records) != len(EXPECTED):
        raise AssertionError("all three separate CPU reports are required")
    seen = set()
    for args in records:
        if len(args) != 11 or args.count("-input_pins") != 1:
            raise AssertionError("unexpected or missing report options")
        pairs = args[:]
        pairs.remove("-input_pins")
        options = dict(zip(pairs[::2], pairs[1::2]))
        if len(options) != 5 or set(options) != {"-from", "-to", "-delay_type", "-max_paths", "-file"}:
            raise AssertionError("unexpected or duplicate report options")
        name = options["-file"]
        if name in seen or name not in EXPECTED:
            raise AssertionError("missing or duplicate CPU report name")
        seen.add(name)
        if options["-from"] != "cpu_clock_fixture" or options["-to"] != "cpu_clock_fixture":
            raise AssertionError("CPU report scope changed")
        if options["-delay_type"] != EXPECTED[name] or options["-max_paths"] != "20":
            raise AssertionError("CPU report delay type or path limit changed")
    if seen != set(EXPECTED):
        raise AssertionError("incomplete CPU report set")


class CpuTimingReportTests(unittest.TestCase):
    def setUp(self):
        self.block = report_block(SOURCE.read_text())

    def test_actual_board_script_preserves_legacy_and_explicit_setup_hold(self):
        check_commands(self.block)

    def test_missing_report_is_rejected(self):
        for name in EXPECTED:
            with self.subTest(name=name), self.assertRaises(AssertionError):
                check_commands("\n".join(line for line in self.block.splitlines() if name not in line))

    def test_setup_and_hold_cannot_be_interchanged_or_combined(self):
        for name, delay in EXPECTED.items():
            for wrong in set(EXPECTED.values()) - {delay}:
                changed = "\n".join(line.replace("-delay_type " + delay, "-delay_type " + wrong)
                                    if name in line else line for line in self.block.splitlines())
                with self.subTest(name=name, wrong=wrong), self.assertRaises(AssertionError):
                    check_commands(changed)

    def test_wrong_clock_or_one_sided_scope_is_rejected(self):
        for before, after in (("u_soc/clock", "u_soc/io_alwaysOnClock"),
                              ("-from $cpuClock", "-from unrelated_clock"),
                              ("-to $cpuClock", "-to unrelated_clock"),
                              ("-from $cpuClock ", ""), ("-to $cpuClock ", "")):
            with self.subTest(before=before), self.assertRaises(AssertionError):
                check_commands(self.block.replace(before, after))

    def test_duplicate_outputs_and_missing_detail_are_rejected(self):
        for before, after in (("cpu_setup_paths.rpt", "cpu_paths.rpt"),
                              ("-input_pins ", ""), ("-max_paths 20", "-max_paths 1")):
            with self.subTest(before=before), self.assertRaises(AssertionError):
                check_commands(self.block.replace(before, after))

    def test_unexpected_command_cannot_invoke_fpga_tool(self):
        with self.assertRaises(AssertionError):
            check_commands(self.block + "\nroute_design\n")


if __name__ == "__main__":
    unittest.main()
