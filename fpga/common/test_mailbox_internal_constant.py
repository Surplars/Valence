#!/usr/bin/env python3
"""Run the 94 structural Tcl cases and 13 in-memory mutation controls.

Run from the repository root with:
    python3 -m unittest fpga.common.test_mailbox_internal_constant
or invoke this file directly. This invokes Tcl only, not Vivado, and never
rewrites the checker. The immutable old checker is read from Git, verified,
and materialized only in a temporary directory.
"""
import base64
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TEST = Path(__file__).resolve().with_suffix(".tcl")
CANDIDATE = TEST.with_name("common_cdc.tcl")
BASELINE_BLOB = "86f762352bcfea354bd7a030d6e981354e0a1a88"
BASELINE_SHA256 = "99b5ce0b4c2998275122cf4ed3189cdaa7138f59027c9640a5b5bc5d6fd2dc10"


def tcl_value(value):
    encoded = base64.b64encode(str(value).encode()).decode()
    return f"[encoding convertfrom utf-8 [binary decode base64 {{{encoded}}}]]"


class MailboxInternalConstantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        original = subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "blob", BASELINE_BLOB],
            check=True, stdout=subprocess.PIPE,
        ).stdout
        actual = hashlib.sha256(original).hexdigest()
        if actual != BASELINE_SHA256:
            raise RuntimeError(
                f"Frozen checker SHA-256 mismatch: {actual}; expected {BASELINE_SHA256}"
            )
        temporary = tempfile.TemporaryDirectory(prefix="mailbox-internal-constant-")
        cls.addClassCleanup(temporary.cleanup)
        cls.baseline = Path(temporary.name) / "common_cdc.baseline.tcl"
        cls.baseline.write_bytes(original)

    def test_structural_cases(self):
        result = subprocess.run(
            ["tclsh", str(TEST), "--candidate", str(CANDIDATE),
             "--baseline", str(self.baseline)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("MAILBOX_INTERNAL_CONSTANT_PASS cases=94 ", result.stdout)
        print(result.stdout, end="", flush=True)

    def test_mutation_controls(self):
        candidate = CANDIDATE.resolve(strict=True)
        helper = "common_cdc::mailbox_unconsumed_constant"
        mutants = [
            ("fanin_quiet", helper, "all_fanin -flat -trace_arcs all -to $lower", "all_fanin -quiet -flat -trace_arcs all -to $lower", "must not suppress traversal errors"),
            ("fanout_quiet", helper, "all_fanout -flat -trace_arcs all -endpoints_only -from $p", "all_fanout -quiet -flat -trace_arcs all -endpoints_only -from $p", "must not suppress traversal errors"),
            ("fanin_startpoints_only", helper, "all_fanin -flat -trace_arcs all -to $lower", "all_fanin -flat -startpoints_only -trace_arcs all -to $lower", "must not hide internal LUT/FF pins"),
            ("fanin_enabled_arcs", helper, "all_fanin -flat -trace_arcs all -to $lower", "all_fanin -flat -trace_arcs enabled -to $lower", "must traverse all arcs"),
            ("skip_primitive_property", helper, "[get_property IS_PRIMITIVE $owner] ni {1 true TRUE}", "0", "nonprimitive_constant_owner accepted"),
            ("skip_owner_class", helper, "[get_property CLASS $owner] ne {cell}", "0", "owner_wrong_class accepted"),
            ("skip_output_clocks", helper, "[llength [get_clocks -of_objects $p]]", "0", "output_clock_present accepted"),
            ("skip_fanout", helper, "[llength [all_fanout -flat -trace_arcs all -endpoints_only -from $p]]", "0", "output_fanout_endpoint accepted"),
            ("skip_lower_type", helper, 'if {$type ni {GROUND POWER}} {error "COMMON_CDC nonliteral internal lower net $output"}', "", "lower_nonliteral_type_SIGNAL accepted"),
            ("regress_pin_instead_of_lower_net", helper, "set cone [all_fanin -flat -trace_arcs all -to $lower]", "set cone [all_fanin -flat -trace_arcs all -to $p]", "internal lower-net driver/cone mismatch"),
            ("skip_lower_polarity", helper, 'if {$value!=($type eq {POWER})} {error "COMMON_CDC lower-net type/driver literal mismatch $output"}', "", "lower_type_driver_polarity_mismatch accepted"),
            ("skip_unknown_name", helper, 'if {$name eq {}} {error "COMMON_CDC unnamed internal constant cone object $output"}', "", "cone_unnamed_driver accepted"),
            ("skip_surplus_capture_census", "common_cdc::mailbox_width", "if {[lsearch -exact $captures $name]>=0} {continue}", "continue", "surplus_unaccounted_capture accepted"),
        ]
        self.assertEqual(len(mutants), 13)
        for name, proc_name, before, after, expected in mutants:
            script = f"""
    set ::valence(root) {tcl_value(ROOT)}
    set candidate {tcl_value(candidate)}
    source $candidate
    set procName {tcl_value(proc_name)}
    set body [info body $procName]
    set before {tcl_value(before)}
    set after {tcl_value(after)}
    if {{[string first $before $body]<0}} {{puts stderr MUTATION_TARGET_NOT_FOUND; exit 2}}
    set replacement [string map [list $before $after] $body]
    proc $procName [info args $procName] $replacement
    # The test sources the same candidate. Keep this interpreter-local mutation
    # instead; no checker or test files are rewritten.
    rename source unmodified_source
    proc source {{path}} {{
        if {{[file normalize $path] eq $::candidate}} {{return}}
        uplevel 1 [list unmodified_source $path]
    }}
    set argv [list --candidate $candidate]
    if {{[catch {{unmodified_source {tcl_value(TEST)}}} why]}} {{puts stderr $why; exit 1}}
    puts stderr MUTANT_UNEXPECTEDLY_ACCEPTED
    exit 0
    """
            result = subprocess.run(
                ["tclsh"], input=script, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            diagnostic = (
                f"{name}: rc={result.returncode}, expected={expected!r}\n"
                f"{result.stdout}\n{result.stderr}"
            )
            self.assertEqual(result.returncode, 1, diagnostic)
            self.assertIn(expected, result.stderr, diagnostic)
            print(f"MUTANT_REJECTED {name}: {expected}", flush=True)
        print(
            f"MAILBOX_MUTATION_CONTROLS_PASS count={len(mutants)} "
            "STRUCTURAL_TCL_ONLY_NOT_NATIVE_VIVADO_QUALIFIED", flush=True,
        )


if __name__ == "__main__":
    unittest.main()
