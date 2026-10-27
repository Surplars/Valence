#!/usr/bin/env python3
"""One tiny elastic D/T/R GSIM fixture; disposable conflicting-D peeks cannot publish proof."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
import run as common
import m2_r1_compile_gate as compile_gate

INPUTS = (
    'src/main/scala/core/ooo/lsu/ElasticVirtualRamLoadPreparation.scala',
    'src/main/scala/core/ooo/lsu/VirtualRamLoadPrecheck.scala',
    'src/main/scala/core/ooo/lsu/AlignedMemoryDisjoint.scala',
    'src/main/scala/core/ooo/lsu/SpeculativeRamRange.scala',
    'src/main/scala/core/ooo/mmu/PhysicalMemoryProtection.scala',
    'src/main/scala/core/ooo/config/OooParams.scala',
    'src/main/scala/core/ooo/platform/BoardSocTop.scala',
    'src/main/scala/core/ooo/interfaces/BackendTypes.scala',
    'src/main/scala/platform/CommonA1RebuildProfile.scala',
    'src/test/scala/ooo/ElasticLoadProofGsim.scala',
    'simulator/gsim/harness/elastic_load_proof.cpp',
    'simulator/gsim/elastic_load_proof.py',
    'simulator/gsim/run.py',
    'simulator/gsim/m2_r1_compile_gate.py',
    'simulator/gsim/config/toolchain.json',
    'build.mill',
)
PROPOSAL = 'build/gsim/elastic-load-proof-proposal-20261024-r2/proposal.md'
PROPOSAL_SHA = '47caaf6adc8694235bfc4732da8ad96c160bc906ca3962c724a48bbd564a5b2c'
NEGATIVES = {
    'owner': ('ELASTIC_LOAD_PROOF_INJECTION_REACHED kind=owner mutation=sampled_high_tag',
              'independent full owner key mismatch slot=1'),
    'permission': ('ELASTIC_LOAD_PROOF_INJECTION_REACHED kind=permission mutation=sampled_allowed',
                   'independent byte permission mismatch'),
    'credit': ('ELASTIC_LOAD_PROOF_INJECTION_REACHED kind=credit mutation=borrow_same_edge_issue',
               'independent raw pre-edge R credit mismatch'),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    # Bind transitive Scala dependencies as well as the mandatory real-header
    # gate. A successful old host or generated model is never substituted.
    names = set(INPUTS)
    names.update(str(p.relative_to(common.ROOT)) for p in (common.ROOT / 'src/main/scala').rglob('*.scala'))
    return {name: sha(common.ROOT / name) for name in sorted(names)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--build-run', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        parser.error('tag must be a fresh filesystem-safe evidence label')
    if sha(common.ROOT / PROPOSAL) != PROPOSAL_SHA:
        raise RuntimeError('approved r2 contract bytes changed')
    before = inputs()
    report = {
        'status': 'PREFLIGHT_ONLY', 'inputs': before, 'proposal': PROPOSAL, 'proposal_sha256': PROPOSAL_SHA,
        'contract_amendment': 'registered D may issue one side-effect-free hit-only peek despite a live lookahead key conflict; full-token next-state cancellation must discard it before any valid T/R publication',
        'amendment_scope': 'remove only live-lookahead conflict from registered-D query selection; no new state, capacity, same-edge credit or relaxation of current-key/proof checks',
        'scope': 'tiny real production module, injected raw hit-only lookup response and sixteen raw PMP entries',
        'owner_oracle': 'independent finite ROB tickets: pending, ordinary class, full generation, size, saved VA and epoch',
        'permission_oracle': 'independent half-open PMP regions and exhaustive access-byte containment',
        'logical_state_bits_current_shape': {'D': 167, 'T': 233, 'R': 232, 'total': 632, 'added': 167},
        'state_count_shape': {'rob_entries': 16, 'tag_bits': 64},
        'minimum_latency': {'accepted_current_query': 2, 'descriptor_capture': 3},
        'ideal_continuous_distinct_owner_II_target': 2,
        'capacity': {'descriptor': 1, 'translated': 1, 'prepared': 1, 'peek_ports': 1},
        'same_edge_issue_to_result_credit': False, 'same_edge_descriptor_transfer_refill': False,
        'negative_scope': 'three minimal sampled-observation injections rejected by the independent oracle, not RTL mutants',
        'backend_connected': False,
        'actual_CPU_throughput': 'UNVERIFIED by this standalone model; separate no-force matched CPU experiment required',
        'physical_timing_and_board': 'UNVERIFIED',
    }
    if not args.build_run:
        print(json.dumps(report))
        return
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    report['status'] = 'RUNNING'
    try:
        gsim = common.SOURCE / 'build/gsim/gsim'
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=common.SOURCE, text=True).strip()
        changes = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'],
                                         cwd=common.SOURCE, text=True)
        if revision != common.LOCK['revision'] or changes or not gsim.is_file():
            raise RuntimeError('clean prebuilt pinned GSIM required; this runner does not install tools')
        cxx, compiler = common.compiler()
        cxx = shutil.which(cxx)
        if not cxx:
            raise RuntimeError('selected compiler executable disappeared before the real-header gate')
        report.update(compiler=compiler, gsim_revision=revision, gsim_sha256=sha(gsim))
        compile_gate.install()
        model = common.test(gsim, cxx, args.tag + '/model', 'ooo.ElasticLoadProofGsimMain',
                            'ElasticLoadProofGsim', 'elastic_load_proof.cpp', defines={})
        normal = (model / 'test.log').read_text()
        if 'ELASTIC_LOAD_PROOF_PASS ' not in normal or \
                'ELASTIC_LOAD_PROOF_IDEAL issues=48 unique_queries=48 steady_issue_interval=2 ' not in normal:
            raise RuntimeError('positive independent permission/ownership/ideal-supply markers absent')
        report['positive'] = normal
        report['negative'] = {}
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        for kind, (marker, rejection) in NEGATIVES.items():
            flag = '--inject-' + kind
            result = subprocess.run([str(model / 'run'), flag], capture_output=True, text=True,
                                    timeout=30, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
            log = result.stdout + result.stderr
            path = out / (kind + '-negative.log')
            path.write_text(log)
            if result.returncode != 1 or log.count(marker) != 1 or rejection not in log or \
                    'ELASTIC_LOAD_PROOF_FAIL ' not in log or 'ELASTIC_LOAD_PROOF_PASS ' in log or \
                    'AddressSanitizer' in log or 'runtime error:' in log or 'Assertion failed:' in log:
                raise RuntimeError('negative missed its exact independent-oracle rejection: ' + flag)
            report['negative'][kind] = {'status': 'REJECTED', 'returncode': result.returncode,
                                       'marker': marker, 'rejection': rejection,
                                       'independent_oracle': True, 'log_sha256': sha(path)}
        gate_receipt = model / 'run-compile-receipt.json'
        gate = json.loads(gate_receipt.read_text())
        if not gate.get('syntax_pass') or not gate.get('headers') or not gate.get('objects'):
            raise RuntimeError('mandatory real generated-header syntax gate was not recorded')
        report['real_header_gate_sha256'] = sha(gate_receipt)
        report['status'] = 'PASS_STANDALONE_ELASTIC_LOAD_PROOF'
    except Exception as error:
        report.update(status='FAIL', failure=str(error))
        raise
    finally:
        report['inputs_unchanged'] = inputs() == before
        report['proposal_unchanged'] = sha(common.ROOT / PROPOSAL) == PROPOSAL_SHA
        if not report['inputs_unchanged'] or not report['proposal_unchanged']:
            report['status'] = 'FAIL_INPUT_DRIFT'
        report['artifacts'] = {str(path.relative_to(out)): sha(path) for path in sorted(out.rglob('*'))
                               if path.is_file() and path.name != 'receipt.json'}
        (out / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    if report['status'] != 'PASS_STANDALONE_ELASTIC_LOAD_PROOF':
        raise RuntimeError(report['status'])
    print(json.dumps({'status': report['status'], 'evidence': str(out), 'backend_connected': False}))


if __name__ == '__main__':
    main()
