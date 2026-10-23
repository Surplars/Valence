"""Control-flow mocks only, not native Vivado validation."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import native_diagnostic as n


class NativeDiagnosticTests(unittest.TestCase):
    def fixture(self, root):
        for name in ('source.scala', 'top.sv', 'pins.xdc', 'post.tcl', 'ip/core.xci', 'ip/core.dcp'):
            path = root/name
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_text(name)
        spec = dict(origin='mock only', root=str(root), part='part', top='top',
                    vivado_version='2025.2', threads=8, sources=['source.scala', 'post.tcl'], rtl=['top.sv'],
                    pre_synth_xdc=['pins.xdc'], clock_requirements=[dict(pin='cpu/clock', period_ns=3.333333)],
                    post_synth=[dict(kind='tcl', path='post.tcl')], post_opt=[], preplace=[], pre_route=[],
                    ips=[dict(xci='ip/core.xci', dcp='ip/core.dcp', product_dirs=['ip'])])
        (root/'spec.json').write_text(json.dumps(spec))
        n.prepare(root/'spec.json', root/'manifest.json')
        return n.verify(root/'manifest.json')

    def test_input_mutation_and_new_ip_product_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); self.fixture(root)
            for name in ('source.scala', 'top.sv', 'post.tcl', 'ip/core.dcp'):
                p = root/name; original = p.read_bytes(); p.write_bytes(b'changed')
                with self.assertRaises(ValueError): n.verify(root/'manifest.json')
                p.write_bytes(original)
            (root/'ip/new.xdc').write_text('unrecorded')
            with self.assertRaises(ValueError): n.verify(root/'manifest.json')

    def test_resume_requires_hash_stage_and_fresh_output(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); self.fixture(root)
            checkpoint = root/'input.dcp'; checkpoint.write_bytes(b'raw')
            with self.assertRaises(ValueError): n.run(root/'manifest.json', root/'out', 'unused', checkpoint, 'raw', 'wrong')
            self.assertFalse((root/'out').exists())
            expected = n.sha(checkpoint)
            checkpoint.write_bytes(b'corrupted')
            with self.assertRaises(ValueError): n.run(root/'manifest.json', root/'out', 'unused', checkpoint, 'raw', expected)
            self.assertEqual(checkpoint.read_bytes(), b'corrupted')
            with self.assertRaises(ValueError): n.run(root/'manifest.json', root/'out', 'unused', checkpoint, 'fresh', n.sha(checkpoint))
            (root/'out').mkdir()
            with self.assertRaises(FileExistsError): n.run(root/'manifest.json', root/'out', 'unused')

    def test_zero_exit_is_not_completion_and_inputs_rechecked(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); self.fixture(root)
            with patch.object(n.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
                with self.assertRaisesRegex(ValueError, 'completion/checkpoint'):
                    n.run(root/'manifest.json', root/'out', 'mock')
            self.assertTrue((root/'out/failure.json').is_file())
            self.assertFalse((root/'out/outputs.json').exists())
            def fake(*args, **kwargs):
                (root/'top.sv').write_text('changed')
                return subprocess.CompletedProcess([], 0)
            with patch.object(n.subprocess, 'run', side_effect=fake):
                with self.assertRaisesRegex(ValueError, 'changed'):
                    n.run(root/'manifest.json', root/'out2', 'mock')

    def test_required_routed_reports_present_nonempty_for_fresh_and_resume(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); self.fixture(root)
            checkpoint = root/'input.dcp'; checkpoint.write_bytes(b'original checkpoint')
            expected = n.sha(checkpoint)
            # Marker plus DCP is insufficient; test all missing/empty required
            # reports, then a complete mocked artifact set, for both entry modes.
            cases = [('none', None)] + [(kind, name) for kind in ('missing', 'empty')
                                        for name in n.ROUTED_REPORTS] + [('complete', None)]
            for stage in ('fresh', 'routed'):
                for index, (kind, target) in enumerate(cases):
                    output = root/(stage + str(index))
                    def fake(*args, **kwargs):
                        (output/'native-complete.txt').write_text(n.STATUS)
                        (output/'routed-unqualified.dcp').write_bytes(b'MOCK DCP')
                        for name in n.ROUTED_REPORTS:
                            if kind == 'none' or (kind == 'missing' and name == target):
                                continue
                            (output/name).write_text('' if kind == 'empty' and name == target else 'MOCK REPORT')
                        return subprocess.CompletedProcess([], 0)
                    resume = {} if stage == 'fresh' else dict(checkpoint=checkpoint, stage=stage, expected=expected)
                    with patch.object(n.subprocess, 'run', side_effect=fake):
                        if kind == 'complete':
                            n.run(root/'manifest.json', output, 'mock', **resume)
                            result = json.loads((output/'outputs.json').read_text())
                            self.assertFalse(result['qualification'])
                            self.assertTrue(set(n.ROUTED_REPORTS) <= set(result['files_sha256']))
                        else:
                            with self.assertRaisesRegex(ValueError, 'Required routed report missing or empty'):
                                n.run(root/'manifest.json', output, 'mock', **resume)
                            self.assertFalse((output/'outputs.json').exists())
                            self.assertTrue((output/'failure.json').exists())
                        self.assertTrue((output/'routed-unqualified.dcp').exists())
                        self.assertEqual(n.sha(checkpoint), expected)

    @unittest.skipUnless(shutil.which('tclsh'), 'Tcl unavailable')
    def test_tcl_word_literal(self):
        value = 'C:\\space [bad] $injection {quoted} "path"'
        result = subprocess.run(['tclsh'], input='puts '+n.word(value), text=True, capture_output=True)
        self.assertEqual(result.stdout.rstrip('\n'), value)

    @unittest.skipUnless(shutil.which('tclsh'), 'Tcl unavailable')
    def test_mock_stage_order_resume_and_failure_checkpoint_preservation(self):
        script = (n.HERE/'native_diagnostic.tcl').read_text()
        definitions = script[:script.index('if {[catch {native_main}')]
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); record = self.fixture(root)
            for stage, physical in [(stage, physical) for stage in n.STAGES for physical in (False, True)]:
                record['spec']['phys_opt'] = physical
                for failure in ('', 'post_synth', 'post_opt', 'preplace', 'pre_route'):
                    output = root/(stage+'-'+str(physical)+'-'+(failure or 'ok')); output.mkdir()
                    cfg = output/'config.tcl'
                    cfg.write_text(n.config(record['spec'], root/'resume.dcp' if stage != 'fresh' else None, stage))
                    mock = '''
proc version {args} {return 2025.2}
proc set_param {args} {}
proc get_param {args} {return 8}
proc current_design {} {return design}
proc current_project {} {return project}
proc current_fileset {} {return fileset}
proc get_property {key object} {
 switch $key {PART {return part} TOP {return top} NAME {return $object} PERIOD {return 3.333333} default {error "unexpected property $key"}}
}
proc get_files {args} {return [list $::ip_dcp]}
proc get_pins {args} {return pin}
proc get_clocks {args} {return clock}
proc write_checkpoint {path} {lappend ::events $path; set f [open $path w]; puts $f MOCK; close $f}
foreach command {create_project set_property read_ip read_verilog read_xdc open_checkpoint synth_design opt_design place_design phys_opt_design route_design} {
 proc $command {args} [format {lappend ::events %s} $command]
}
foreach command {report_timing_summary check_timing report_clocks report_route_status report_drc report_cdc report_bus_skew report_utilization} {proc $command {args} {}}
proc native_constraints {phase} {lappend ::events $phase; if {$phase eq $::failure} {error INJECTED}}
'''
                    mock += 'set ip_dcp '+n.word(record['spec']['ips'][0]['dcp'])+'\n'
                    mock += 'set failure '+n.word(failure)+'\nset argv [list '+n.word(cfg)+']\nset events {}\n'
                    mock += 'set code [catch {native_main} why]\nputs [list $code $events $why]\n'
                    result = subprocess.run(['tclsh'], input=definitions+mock, text=True, capture_output=True, cwd=output)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    events = result.stdout.splitlines()[-1]
                    if stage != 'fresh': self.assertNotIn('synth_design', events)
                    if stage in ('optimized-raw', 'optimized', 'placed', 'physical', 'routed'): self.assertNotIn(' opt_design ', ' '+events+' ')
                    if stage in ('placed', 'physical', 'routed'): self.assertNotIn('place_design', events)
                    if stage == 'routed': self.assertNotIn('route_design', events)
                    if stage in ('physical', 'routed') or not physical: self.assertNotIn('phys_opt_design', events)
                    if not failure and physical and stage not in ('physical', 'routed'):
                        self.assertTrue((output/'physical-unqualified.dcp').exists())
                    if stage == 'fresh' and failure == 'post_synth':
                        self.assertTrue((output/'raw-unqualified.dcp').exists())
                        self.assertFalse((output/'synthesized-unqualified.dcp').exists())
                    if stage == 'fresh' and failure == 'post_opt':
                        self.assertTrue((output/'optimized-raw-unqualified.dcp').exists())
                    if stage == 'fresh' and failure == 'pre_route':
                        self.assertTrue((output/'placed-unqualified.dcp').exists())
                        self.assertFalse((output/'routed-unqualified.dcp').exists())
                    if not failure:
                        self.assertTrue((output/'native-complete.txt').exists(), events)


if __name__ == '__main__': unittest.main()
