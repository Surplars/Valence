import hashlib
import json
import time
from unittest import mock
from pathlib import Path
import tempfile
import unittest
import resume_diagnostic as resume

class CachedPostOptResumeTests(unittest.TestCase):
    def test_explicit_checkpoint_digest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            p=root/'diagnostic-run/implementation/optimized-unqualified.dcp'
            p.parent.mkdir(parents=True);p.write_bytes(b'checkpoint')
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            self.assertEqual(resume.verify_checkpoint(root,digest),p)
            for wrong in ('', '0'*64, digest.upper()):
                with self.assertRaises(ValueError):resume.verify_checkpoint(root,wrong)
            p.write_bytes(b'changed')
            with self.assertRaises(ValueError):resume.verify_checkpoint(root,digest)
    def test_all_cache_tools_bound_and_no_mutation(self):
        for name in ('exact_object_cache.tcl','cached_post_opt.tcl','test_exact_object_cache.tcl'):
            self.assertIn(name,resume.CACHE_TOOLS)
        source=Path(__file__).with_name('resume_diagnostic.tcl').read_text()
        for command in ('synth_design','opt_design','place_design','route_design','launch_runs'):
            self.assertNotIn('common_design_step '+command,source)
            self.assertNotIn('\n        '+command+' ',source)
        self.assertLess(source.index('resume_diagnostic.py'),source.index('open_checkpoint'))
        self.assertLess(source.index('open_checkpoint'),source.index('source [file join $recovery_tools cached_post_opt.tcl]'))

    def test_default_entry_paths_enable_cache(self):
        root=Path(__file__).parent
        self.assertIn('common_exact_cache::enable',(root/'synthesize.tcl').read_text())
        for name in ('implement.tcl','diagnostic.tcl'):
            text=(root/name).read_text()
            self.assertIn('cached_post_opt.tcl',text)
            self.assertNotIn('source $valence(post_opt_constraints)',text)
        for name in ('post_synth.tcl','post_opt.tcl','common_cdc.tcl','board_audit.tcl'):
            self.assertIn(name,resume.CACHE_TOOLS)

    def test_collect_session_and_fixed_targets_are_bound(self):
        for names in (resume.CACHE_TOOLS,resume.POST_PROOFS):
            self.assertIn('common_collect_session.tcl',names)
            self.assertIn('dynamic/performance_targets.tcl',names)
        text=Path(__file__).with_name('post_opt.tcl').read_text()
        self.assertIn('[file dirname [file normalize [info script]]] dynamic performance_targets.tcl',text)

    def test_post_opt_complete_seal_and_budget_rejection(self):
        for elapsed, allowed in ((2500,True),(600001,False)):
            with self.subTest(elapsed=elapsed), tempfile.TemporaryDirectory() as d:
                root=Path(d); out=root/'diagnostic-run/cached-post-opt-test'; out.mkdir(parents=True)
                initial=dict(mode='cached-post-opt-only',optimized_checkpoint_sha256='a'*64,cache_overlay_sha256={'helper':'b'*64})
                (out/'provenance.json').write_text(json.dumps(initial))
                start=1000000
                native=dict(status='POST_OPT_RETURNED',started_unix_ms=start,completed_unix_ms=start+1000,deadline_unix_ms=start+600000,budget_ms=600000)
                (out/'post-opt-native.json').write_text(json.dumps(native))
                (out/'optimized-candidate-unqualified.dcp').write_bytes(b'candidate')
                with mock.patch.object(resume,'prepare_post_opt',return_value=initial), mock.patch.object(resume.time,'time_ns',return_value=(start+elapsed)*1000000):
                    if not allowed:
                        with self.assertRaisesRegex(ValueError,'PERF_FAIL_INCOMPLETE'): resume.seal_post_opt(root,out)
                        self.assertFalse((out/'optimized-checked-unqualified.dcp').exists())
                        self.assertFalse((out/'post-opt-complete.json').exists())
                        continue
                    record=resume.seal_post_opt(root,out)
                checked=out/'optimized-checked-unqualified.dcp'
                self.assertEqual(record['elapsed_ms'],elapsed)
                resume.verify_post_opt_seal(root,checked,resume.sha(checked))
                seal=out/'post-opt-complete.json'
                for key,value in (('elapsed_ms',600001),('checkpoint_sha256','0'*64),('tool_sha256',{}),('status','INCOMPLETE')):
                    seal.write_text(json.dumps(dict(record,**{key:value})))
                    with self.assertRaises(ValueError): resume.verify_post_opt_seal(root,checked,resume.sha(checked))
                seal.unlink()
                with self.assertRaises(FileNotFoundError): resume.verify_post_opt_seal(root,checked,resume.sha(checked))

    def test_native_post_opt_dispatch_only_promotes_complete_session(self):
        import subprocess
        code=Path(__file__).with_name('resume_diagnostic.tcl').read_text()
        for failure in ('none','session','deadline','top'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as d:
                root=Path(d); (root/'diagnostic-run/synthesis').mkdir(parents=True)
                script=r'''
set failure FAILURE
set valence(root) {ROOT}
set argv [list [file join $valence(root) diagnostic-run config.tcl] post-opt observed-sha]
set valence(diagnosticOnly) 1
set valence(clock_profile) boot50-dynamic
set valence(threads) 8
set valence(profile_sha256) fixture
set valence(python) python
set ::env(VALENCE_POST_OPT_DEADLINE_MS) [expr {[clock milliseconds]+600000}]
proc source {path} {
 if {[file tail $path] in {config.tcl producer_common.tcl}} {return}
 if {[file tail $path] ne {cached_post_opt.tcl}} {error "Unexpected source $path"}
 namespace eval ::common_collect_session {
  variable active 0; variable last [dict create outcome COMPLETE incomplete_phases {}]
  foreach name {properties kinds ambiguous queries guarded} {variable $name {}}
 }
 if {$::failure eq {session}} {set ::common_collect_session::active 1}
 if {$::failure eq {deadline}} {set ::post_opt_deadline [expr {[clock milliseconds]-1}]}
 puts NEW_POST_OPT_RETURNED
}
proc set_param args {}
proc get_param args {return 8}
proc version args {return 2025.2}
proc open_checkpoint args {puts OPEN_OPTIMIZED_ONLY}
proc current_design args {return checkpoint_alias_not_top}
proc get_property {key object} {
 if {$key eq {PART}} {return xczu15eg-ffvb1156-2-i}
 if {$key eq {TOP}} {return [expr {$::failure eq {top} ? {wrong_top} : {soc_top_common_ddr}}]}
 error "Unexpected property $key"
}
proc exec args {if {[lsearch -exact $args seal-post-opt]>=0} {puts SEALED}; return {}}
proc write_checkpoint {path} {puts "WRITE $path"}
'''.replace('ROOT',str(root)).replace('FAILURE',failure)
                result=subprocess.run(['tclsh'],input=script+'\n'+code,text=True,capture_output=True,timeout=10)
                if failure=='none':
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertIn('WRITE optimized-candidate-unqualified.dcp',result.stdout)
                    self.assertIn('SEALED',result.stdout)
                else:
                    self.assertEqual(result.returncode,1,result.stderr)
                    self.assertNotIn('SEALED',result.stdout)
                    self.assertNotIn('WRITE optimized-candidate-unqualified.dcp',result.stdout)
                self.assertNotIn('WRITE optimized-checked-unqualified.dcp',result.stdout)
