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
        self.assertIn('.cpuClock(clk_soc), .fabricClock(clk_fabric)', text)
        self.assertIn('assign clk_fabric = ui_clk;', board_inputs.selected_shell(text, False))
        self.assertNotIn('.ddrClock(ui_clk)', board_inputs.selected_shell(text, False))
        self.assertIn('.ddrClock(ui_clk), .timebaseClock(ui_clk), .debugClock(ui_clk)', board_inputs.selected_shell(text, True))
        self.assertIn('.JTAG_CHAIN(2), .SCAN_BITS(65)', text)
        self.assertIn('.c0_ddr4_ui_clk(ui_clk)', text)
        self.assertNotIn('axi_clock_converter', text)
        self.assertIn('native_rgmii_trispeed_quarter', text)
        self.assertIn('.RX_DATA_DELAY_PS(1100)', text)
        self.assertNotIn('jtag_tck', text)

    def test_low_profile_requires_fresh_static_three_output_ip(self):
        script = (HERE / 'synthesize.tcl').read_text()
        self.assertIn('create_ip -name clk_wiz', script)
        self.assertIn('CONFIG.USE_DYN_RECONFIG false', script)
        self.assertIn('CONFIG.NUM_OUT_CLKS 3', script)
        self.assertIn('CONFIG.CLKOUT3_REQUESTED_OUT_FREQ [expr {$valence(hz_fabric)/1.0e6}]', script)
        self.assertIn('get_property PERIOD $clocks', script)
        self.assertIn('clock-output-checks.txt', script)
        self.assertIn('get_property IS_GENERATED $clocks', script)
        self.assertIn('generated-clocks.rpt', (HERE / 'freeze.py').read_text())
        self.assertNotIn('read_verilog -sv -define', script)
        self.assertIn('get_property verilog_define [current_fileset]', script)
        for name in ('post_synth.tcl', 'post_opt.tcl'):
            self.assertIn('set debugPin u_soc/debugClock', (HERE / name).read_text())
        audit = (HERE / 'board_audit.tcl').read_text()
        self.assertIn('u_soc/ddrClock u_soc/timebaseClock u_soc/debugClock', audit)
        self.assertIn('u_soc/ddrCrossing', audit)

    def test_dci_bootstrap_is_independent_of_mig(self):
        helper = (HERE / 'native_dci_startup.sv').read_text()
        shell = (HERE / 'soc_top_common_ddr.sv').read_text()
        self.assertIn('DCIRESET dci (.RST(reset_dci), .LOCKED(locked))', helper)
        self.assertIn('.CFGMCLK(cfg_raw)', helper)
        self.assertIn('wire restart = cold_reset | ~eos;', helper)
        self.assertNotIn('input wire ui_', helper)
        self.assertNotIn('calib_complete', helper)
        self.assertIn('wire mig_reset = board_reset | ~dci_ready;', shell)
        self.assertIn('.sys_rst(mig_reset)', shell)
        self.assertIn('common_dci_startup_tb COMMON_DCI_STARTUP_PASS', (HERE / 'simulate.tcl').read_text())
        self.assertIn('dci-run.log', (HERE / 'freeze.py').read_text())
        self.assertIn('dci_short-run.log', (HERE / 'freeze.py').read_text())
        self.assertIn('pulse_age == 3\'d7', helper)
        self.assertNotIn('posedge local_reset)', helper)
        self.assertIn('Timing[[:space:]]+Violation', (HERE / 'simulate.tcl').read_text())

    def test_native_log_rejects_vendor_timing_error_even_with_pass(self):
        script = (HERE / 'simulate.tcl').read_text()
        import re
        pattern = re.search(r'regexp -nocase \{(Timing.*)\} \$log', script)[1]
        tcl = 'set pattern {' + pattern + '}\n'
        for log in ('COMMON_DCI_STARTUP_PASS\nTiming Violation Error : RST pulse',
                    'COMMON_DCI_STARTUP_PASS\nERROR: failure',
                    'COMMON_DCI_STARTUP_PASS\n FATAL: failure'):
            tcl += 'if {![regexp -nocase $pattern {' + log + '}]} {exit 2}\n'
        tcl += 'if {[regexp -nocase $pattern {COMMON_DCI_STARTUP_PASS}]} {exit 3}\nputs OK\n'
        result = subprocess.run(['tclsh'], input=tcl, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'OK')

    def test_performance_profile_is_explicit_i1_and_preserves_all_fixed_rates(self):
        expected = dict(cpu=300000000,fabric=250000000,timebase=250000000,
                        ddr_ui=250000000,uart=50000000,aon=50000000)
        self.assertEqual(producer.gate.reviewed_board_clocks('i1','performance300-static'), expected)
        with self.assertRaises(ValueError): producer.gate.reviewed_board_clocks('a1','performance300-static')
        self.assertEqual(producer.gate.reviewed_board_clocks('i1')['cpu'], 300000000)
        self.assertEqual(producer.gate.reviewed_board_clocks('a1')['cpu'], 100000000)
        self.assertEqual(producer.gate.reviewed_board_clocks('i1','boot50-static')['fabric'], 50000000)

    def test_emission_paths_accept_windows_and_posix_without_mutation(self):
        import hashlib
        for root in ('/tmp/emit', 'C:\\build\\emit'):
            sep = '\\' if root.startswith('C:') else '/'
            artifacts = {root+sep+'CommonMachinePlatform.sv':'top-hash',
                         root+sep+'verification'+sep+'Assert.sv':'assert-hash'}
            original = json.dumps(artifacts).encode()
            expected = {'CommonMachinePlatform.sv':'top-hash','verification/Assert.sv':'assert-hash'}
            self.assertEqual(board_inputs.emitted_artifacts(artifacts), expected)
            self.assertEqual(hashlib.sha256(original).hexdigest(), hashlib.sha256(json.dumps(artifacts).encode()).hexdigest())
            sources = {root+sep+sep.join(('src','main','scala','Top.scala')):'source-hash'}
            self.assertEqual(board_inputs.emitted_sources(sources), {'src/main/scala/Top.scala':'source-hash'})

    def test_emission_duplicate_top_alias_and_escape_rejected(self):
        top = 'C:\\emit\\CommonMachinePlatform.sv'
        for other in ('C:/emit/CommonMachinePlatform.sv', 'c:/EMIT/CommonMachinePlatform.sv',
                      'C:/other/CommonMachinePlatform.sv', 'C:/emit/../outside.sv',
                      'C:/emit-sibling/outside.sv'):
            with self.assertRaises(ValueError): board_inputs.emitted_artifacts({top:'a',other:'b'})
        with self.assertRaises(ValueError): board_inputs.emitted_artifacts({'C:emit/CommonMachinePlatform.sv':'a'})
        with self.assertRaises(ValueError): board_inputs.emitted_artifacts({'/tmp/a/CommonMachinePlatform.sv':'a','/tmp/b/CommonMachinePlatform.sv':'b'})
        with self.assertRaises(ValueError): board_inputs.emitted_sources({'C:/a/src/main/scala/T.scala':'a','D:/b/src/main/scala/T.scala':'a'})

    def test_performance_parent_complete_control_binding(self):
        parent = """  output [4:0] rgmiiTxRise, rgmiiTxFall;
  TriSpeedRgmiiTx encode (
    .clock           (rawTxClock),
    .reset           (_rawTxRelease_resetOut),
    .io_rate_ready   (_encode_io_rate_ready),
    .io_rate_valid   (_txRate_destination_valid),
    .io_rate_bits    (_txRate_destination_bits),
    .io_datapathIdle (~_tx_io_busy & _txFifo_destinationIdle),
    .io_byteStep     (_encode_io_byteStep),
    .io_gmiiData     (_tx_io_gmiiData),
    .io_gmiiEnable   (_tx_io_gmiiEnable),
    .io_rise         (rgmiiTxRise),
    .io_fall         (rgmiiTxFall),
    .io_clockRise    (rgmiiTxClockRise),
    .io_clockFall    (rgmiiTxClockFall),
    .io_idle         (_encode_io_idle)
  );"""
        board_inputs.performance_mac_control_form(parent)
        for bad in (parent.replace('(rawTxClock)', '(otherClock)'),
                    parent.replace('(_rawTxRelease_resetOut)', '(otherReset)'),
                    parent.replace('(rgmiiTxFall)', '(otherOutput)'),
                    parent+'\nassign rgmiiTxRise = 0;', parent+parent):
            with self.assertRaises(ValueError): board_inputs.performance_mac_control_form(bad)

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
                low=copy.deepcopy(m);low['configuration']['clock_profile']='boot50-static'
                low['configuration']['clocks_hz']=producer.gate.reviewed_board_clocks('i1','boot50-static')
                producer.validate(root,low)
                for key in ('cpu','fabric','timebase','ddr_ui','uart','aon'):
                    bad=copy.deepcopy(low);bad['configuration']['clocks_hz'][key]+=1000000
                    with self.assertRaises(ValueError): producer.validate(root,bad)
                performance=copy.deepcopy(m);performance['configuration']['clock_profile']='performance300-static'
                producer.validate(root,performance)
                for key in ('cpu','fabric','timebase','ddr_ui','uart','aon'):
                    bad=copy.deepcopy(performance);bad['configuration']['clocks_hz'][key]+=1000000
                    with self.assertRaises(ValueError): producer.validate(root,bad)
                bad=copy.deepcopy(performance);bad['configuration']['cpu']='a1'
                with self.assertRaises(ValueError): producer.validate(root,bad)
                bad=copy.deepcopy(low);bad['configuration'].pop('clock_profile')
                with self.assertRaises(ValueError): producer.validate(root,bad)
                bad=copy.deepcopy(m);bad['configuration']['features']['mac']=False
                with self.assertRaises(ValueError): producer.validate(root,bad)
                (root/'rom').write_bytes(b'\x01'+bytes(131071))
                with self.assertRaisesRegex(ValueError,'content mismatch'): producer.validate(root,m)

if __name__=='__main__': unittest.main()
