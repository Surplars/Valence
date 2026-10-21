import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import resume_diagnostic as r

HERE=Path(__file__).parent

class ResumeTests(unittest.TestCase):
    def test_ooc_hash_missing_and_modified_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=root/'common_board.runs/test_synth_1/test.dcp'
            expected={'test':(hashlib.sha256(b'checked').hexdigest(),7)}
            with self.assertRaises(ValueError):r.verify_dcps(root,expected)
            p.parent.mkdir(parents=True);p.write_bytes(b'checked')
            self.assertEqual(len(r.verify_dcps(root,expected)),1)
            p.write_bytes(b'changed')
            with self.assertRaises(ValueError):r.verify_dcps(root,expected)

    @unittest.skipUnless(shutil.which('tclsh'),'Tcl unavailable')
    def test_resume_branch_never_generates_ip_and_checks_macro_and_status(self):
        script=(HERE/'synthesize.tcl').read_text()
        branch=script[script.index('if {![info exists valence(resume_ooc)]'):script.index('set ipEvidence {}')]
        macro=script[script.index('set defines '):script.index('foreach source [common_files')]
        status=script[script.index('    set status [get_property STATUS'):script.index('    if {[info exists valence(resume_ooc)] && $valence(resume_ooc)}', script.index('set ipEvidence {}'))]
        for defines,state,ok in [('VALENCE_INDEPENDENT_FIXED_DOMAINS','synth_design Complete!',True),
                                 ('','synth_design Complete!',False),
                                 ('VALENCE_INDEPENDENT_FIXED_DOMAINS','synth_design ERROR',False)]:
            pre='''set valence(resume_ooc) 1
set valence(diagnosticOnly) 1
set valence(clock_profile) performance300-static
set valence(part) part
set valence(out) /original
set run test
proc open_project {p} {if {$p ne "/original/project/common_board.xpr"} {error "wrong project"}}
proc current_project {} {return project}
proc current_fileset {} {return sources_1}
proc get_runs {args} {return {blk_mem_gen_0_synth_1 clk_wiz_common_synth_1 ddr4_0_synth_1}}
proc get_property {key obj} {
 if {$key eq "PART"} {return part}
 if {$key eq "verilog_define"} {return $::defines}
 if {$key eq "STATUS"} {return $::state}
 error "unexpected property"
}
'''
            test=pre+'set defines {'+defines+'}\nset state {'+state+'}\nif {[catch {\n'+branch+macro+status+'\n} result]} {puts stderr $result; exit 1}\n'
            result=subprocess.run(['tclsh'],input=test,text=True,capture_output=True)
            self.assertEqual(result.returncode==0,ok,result.stderr)
        self.assertNotIn('read_verilog -sv -define',script)
        self.assertNotIn('set_property is_compile_unit_mode',script)


    @unittest.skipUnless(shutil.which('tclsh'),'Tcl unavailable')
    def test_checkpoint_survives_injected_first_post_failure(self):
        script=(HERE/'synthesize.tcl').read_text()
        fragment=script[script.index('common_design_step synth_design'):script.index('# Verify actual')]
        with tempfile.TemporaryDirectory() as t:
            commands = """set valence(top) top
set valence(part) part
proc common_design_step {args} {}
proc write_checkpoint {path} {set f [open $path w]; puts $f RAW; close $f}
if {[catch {
if {1} {
"""+fragment+"""
error INJECTED_POST_FAILURE
} reason]} {
 if {![file exists raw-synthesized-unqualified.dcp]} {error "expensive result lost"}
 if {[file exists synthesized.dcp]} {error "unqualified result admitted"}
 puts SAVED_BEFORE_FAILURE
} else {error "fault not injected"}
"""
            run=subprocess.run(['tclsh'],input=commands,text=True,capture_output=True,cwd=t)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertIn('SAVED_BEFORE_FAILURE',run.stdout)
        self.assertLess(script.index('write_checkpoint raw-synthesized-unqualified.dcp'),script.index('get_pins -quiet u_clk_wiz'))
        self.assertLess(script.index('write_checkpoint raw-synthesized-unqualified.dcp'),script.index('source $valence(post_synth_constraints)'))

    @unittest.skipUnless(shutil.which('tclsh'),'Tcl unavailable')
    def test_raw_resume_skips_all_ip_and_top_synthesis(self):
        script=(HERE/'synthesize.tcl').read_text().split('# Verify actual')[0]
        pre="""set valence(root) /frozen
set valence(resume_raw) 1
proc source {args} {}
proc open_checkpoint {p} {if {$p ne "raw-synthesized-unqualified.dcp"} {error "wrong raw"}; puts RAW_OPENED}
proc common_record {args} {}
"""
        # create_project, launch_runs and synth_design are intentionally undefined.
        run=subprocess.run(['tclsh'],input=pre+'if {[catch {\n'+script+'\n} why]} {puts stderr $why; exit 1}\n',text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('RAW_OPENED',run.stdout)

    def test_raw_binding_detects_checkpoint_or_manifest_mutation(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);out=root/'diagnostic-run/synthesis';out.mkdir(parents=True)
            (root/'diagnostic.json').write_text('original manifest')
            raw=out/'raw-synthesized-unqualified.dcp';raw.write_bytes(b'raw')
            first=r.raw_binding(root,'profile')
            raw.write_bytes(b'changed')
            self.assertNotEqual(first,r.raw_binding(root,'profile'))
            raw.write_bytes(b'raw');(root/'diagnostic.json').write_text('changed manifest')
            self.assertNotEqual(first,r.raw_binding(root,'profile'))

    def test_lemma_follows_exact_frozen_validation_and_stages_save_first(self):
        script=(HERE/'resume_diagnostic.tcl').read_text()
        self.assertLess(script.index('set evidence [exec'),script.index('set valence(control_lemma) 1'))
        fresh=(HERE/'diagnostic.tcl').read_text()
        self.assertLess(fresh.index('check --manifest'),fresh.index('set valence(control_lemma) 1'))
        self.assertLess(fresh.index('write_checkpoint optimized-unqualified.dcp'),fresh.index('cached_post_opt.tcl'))
        self.assertIn('placed physical phys_opt_design physical-optimized-unqualified.dcp',fresh)
        self.assertLess(fresh.index('write_checkpoint $file'),fresh.index('diagnostic_stage_gate $stage'))
        self.assertIn('catch {write_checkpoint failed-resume-unqualified-',script)

if __name__=='__main__':unittest.main()
