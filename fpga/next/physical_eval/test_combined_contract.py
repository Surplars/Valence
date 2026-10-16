"""Synthetic mocks only: input rejection tests, never real native/physical evidence."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from combined_stage_receipt import check_synthesis, seal
from combined_contract import validate_ip_asset
from combined_project_inputs import verify as verify_project_inputs
from combined_contract import (FLAGS, IP_FILES, ROM_FILES, info, read, sha, source_closure,
                               validate_ip, validate_native, validate_rom)

HERE = Path(__file__).resolve().parent


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True, indent=2)+'\n')


class MockContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mock-combined-contract-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = self.root/'native'
        self.native.mkdir()
        self.closure = dict(schema='MOCK_SOURCE_NOT_REAL_EXPORT', commit='a'*40)
        self.toolchain = dict(mock=True)
        core = dict(memoryEntries=4, **{f'core{i}': i for i in range(177)})
        profile = dict(independentDemandAdmission=True, memoryScheduleOverlap=True,
                       **{f'profile{i}': i for i in range(93)})
        ports = [dict(name='mock'+str(i), width=1, direction='Input') for i in range(76)]
        self.actual = dict(schema='combined-bandwidth-native-actual-v1', featureFlags=FLAGS.copy(),
            counts=dict(residentSelectors=1, sharedPmpHelpers=2, nonBlockingCaches=1, nativeMacs=1,
                        bscanTransports=1, standaloneTaps=0), core=core, profile=profile, coreFields=178,
            profileFields=95, fieldOrder=dict(core=list(core), profile=list(profile)),
            geometry=dict(cacheLines=512, cacheWays=2, proofRows=3, earlyLoadCredits=2, lsuOwners=4),
            nativeBoundaries=dict(rawHandoffPresent=True, ramLoaderPresent=True, bscanChain=2,
                                  nativeMacPhysicalGenericsApplied=False),
            clockHz=dict(cpu=100000000, aon=50000000, uart=50000000, ddrUi=250000000),
            topPorts=ports, qualificationInherited=False, physicalQualification=False)
        (self.native/'FpgaNextSocTop.sv').write_text('module FpgaNextSocTop('+','.join('input '+p['name'] for p in ports)+'); endmodule\n')
        (self.native/'MockResource.sv').write_text('module MockResource(); endmodule\n')
        (self.native/'filelist.f').write_text('FpgaNextSocTop.sv\nMockResource.sv\n')
        put(self.native/'actual-combined-native.json', self.actual)
        put(self.native/'rtl-inventory.json', dict(schema='combined-bandwidth-rtl-inventory-v1',
            files={name: info(self.native/name) for name in ('FpgaNextSocTop.sv', 'MockResource.sv', 'filelist.f')}))
        self.entry = dict(schema='combined-bandwidth-experimental-native-entry-v1',
            identity='combined-bandwidth-native-experimental', mode='native', coreFields=178,
            profileFields=95, nativeTopPorts=76, physicalQualification=False, qualificationInherited=False,
            nativeMacPhysicalGenericsApplied=False)
        self.reseal_mock()

    def reseal_mock(self):
        self.entry.update(actualAuditSha256=sha(self.native/'actual-combined-native.json'),
                          rtlInventorySha256=sha(self.native/'rtl-inventory.json'))
        put(self.native/'native-entry.json', self.entry)
        artifacts = {p.name: info(p) for p in self.native.iterdir() if p.name != 'export-provenance.json'}
        put(self.native/'export-provenance.json', dict(schema='combined-bandwidth-export-provenance-v1',
            status='PASS_FRESH_NATIVE_EXPORT_ONLY', sourceClosure=self.closure, toolchain=self.toolchain,
            artifacts=artifacts))

    def validate(self):
        return validate_native(self.native, self.closure, self.toolchain)

    def test_mock_valid_variable_inventory_not_legacy_count(self):
        self.assertEqual(len(self.validate()['inventory']['files']), 3)

    def test_each_wrong_feature_rejected_even_resealed(self):
        for key in FLAGS:
            with self.subTest(key=key):
                actual = copy.deepcopy(self.actual)
                actual['featureFlags'][key] = not FLAGS[key]
                put(self.native/'actual-combined-native.json', actual)
                self.reseal_mock()
                with self.assertRaisesRegex(ValueError, 'feature flags'):
                    self.validate()

    def test_numeric_boolean_rejected(self):
        actual = copy.deepcopy(self.actual)
        actual['featureFlags']['rankResidentPriority'] = 1
        put(self.native/'actual-combined-native.json', actual)
        self.reseal_mock()
        with self.assertRaises(ValueError): self.validate()

    def test_string_inventory_size_rejected(self):
        inventory = read(self.native/'rtl-inventory.json')
        inventory['files']['FpgaNextSocTop.sv']['bytes'] = str(inventory['files']['FpgaNextSocTop.sv']['bytes'])
        put(self.native/'rtl-inventory.json', inventory)
        self.reseal_mock()
        with self.assertRaisesRegex(ValueError, 'bytes/hash mismatch'):
            self.validate()

    def test_stale_audit_receipt(self):
        with (self.native/'actual-combined-native.json').open('a') as f: f.write(' ')
        with self.assertRaisesRegex(ValueError, 'Stale actual'): self.validate()

    def test_missing_rtl(self):
        (self.native/'MockResource.sv').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing'): self.validate()

    def test_extra_rtl(self):
        (self.native/'extra.sv').write_text('module extra; endmodule')
        with self.assertRaisesRegex(ValueError, 'extra RTL'): self.validate()

    def test_extra_unsealed_resource(self):
        (self.native/'extra.mem').write_text('0')
        with self.assertRaisesRegex(ValueError, 'extra native'): self.validate()

    def test_changed_source_or_tools(self):
        self.closure['commit'] = 'b'*40
        with self.assertRaisesRegex(ValueError, 'Changed source'): self.validate()
        self.closure['commit'] = 'a'*40
        self.toolchain['mock'] = False
        with self.assertRaisesRegex(ValueError, 'toolchain'): self.validate()

    def test_wrong_top_width_resealed(self):
        actual = copy.deepcopy(self.actual)
        actual['topPorts'][0]['width'] = 2
        put(self.native/'actual-combined-native.json', actual)
        self.reseal_mock()
        with self.assertRaisesRegex(ValueError, 'top-port'): self.validate()

    def test_changed_source_checkout_rejected(self):
        source = self.root/'source'
        source.mkdir()
        def git(*args):
            return subprocess.run(['git', '-C', str(source), *args], capture_output=True, check=True)
        git('init', '-q')
        (source/'build.mill').write_text('// MOCK\n')
        (source/'.mill-version').write_text('MOCK\n')
        git('add', '.')
        git('-c', 'user.name=Mock', '-c', 'user.email=mock@example.invalid', 'commit', '-qm', 'mock fixture')
        self.assertIn('build.mill', source_closure(source)['files'])
        (source/'build.mill').write_text('// changed\n')
        with self.assertRaisesRegex(ValueError, 'clean'): source_closure(source)

    def rom_fixture(self):
        rom = self.root/'rom'; rom.mkdir()
        raw = bytes(range(64)); padded = raw+bytes(131072-len(raw))
        words = [int.from_bytes(padded[i:i+4], 'little') for i in range(0, len(padded), 4)]
        (rom/'bootrom.bin').write_bytes(raw)
        (rom/'bootrom.coe').write_text('memory_initialization_radix=16;\nmemory_initialization_vector=\n'+','.join(f'{x:08x}' for x in words)+';\n')
        for n, bank in enumerate(('even', 'odd')):
            (rom/f'bootrom.{bank}.hex').write_text('\n'.join(f'{x:08x}' for x in words[n::2]))
        put(rom/'bootrom-contract.json', dict(bootrom_sha256=sha(rom/'bootrom.bin'), cpu_hz=100000000, timebase_hz=100000000))
        (rom/'bootrom.map').write_text('MOCK LINK MAP, NOT REAL FIRMWARE\n')
        return rom, padded

    def test_rom_all_six_and_bank_equality(self):
        rom, padded = self.rom_fixture()
        manifest = {name: info(rom/name) for name in ROM_FILES}
        args = (rom, manifest, sha(rom/'bootrom.bin'), hashlib.sha256(padded).hexdigest())
        self.assertEqual(validate_rom(*args), padded)
        (rom/'bootrom.odd.hex').write_text('00000000\n')
        manifest['bootrom.odd.hex'] = info(rom/'bootrom.odd.hex')
        with self.assertRaisesRegex(ValueError, 'odd bank'): validate_rom(*args)
        del manifest['bootrom.map']
        with self.assertRaisesRegex(ValueError, 'six'): validate_rom(*args)

    def test_missing_external_ip_and_historical_checkpoint_rejected(self):
        with self.assertRaisesRegex(ValueError, 'four XCI'): validate_ip(self.root, {}, bytes(131072), self.root/'run')
        inputs = {name: {} for name in IP_FILES}
        inputs['ip-build/historical-soc.dcp'] = {}
        with self.assertRaisesRegex(ValueError, 'Historical checkpoint'):
            validate_ip(self.root, inputs, bytes(131072), self.root/'run')

    def test_no_inputs_cli_fails_closed(self):
        result = subprocess.run([sys.executable, '-B', str(HERE/'prepare_combined.py')], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'required', result.stderr)


class MockStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mock-stage-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root/'synthesis'; self.stage.mkdir()
        (self.stage/'post_synth_unconstrained.dcp').write_text('MOCK CHECKPOINT A')
        (self.stage/'stage-result.txt').write_text('MOCK COMPLETE MARKER')
        self.identity = dict(mock=True, sourceCommit='a'*40)
        seal(self.root, 'synthesis', self.identity)

    def test_matching_mock_stage(self):
        self.assertEqual(check_synthesis(self.root, self.identity)['stage'], 'synthesis')

    def test_swapped_checkpoint_rejected(self):
        (self.stage/'post_synth_unconstrained.dcp').write_text('MOCK HISTORICAL CHECKPOINT')
        with self.assertRaisesRegex(ValueError, 'Swapped'): check_synthesis(self.root, self.identity)

    def test_stale_pass_source_rejected(self):
        with self.assertRaisesRegex(ValueError, 'inputs/source/toolchain'):
            check_synthesis(self.root, dict(mock=True, sourceCommit='b'*40))

    def test_failure_after_pass_rejected(self):
        (self.stage/'failure.txt').write_text('MOCK FAILURE')
        with self.assertRaisesRegex(ValueError, 'Failed synthesis'): check_synthesis(self.root, self.identity)

    def test_existing_stage_receipt_never_overwritten(self):
        with self.assertRaises(FileExistsError): seal(self.root, 'synthesis', self.identity)

    def test_discovered_external_and_unsealed_files_rejected(self):
        put(self.root/'package-seal.json', dict(files={'synthesis/stage-result.txt': info(self.stage/'stage-result.txt')}))
        listing = self.root/'listing.txt'
        listing.write_text(str(self.stage/'post_synth_unconstrained.dcp'))
        with self.assertRaisesRegex(ValueError, 'Unsealed'): verify_project_inputs(self.root, listing, self.root/'vendor')
        outside = Path(self.temp.name).parent/'MOCK-no-such-file'
        listing.write_text(str(outside))
        with self.assertRaises(FileNotFoundError): verify_project_inputs(self.root, listing, self.root/'vendor')


class MockIpOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mock-IP-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.xci = IP_FILES[1]
        self.asset = 'ip-build/board_ip.gen/sources_1/ip/clk_wiz_ddr/clk_wiz_ddr.dcp'
        self.inventory = {self.xci: dict(sha256='a'*64, bytes=1)}
        self.ownership = {self.asset: dict(xci=self.xci, xciSha256='a'*64,
            top='clk_wiz_ddr', part='xczu15eg-ffvb1156-2-i')}
        self.make_dcp('clk_wiz_ddr')

    def make_dcp(self, top):
        path = self.root/self.asset; path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('dcp.xml', '<Checkpoint><Top Name="'+top+'"/><Part Name="xczu15eg-ffvb1156-2-i"/><OutOfContext Name="1"/></Checkpoint>')

    def test_matching_mock_ip_metadata(self):
        validate_ip_asset(self.root, self.asset, self.inventory, self.ownership)

    def test_disguised_soc_checkpoint(self):
        self.make_dcp('soc_top_fpga_next_ddr')
        with self.assertRaisesRegex(ValueError, 'Disguised SoC'):
            validate_ip_asset(self.root, self.asset, self.inventory, self.ownership)

    def test_wrong_ip_directory(self):
        wrong = self.asset.replace('/clk_wiz_ddr/', '/wrong_ip/')
        with self.assertRaisesRegex(ValueError, 'Wrong IP asset directory'):
            validate_ip_asset(self.root, wrong, self.inventory, {wrong:self.ownership[self.asset]})

    def test_missing_hash_and_ownership(self):
        with self.assertRaisesRegex(ValueError, 'ownership'):
            validate_ip_asset(self.root, self.asset, self.inventory, {})
        self.ownership[self.asset].pop('xciSha256')
        with self.assertRaisesRegex(ValueError, 'binding'):
            validate_ip_asset(self.root, self.asset, self.inventory, self.ownership)


if __name__ == '__main__':
    unittest.main()
