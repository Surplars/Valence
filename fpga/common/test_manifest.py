"""Synthetic contract fixtures only: no FPGA or Windows qualification evidence."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import manifest as gate

HERE = Path(__file__).resolve().parent


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'manifest.json'
        config = dict(cpu='i1', top='SyntheticTop', part='xczu15eg-ffvb1156-2-i', abi=1,
                      interrupt_abi='aia', rom_base=0x80000000, rom_bytes=131072,
                      clocks_hz=dict(cpu=300000000, fabric=250000000, timebase=250000000,
                                     ddr_ui=250000000, uart=50000000, aon=50000000),
                      features=dict(mac=False, network_dma=False))
        self.profile = gate.digest(config)
        for name in gate.ROOTS:
            (self.root / name).mkdir(parents=True)
        self.write('src/main/scala/platform/Fake.scala', '// SYNTHETIC, NOT HARDWARE\n')
        self.write('src/main/resources/fake.sv', '// SYNTHETIC RESOURCE\n')
        self.write('src/test/scala/platform/FakeSpec.scala', '// SYNTHETIC ORACLE\n')
        for name in ('manifest.py', 'stage.tcl', 'signoff.tcl', 'run-local.ps1'):
            shutil.copy2(HERE / name, self.root / 'fpga/common' / name)
        for name, text in {'rtl/top.sv': 'module SyntheticTop(); endmodule\n',
                           'rtl/files.f': 'rtl/top.sv\n', 'firmware/rom.bin': 'FAKE_ROM',
                           'board/pins.xdc': '# FAKE_XDC', 'ip/fake.xci': 'FAKE_IP',
                           'producers/stage.tcl': '# not executable hardware evidence',
                           'producers/audit.tcl': '# not executable hardware evidence'}.items():
            self.write(name, text)
        self.write_json('firmware/contract.json', dict(abi=1, cpu_hz=300000000, fabric_hz=250000000,
                                                     timebase_hz=250000000, rom_sha256=gate.sha(self.root / 'firmware/rom.bin')))
        production = {p.relative_to(self.root).as_posix(): gate.sha(p) for name in ('src/main/scala', 'src/main/resources')
                      for p in (self.root / name).rglob('*') if p.is_file()}
        self.write_json('evidence/functional.json', dict(status='PASS', scope='common-platform-affected-short',
                                                       physical_qualified=False, profile_sha256=self.profile,
                                                       source_sha256=production))
        self.m = dict(schema=gate.SCHEMA, configuration=config, threads=8,
                      source_roots=list(gate.ROOTS), inputs={},
                      roles=dict(rtl_filelist='rtl/files.f', firmware_contract='firmware/contract.json',
                                 functional_receipt='evidence/functional.json', rom='firmware/rom.bin',
                                 board_audit_script='producers/audit.tcl', constraints=['board/pins.xdc'], ip=['ip/fake.xci']),
                      stages={phase: dict(script='producers/stage.tcl', outputs=['routed.dcp' if phase == 'implementation' else 'done.txt'])
                              for phase in gate.STAGES},
                      signoff=dict(bus_skew_checks=2, clock_pins={name: 'u_soc/' + name + '_clock' for name in gate.CLOCKS}))
        self.refresh()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def write_json(self, name, value):
        return self.write(name, json.dumps(value))

    def refresh(self):
        self.m['inputs'] = {p.relative_to(self.root).as_posix(): gate.sha(p) for p in self.root.rglob('*')
                            if p.is_file() and p != self.path and 'local-run' not in p.parts}
        self.path.write_text(json.dumps(self.m))

    def save(self):
        self.path.write_text(json.dumps(self.m))

    def runtime_contract(self):
        original = self.write('firmware/bootrom.bin', 'SYNTHETIC_SHARED_ROM_NOT_HARDWARE')
        padded = self.root / self.m['roles']['rom']
        padded.write_bytes(original.read_bytes() + bytes(131072 - original.stat().st_size))
        build = self.write_json('firmware/bootrom-contract.json', dict(
            schema=1, cpu_hz=None, cpu_clock_source='CMU resource 1 nominalHz', cmu_clock_metadata=True,
            fabric_hz=250000000, timebase_hz=250000000,
            timebase_source='MachineTimer.timeValue -> TIME CSR; ticks in configured timebase domain',
            bootrom_sha256=gate.sha(original)))
        fw = dict(abi=1, cpu_hz=None, fabric_hz=250000000, timebase_hz=250000000,
                  rom_sha256=gate.sha(padded), runtime_cpu_hz_source='CMU resource 1 nominalHz',
                  runtime_cpu_hz_resource_index=1, runtime_cpu_hz_address=0x10080148,
                  profile_cpu_hz=self.m['configuration']['clocks_hz']['cpu'],
                  build_contract=dict(path='firmware/bootrom-contract.json', sha256=gate.sha(build)),
                  unpadded_rom=dict(path='firmware/bootrom.bin', sha256=gate.sha(original),
                                    bytes=original.stat().st_size))
        self.write_json('firmware/contract.json', fw); self.refresh()
        return fw

    def frozen_run(self):
        self.write('local-run/config.tcl', '# synthetic resolved config\n')
        self.write('local-run/config-sha256.txt', gate.sha(self.root / 'local-run/config.tcl'))
        self.write('local-run/manifest-sha256.txt', gate.sha(self.path))
        for phase in gate.STAGES:
            folder = 'local-run/' + phase + '/'
            output = self.m['stages'][phase]['outputs'][0]
            self.write(folder + output, 'SYNTHETIC_STAGE_OUTPUT')
            log = self.write(folder + 'thread.log', 'SYNTHETIC configured thread limit=8; not a tool run')
            tools = {name: dict(requested_threads=8, effective_thread_limit=8, status='configured',
                                command=[name, '-mt', '8'] if name == 'xelab' else [name],
                                evidence=dict(path='thread.log', sha256=gate.sha(log))) for name in gate.TOOLS[phase]}
            self.write_json(folder + 'stage-receipt.json', dict(status='PASS', phase=phase, profile_sha256=self.profile,
                                                               outputs_sha256={output: gate.sha(self.root / folder / output)}, tools=tools))
        self.reports = self.root / 'local-run/signoff'
        self.dcp = self.root / 'local-run/implementation/routed.dcp'
        self.dcp_hash = gate.sha(self.dcp)
        for name in gate.REPORTS:
            self.write('local-run/signoff/' + name, 'SYNTHETIC REPORT ONLY\n')
        self.write('local-run/signoff/timing.rpt', 'All user specified timing constraints are met.\n'
                   '0.001 0.000 0 100 0.002 0.000 0 100 0.003 0.000 0 100\n')
        self.write('local-run/signoff/coverage.rpt', '\n'.join('checking ' + x + ' (0)' for x in gate.COVERAGE))
        self.write('local-run/signoff/route.rpt', '# of routable nets..... : 100\n# of fully routed nets..... : 100\n'
                   '# of nets with routing errors..... : 0 :\n')
        self.write('local-run/signoff/bus_skew.rpt', 'Slack (MET) : 0.100ns\nSlack (MET) : 0.200ns\n')
        self.facts = dict(profile_sha256=self.profile, dcp_sha256=self.dcp_hash, part=self.m['configuration']['part'],
                          top='SyntheticTop', critical_drc=0, blackboxes=0, requested_threads=8, effective_thread_limit=8,
                          domains={name: dict(period_ns=1e9 / self.m['configuration']['clocks_hz'][name],
                                              setup_ns=0.1, hold_ns=0.1) for name in gate.CLOCKS})
        self.write_json('local-run/signoff/facts.json', self.facts)
        self.audit = dict(status='PASS', profile_sha256=self.profile, dcp_sha256=self.dcp_hash,
                          unreviewed_critical_cdc=0, cdc_review_scope='SYNTHETIC: not physical evidence',
                          checks=dict(rom_content_and_mapping='PASS', reset_cdc='PASS', cpu_selection='PASS'))
        self.write_json('local-run/signoff/board-audit.json', self.audit)

    def signoff(self):
        original = gate.preflight
        # Skip only the unavailable Windows host check, retaining every other gate.
        with patch.object(gate, 'preflight', side_effect=lambda m, windows=False: original(m, windows=False)):
            return gate.signoff(self.path, self.reports, self.dcp, self.dcp_hash)

    def test_valid_input_contract_for_both_cpus(self):
        for cpu in ('i1', 'a1'):
            with self.subTest(cpu=cpu):
                self.m['configuration']['cpu'] = cpu
                receipt = gate.read(self.root / 'evidence/functional.json')
                receipt['profile_sha256'] = gate.digest(self.m['configuration'])
                self.write_json('evidence/functional.json', receipt)
                self.refresh()
                gate.preflight(self.path)

    def test_runtime_shared_rom_accepts_both_cpu_profiles_without_rewriting_build(self):
        fw = self.runtime_contract()
        original_build = (self.root / 'firmware/bootrom-contract.json').read_bytes()
        original_rom = (self.root / 'firmware/bootrom.bin').read_bytes()
        for cpu, hz in (('i1', 300000000), ('a1', 100000000)):
            with self.subTest(cpu=cpu):
                self.m['configuration']['cpu'] = cpu
                self.m['configuration']['clocks_hz']['cpu'] = hz
                fw['profile_cpu_hz'] = hz
                self.write_json('firmware/contract.json', fw)
                receipt = gate.read(self.root / 'evidence/functional.json')
                receipt['profile_sha256'] = gate.digest(self.m['configuration'])
                self.write_json('evidence/functional.json', receipt); self.refresh()
                gate.preflight(self.path)
                self.assertEqual((self.root / 'firmware/bootrom-contract.json').read_bytes(), original_build)
                self.assertEqual((self.root / 'firmware/bootrom.bin').read_bytes(), original_rom)

    def test_runtime_cpu_source_profile_and_explicit_null_required(self):
        fw = self.runtime_contract()
        cases = [('runtime_cpu_hz_source', 'TIME CSR'), ('runtime_cpu_hz_source', None),
                 ('runtime_cpu_hz_resource_index', 2), ('runtime_cpu_hz_resource_index', True),
                 ('runtime_cpu_hz_address', 0x10080188), ('runtime_cpu_hz_address', '0x10080148'),
                 ('profile_cpu_hz', 250000000), ('profile_cpu_hz', 300000000.0),
                 ('cpu_hz', 300000000), ('cpu_hz', 'null'), ('timebase_hz', 300000000)]
        for key, value in cases:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                bad = copy.deepcopy(fw); bad[key] = value
                self.write_json('firmware/contract.json', bad); self.refresh()
                gate.preflight(self.path)
        for key in ('cpu_hz', *gate.RUNTIME_CPU_FIELDS):
            with self.subTest(missing=key), self.assertRaises(ValueError):
                bad = copy.deepcopy(fw); del bad[key]
                self.write_json('firmware/contract.json', bad); self.refresh()
                gate.preflight(self.path)

    def test_runtime_build_metadata_cannot_claim_static_cpu_or_cpu_timebase(self):
        fw = self.runtime_contract()
        build = gate.read(self.root / fw['build_contract']['path'])
        cases = [('cpu_hz', 300000000), ('cpu_clock_source', 'build constant'),
                 ('cmu_clock_metadata', False), ('schema', 2), ('fabric_hz', 300000000),
                 ('timebase_hz', 300000000), ('timebase_source', 'CPU clock'),
                 ('bootrom_sha256', '0' * 64)]
        for key, value in cases:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'build contract'):
                bad = copy.deepcopy(build); bad[key] = value
                path = self.write_json(fw['build_contract']['path'], bad)
                fw['build_contract']['sha256'] = gate.sha(path)
                self.write_json('firmware/contract.json', fw); self.refresh()
                gate.preflight(self.path)
        bad = copy.deepcopy(build); del bad['cpu_hz']
        path = self.write_json(fw['build_contract']['path'], bad)
        fw['build_contract']['sha256'] = gate.sha(path)
        self.write_json('firmware/contract.json', fw); self.refresh()
        with self.assertRaisesRegex(ValueError, 'build contract'):
            gate.preflight(self.path)

    def test_runtime_references_are_collected_and_missing_files_rejected(self):
        static = gate.read(self.root / 'firmware/contract.json')
        self.assertEqual(gate.firmware_inputs(self.root, static), [])
        fw = self.runtime_contract()
        self.assertEqual(gate.firmware_inputs(self.root, fw),
                         ['firmware/bootrom-contract.json', 'firmware/bootrom.bin'])
        for name in ('build_contract', 'unpadded_rom'):
            path = self.root / fw[name]['path']; original = path.read_bytes(); path.unlink()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'missing input'):
                gate.firmware_inputs(self.root, fw)
            path.write_bytes(original)
        bad = copy.deepcopy(fw); bad['build_contract']['path'] = '../escape.json'
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            gate.firmware_inputs(self.root, bad)

    def test_runtime_references_must_be_frozen_and_match_both_hashes(self):
        fw = self.runtime_contract()
        for name in ('build_contract', 'unpadded_rom'):
            self.write_json('firmware/contract.json', fw); self.refresh()
            del self.m['inputs'][fw[name]['path']]; self.save()
            with self.subTest(unfrozen=name), self.assertRaisesRegex(ValueError, 'unfrozen runtime'):
                gate.preflight(self.path)
            bad = copy.deepcopy(fw); bad[name]['sha256'] = '0' * 64
            self.write_json('firmware/contract.json', bad); self.refresh()
            with self.subTest(hash=name), self.assertRaisesRegex(ValueError, 'reference hash mismatch'):
                gate.preflight(self.path)

    def test_runtime_board_rom_requires_exact_original_and_zero_padding(self):
        fw = self.runtime_contract()
        path = self.root / self.m['roles']['rom']; original = path.read_bytes()
        for content in (b'X' + original[1:], original[:-1] + b'X', original[:-1], original + b'\0'):
            with self.subTest(size=len(content)), self.assertRaisesRegex(ValueError, 'zero padding'):
                path.write_bytes(content); fw['rom_sha256'] = gate.sha(path)
                self.write_json('firmware/contract.json', fw); self.refresh()
                gate.preflight(self.path)
        path.write_bytes(original); fw['rom_sha256'] = gate.sha(path)
        for size in (0, True, 131073, fw['unpadded_rom']['bytes'] + 1):
            with self.subTest(bytes=size), self.assertRaises(ValueError):
                bad = copy.deepcopy(fw); bad['unpadded_rom']['bytes'] = size
                self.write_json('firmware/contract.json', bad); self.refresh()
                gate.preflight(self.path)

    def test_paths_reject_traversal_unc_ads_and_windows_aliases(self):
        for value in ('../escape', '/tmp/x', 'C:/x', r'\\wsl$\Ubuntu\x', 'a\\b', 'a:b', 'a/../b',
                      'a//b', './a', 'NUL.txt', 'a/COM1', 'a.', 'a ', 'a/*'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                gate.relative(value)
        for value in ('/mnt/e/x', r'\\wsl$\Ubuntu\x', r'\\server\share\x', 'relative'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                gate.local_windows_path(value)
        gate.local_windows_path(r'D:\Valence\candidate')

    def test_duplicate_json_and_nan_rejected(self):
        for text in ('{"status":"FAIL","status":"PASS"}', '{"slack":NaN}'):
            path = self.write('bad.json', text)
            with self.assertRaises(ValueError):
                gate.read(path)

    def test_missing_input_and_hash_drift(self):
        self.write('rtl/top.sv', 'tampered')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            gate.preflight(self.path)
        (self.root / 'rtl/top.sv').unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            gate.preflight(self.path)

    def test_unmanifested_common_source(self):
        self.write('src/main/scala/platform/New.scala', '// NEW UNBOUND SOURCE')
        with self.assertRaisesRegex(ValueError, 'unmanifested source'):
            gate.preflight(self.path)

    def test_symlink_rejected(self):
        link = self.root / 'linked'
        link.symlink_to(self.root / 'rtl', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            gate.file_at(self.root, 'linked/top.sv')

    def test_wrong_timebase_firmware_and_old_profile(self):
        fw = gate.read(self.root / 'firmware/contract.json')
        fw['timebase_hz'] = 300000000
        self.write_json('firmware/contract.json', fw); self.refresh()
        with self.assertRaisesRegex(ValueError, 'timebase'):
            gate.preflight(self.path)
        self.m['configuration']['clocks_hz']['timebase'] = 300000000; self.save()
        with self.assertRaisesRegex(ValueError, 'timebase must equal fabric'):
            gate.preflight(self.path)

    def test_thread_request_and_explicit_off_rejected(self):
        self.m['threads'] = 4; self.save()
        with self.assertRaisesRegex(ValueError, 'eight threads'):
            gate.preflight(self.path)
        self.m['threads'] = 8; self.save(); self.frozen_run()
        r = gate.read(self.root / 'local-run/simulation/stage-receipt.json')
        r['tools']['xelab']['command'] = ['xelab', '-mt', 'off']
        self.write_json('local-run/simulation/stage-receipt.json', r)
        with self.assertRaisesRegex(ValueError, 'multithreading-off'):
            gate.check_stage(self.root, self.m, self.profile, 'simulation', self.root / 'local-run/simulation')

    def test_unsupported_threading_requires_evidence_and_is_disclosed(self):
        self.frozen_run()
        r = gate.read(self.root / 'local-run/simulation/stage-receipt.json')
        record = r['tools']['xsim']
        record.update(status='unsupported', effective_thread_limit=None, reason='SYNTHETIC installed-tool limit evidence')
        self.write_json('local-run/simulation/stage-receipt.json', r)
        self.assertIn('xsim:', self.signoff()['threading_limitations'][0])
        record['reason'] = ''
        self.write_json('local-run/simulation/stage-receipt.json', r)
        with self.assertRaisesRegex(ValueError, 'unsupported threading'):
            self.signoff()

    def test_synthetic_report_contract_only(self):
        self.frozen_run()
        result = self.signoff()
        self.assertEqual(result['status'], 'PASS_REPORT_CONTRACT')
        self.assertFalse(result['board_tested'])
        self.assertFalse(result['full_cdc_signoff'])
        self.assertFalse((self.reports / 'qualified.bit').exists())

    def test_final_negative_reports(self):
        self.frozen_run()
        cases = [('timing.rpt', 'All user specified timing constraints are met.\n'
                  '-0.001 -0.001 1 100 0.002 0.000 0 100 0.003 0.000 0 100\n'),
                 ('timing.rpt', 'UNKNOWN FORMAT\n'),
                 ('coverage.rpt', 'checking no_clock (1)\n'),
                 ('route.rpt', '# of routable nets.... : 100\n# of fully routed nets.... : 99\n'
                  '# of nets with routing errors.... : 1\n'),
                 ('bus_skew.rpt', 'Slack (MET) : 0.1ns\nSlack (VIOLATED) : -0.1ns\n'),
                 ('bus_skew.rpt', 'Slack (MET) : 0.1ns\n')]
        for name, bad in cases:
            path = self.reports / name
            original = path.read_text()
            with self.subTest(name=name, bad=bad):
                path.write_text(bad)
                with self.assertRaises(ValueError):
                    self.signoff()
                path.write_text(original)

    def test_drc_blackbox_clock_and_audit_failures(self):
        self.frozen_run()
        variants = []
        for key in ('critical_drc', 'blackboxes'):
            bad = copy.deepcopy(self.facts); bad[key] = 1; variants.append(bad)
        bad = copy.deepcopy(self.facts); bad['domains']['timebase']['period_ns'] = 3.333; variants.append(bad)
        bad = copy.deepcopy(self.facts); bad['domains']['cpu']['hold_ns'] = -0.001; variants.append(bad)
        for bad in variants:
            self.write_json('local-run/signoff/facts.json', bad)
            with self.assertRaises(ValueError):
                self.signoff()
        self.write_json('local-run/signoff/facts.json', self.facts)
        self.audit['unreviewed_critical_cdc'] = 1
        self.write_json('local-run/signoff/board-audit.json', self.audit)
        with self.assertRaisesRegex(ValueError, 'audit missing'):
            self.signoff()

    def test_changed_dcp_config_and_manifest(self):
        self.frozen_run()
        self.dcp.write_text('changed checkpoint')
        with self.assertRaisesRegex(ValueError, 'output drift'):
            self.signoff()
        self.write('local-run/config.tcl', '# changed config')
        with self.assertRaisesRegex(ValueError, 'configuration changed'):
            gate.preflight(self.path)
        self.m['threads'] = 9; self.save()
        with self.assertRaisesRegex(ValueError, 'manifest changed'):
            gate.preflight(self.path)

    def test_missing_report_blocks(self):
        self.frozen_run()
        (self.reports / 'bus_skew.rpt').unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.signoff()

    def test_template_is_intentionally_unusable(self):
        with self.assertRaises(ValueError):
            gate.preflight(HERE / 'manifest.template.json')

    @unittest.skipUnless(shutil.which('tclsh'), 'tclsh unavailable; no tool installation')
    def test_real_stage_wrapper_blocks_early_bit_and_failure(self):
        folder = self.root / 'local-run/simulation'; folder.mkdir(parents=True)
        config = self.write('mock-config.tcl', 'set valence(root) ' + gate.tcl(self.root) + '\n'
                            'set valence(threads) 8\nset valence(profile_sha256) mock\n'
                            'set valence(script_simulation) ' + gate.tcl(self.root / 'mock-producer.tcl') + '\n')
        for body in ('write_bitstream forbidden.bit', 'error {MOCK PRODUCER FAILED}'):
            self.write('mock-producer.tcl', body)
            driver = self.write('mock-driver.tcl', 'proc set_param {args} {}\nproc get_param {args} {return 8}\n'
                                'proc write_bitstream {args} {error {native bit must never run}}\n'
                                'set argc 2\nset argv [list ' + gate.tcl(config) + ' simulation]\n'
                                'source ' + gate.tcl(HERE / 'stage.tcl'))
            result = subprocess.run(['tclsh', str(driver)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('COMMON_STAGE_FAILED', result.stderr)
            self.assertFalse((folder / 'forbidden.bit').exists())


    @unittest.skipUnless(shutil.which('tclsh'), 'tclsh unavailable; no tool installation')
    def test_real_final_tcl_calls_gate_before_only_bit_write(self):
        # The Vivado commands and gate subprocess below are explicit mocks.
        # Actual Python report acceptance/rejection is separately exercised above.
        out = self.root / 'local-run/signoff'; out.mkdir(parents=True)
        self.write('local-run/implementation/routed.dcp', 'MOCK CHECKPOINT')
        audit = self.write('mock-audit.tcl', 'set f [open board-audit.json w]; puts $f {MOCK}; close $f')
        pairs = dict(root=str(self.root), manifest=str(self.path), threads=8, profile_sha256=self.profile,
                     top='SyntheticTop', part=self.m['configuration']['part'], audit_script=str(audit))
        for name in gate.CLOCKS:
            pairs['hz_' + name] = self.m['configuration']['clocks_hz'][name]
            pairs['pin_' + name] = name
        config = self.write('mock-final-config.tcl', '\n'.join('set valence(' + k + ') ' + gate.tcl(v) for k, v in pairs.items()))
        mocks = r'''proc set_param {args} {}
proc get_param {args} {return 8}
proc open_checkpoint {args} {}
proc current_design {} {return design}
proc get_pins {args} {return [lindex $args end]}
proc get_clocks {args} {return [lindex $args end]}
proc get_timing_paths {args} {return path}
proc get_cells {args} {return {}}
proc get_drc_violations {args} {return {}}
proc get_property {property object} {
    global valence
    switch $property {
        PART {return $valence(part)} NAME {return $valence(top)}
        PERIOD {return [expr {1e9/$valence(hz_$object)}]} SLACK {return 0.1}
        default {error "unexpected mocked property"}
    }
}
foreach command {report_timing_summary check_timing report_route_status report_bus_skew report_drc report_cdc report_clocks} {
    proc $command {args} {set f [open [lindex $args end] w]; puts $f {MOCK REPORT}; close $f}
}
proc write_bitstream {path} {
    if {![file exists mock-gate-passed]} {error "Gate must precede bit write"}
    set f [open $path w]; puts $f {MOCK BIT, NOT FPGA DATA}; close $f
}
proc close_design {} {}
'''
        for allow in (False, True):
            checker = 'import sys\n' + ('open("mock-gate-passed", "w").write("MOCK")\nprint("MOCK_GATE_ACCEPT")\n' if allow
                                       else 'sys.exit("MOCK_GATE_REJECT_MISSING_BUS_SKEW")\n')
            self.write('fpga/common/manifest.py', checker)
            driver = self.write('mock-final-driver.tcl', mocks + '\nset argc 4\nset argv [list ' + gate.tcl(config) + ' ' +
                                gate.tcl(sys.executable) + ' ' + gate.tcl('a' * 64) + ' 1]\nsource ' + gate.tcl(HERE / 'signoff.tcl'))
            result = subprocess.run(['tclsh', str(driver)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0 if allow else 1, result.stdout + result.stderr)
            self.assertEqual((out / 'qualified.bit').exists(), allow)
            facts = gate.read(out / 'facts.json')
            self.assertEqual(facts['domains']['cpu']['period_ns'], 1e9 / 300000000)
            self.assertEqual(facts['domains']['timebase']['period_ns'], 4.0)


if __name__ == '__main__':
    unittest.main()
