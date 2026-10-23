"""Fail-closed structural receipt tests; synthetic fixtures are not FPGA evidence."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import board_inputs as b
import diagnostic


class SoftwareParameterReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.base = Path('emitted')
        self.meta = dict(functionalProfile=b.SOFTWARE_PARAMETER_PROFILE,
            softwareParameterMode=True, hardwareRateWhitelist=False,
            clockRateAbi=2, performanceTelemetryAbi=1, performanceTelemetry=True,
            rateAdmission='explicit-diagnostic-not-qualified', diagnosticPointFlags=48,
            qualifiedRatePointsHz=[], rateParameterLimits=dict(D=10,minM=32,maxM=62,minO=3,maxO=128,
                referenceHz=250000000,minimumHz=10000000,maximumCpuHz=300000000,maximumFabricHz=250000000),
            frequencyMeasurement='managed-edge-count-over-aon-window',
            telemetryBase='0x10080900', cpuClockHz=50000000, fabricClockHz=50000000,
            physicalTimingVerified=False, boardVerified=False)
        self.m = dict(configuration=dict(performance_telemetry=True, functional_profile=b.SOFTWARE_PARAMETER_PROFILE),
            roles=dict(software_parameter_review='review.json', rom='rom.bin', rom_coe='rom.coe', firmware_contract='firmware.json'),
            source_commit='a'*40, inputs={})
        sources = set(b.BOARD_RTL) | {'fpga/firmware/valence_clock.h', 'fpga/firmware/valence_cmu.h',
            'fpga/firmware/boot_clock_console.h', 'fpga/firmware/bootrom.c',
            'fpga/zu15eg/performance-telemetry-constraints.tcl', 'fpga/common/performance_telemetry_constraints.tcl'}
        self.artifacts = {n+'.sv': 'b'*64 for n in ('ClockPerformanceTelemetry',
            'ClockPerformanceTelemetryRegisters', 'ClockRateManagement', 'ClockRateManagementBoundary')}
        self.review = dict(schema='common-software-parameter-feature-review-v1', status='REVIEWED_STRUCTURAL_ONLY',
            physical_qualified=False, board_qualified=False, source_commit='a'*40,
            features=copy.deepcopy(self.meta), sources_sha256={n:'b'*64 for n in sources},
            artifacts_sha256=self.artifacts.copy(), firmware_sha256={}, instances=[dict(file=f,module=m,instance=i)
            for f,m,i in [('ManagedPeripheralBank.sv','TriSpeedManagedGmac','gmac'),
                         ('ManagedPeripheralBank.sv','FixedMacBoundary','crossing'),
                         ('CommonMachinePlatform.sv','ManagedPeripheralBank','peripherals'),
                         ('CommonMachinePlatform.sv','ClockPerformanceTelemetry','monitor')]])
        for name in ('rom.bin','rom.coe','firmware.json'):
            (self.root/name).write_text(name); h=b.gate.sha(self.root/name)
            self.m['inputs'][name]=h; self.review['firmware_sha256'][name]=h
        self.build = dict(clock_console=True, clock_console_rate_abi=2, clock_console_telemetry_abi=1,
            boot_menu=True, clock_console_auto_change=False, clock_console_initial_candidates_mhz=list(range(50,151,5)))
        (self.root/'build.json').write_text(json.dumps(self.build)); h=b.gate.sha(self.root/'build.json')
        self.m['inputs']['build.json']=h; self.review['firmware_sha256']['build.json']=h
        (self.root/'firmware.json').write_text(json.dumps(dict(build_contract=dict(path='build.json',sha256=h))))
        h=b.gate.sha(self.root/'firmware.json')
        self.m['inputs']['firmware.json']=h; self.review['firmware_sha256']['firmware.json']=h
        (self.root/self.base).mkdir()
        (self.root/self.base/'CommonMachinePlatform.sv').write_text('\n'.join(
            f'output [23:0] rateBackend_{d}_program_bits_parameters,' for d in (0,1)))

    def check(self):
        (self.root/'review.json').write_text(json.dumps(self.review))
        self.m['inputs']['review.json']=b.gate.sha(self.root/'review.json')
        with patch.object(b,'emitted_sources',return_value={}), patch.object(b,'emitted_artifacts',return_value=self.artifacts):
            return b.software_parameter_review(self.root,self.m,self.meta,self.base)

    def test_configuration_and_emission_selectors_must_agree(self):
        self.assertTrue(b.software_parameter_selection(self.m['configuration'], self.meta))
        for configuration, meta in [(self.m['configuration'], {}), ({}, self.meta),
                ({**self.m['configuration'], 'performance_telemetry': False}, self.meta)]:
            with self.assertRaises(ValueError): b.software_parameter_selection(configuration,meta)

    def test_explicit_structural_only_receipt(self): self.assertEqual(self.check(),self.review)
    def test_every_feature_mismatch_rejected(self):
        for key in self.meta:
            with self.subTest(key=key):
                old=self.meta[key]; self.meta[key]=None
                with self.assertRaises(ValueError): self.check()
                self.meta[key]=old
    def test_missing_source_and_artifact_rejected(self):
        for key in ('sources_sha256','artifacts_sha256'):
            old=self.review[key]; self.review[key]={}
            with self.assertRaises(ValueError): self.check()
            self.review[key]=old
    def test_wrong_commit_or_claimed_qualification_rejected(self):
        for key,value in [('source_commit','c'*40),('physical_qualified',True),('board_qualified',True)]:
            old=self.review[key]; self.review[key]=value
            with self.assertRaises(ValueError): self.check()
            self.review[key]=old
    def test_old_consistently_hashed_rom_contract_rejected(self):
        self.build['clock_console']=False
        (self.root/'build.json').write_text(json.dumps(self.build)); h=b.gate.sha(self.root/'build.json')
        self.m['inputs']['build.json']=h; self.review['firmware_sha256']['build.json']=h
        (self.root/'firmware.json').write_text(json.dumps(dict(build_contract=dict(path='build.json',sha256=h))))
        h=b.gate.sha(self.root/'firmware.json')
        self.m['inputs']['firmware.json']=h; self.review['firmware_sha256']['firmware.json']=h
        with self.assertRaises(ValueError): self.check()

    def test_stale_rom_rejected(self):
        (self.root/'rom.bin').write_text('stale')
        with self.assertRaises(ValueError): self.check()
    def test_missing_monitor_and_parameter_ports_rejected(self):
        old=self.review['instances']; self.review['instances']=old[:-1]
        with self.assertRaises(ValueError): self.check()
        self.review['instances']=old
        (self.root/self.base/'CommonMachinePlatform.sv').write_text('')
        with self.assertRaises(ValueError): self.check()

class SoftwareParameterDelivery(unittest.TestCase):
    def test_exact_new_inventory_and_no_old_hash_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = set(b.PUBLIC_INPUTS) | set(b.BOARD_RTL) | {'src/main/scala/NewMeter.scala',
                'fpga/firmware/valence_clock.h'}
            files = {}
            for name in names:
                path=root/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(name)
                files[name]=b.gate.sha(path)
            name='delivery/software-parameters/source-inputs.json'
            inv=dict(schema='common-software-parameter-source-inventory-v1',source_commit='a'*40,
                status='REVIEWED_STRUCTURAL_ONLY',physical_qualified=False,board_qualified=False,files_sha256=files)
            path=root/name; path.parent.mkdir(parents=True); path.write_text(json.dumps(inv))
            m=dict(source_commit='a'*40,production_source_baseline='a'*40,
                configuration=dict(functional_profile=b.SOFTWARE_PARAMETER_PROFILE),
                roles=dict(source_inventory=name),inputs={**files,name:b.gate.sha(path)})
            self.assertEqual(diagnostic.dynamic_delivery(root,m)['inputs'],files)
            for field,value in [('source_commit','b'*40),('production_source_baseline',diagnostic.DYNAMIC_BASELINE)]:
                changed=copy.deepcopy(m);changed[field]=value
                with self.assertRaises(ValueError): diagnostic.dynamic_delivery(root,changed)
            changed=copy.deepcopy(m);changed['inputs']['src/main/scala/Unexpected.scala']='0'*64
            with self.assertRaises(ValueError): diagnostic.dynamic_delivery(root,changed)
            (root/'fpga/firmware/valence_clock.h').write_text('stale')
            with self.assertRaises(ValueError): diagnostic.dynamic_delivery(root,m)

if __name__ == '__main__': unittest.main()
