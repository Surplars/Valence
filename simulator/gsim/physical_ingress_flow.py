#!/usr/bin/env python3
"""Independent actual-RTL off/on proof for physicalLoadIngressFlow.

Both adapter fixtures enable identity flow, registered memory/translation/checked
boundaries and next-line prefetch. Only physicalLoadIngressFlow changes. The
external DTLB responder is deliberately not a real page walker. Whole-CPU current
access PMP, ROB cancellation and full-board timing require separate composition
proofs. Every latency/count below comes from GSIM handshakes, not future-latency
subtraction. Generation and C++ translation units run serially.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

import run as common


TOP = 'PhysicalIngressFlowGsim'
HARNESS = common.HERE / 'harness/physical_ingress_flow.cpp'
WRAPPER = common.ROOT / 'src/test/scala/ooo/PhysicalIngressFlowGsim.scala'
NEGATIVES = {
    '--inject-data': 'independent response data/fault/order mismatch',
    '--inject-context': 'independent captured VM context mismatch',
    '--inject-prefetch': 'independent captured prefetch permission mismatch',
    '--inject-order': 'independent physical request/order mismatch',
}
ORIGINAL_CASES = {
    'bare_single_l1', 'bare_single_l5', 'u_bare', 's_bare', 'm_satp_bypass',
    'mprv_effective_s', 'bare_dependent64', 'vm_immediate', 'vm_delayed', 'mixed_held',
    'identity_spill', 'vm_pmp_allow_snapshot', 'vm_pmp_deny_snapshot',
    'vm_locked_machine_pmp', 'vm_atomic_outside', 'reset_recovery',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    files = list((common.ROOT / 'src/main').rglob('*.scala'))
    files += list((common.ROOT / 'third_party/berkeley-hardfloat').rglob('*.scala'))
    files += [WRAPPER, HARNESS, Path(__file__), common.HERE / 'harness/translation_context.cpp',
              common.ROOT / 'src/test/scala/ooo/PhysicalLoadIngressFlowSpec.scala',
              common.HERE / 'run.py', common.HERE / 'config/toolchain.json',
              common.ROOT / 'build.mill', common.ROOT / '.mill-version', common.ROOT / '.mill-jvm-opts']
    return {str(path.relative_to(common.ROOT)): digest(path) for path in sorted(set(files))}


def parse_cases(log):
    cases = {}
    for line in log.splitlines():
        if line.startswith('PHYSICAL_INGRESS_CASE '):
            fields = dict(item.split('=', 1) for item in line.split()[1:])
            name = fields.pop('name')
            assert name not in cases, ('duplicate case', name)
            cases[name] = {key: int(value) for key, value in fields.items()}
    assert ORIGINAL_CASES <= cases.keys(), 'retained identity/context cases missing'
    assert len(cases) == 40, ('case coverage drift', len(cases))
    return cases


def reuse_model(priors, key, target):
    for prior in priors:
        root = Path(prior)
        receipt_path = root / 'receipt.json'
        old = root / key
        if not receipt_path.exists():
            continue
        recorded = json.loads(receipt_path.read_text()).get('models', {}).get(key, {})
        if not recorded or digest(target / (TOP + '.fir')) != recorded.get('chirrtl_sha256'):
            continue
        manifest = recorded.get('generated_file_sha256', {})
        objects = recorded.get('model_object_sha256', {})
        if not manifest or not objects:
            continue
        assert digest(old / (TOP + '.fir')) == recorded['chirrtl_sha256'], 'reuse FIR drift'
        for name, expected in {**manifest, **objects}.items():
            assert digest(old / name) == expected, ('reuse artifact drift', old, name)
            shutil.copy2(old / name, target / name)
        return {'source': str(old), 'receipt_sha256': digest(receipt_path), 'chirrtl_equality': 'byte-exact'}
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--reuse', action='append', default=[], help='Reuse only exact FIR/hash-matched model objects')
    parser.add_argument('--baseline-ref', help='Optional real-RTL shadow build of an exact pre-change git baseline')
    parser.add_argument('--configuration-from', help='Reuse a source-matched prior successful configuration log')
    args = parser.parse_args()
    if not re.fullmatch('[A-Za-z0-9_-]+', args.tag):
        parser.error('tag must use letters, digits, underscores or hyphens')
    output = common.BUILD / ('physical-ingress-flow-' + args.tag)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        'status': 'RUNNING',
        'git_base': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=common.ROOT, text=True).strip(),
        'source_sha256': sources(), 'models': {},
        'scope': 'adapter-only actual GSIM off/on; no whole-CPU, real walker, current-access core PMP, ROB cancellation, synthesis or board claim',
        'policy': 'identity flow, registered memory/translation/checked boundaries and dataNextLinePrefetch are true in both fixtures; only physicalLoadIngressFlow changes',
        'upstream_contract': 'ordinary physical requests represent the registered LSU output after core current-access authorization; this fixture independently checks next-line PMP at checked capture',
        'cancelled_field': 'retained identity-driver marker requires accepted responses to drain; it does not model ROB cancellation',
        'translation_model': 'external ordered immediate/delayed DTLB responder, not a real SvTranslationService or page walker',
    }

    def save():
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

    for name in receipt['source_sha256']:
        frozen = output / 'source' / name
        frozen.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(common.ROOT / name, frozen)
    (output / 'freeze.json').write_text(json.dumps(receipt, indent=2) + '\n')
    try:
        os.environ.setdefault('GSIM_BUILD_JOBS', '1')
        gsim, cxx = common.setup(False)
        if args.configuration_from:
            prior = Path(args.configuration_from)
            freeze = json.loads((prior / 'freeze.json').read_text())['source_sha256']
            selected = [name for name in receipt['source_sha256']
                        if name.startswith('src/main/') or name.endswith('PhysicalLoadIngressFlowSpec.scala')]
            assert all(freeze.get(name) == receipt['source_sha256'][name] for name in selected), 'configuration source drift'
            log = (prior / 'configuration.log').read_text()
            assert 'Running Test Class ooo.PhysicalLoadIngressFlowSpec' in log and 'All tests passed.' in log and 'SUCCESS' in log
            shutil.copy2(prior / 'configuration.log', output / 'configuration.log')
            receipt['configuration'] = {'status': 'PASS', 'source': str(prior), 'log_sha256': digest(prior / 'configuration.log')}
        else:
            common.run(['mill', '-i', 'IonSoC.test.testOnly', 'ooo.PhysicalLoadIngressFlowSpec'],
                       log=output / 'configuration.log')
            receipt['configuration'] = 'PASS'
        env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}

        def build_and_run(key, flag, root=common.ROOT):
            target = output / key
            target.mkdir()
            common.run(['mill', '-i', 'IonSoC.test.runMain', 'ooo.' + TOP + 'Main', target, str(flag)],
                       cwd=root, log=target / 'elaborate.log')
            reused = reuse_model(args.reuse, key, target)
            if not reused:
                common.run([gsim, '--threads=1', f'--dir={target}', target / (TOP + '.fir')],
                           log=target / 'generate.log')
            flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                     '-fno-sanitize-recover=all', f'-I{target}']
            objects = []
            for source in sorted(target.glob(TOP + '[0-9]*.cpp')):
                obj = source.with_suffix('.o')
                if not obj.exists():
                    common.run([cxx, *flags, '-c', source, '-o', obj], log=obj.with_suffix('.compile.log'))
                objects.append(obj)
            assert objects, 'generated model objects missing'
            model = receipt['models'][key] = {
                'chirrtl_sha256': digest(target / (TOP + '.fir')), 'reused_model': reused,
                'generated_file_sha256': {p.name: digest(p) for p in sorted(target.glob(TOP + '*.cpp')) + [target / (TOP + '.h')]},
                'model_object_sha256': {p.name: digest(p) for p in objects},
            }
            save()
            common.run([cxx, *flags, f'-DPHYSICAL_INGRESS_FLOW={flag}', HARNESS, *objects, '-ldl', '-o', target / 'run'],
                       log=target / 'compile.log')
            common.run([target / 'run'], log=target / 'test.log', timeout=120, env=env)
            log = (target / 'test.log').read_text()
            print(log, end='', flush=True)
            assert f'PHYSICAL_INGRESS_FLOW_PASS flag={flag}' in log, 'positive PASS anchor missing'
            model.update({'positive': 'PASS', 'cases': parse_cases(log), 'binary_sha256': digest(target / 'run')})
            model['negative_controls'] = {}
            for mutation, anchor in NEGATIVES.items():
                result = subprocess.run([target / 'run', mutation], capture_output=True, text=True, timeout=120, env=env)
                text = result.stdout + result.stderr
                (target / (mutation[2:] + '.log')).write_text(text)
                assert result.returncode == 1 and anchor in text, (key, mutation, 'negative not rejected')
                model['negative_controls'][mutation] = 'REJECTED'
            # Compile the original independent oracle unchanged against this same generated model.
            (target / 'TranslationContextGsim.h').write_text(
                '#include "PhysicalIngressFlowGsim.h"\nusing STranslationContextGsim = SPhysicalIngressFlowGsim;\n')
            common.run([cxx, *flags, '-DPROGRAMMABLE_PMP=1', common.HERE / 'harness/translation_context.cpp',
                        *objects, '-ldl', '-o', target / 'context-run'], log=target / 'context-compile.log')
            common.run([target / 'context-run'], log=target / 'context.log', timeout=120, env=env)
            context = (target / 'context.log').read_text()
            assert 'TRANSLATION_CONTEXT_PASS checked=192 epochs=32 contexts=64' in context
            result = subprocess.run([target / 'context-run', '--inject-mismatch'],
                                    capture_output=True, text=True, timeout=120, env=env)
            negative = result.stdout + result.stderr
            (target / 'context-negative.log').write_text(negative)
            assert result.returncode == 1 and 'VM context independent oracle mismatch' in negative
            model['retained_context_oracle'] = {'positive': context.strip(), 'negative': 'REJECTED',
                                                'source_sha256': digest(common.HERE / 'harness/translation_context.cpp')}
            assert sources() == receipt['source_sha256'], 'qualification source drift'
            save()
            return model['cases']

        off = build_and_run('off', 0)
        on = build_and_run('on', 1)
        assert off.keys() == on.keys(), 'paired case set drift'
        semantic = ('accepted', 'returned', 'physical', 'translations', 'physical_trace', 'response_trace',
                    'cancelled', 'permission_allowed', 'permission_denied', 'faults')
        for case in off:
            for field in semantic:
                assert off[case][field] == on[case][field], (case, field, off[case], on[case])
        faster = ('bare_single_l1', 'bare_single_l5', 'u_bare', 's_bare', 'm_satp_bypass',
                  'physical_response_error', 'pmp_current_allowed_next_denied_s',
                  'page_last_line_no_prefetch', 'ram_last_line_no_prefetch', 'reset_recovery')
        for case in faster:
            assert off[case]['min_latency'] == 2 and on[case]['min_latency'] == 1, (case, 'registered latency not 2 -> 1')
            assert off[case]['response_latency'] == on[case]['response_latency'] + 1, (case, 'response latency delta')
            assert off[case]['shortcuts'] == 0 and on[case]['shortcuts'] == 1
        assert off['bare_dependent64']['cycles'] == on['bare_dependent64']['cycles'] + 64
        for case in ('vm_immediate', 'vm_delayed', 'mprv_effective_s', 'vm_pmp_allow_snapshot',
                     'vm_pmp_deny_snapshot', 'vm_locked_machine_pmp', 'vm_atomic_outside',
                     'virtual_page_fault', 'virtual_pbmt_no_prefetch',
                     *(name for name in off if name.startswith('fallback_'))):
            assert off[case] == on[case], ('fallback or VM timing/event drift', case, off[case], on[case])
        for side in (off, on):
            assert side['physical_shapes_stream48']['physical_span'] == 47
            for field in ('checked_full_pops', 'checked_turnovers', 'full_pop_then_push',
                          'stalls', 'physical_holds', 'response_holds'):
                assert side['checked_spill_full_turnover'][field] > 0, ('pressure coverage', field)
            assert side['older_translated_priority']['older_translated_ingress'] > 0
            assert side['older_walker_priority']['walker_blocked_ingress'] > 0
        assert on['checked_spill_full_turnover']['eligible_spills'] > 0
        receipt['paired_semantic_equivalence'] = 'PASS for all 40 directed cases'
        receipt['measured_timing'] = {
            'unit': 'actual GSIM cycles', 'off_request_latency': off['bare_single_l1']['min_latency'],
            'on_request_latency': on['bare_single_l1']['min_latency'],
            'off_dependent64_cycles': off['bare_dependent64']['cycles'],
            'on_dependent64_cycles': on['bare_dependent64']['cycles'],
            'off_48_issue_span': off['physical_shapes_stream48']['physical_span'],
            'on_48_issue_span': on['physical_shapes_stream48']['physical_span'],
        }
        if args.baseline_ref:
            revision = subprocess.check_output(['git', 'rev-parse', args.baseline_ref], cwd=common.ROOT, text=True).strip()
            archive = output / 'baseline-source.tar'
            with archive.open('wb') as stream:
                subprocess.run(['git', 'archive', revision], cwd=common.ROOT, stdout=stream, check=True)
            root = output / 'baseline-source'
            root.mkdir()
            with tarfile.open(archive) as stream:
                stream.extractall(root, filter='data')
            original = WRAPPER.read_text()
            shadow = original.replace('physicalLoadIngressFlow = enabled, ', '').replace(
                'BoringUtils.bore(adapter.physicalIngressPass)', 'false.B')
            assert shadow != original and 'physicalLoadIngressFlow =' not in shadow
            wrapper = root / WRAPPER.relative_to(common.ROOT)
            wrapper.write_text(shadow)
            receipt['baseline_shadow'] = {
                'revision': revision, 'archive_sha256': digest(archive), 'wrapper_sha256': digest(wrapper),
                'wrapper_delta': 'Remove unavailable new flag and observe constant false shortcut; all independent stimuli/oracles unchanged.',
            }
            baseline = build_and_run('baseline', 0, root)
            assert baseline == off, 'baseline exact case/cycle/event/trace drift'
            receipt['baseline_shadow']['case_cycle_trace_equality'] = 'PASS for all 40 directed cases'
        assert sources() == receipt['source_sha256'], 'qualification source changed'
        receipt['status'] = 'PASS'
    except BaseException as error:
        receipt['status'] = 'FAIL'
        receipt['error'] = str(error)
        raise
    finally:
        save()


if __name__ == '__main__':
    main()
