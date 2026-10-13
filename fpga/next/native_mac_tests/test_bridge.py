import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
HERE=Path(__file__).resolve().parent
SRC=Path(os.environ.get('MAC_BRIDGE_SOURCE', HERE.parents[2])).resolve()
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
old=load('legacy_host_tests',SRC/'fpga/next/test_board_t1.py')
t1=old.t1;exporter=old.exporter
class BridgeTests(old.BoardT1Tests):
    def test_four_selected_modes_preserve_cpu_and_emit(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp); baseline=None
            for reset in (False,True):
                for selected in (False,True):
                    args=['--experimental-trispeed-ethernet']+[t1.FLAG]*reset+[t1.SELECTED_FLAG]*selected
                    p=self.preflight(args,tmp/'absent')
                    shape=(p['configuration'],p['command'])
                    if baseline is None:baseline=shape
                    self.assertEqual(shape,baseline)
                    self.assertEqual(p['native_mac_mode'],t1.selection(reset,selected))
                    out=tmp/f'out-{reset}-{selected}'
                    receipt=self.emit_mock(out,reset,True,selected)
                    result=t1.verify(out)
                    self.assertEqual(result['generics'],t1.selection(reset,selected)['generics'])
                    self.assertFalse(result['synthesis_consumer_executed'])
                    self.assertFalse(result['mapped_topology_checked'])
                    self.assertFalse(receipt['physical_qualification'])
    def test_selected_exact_flag_guards(self):
        bad=[[t1.SELECTED_FLAG],['--experimental-trispeed-ethernet',t1.SELECTED_FLAG,t1.SELECTED_FLAG],
             ['--experimental-trispeed-ethernet','--native-mac-register-selected'],
             *[['--experimental-trispeed-ethernet',t1.SELECTED_FLAG+'='+x] for x in ('0','1','true','false','on')]]
        with tempfile.TemporaryDirectory() as tmp:
            for args in bad:
                with self.subTest(args=args),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                    exporter.main(['--output',str(Path(tmp)/'none'),*args])
                self.assertFalse((Path(tmp)/'none').exists())
    def test_forwarding_and_boolean_contract_rejected(self):
        for args in ((1,False),(False,1),("true",False)):
            with self.assertRaises(ValueError):t1.selection(*args)
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';self.emit_mock(out,True,True,True)
            path=out/'board/soc_top_fpga_next_ddr.sv'
            path.write_text(path.read_text().replace('.REGISTER_SELECTED_HALF(NATIVE_MAC_REGISTER_SELECTED_HALF)', '.REGISTER_SELECTED_HALF(0)'))
            with self.assertRaisesRegex(RuntimeError,'forwarding'):t1.stage(SRC,out,True,True)

    def test_selected_binding_mutations(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'; receipt=self.emit_mock(out,True,True,True)
            for file in ['board/native_mac_roles.tcl','board/native_mac_contract.py','board/native_rgmii_trispeed_quarter.sv','synthesis-files.f','board-synthesis-files.f','rtl/FpgaNextSocTop.sv']:
                path=out/file; original=path.read_bytes();path.write_bytes(original+b'\n')
                with self.subTest(file=file),self.assertRaises(RuntimeError):t1.verify(out)
                path.write_bytes(original)
            bad=copy.deepcopy(receipt);bad['native_mac_mode']['native_mac_register_selected_half']=False
            (out/'receipt.json').write_text(json.dumps(bad))
            with self.assertRaises(RuntimeError):t1.verify(out)
            (out/'receipt.json').write_text(json.dumps(receipt))
            manifest=out/'board/native-mac-mode.json';original=manifest.read_text(); changed=json.loads(original)
            changed['source_sha256']['fpga/next/export.py']='0'*64
            manifest.write_text(json.dumps(changed));receipt['native_mac_mode']['sha256']=t1.sha(manifest)
            (out/'receipt.json').write_text(json.dumps(receipt))
            with self.assertRaisesRegex(RuntimeError,'source binding'):t1.verify(out)
    def test_actual_same_call_consumer_capture_is_mock_only(self):
        for reset in (False,True):
            for selected in (False,True):
                with tempfile.TemporaryDirectory() as tmp:
                    out=Path(tmp)/'out';self.emit_mock(out,reset,True,selected)
                    script=f'''set calls {{}}
proc synth_design {{args}} {{global calls; lappend calls $args}}
proc read_verilog {{args}} {{return MOCK_READ_ONLY}}
proc current_design {{args}} {{return live_mock_design}}
proc get_property {{key object}} {{if {{$key eq "PART"}} {{return MOCK}};return soc_top_fpga_next_ddr}}
source {{{out/'board/native-mac-mode.tcl'}}}
valence_native_mac_configure_python native [list python3]
if {{[llength $calls]!=0}} {{error {{implicit synthesis}}}}
valence_native_mac_synth_design -part test-part
set actual [lindex $calls 0]
if {{[lindex $actual 1] ne "{t1.TOP}" || [lindex $actual 3] ne "{t1.PARAMETER}={int(reset)} {t1.SELECTED_PARAMETER}={int(selected)}"}} {{error {{wrong actual command}}}}
'''
                    for opt in ('-t','-to','-top','-top=wrong','-g','-ge','-gen','-gene','-generic','-generic=X=1'):
                        script+=f'if {{![catch {{valence_native_mac_synth_design {opt} wrong}}]}} {{error {{override allowed}}}}\n'
                    script+='if {[llength $calls]!=1} {error {override reached synthesis}}\n'
                    script+='if {![catch {valence_native_mac_checkpoint postopt never.dcp}]} {error {postopt without optimization}}\n'
                    script+=f'source {{{out/"board/native-mac-mode.tcl"}}}\nif {{!$::valence_native_mac_mode::consumed}} {{error {{resourcing lost actual consumer state}}}}\n'
                    script+='proc synth_design {args} {error {synthetic synthesis failure}}\ncatch {valence_native_mac_synth_design -part test-part}\nif {$::valence_native_mac_mode::consumed} {error {failed synthesis kept success state}}\n'
                    script+='puts {HOST_COMMAND_CAPTURE_PASS actual_synthesis_executed=false}\n' 
                    proc=subprocess.run(['tclsh'],input='if {[catch {\n'+script+'\n} err]} {puts stderr $err;exit 1}\n',capture_output=True,text=True)
                    self.assertEqual(proc.returncode,0,proc.stderr)
                    self.assertIn('actual_synthesis_executed=false',proc.stdout)
    def test_source_control_lemma_only_matches_complete_fresh_bytes(self):
        fixture=HERE/'fixtures'
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);(out/'rtl').mkdir();(out/'board').mkdir()
            for name in ('TriSpeedRgmiiTx.sv','TriSpeedManagedGmac.sv'):shutil.copy2(fixture/name,out/'rtl'/name)
            shutil.copy2(SRC/'fpga/zu15eg/native_rgmii_trispeed_quarter.sv',out/'board')
            proof=t1.source_control_lemma(out)
            self.assertTrue(proof['proved']);self.assertEqual(proof['reset_phase_induction_vectors'],16)
            self.assertFalse(proof['mapped_chain_checked'])
            path=out/'rtl/TriSpeedRgmiiTx.sv';path.write_text(path.read_text().replace('io_fall_REG <= {enable,','io_fall_REG <= {~enable,'))
            self.assertFalse(t1.source_control_lemma(out)['proved'])
    def test_receipt_requires_actual_command_and_fresh_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';self.emit_mock(out,True,True,True)
            dcp=Path(tmp)/'mock.dcp';dcp.write_text('HOST FIXTURE ONLY')
            fields={'schema':'valence-native-mac-consumer-v2','actual_synthesis_executed':'1','stage':'synth',
                    'top':t1.TOP,'t1':'1','selected_half':'1','tool':'MOCK','part':'MOCK',
                    'export_session_identity':t1.session_identity(out),'session_generation':'1',
                    'invocation':f'-top {t1.TOP} -generic {{{t1.PARAMETER}=1 {t1.SELECTED_PARAMETER}=1}} -part MOCK',
                    'audit':'PASS_MAC_ROLE_SEMANTICS t1=1 selected_half=1 fixture_only=1'}
            def write(data):Path(str(dcp)+'.mac.tsv').write_text(''.join(k+'\t'+v.encode().hex()+'\n' for k,v in data.items()))
            write(fields);t1.consumer_receipt(out,dcp,seal=True);t1.consumer_receipt(out,dcp)
            for key,value in [('selected_half','0'),('audit',''),('tool',''),('invocation',f'-top {t1.TOP} -generic {t1.PARAMETER}=1')]:
                bad=dict(fields);bad[key]=value;write(bad)
                with self.subTest(key=key),self.assertRaises(RuntimeError):t1.consumer_receipt(out,dcp)
            write(fields);dcp.write_text('changed')
            with self.assertRaises(RuntimeError):t1.consumer_receipt(out,dcp)
if __name__=='__main__':unittest.main()
