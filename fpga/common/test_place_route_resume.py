"""Mock-only continuation checks; these do not qualify a physical FPGA run."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import resume_diagnostic as resume

HERE = Path(__file__).resolve().parent


@unittest.skipUnless(shutil.which('tclsh'), 'Tcl unavailable')
class DiagnosticTailTests(unittest.TestCase):
    def run_tail(self, start, fail_gate='', drc=False, wrong_clock=False):
        # Read definitions, not the native entry point. Forbidden expensive
        # synthesis/optimization commands remain completely undefined.
        script = r'''
set ::diagnostic_definitions_only 1
source {%s}
set calls {}
set valence(python) python
set valence(continuation) 0
proc common_design_step {command} {uplevel #0 $command}
foreach command {place_design phys_opt_design route_design} {
    proc $command {} [format {lappend ::calls %%s} $command]
}
proc write_checkpoint {path} {lappend ::calls "save:$path"}
proc check_timing {args} {
    set path [lindex $args end]
    set f [open $path w]
    set count [expr {$path eq "$::fail_gate-coverage.rpt" ? 1 : 0}]
    puts $f "checking no_clock ($count)"
    puts $f "checking unconstrained_internal_endpoints (0)"
    close $f
}
foreach command {report_drc report_timing_summary report_cdc report_clocks report_route_status report_bus_skew report_utilization report_timing} {
    proc $command {args} {}
}
proc get_drc_violations {args} {if {$::bad_drc} {return critical_violation}; return {}}
proc get_pins {args} {return [lindex $args end]}
proc get_clocks {args} {return [lindex $args end]}
proc get_property {key object} {
    if {$::bad_clock} {return 100.0}
    if {[string match *cpuClock $object]} {return 3.333333333333}
    return 4.0
}
rename exec original_exec
proc exec {args} {return mock-checkpoint-hash}
rename source original_source
proc source {path} {
    if {[file tail $path] ne "board_audit.tcl"} {error "Unexpected source $path"}
}
namespace eval common_board {proc run {} {}}
foreach forbidden {synth_design opt_design launch_runs} {
    if {[llength [info commands $forbidden]]} {error "Unexpected command $forbidden"}
}
set bad_drc %d
set bad_clock %d
set fail_gate {%s}
set failed [catch {diagnostic_tail {%s}} reason]
puts "FAILED=$failed"
puts "CALLS=[join $calls ,]"
puts "REASON=$reason"
''' % (HERE / 'diagnostic.tcl', drc, wrong_clock, fail_gate, start)
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(['tclsh'], input=script, text=True,
                                    capture_output=True, cwd=directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '', result.stderr)
        return result.stdout

    def test_shared_tail_runs_only_remaining_physical_steps(self):
        stages = [
            ('optimized', 'place_design,save:placed.dcp,phys_opt_design,save:physical-optimized-unqualified.dcp,route_design,save:routed.dcp'),
            ('placed', 'phys_opt_design,save:physical-optimized-unqualified.dcp,route_design,save:routed.dcp'),
            ('physical', 'route_design,save:routed.dcp'),
            ('routed', 'save:routed.dcp'),
        ]
        for stage, expected in stages:
            with self.subTest(stage=stage):
                output = self.run_tail(stage)
                self.assertIn('FAILED=0\n', output)
                self.assertIn('CALLS=' + expected + '\n', output)

    def test_completed_stage_saved_before_failing_gate(self):
        output = self.run_tail('optimized', 'placed')
        self.assertIn('FAILED=1\n', output)
        self.assertIn('CALLS=place_design,save:placed.dcp\n', output)
        self.assertIn('Blocked placed: no_clock=1', output)

    def test_entry_gate_failure_never_starts_placement(self):
        output = self.run_tail('optimized', 'entry')
        self.assertIn('FAILED=1\n', output)
        self.assertIn('CALLS=\n', output)

    def test_critical_drc_or_wrong_clock_blocks_before_placement(self):
        for kwargs, reason in (({'drc': True}, 'Error/Critical Warning DRC'),
                               ({'wrong_clock': True}, 'Actual performance clock changed')):
            with self.subTest(kwargs=kwargs):
                output = self.run_tail('optimized', **kwargs)
                self.assertIn('FAILED=1\n', output)
                self.assertIn('CALLS=\n', output)
                self.assertIn(reason, output)

    def test_unknown_stage_rejected_without_work(self):
        output = self.run_tail('synthesis')
        self.assertIn('FAILED=1\n', output)
        self.assertIn('CALLS=\n', output)
        self.assertIn('Invalid continuation stage', output)


class ContinuationProvenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.raw = self.root / 'diagnostic-run/implementation/optimized-unqualified.dcp'
        self.raw.parent.mkdir(parents=True)
        self.raw.write_bytes(b'original raw optimized checkpoint')
        self.checkpoint = self.root / 'diagnostic-run/cached-post-opt-test/optimized-checked-unqualified.dcp'
        self.checkpoint.parent.mkdir()
        self.checkpoint.write_bytes(b'checked post-opt checkpoint')
        self.digest = resume.sha(self.checkpoint)
        self.current = dict(status='DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM',
                            original_manifest_sha256='a' * 64,
                            profile_sha256='b' * 64, project_sha256='c' * 64,
                            ooc_sha256={'original-ip.dcp': 'd' * 64})
        patcher = mock.patch.object(resume, 'check', return_value=self.current)
        self.checked = patcher.start()
        self.addCleanup(patcher.stop)
        self.provenance = self.checkpoint.parent / 'provenance.json'
        self.record = dict(self.current, mode='cached-post-opt-only',
                           optimized_checkpoint_sha256=resume.sha(self.raw),
                           cache_overlay_sha256=resume.continuation_tools())
        self.write_record()

    def write_record(self):
        self.provenance.write_text(json.dumps(self.record))

    def verify(self, checkpoint=None, digest=None):
        return resume.verify_continuation(self.root, checkpoint or self.checkpoint,
                                          digest or self.digest)

    def make_stage(self, source, stage, suffix):
        out = self.root / ('diagnostic-run/continuation-' + suffix)
        out.mkdir()
        initial = self.verify(source, resume.sha(source))
        (out / 'provenance.json').write_text(json.dumps(initial))
        filename = next(name for name, value in resume.STAGES.items() if value == stage)
        checkpoint = out / filename
        checkpoint.write_bytes(('mock ' + stage).encode())
        resume.seal_stage(self.root, out, stage)
        return checkpoint

    def test_valid_checked_opt_and_recursive_stage_chain(self):
        first = self.verify()
        self.assertEqual(first['start_stage'], 'optimized')
        self.assertFalse(first['qualification'])
        self.assertEqual(first['input_sha256'], self.digest)
        self.checked.assert_called_with(self.root, 'implementation')
        current = self.checkpoint
        for stage in ('placed', 'physical', 'routed'):
            current = self.make_stage(current, stage, stage)
            record = self.verify(current, resume.sha(current))
            self.assertEqual(record['start_stage'], stage)
            self.assertFalse(record['qualification'])

    def test_tampered_checkpoint_or_explicit_digest_rejected(self):
        for digest in ('', '0' * 64, self.digest.upper()):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                resume.verify_continuation(self.root, self.checkpoint, digest)
        self.checkpoint.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'SHA changed'):
            self.verify()

    def test_original_validation_failure_is_not_bypassed(self):
        self.checked.side_effect = ValueError('original frozen validation failed')
        with self.assertRaisesRegex(ValueError, 'original frozen validation failed'):
            self.verify()

    def test_input_provenance_fields_must_match_original(self):
        for key in ('original_manifest_sha256', 'profile_sha256', 'project_sha256', 'ooc_sha256'):
            original = self.record[key]
            with self.subTest(key=key):
                self.record[key] = 'mismatch'
                self.write_record()
                with self.assertRaisesRegex(ValueError, 'provenance mismatch: ' + key):
                    self.verify()
            self.record[key] = original
        self.record['mode'] = 'unchecked-post-opt'
        self.write_record()
        with self.assertRaisesRegex(ValueError, 'Not checked post-opt provenance'):
            self.verify()

    def test_raw_opt_binding_rejects_changed_or_wrong_digest(self):
        self.record['optimized_checkpoint_sha256'] = '0' * 64
        self.write_record()
        with self.assertRaises(ValueError):
            self.verify()
        self.record['optimized_checkpoint_sha256'] = resume.sha(self.raw)
        self.write_record()
        self.raw.write_bytes(b'tampered original raw opt')
        with self.assertRaises(ValueError):
            self.verify()

    def test_proof_tools_and_post_producer_identity_are_bound(self):
        for name in (*resume.POST_PROOFS, *resume.REVIEWED_POST_PRODUCER):
            original = self.record['cache_overlay_sha256'][name]
            with self.subTest(tool=name):
                self.record['cache_overlay_sha256'][name] = '0' * 64
                self.write_record()
                with self.assertRaises(ValueError):
                    self.verify()
            self.record['cache_overlay_sha256'][name] = original
        self.record['cache_overlay_sha256'].update(resume.REVIEWED_POST_PRODUCER)
        self.write_record()
        self.assertEqual(self.verify()['start_stage'], 'optimized')

    def test_stage_seal_rejects_checkpoint_and_tool_mutation(self):
        checkpoint = self.make_stage(self.checkpoint, 'placed', 'tamper')
        seal = Path(str(checkpoint) + '.provenance.json')
        original = json.loads(seal.read_text())
        for key, wrong in (('stage', 'routed'), ('checkpoint_sha256', '0' * 64),
                           ('tool_sha256', {})):
            with self.subTest(field=key):
                seal.write_text(json.dumps(dict(original, **{key: wrong})))
                with self.assertRaises(ValueError):
                    self.verify(checkpoint, resume.sha(checkpoint))
        seal.write_text(json.dumps(original))
        checkpoint.write_bytes(b'tampered placement')
        with self.assertRaises(ValueError):
            self.verify(checkpoint, resume.sha(checkpoint))

    def test_source_provenance_hash_and_seal_exclusivity(self):
        checkpoint = self.make_stage(self.checkpoint, 'placed', 'source')
        with self.assertRaises(FileExistsError):
            resume.seal_stage(self.root, checkpoint.parent, 'placed')
        # Semantically equivalent JSON still must match the exact parent seal.
        self.provenance.write_text(self.provenance.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'source provenance changed'):
            self.verify(checkpoint, resume.sha(checkpoint))

    def test_unreviewed_path_and_excessive_depth_rejected(self):
        outside = self.root / 'placed.dcp'
        outside.write_bytes(b'outside')
        with self.assertRaisesRegex(ValueError, 'outside reviewed'):
            self.verify(outside, resume.sha(outside))
        with self.assertRaisesRegex(ValueError, 'chain too deep'):
            resume.verify_continuation(self.root, self.checkpoint, self.digest, depth=7)


if __name__ == '__main__':
    unittest.main()
