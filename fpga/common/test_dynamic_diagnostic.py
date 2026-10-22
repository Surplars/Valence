"""Exact delivered source/input controls; not mapped/Vivado qualification."""
import copy
import json
from pathlib import Path
import unittest
import tempfile
import board_inputs as board
import diagnostic
import manifest as gate

ROOT = Path(__file__).resolve().parents[2]
BASE = Path('delivery/boot50-dynamic-r25/rtl')

class DynamicDiagnostic(unittest.TestCase):
    def test_native_mig_replacement_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root/'native.txt'; report.write_text('synthetic parser fixture, not native evidence')
            r = dict(schema='common-native-mig2025p2-replacement-v1', status='PASS',
                     original_xci_sha256=diagnostic.OLD_DYNAMIC_MIG, xci_sha256=diagnostic.NEW_DYNAMIC_MIG,
                     xci_size=54491, component_dcp_sha256=diagnostic.NEW_DYNAMIC_MIG_DCP,
                     component_dcp_size=5049818, vivado='2025.2', ip_version='2.2',
                     ip_revision=28, part='xczu15eg-ffvb1156-2-i', ip_locked=False,
                     common_config_differences={}, port_count=871, port_differences=[],
                     ui_clock_period_ns=4.0, ooc_exit_code=0, ooc_errors=0,
                     ooc_critical_warnings=0, requested_threads=8, general_thread_limit=8,
                     board_tested=False, physical_qualified=False,
                     evidence_sha256={'native.txt':gate.sha(report)})
            m = dict(roles=dict(ip=['new.xci'],native_mig_replacement='mig.json'),
                     native_evidence=['mig.json'], inputs={'new.xci':diagnostic.NEW_DYNAMIC_MIG,
                                                         'native.txt':gate.sha(report)})
            receipt = root/'mig.json'
            receipt.write_text(json.dumps(r)); diagnostic.dynamic_mig(root,m)
            for key,value in (('vivado','2025.1'),('ip_revision',27),('ip_locked',True),
                              ('common_config_differences',{'width':'changed'}),('port_count',870),
                              ('port_differences',['direction']),('ui_clock_period_ns',5),
                              ('component_dcp_sha256','0'*64),('ooc_exit_code',1),
                              ('ooc_critical_warnings',1),('board_tested',True),('evidence_sha256',{})):
                changed=copy.deepcopy(r); changed[key]=value; receipt.write_text(json.dumps(changed))
                with self.subTest(key=key),self.assertRaises(ValueError): diagnostic.dynamic_mig(root,m)
            receipt.write_text(json.dumps(r))
            for digest in (diagnostic.OLD_DYNAMIC_MIG,'0'*64):
                changed=copy.deepcopy(m); changed['inputs']['new.xci']=digest
                with self.subTest(digest=digest),self.assertRaises(ValueError): diagnostic.dynamic_mig(root,changed)
            report.write_text('mutated native report')
            with self.assertRaises(ValueError): diagnostic.dynamic_mig(root,m)

    def fixture(self):
        meta = gate.read(ROOT / BASE / 'emission-profile.json')
        review_name = 'fpga/common/dynamic/mac_diagnostic_review.json'
        review = gate.read(ROOT / review_name)
        paths = [review_name, *(review['sources_sha256']),
                 *((BASE / name).as_posix() for name in review['artifacts_sha256'])]
        m = dict(diagnosticOnly=True, configuration=dict(cpu='i1',clock_profile='boot50-dynamic'),
                 inputs={name:gate.sha(ROOT/name) for name in paths})
        return m,meta

    def test_exact_fixed_source_composition(self):
        m,meta=self.fixture()
        board.dynamic_mac_control_form(ROOT,m,meta,BASE)

    def test_changed_profile_capabilities_or_qualification_rejected(self):
        original,meta=self.fixture()
        for field,value in (('diagnosticOnly',False),('cpu','a1'),('clock_profile','performance300-static')):
            m=copy.deepcopy(original)
            (m if field=='diagnosticOnly' else m['configuration'])[field]=value
            with self.subTest(field=field), self.assertRaises(ValueError):
                board.dynamic_mac_control_form(ROOT,m,meta,BASE)
        for field,value in (('runtimeClockReconfiguration',False),('hardwareClocks',False),
                            ('independentFixedDomains',False),('oneSidedResetSupported',True),
                            ('physicalTimingVerified',True),('boardVerified',True),
                            ('fabricClockHz',250000000),('fifoDepth',8)):
            changed=copy.deepcopy(meta);changed[field]=value
            with self.subTest(field=field), self.assertRaises(ValueError):
                board.dynamic_mac_control_form(ROOT,original,changed,BASE)

    def test_owner_source_boundary_or_review_changes_rejected(self):
        original,meta=self.fixture()
        for suffix in ('CommonMachinePlatformMain.scala','ClockRateControl.scala',
                       'FixedSourceManagedGmac.scala','CommonFixedMacRuntimeAdapter.scala',
                       'ManagedPeripheralBank.sv','HeldResponseCdcDataFifo_33.sv',
                       'soc_top_common_ddr.sv','mac_diagnostic_review.json'):
            m=copy.deepcopy(original)
            names=[n for n in m['inputs'] if n.endswith('/'+suffix)]
            self.assertEqual(len(names),1)
            m['inputs'][names[0]]='0'*64
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                board.dynamic_mac_control_form(ROOT,m,meta,BASE)

    def test_actual_delivery_commit_and_source_inventory(self):
        name = 'delivery/boot50-dynamic-r25/source-inputs.json'
        inventory = gate.read(ROOT/name)
        # Synthetic published identity: this unit check asserts byte matching,
        # not that a release commit or native execution exists.
        m = dict(source_commit='a'*40, roles=dict(source_inventory=name),
                 inputs={**inventory['files_sha256'],name:gate.sha(ROOT/name)})
        diagnostic.dynamic_delivery(ROOT,m)
        for field in ('commit','missing','source'):
            changed=copy.deepcopy(m)
            if field=='commit': changed['source_commit']='unknown'
            if field=='missing': changed['roles'].pop('source_inventory')
            if field=='source': changed['inputs']['fpga/common/diagnostic.py']='0'*64
            with self.subTest(field=field),self.assertRaises(ValueError):
                diagnostic.dynamic_delivery(ROOT,changed)

    def test_dynamic_baseline_keeps_actual_gate_patch_and_no_bit(self):
        baseline=gate.read(ROOT/'fpga/common/dynamic/diagnostic-baseline.json')
        self.assertEqual(baseline['commit'],diagnostic.DYNAMIC_BASELINE)
        for name in ('native_clock_gate.sv','native_clock_drp.sv','native_dynamic_clock_domain.sv'):
            path='fpga/common/dynamic/'+name
            self.assertEqual(baseline['inputs'][path],gate.sha(ROOT/path))
            self.assertNotIn(path,diagnostic.DYNAMIC_OVERLAYS)
        for path in ('diagnostic.tcl','resume_diagnostic.tcl'):
            text=(ROOT/'fpga/common'/path).read_text()
            self.assertIn('write_bitstream write_device_image',text)
            self.assertIn('performance300-static boot50-dynamic',text)

if __name__ == '__main__': unittest.main()
