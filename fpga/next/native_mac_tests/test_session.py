import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_bridge as bridge
SRC=bridge.SRC; t1=bridge.t1

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.host=bridge.BridgeTests();self.host.setUp();self.addCleanup(self.host.doCleanups)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.a=self.base/'a';self.b=self.base/'b'
        self.host.emit_mock(self.a,True,True,True)
        self.host.emit_mock(self.b,True,True,True)
    def run_tcl(self,code):
        setup='''set design A
proc synth_design {args} {set ::design A}
proc opt_design {args} {}
proc read_verilog {args} {}
proc open_checkpoint {args} {set ::design OTHER}
proc close_design {args} {set ::design CLOSED}
proc read_checkpoint {args} {set ::design OTHER}
proc link_design {args} {set ::design OTHER}
proc place_design {args} {}
proc route_design {args} {}
proc phys_opt_design {args} {}
proc current_design {args} {if {[llength $args]} {set ::design [lindex $args 0]};return $::design}
proc get_property {key object} {if {$key eq "PART"} {return MOCK_PART};return $object}
'''
        setup+=f'source {{{self.a/"board/native-mac-mode.tcl"}}}\nvalence_native_mac_configure_python native [list python3]\n'
        p=subprocess.run(['tclsh'],input='if {[catch {\n'+setup+code+'\n} why options]} {puts stderr $why;puts stderr [dict get $options -errorinfo];exit 1}\n',capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        return p.stdout
    def test_same_generic_different_export_cannot_reuse_session(self):
        # Both are valid exports with identical modes; B has a different RTL
        # artifact and internally consistent manifest/receipt bindings.
        rtl=self.b/'rtl/FpgaNextSocTop.sv';rtl.write_text(rtl.read_text()+'// distinct B\n')
        receipt=json.loads((self.b/'receipt.json').read_text());receipt['rtl_sha256']['rtl/FpgaNextSocTop.sv']=t1.sha(rtl)
        (self.b/'receipt.json').write_text(json.dumps(receipt))
        t1.verify(self.b)
        self.run_tcl(f'''valence_native_mac_synth_design -part MOCK_PART
valence_native_mac_opt_design
source {{{self.a/'board/native-mac-mode.tcl'}}}
valence_mac_session::assert postopt
source {{{self.b/'board/native-mac-mode.tcl'}}}
if {{![catch {{valence_mac_session::assert postopt}}] || $::valence_native_mac_mode::consumed || $::valence_native_mac_mode::optimized}} {{error {{export swap retained A session}}}}
if {{![catch {{valence_native_mac_checkpoint postopt {{{self.base/'never.dcp'}}}}}]}} {{error {{stale checkpoint captured}}}}
''')
        self.assertFalse((self.base/'never.dcp').exists())
    def test_design_lifecycle_and_failed_operations_invalidate(self):
        for command in ('open_checkpoint other.dcp','close_design','read_checkpoint other.dcp','read_verilog other.sv','link_design -top OTHER','current_design OTHER','place_design','route_design','phys_opt_design'):
            with self.subTest(command=command):
                self.run_tcl('valence_native_mac_synth_design -part MOCK_PART\nvalence_native_mac_opt_design\n'+command+'\nif {![catch {valence_mac_session::assert postopt}]} {error {stale lifecycle session}}')
        self.run_tcl('''valence_native_mac_synth_design -part MOCK_PART
valence_native_mac_opt_design
if {![catch {valence_native_mac_checkpoint synth never.dcp}]} {error {optimized design labeled synth}}
proc opt_design {args} {error {intentional opt failure}}
catch {valence_native_mac_opt_design}
if {$::valence_native_mac_mode::optimized || $::valence_native_mac_mode::consumed || ![catch {valence_mac_session::assert}]} {error {failed opt retained session}}
valence_native_mac_synth_design -part MOCK_PART
proc synth_design {args} {error {intentional synth failure}}
catch {valence_native_mac_synth_design -part MOCK_PART}
if {$::valence_native_mac_mode::consumed || ![catch {valence_mac_session::assert}]} {error {failed synth retained session}}
''')
    def test_same_directory_changed_identity_rejected(self):
        self.run_tcl(f'''valence_native_mac_synth_design -part MOCK_PART
set f [open {{{self.a/'receipt.json'}}} a];puts $f {{ }};close $f
source {{{self.a/'board/native-mac-mode.tcl'}}}
if {{![catch {{valence_mac_session::assert synth}}]}} {{error {{changed same-directory export accepted}}}}
''')
    def test_explicit_wsl_paths_stderr_and_nonzero_exit(self):
        fake=self.base/'fake_wsl.py';log=self.base/'arguments.jsonl'
        fake.write_text('''import json,os,sys
with open(os.environ['WSL_TEST_ARGS'],'a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')
args=sys.argv[1:]
assert args[:3]==['-d','Ubuntu-24.04','--']
args=args[3:]
print('synthetic WSL warning',file=sys.stderr)
if os.environ.get('WSL_TEST_FAIL')=='1':sys.exit(7)
if args[0]=='wslpath':
 assert args[1]=='-u'
 print('relative' if os.environ.get('WSL_TEST_BADPATH')=='1' else '/mapped/'+args[2].encode().hex())
else:
 assert args[0]=='/usr/bin/python3' and args[1].startswith('/mapped/')
 assert args[2]=='--session-identity' and args[3].startswith('/mapped/')
 print('a'*64)
''')
        logs=self.base/'windows-stderr'
        out=self.run_tcl(f'''set env(WSL_TEST_ARGS) {{{log}}}
valence_native_mac_configure_python wsl Ubuntu-24.04 [list python3 {{{fake}}}] {{{logs}}}
if {{[valence_native_mac_verify_export] ne [string repeat a 64]}} {{error {{warning-only WSL rejected}}}}
set env(WSL_TEST_FAIL) 1
if {{![catch {{valence_native_mac_verify_export}}]}} {{error {{nonzero WSL accepted}}}}
unset env(WSL_TEST_FAIL)
set env(WSL_TEST_BADPATH) 1
if {{![catch {{valence_native_mac_verify_export}}]}} {{error {{relative mapping accepted}}}}
set tcl_platform(platform) windows
if {{![catch {{valence_native_mac_configure_python native [list python3]}}]}} {{error {{unreviewed Windows Python accepted}}}}
puts WSL_HOST_TEST_ONLY
''')
        self.assertIn('WSL_HOST_TEST_ONLY',out)
        commands=[json.loads(x) for x in log.read_text().splitlines()]
        py=[x for x in commands if x[3]=='/usr/bin/python3']
        self.assertEqual(len(py),1)
        self.assertEqual(bytes.fromhex(py[0][4].removeprefix('/mapped/')).decode(),str(self.a/'board/native_mac_contract.py'))
        self.assertEqual(bytes.fromhex(py[0][6].removeprefix('/mapped/')).decode(),str(self.a))
        files=list(logs.glob('*.log'));self.assertGreaterEqual(len(files),5)
        self.assertTrue(all('synthetic WSL warning' in p.read_text() for p in files))
if __name__=='__main__':unittest.main()
