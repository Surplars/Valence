#!/usr/bin/env python3
"""Audit same-source accepted/admission CPU A/B without rebuilding hardware.

Rehash every saved artifact, bind fixed capacities and retired work, and permit
only the independentDemandAdmission policy difference. No STA or board claim.
"""
import argparse
import json
from pathlib import Path
import cpu_sv39_bandwidth as bench


def require(value, message):
    if not value:
        raise RuntimeError(message)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--receipt', type=Path, required=True)
    ap.add_argument('--retained-receipt', type=Path,
                    help='optional subsequent single-candidate retention scheduling ablation')
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    path = args.receipt.resolve()
    receipt = json.loads(path.read_text())
    require(receipt['status'] == 'PASS_ACTUAL_S_MODE_CPU_SV39_BANDWIDTH', 'CPU run not passed')
    require(receipt['profiles'] == ['accepted', 'admission'], 'matched OFF/ON profiles required')
    require(receipt['sizes'] == [4096, 65536] and receipt['reps'] == 2, 'traffic changed')
    require(receipt['geometry'] == {'issue': 2, 'LSU': 2, 'ROB': 16, 'PRF': 48,
        'DTLB': 8, 'ITLB': 8, 'PTE_cache': 4, 'I_L1_bytes': 32768, 'D_L1_bytes': 32768,
        'read_MSHR': 2, 'writeback': 2, 'DDR_shared': 4, 'DDR_write': 2}, 'capacity changed')
    for relative, digest in receipt['artifacts'].items():
        artifact = (path.parent / relative).resolve()
        require(artifact.is_relative_to(path.parent), 'artifact escapes evidence directory')
        require(bench.sha(artifact) == digest, 'artifact changed: ' + str(artifact))
    commands = receipt['commands']
    require(len([c for c in commands if '-negative-' in c['name']]) == 6, 'negative coverage missing')
    require(all(c['exit'] == c['expected'] for c in commands), 'command exit changed')
    configs = {label: json.loads((path.parent / label / 'profile.json').read_text())
               for label in ('accepted', 'admission')}
    a, b = configs['accepted'], configs['admission']
    require(set(a) == set(b), 'profile sections changed')
    for section in a:
        if section in ('profile', 'cache'):
            require(a[section]['independentDemandAdmission'] is False and
                    b[section]['independentDemandAdmission'] is True, 'policy not OFF/ON')
            require({k: v for k, v in a[section].items() if k != 'independentDemandAdmission'} ==
                    {k: v for k, v in b[section].items() if k != 'independentDemandAdmission'},
                    'hidden capacity/policy difference: ' + section)
        else:
            require(a[section] == b[section], 'hidden hardware configuration: ' + section)
    require(a['cache']['responseEntries'] == 2 and a['profile']['dmaLineEntries'] == 1,
            'response or DMA owners expanded')
    off, on = receipt['cases']['accepted'], receipt['cases']['admission']
    require(set(off) == set(on) and len(on) == 12, 'case coverage drift')
    rows = []
    for key in sorted(on):
        before, after = off[key], on[key]
        for field in ('mode', 'op', 'bytes', 'reps', 'retired', 'pc_hash', 'loads', 'stores'):
            require(before[field] == after[field], 'retired work drift: ' + key + '/' + field)
        ipc = {}
        for label, row in (('accepted', before), ('admission', after)):
            lines = (path.parent / (label + '-' + key + '.log')).read_text().splitlines()
            text = next(line for line in lines if line.startswith('BOARD_IPC name=S_mode_kernel '))
            fields = dict(word.split('=') for word in text.split()[1:])
            require(int(fields['cycles']) == row['cycles'] and int(fields['retired']) == row['retired'],
                    'IPC observation window differs')
            ipc[label] = {k: int(v) for k, v in fields.items() if k not in ('name', 'ipc')}
        rows.append({'case': key, 'before_cycles': before['cycles'], 'after_cycles': after['cycles'],
            'before_MiBps': before['payload_MiBps'], 'after_MiBps': after['payload_MiBps'],
            'throughput_delta_percent': 100 * (before['cycles'] / after['cycles'] - 1),
            'physical_request_duty_percent': 100 * after['event15'] / after['cycles'],
            'two_MSHR_duty_percent': 100 * after['two_cache_owner_cycles'] / after['cycles'],
            'R_beat_duty_percent': 100 * after['r_beats'] / after['cycles'],
            'W_beat_duty_percent': 100 * after['w_beats'] / after['cycles'],
            'before_backend': ipc['accepted'], 'after_backend': ipc['admission'],
            'before_counters': before, 'after_counters': after})
    result = {'status': 'PASS_MATCHED_CPU_MEMORY_ADMISSION_AB', 'scope': __doc__,
        'receipt': str(path), 'receipt_sha256': bench.sha(path), 'toolchain': receipt['toolchain'],
        'guest_sha256': bench.sha(path.parent / 'guest/guest.bin'), 'geometry': receipt['geometry'],
        'policy_delta': {'independentDemandAdmission': True}, 'rows': rows}
    if args.retained_receipt:
        retained_path = args.retained_receipt.resolve()
        retained = json.loads(retained_path.read_text())
        label = 'admission-retained'
        require(retained['status'] == receipt['status'] and retained['profiles'] == [label],
                'retention run not passed or unexpected profiles')
        for field in ('geometry', 'sizes', 'reps', 'toolchain', 'symbols'):
            require(retained[field] == receipt[field], 'retention comparison drift: ' + field)
        source_deltas = {name for name in receipt['source_sha256']
                         if receipt['source_sha256'][name] != retained['source_sha256'].get(name)}
        require(set(receipt['source_sha256']) == set(retained['source_sha256']), 'source set changed')
        require(source_deltas == {'simulator/gsim/cpu_sv39_bandwidth.py',
                                 'src/test/scala/ooo/CpuSv39BandwidthGsimMain.scala'},
                'production or guest source drift in retention ablation')
        for relative, digest in retained['artifacts'].items():
            artifact = (retained_path.parent / relative).resolve()
            require(artifact.is_relative_to(retained_path.parent), 'retention artifact escapes directory')
            require(bench.sha(artifact) == digest, 'retention artifact drift: ' + str(artifact))
        require(bench.sha(retained_path.parent / 'guest/guest.bin') == result['guest_sha256'], 'guest changed')
        require(len([c for c in retained['commands'] if '-negative-' in c['name']]) == 3 and
                all(c['exit'] == c['expected'] for c in retained['commands']), 'retention command failure')
        c = json.loads((retained_path.parent / label / 'profile.json').read_text())
        require(set(c) == set(b), 'retention profile sections changed')
        for section in b:
            if section in ('profile', 'cache'):
                require(b[section]['prefetchCandidateCycles'] == 1 and c[section]['prefetchCandidateCycles'] == 16,
                        'retention policy not 1->16')
                require({k: v for k, v in b[section].items() if k != 'prefetchCandidateCycles'} ==
                        {k: v for k, v in c[section].items() if k != 'prefetchCandidateCycles'},
                        'hidden retention policy: ' + section)
            else:
                require(b[section] == c[section], 'hidden retention hardware change: ' + section)
        results = retained['cases'][label]
        require(set(results) == set(on), 'retention case drift')
        for row in rows:
            key = row['case']
            after = results[key]
            for field in ('mode', 'op', 'bytes', 'reps', 'retired', 'pc_hash', 'loads', 'stores'):
                require(on[key][field] == after[field], 'retention retired work drift: ' + field)
            text = next(line for line in (retained_path.parent / (label + '-' + key + '.log')).read_text().splitlines()
                        if line.startswith('BOARD_IPC name=S_mode_kernel '))
            fields = dict(word.split('=') for word in text.split()[1:])
            require(int(fields['cycles']) == after['cycles'], 'retention observation window mismatch')
            row['retained_counters'] = after
            row['retained_backend'] = {k: int(v) for k, v in fields.items() if k not in ('name', 'ipc')}
            row['retained_vs_off_percent'] = 100 * (off[key]['cycles'] / after['cycles'] - 1)
            row['retained_vs_admission_percent'] = 100 * (on[key]['cycles'] / after['cycles'] - 1)
        result['retention_ablation'] = {'receipt': str(retained_path), 'sha256': bench.sha(retained_path),
            'policy_delta': {'prefetchCandidateCycles': 16}, 'test_only_source_deltas': sorted(source_deltas),
            'scope': 'Identical production hardware sources, toolchain, guest, geometry and retired work; '
                     'separately frozen fixture/runner revisions add only the optional profile label.'}
    document = json.dumps(result, indent=2) + '\n'
    if args.output:
        with args.output.open('x') as stream:
            stream.write(document)
        print(result['status'], str(args.output))
    else:
        print(document, end='')


if __name__ == '__main__':
    main()
