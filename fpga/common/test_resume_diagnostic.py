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
        branch=script[script.index('if {![info exists'):script.index('set ipEvidence {}')]
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

if __name__=='__main__':unittest.main()
