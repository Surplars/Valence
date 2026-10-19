"""Short source/contract tests. Synthetic fixtures are not FPGA evidence."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import board_inputs
import producer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


class BoardInputs(unittest.TestCase):
    def test_actual_shell_connects_shared_clock_and_debug_contract(self):
        text = (HERE / 'soc_top_common_ddr.sv').read_text()
        self.assertIn('.cpuClock(clk_soc), .fabricClock(ui_clk)', text)
        self.assertIn('.JTAG_CHAIN(2), .SCAN_BITS(65)', text)
        self.assertIn('.c0_ddr4_ui_clk(ui_clk)', text)
        self.assertNotIn('axi_clock_converter', text)
        self.assertIn('native_rgmii_trispeed_quarter', text)
        self.assertIn('.RX_DATA_DELAY_PS(1100)', text)
        self.assertNotIn('jtag_tck', text)

    def test_bit_is_blocked_before_scenario_code(self):
        script = (HERE / 'signoff.tcl').read_text()
        self.assertLess(script.index('rename write_bitstream'), script.index('source $valence(media_scenarios)'))
        self.assertLess(script.index('manifest.py] signoff'), script.index('valence_blocked_write_bitstream [file join'))

    def test_port_drift_and_missing_input_rejected(self):
        rtl = 'module CommonMachinePlatform(input cpuClock, fabricClock, output io_out); endmodule'
        shell = 'CommonMachinePlatform u_soc ( .cpuClock(a), .fabricClock(b)\n    );'
        self.assertEqual(board_inputs.port_check(rtl, shell)['connections'], 2)
        for bad in (shell.replace('.fabricClock(b)', '.oldClock(b)'), shell.replace('.fabricClock(b)', '.cpuClock(b)')):
            with self.assertRaises(ValueError): board_inputs.port_check(rtl, bad)
        with self.assertRaises(ValueError):
            board_inputs.port_check(rtl.replace('output io_out', 'input io_new'), shell)

    def test_public_media_adapter_loads_without_bypassing_semantic_proof(self):
        script = f'set valence(root) {{{ROOT}}}\nsource {{{HERE / "media_constraints.tcl"}}}\n'
        script += 'if {[string first {u_soc/board/nativeBank/gmac} [info body ::valence_mac_roles::clocks]]>=0} {exit 2}\n'
        script += 'if {[string first {u_soc/peripherals/gmac} [info body ::valence_mac_roles::clocks]]<0} {exit 3}\nputs OK\n'
        result = subprocess.run(['tclsh'], input=script, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr); self.assertEqual(result.stdout.strip(), 'OK')

    def test_producer_thread_limit_truthful(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = 'array set valence {' + ' '.join(k+' x' for k in ('root out phase threads profile_sha256 rtl_filelist simulation_filelist mig_xci cpu post_synth_constraints post_opt_constraints media_scenarios simulation_suite rom_coe constraints').split()) + '}\n'
            script += f'set valence(out) {{{tmp}}}\nset valence(threads) 8\nset ::env(VALENCE_WINDOWS_PYTHON) python\n'
            script += 'proc get_param {x} {return 8}\nproc version {x} {return SYNTHETIC}\nproc synth_design {args} {}\nproc opt_design {args} {}\n'
            script += f'source {{{HERE / "producer_common.tcl"}}}\ncommon_design_step synth_design\ncommon_design_step opt_design\ncommon_log tools.json "\\{{[join $::common_records ,]\\}}"\n'
            result = subprocess.run(['tclsh'], input=script, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            records = json.loads((Path(tmp)/'tools.json').read_text())
            self.assertEqual(records['synth_design']['requested_threads'], 8)
            self.assertEqual(records['synth_design']['effective_thread_limit'], 4)
            self.assertEqual(records['synth_design']['status'], 'unsupported')
            self.assertIsNone(records['opt_design']['effective_thread_limit'])

    def test_coe_binary_and_profile_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); inputs={p:'fake' for p in board_inputs.PUBLIC_INPUTS}
            roles={k:k for k in ('rom', 'rom_coe', 'simulation_filelist', 'rtl_filelist', 'post_synth_constraints', 'post_opt_constraints', 'media_scenarios')}
            roles['ip']=['mig.xci']; inputs.update({p:'fake' for p in roles if p!='ip'}); inputs['mig.xci']='fake'
            (root/'rom').write_bytes(bytes(131072))
            (root/'rom_coe').write_text('memory_initialization_radix=16;\nmemory_initialization_vector=\n'+',\n'.join(['00000000']*32768)+';\n')
            for role, paths in [('rtl_filelist',board_inputs.BOARD_RTL),('simulation_filelist',board_inputs.SIM_RTL)]:
                (root/role).write_text('\n'.join(paths)); inputs.update({p:'fake' for p in paths})
            m=dict(inputs=inputs,roles=roles,producer=dict(schema='common-board-producer-v1',simulation_suite='common-physical-boundaries-v1',media_rates_mbps=[10,100,1000]),
                   configuration=dict(top='soc_top_common_ddr',cpu='i1',features=dict(mac=True,network_dma=True),
                                      clocks_hz=dict(cpu=300000000,fabric=250000000,timebase=250000000,ddr_ui=250000000,uart=50000000,aon=50000000)))
            with patch.object(board_inputs,'emission',return_value={}):
                producer.validate(root,m)
                for key in ('cpu','fabric','timebase'):
                    bad=copy.deepcopy(m);bad['configuration']['clocks_hz'][key]=50000000
                    with self.assertRaises(ValueError): producer.validate(root,bad)
                bad=copy.deepcopy(m);bad['configuration']['features']['mac']=False
                with self.assertRaises(ValueError): producer.validate(root,bad)
                (root/'rom').write_bytes(b'\x01'+bytes(131071))
                with self.assertRaisesRegex(ValueError,'content mismatch'): producer.validate(root,m)

if __name__=='__main__': unittest.main()
