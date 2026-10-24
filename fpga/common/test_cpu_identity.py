"""Synthetic identity/admission tests only, never hardware or timing evidence."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import board_inputs
import cpu_identity as identity
import freeze
import manifest as gate
import test_manifest


def cpu_record(profile='selected', cpu='a1', runtime='static', clock=None):
    candidate = profile in identity.EXPERIMENTAL
    backend = dict(identity.CANDIDATE_BACKEND, completedCanonicalStoreForwarding=str(profile == 'full-r1-m3').lower()) \
        if candidate else dict(identity.PUBLIC_BACKEND)
    config = dict(backend, fetchTransactionSlots='2' if candidate else '1',
                  lsuEntries='4' if candidate else '2', dataTranslationEntries='16' if candidate else '8',
                  alignedFetchSinglePage='true' if candidate else 'false',
                  translationHitFlow='true' if candidate else 'false',
                  _derived=dict(cache=dict(ways='2', readMshrs='2'), sequence=['β', None, 'true']))
    core = dict(backend, memoryEntries='4' if candidate else '2', robEntries='16', physicalRegs='48',
                renameWidth='2', commitWidth='2', completionWidth='2', pmpEntries='16',
                virtualMemoryLevels='3', compressedInstructions='true')
    if cpu == 'i1':
        config = dict(pipelineProfile='fpga8', tlbEntries='16', withC='true')
        core = dict(config)
    shared = copy.deepcopy(config)
    if cpu == 'a1':
        shared.update(identity.PUBLIC_BACKEND, fetchTransactionSlots='1', lsuEntries='2',
                      dataTranslationEntries='8', alignedFetchSinglePage='false', translationHitFlow='false')
    clock = clock or ('boot50-dynamic' if runtime == 'public-i1-runtime' else
                      'boot50-static' if runtime == 'experimental-a1-runtime' else 'production')
    low = clock in ('boot50-static', 'boot50-dynamic')
    nominal = dict(cpuHz='50000000' if low else '300000000' if cpu == 'i1' else '100000000',
                   fabricHz='50000000' if low else '250000000', timebaseHz='250000000',
                   ddrUiHz='250000000', aonHz='50000000', uartHz='50000000')
    runtime_flag = str(runtime != 'static').lower()
    record = dict(schema=1, cpuFamily=cpu, microarchitectureProfile=profile,
                  qualification=identity.EXPERIMENTAL_QUALIFICATION if candidate else identity.PUBLIC_QUALIFICATION,
                  effectiveConfig=config, effectiveCore=core,
                  memoryProfile='experimental-memory-parallel' if candidate else None,
                  boundary=dict(homeAcquireEntries='2', homeWritebackEntries='2',
                                runtimeMaintenance=runtime_flag, runtimeCancellation=runtime_flag,
                                runtimeInterruptHold=runtime_flag),
                  sharedFabricConfig=shared,
                  clockProfile=clock, nominalClocks=nominal, runtimeMode=runtime)
    record['identitySha256'] = identity.identity_sha256(record)
    return record


def emitted(profile='selected', cpu='a1', runtime='static', clock=None):
    record = cpu_record(profile, cpu, runtime, clock)
    return dict(cpu=cpu, clockProfile=record['clockProfile'], cpuMicroarchitecture=record,
                rtlFormat='SystemVerilog', tlbEntries=16 if cpu == 'i1' or profile in identity.EXPERIMENTAL else 8,
                issueWidth=1 if cpu == 'i1' else 2, sources={'same/Source.scala': 'a' * 64})


class CpuIdentityTests(unittest.TestCase):
    def test_same_sources_different_profiles_have_distinct_complete_identity(self):
        records = [emitted(profile) for profile in ('selected', 'full-r1', 'full-r1-m3')]
        self.assertEqual(records[0]['sources'], records[1]['sources'])
        self.assertEqual(records[1]['sources'], records[2]['sources'])
        hashes = {identity.validate_emission(r)['identitySha256'] for r in records}
        self.assertEqual(len(hashes), 3)
        for expected in records:
            for cached in records:
                a, b = expected['cpuMicroarchitecture'], cached['cpuMicroarchitecture']
                if a == b:
                    self.assertEqual(identity.check_reuse(a, b), a['identitySha256'])
                else:
                    with self.assertRaisesRegex(ValueError, 'cached effective identity'):
                        identity.check_reuse(a, b)

    def test_hash_canonicalization_and_order_preserved_without_mutation(self):
        record = cpu_record('full-r1')
        original = copy.deepcopy(record)
        reversed_keys = dict(reversed(list(record.items())))
        self.assertEqual(identity.identity_sha256(record), identity.identity_sha256(reversed_keys))
        payload = {k: v for k, v in record.items() if k != 'identitySha256'}
        expected = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                            separators=(',', ':')).encode('utf-8')).hexdigest()
        self.assertEqual(record['identitySha256'], expected)
        self.assertIn('β'.encode('utf-8'), identity.canonical(record))
        identity.validate(record, 'a1', 'full-r1')
        self.assertEqual(record, original)
        record['effectiveConfig']['_derived']['sequence'].reverse()
        self.assertNotEqual(identity.identity_sha256(record), expected)

    def test_tampered_config_and_digest_fail_closed(self):
        for section, key, value in (('effectiveConfig', 'unrelatedOption', 'changed'),
                                     ('effectiveCore', 'arbitraryPipelineStage', 'false'),
                                     ('boundary', 'homeAcquireEntries', '3'),
                                     ('sharedFabricConfig', 'ddrOutstanding', '5')):
            with self.subTest(section=section):
                record = cpu_record('full-r1')
                record[section][key] = value
                with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                    identity.validate(record, 'a1', 'full-r1')
        for digest in ('0' * 64, 'A' * 64, None, True):
            record = cpu_record('full-r1'); record['identitySha256'] = digest
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                identity.validate(record, 'a1', 'full-r1')

    def test_rehashed_wrong_selector_fields_are_not_trusted(self):
        for section, key, value in (('effectiveConfig', 'completionTopology', 'legacy'),
                                     ('effectiveCore', 'memoryEntries', '2'),
                                     ('effectiveConfig', 'completedCanonicalStoreForwarding', 'true'),
                                     ('effectiveCore', 'compressedInstructions', 'false'),
                                     ('effectiveCore', 'pmpEntries', '0')):
            record = cpu_record('full-r1'); record[section][key] = value
            record['identitySha256'] = identity.identity_sha256(record)
            with self.subTest(section=section, key=key), self.assertRaisesRegex(ValueError, 'selector'):
                identity.validate(record, 'a1', 'full-r1')
        record = cpu_record('selected')
        record['effectiveConfig']['circularFetchPayload'] = 'true'
        record['identitySha256'] = identity.identity_sha256(record)
        with self.assertRaisesRegex(ValueError, 'selector'):
            identity.validate(record, 'a1', 'selected')

    def test_missing_identity_only_legacy_explicit_public(self):
        for cpu, profile in identity.PUBLIC.items():
            self.assertIsNone(identity.validate(None, cpu, profile))
            self.assertIsNone(identity.validate_emission(dict(cpu=cpu)))
            with self.assertRaises(ValueError): identity.validate(None, cpu, None)
        for profile in identity.EXPERIMENTAL:
            with self.assertRaisesRegex(ValueError, 'missing identity'):
                identity.validate(None, 'a1', profile)
            with self.assertRaises(ValueError): identity.validate_emission(dict(cpu='a1'), profile)
            record = emitted(profile); del record['cpuMicroarchitecture']
            with self.assertRaisesRegex(ValueError, 'candidate claims'):
                identity.validate_emission(record)
        for claim in (dict(microarchitectureProfile='full-r1'), dict(completionTopology='dual-owner'),
                      dict(effectiveCore=dict(circularFetchPayload=True)),
                      dict(runtimeMode='experimental-a1-runtime'), dict(tlbEntries=16)):
            with self.subTest(claim=claim), self.assertRaises(ValueError):
                identity.validate_emission(dict(cpu='a1', **claim))
        self.assertIsNone(identity.check_reuse(None, None))
        for a, b in ((None, cpu_record('full-r1')), (cpu_record('full-r1'), None),
                     (None, cpu_record('selected')), (cpu_record('selected'), None)):
            with self.assertRaises(ValueError): identity.check_reuse(a, b)

    def test_wrong_family_unknown_profile_and_schema_rejected(self):
        for profile in ('full-r1', 'full-r1-m3', 'selected', 'unknown'):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                identity.validate(cpu_record(profile), 'i1', profile)
        self.assertEqual(identity.validate(cpu_record('public-i1', 'i1'), 'i1', 'public-i1')['cpuFamily'], 'i1')
        for profile in ('unknown', 'full-m2', 'public-i1'):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                identity.validate(cpu_record('selected'), 'a1', profile)
        for family, profile in (([], 'selected'), ({}, 'selected'), ('a1', []), ('a1', {})):
            with self.subTest(family=family, profile=profile), self.assertRaises(ValueError):
                identity.validate(None, family, profile)
        with self.assertRaises(ValueError):
            identity.validate_emission(dict(cpu='a1', cpuMicroarchitecture=None))
        for schema in (True, '1', 2):
            record = cpu_record(); record['schema'] = schema
            record['identitySha256'] = identity.identity_sha256(record)
            with self.assertRaises(ValueError): identity.validate(record, 'a1', 'selected')
        for change in ('missing', 'extra', 'numeric', 'boolean'):
            record = cpu_record()
            if change == 'missing': del record['boundary']
            elif change == 'extra': record['extraField'] = 'unexpected'
            else: record['effectiveConfig']['_derived']['other'] = 1 if change == 'numeric' else False
            record['identitySha256'] = identity.identity_sha256(record)
            with self.subTest(change=change), self.assertRaises(ValueError):
                identity.validate(record, 'a1', 'selected')

    def test_emission_selection_geometry_and_clock_crosscheck(self):
        for key, value in (('cpu', 'i1'), ('clockProfile', 'boot50-static'), ('tlbEntries', 8),
                           ('issueWidth', 1), ('microarchitectureProfile', 'selected'),
                           ('effectiveConfig', {}), ('memoryProfile', None)):
            record = emitted('full-r1'); record[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): identity.validate_emission(record)
        with self.assertRaises(ValueError): identity.validate_emission(emitted('full-r1'), 'full-r1-m3')
        for clock in ('performance300-static', 'boot50-dynamic'):
            record = cpu_record('full-r1'); record['clockProfile'] = clock
            record['identitySha256'] = identity.identity_sha256(record)
            with self.assertRaisesRegex(ValueError, 'I1-only'): identity.validate(record, 'a1', 'full-r1')
        valid = cpu_record('full-r1', runtime='experimental-a1-runtime')
        identity.validate(valid, 'a1', 'full-r1')
        for changes in (dict(clockProfile='production'), dict(runtimeMode='dynamic'), dict(cpuFamily='i1')):
            record = dict(valid, **changes); record['identitySha256'] = identity.identity_sha256(record)
            with self.assertRaises(ValueError): identity.validate(record, 'a1', 'full-r1')

    def test_candidate_cannot_change_shared_fabric_or_cache_geometry(self):
        for key, value in (('ddrOutstanding', '9'), ('network', {'memoryCredits': '9'})):
            record = cpu_record('full-r1')
            record['effectiveConfig']['_derived'][key] = value
            record['sharedFabricConfig']['_derived'][key] = 'unchanged'
            record['identitySha256'] = identity.identity_sha256(record)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'shared derived'):
                identity.validate(record, 'a1', 'full-r1')
        record = cpu_record('full-r1')
        record['effectiveConfig']['_derived']['cache']['ways'] = '4'
        record['identitySha256'] = identity.identity_sha256(record)
        with self.assertRaisesRegex(ValueError, 'cache geometry'): identity.validate(record, 'a1', 'full-r1')
        record = cpu_record('full-r1')
        record['effectiveConfig']['_derived']['cache']['independentDemandAdmission'] = 'true'
        record['sharedFabricConfig']['_derived']['cache']['independentDemandAdmission'] = 'false'
        record['identitySha256'] = identity.identity_sha256(record)
        identity.validate(record, 'a1', 'full-r1')

    def test_public_i1_runtime_retains_existing_board_admission_path(self):
        record = emitted('public-i1', 'i1', runtime='public-i1-runtime')
        value = record['cpuMicroarchitecture']
        identity.validate_emission(record)
        config = identity.bind_board_configuration(dict(cpu='i1'), record)
        identity.reject_experimental_board(config, record)
        value['clockProfile'] = 'production'
        value['identitySha256'] = identity.identity_sha256(value)
        with self.assertRaises(ValueError): identity.validate(value, 'i1', 'public-i1')

    def test_nominal_clock_tuple_and_outer_emission_are_bound(self):
        for cpu, clocks in (('a1', ('production', 'boot50-static')),
                             ('i1', ('production', 'boot50-static', 'performance300-static', 'boot50-dynamic'))):
            for clock in clocks:
                with self.subTest(cpu=cpu, clock=clock):
                    runtime = 'public-i1-runtime' if clock == 'boot50-dynamic' else 'static'
                    record = emitted(identity.PUBLIC[cpu], cpu, runtime, clock)
                    value = record['cpuMicroarchitecture']
                    for key, outer in identity.EMISSION_CLOCK_KEYS.items():
                        record[outer] = int(value['nominalClocks'][key])
                    identity.validate_emission(record)
                    for key, outer in identity.EMISSION_CLOCK_KEYS.items():
                        bad = copy.deepcopy(value)
                        bad['nominalClocks'][key] = str(int(bad['nominalClocks'][key]) + 1)
                        bad['identitySha256'] = identity.identity_sha256(bad)
                        with self.assertRaisesRegex(ValueError, 'nominalClocks'):
                            identity.validate(bad, cpu, identity.PUBLIC[cpu])
                        bad = copy.deepcopy(record); bad[outer] += 1
                        with self.assertRaisesRegex(ValueError, 'nominal clock mismatch'):
                            identity.validate_emission(bad)
                    for change in ('missing', 'extra', 'numeric'):
                        bad = copy.deepcopy(value)
                        if change == 'missing': del bad['nominalClocks']['uartHz']
                        elif change == 'extra': bad['nominalClocks']['otherHz'] = '1'
                        else: bad['nominalClocks']['uartHz'] = 50000000
                        bad['identitySha256'] = identity.identity_sha256(bad)
                        with self.assertRaisesRegex(ValueError, 'nominalClocks'):
                            identity.validate(bad, cpu, identity.PUBLIC[cpu])
        static = cpu_record('full-r1')
        low = cpu_record('full-r1', clock='boot50-static')
        self.assertNotEqual(static['identitySha256'], low['identitySha256'])
        with self.assertRaisesRegex(ValueError, 'cached effective identity'):
            identity.check_reuse(static, low)

    def test_candidate_boundary_runtime_flags_must_match_mode(self):
        for profile in identity.EXPERIMENTAL:
            for mode in ('static', 'experimental-a1-runtime'):
                record = cpu_record(profile, runtime=mode)
                identity.validate(record, 'a1', profile)
                for key in ('runtimeMaintenance', 'runtimeCancellation', 'runtimeInterruptHold'):
                    bad = copy.deepcopy(record)
                    bad['boundary'][key] = str(mode == 'static').lower()
                    bad['identitySha256'] = identity.identity_sha256(bad)
                    with self.subTest(profile=profile, mode=mode, key=key), self.assertRaisesRegex(ValueError, 'boundary'):
                        identity.validate(bad, 'a1', profile)
                bad = copy.deepcopy(record)
                for key in ('runtimeMaintenance', 'runtimeCancellation', 'runtimeInterruptHold'):
                    del bad['boundary'][key]
                bad['identitySha256'] = identity.identity_sha256(bad)
                with self.assertRaisesRegex(ValueError, 'boundary'): identity.validate(bad, 'a1', profile)

    def test_board_binding_requires_profile_and_digest_and_format(self):
        legacy = dict(cpu='a1', top='untouched')
        before = gate.digest(legacy)
        self.assertEqual(identity.bind_board_configuration(legacy, dict(cpu='a1')), legacy)
        identity.reject_experimental_board(legacy, dict(cpu='a1'))
        self.assertEqual(gate.digest(legacy), before)
        record = emitted()
        bound = identity.bind_board_configuration(legacy, record)
        self.assertNotEqual(gate.digest(bound), before)
        self.assertNotIn(identity.BOARD_KEYS[0], legacy)
        identity.reject_experimental_board(bound, record)
        with self.assertRaisesRegex(ValueError, 'omits'): identity.reject_experimental_board(legacy, record)
        for key in identity.BOARD_KEYS:
            bad = dict(bound); del bad[key]
            with self.assertRaises(ValueError): identity.validate_board_configuration(bad)
        bad = dict(bound, cpu_microarchitecture_sha256='0' * 64)
        with self.assertRaises(ValueError): identity.bind_board_configuration(bad, record)
        bad = dict(record, rtlFormat='CHIRRTL')
        with self.assertRaisesRegex(ValueError, 'CHIRRTL'): identity.reject_experimental_board(bound, bad)

    def test_board_preflight_does_not_promote_leaf_or_fake_pass(self):
        fixture = test_manifest.ContractTests('test_valid_input_contract_for_both_cpus')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        # The old fixture (no CPU identity anywhere) keeps its historical path.
        gate.preflight(fixture.path)
        original = copy.deepcopy(fixture.m)
        for profile in identity.EXPERIMENTAL:
            fixture.m = copy.deepcopy(original)
            fixture.m['configuration']['cpu'] = 'a1'
            record = emitted(profile)
            fixture.m['configuration'] = identity.bind_board_configuration(fixture.m['configuration'], record)
            fake_pass = dict(status='PASS', scope='common-platform-affected-short',
                             profile_sha256=gate.configuration(fixture.m['configuration']),
                             physical_qualified=False, cpuLeafStatus='PASS')
            fixture.write_json('evidence/functional.json', fake_pass)
            fixture.refresh()
            with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, identity.EXPERIMENTAL_QUALIFICATION):
                gate.preflight(fixture.path)
        fixture.m = copy.deepcopy(original)
        fixture.m['configuration']['cpu'] = 'a1'
        fixture.m['roles']['emission_profile'] = 'rtl/emission.json'
        fixture.write_json('rtl/emission.json', emitted('full-r1'))
        fixture.refresh()
        with self.assertRaises(ValueError): gate.preflight(fixture.path)

    def test_freeze_rejects_candidate_before_writing_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = emitted('full-r1-m3')
            record['artifacts'] = {'/synthetic/CommonMachinePlatform.sv': '0' * 64}
            args = argparse.Namespace(root=root, emission='rtl/emission.json', rom='rom.bin', coe='rom.coe',
                                      firmware_contract='firmware.json', functional_receipt='functional.json',
                                      mig='mig.xci', threads=8)
            names = set(board_inputs.PUBLIC_INPUTS + board_inputs.BOARD_RTL + board_inputs.SIM_RTL)
            names.update(('rtl/emission.json', 'rtl/CommonMachinePlatform.sv', 'rtl/TriSpeedRgmiiTx.sv',
                          'rom.bin', 'rom.coe', 'firmware.json', 'functional.json', 'mig.xci'))
            for name in names:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('SYNTHETIC')
            (root / args.emission).write_text(json.dumps(record))
            (root / args.functional_receipt).write_text(json.dumps(dict(status='PASS', cpuLeafStatus='PASS')))
            with self.assertRaisesRegex(ValueError, identity.EXPERIMENTAL_QUALIFICATION): freeze.freeze(args)
            self.assertFalse((root / 'manifest.json').exists())
            self.assertFalse((root / 'board-generated').exists())


if __name__ == '__main__':
    unittest.main()
