#!/usr/bin/env python3
"""Compare source-bound DMA receipts without conflating DMA ROI with fixed-work completion."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def load(path):
    data = json.loads(path.read_text())
    if data['status'] != 'PASS': raise RuntimeError('Unqualified receipt: ' + str(path))
    return data


def keyed(rows, fields):
    result = {tuple(row[k] for k in fields): row for row in rows}
    if len(result) != len(rows): raise RuntimeError('Duplicate measurement key')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline', type=Path, required=True)
    ap.add_argument('--candidate', action='append', required=True, help='label=receipt.json; repeat for variants')
    ap.add_argument('--output', type=Path, required=True, help='Output stem, without suffix')
    args = ap.parse_args()
    baseline = load(args.baseline)
    report = {'status': 'PASS', 'baseline': str(args.baseline.resolve()),
              'baseline_sha256': hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
              'clock_MHz': baseline['clock_MHz'], 'geometry': baseline['geometry'],
              'scope': 'Synthetic CPU DataPort requests, real cache/home/atomic/DMA/AXI; independent delayed sparse DDR model. No executed CPU, physical DDR, synthesis timing, or board performance claim.',
              'latency': 'Accepted CPU request to response; offer blocking separately reported.',
              'completion': 'DMA ROI ends at IRQ after final destination B. Full combined makespan includes fixed CPU work, DMA, control clear, cache/home flush and all AXI response drain.',
              'variants': {}}
    flat = []
    for item in args.candidate:
        label, name = item.split('=', 1); path = Path(name); candidate = load(path)
        if candidate['clock_MHz'] != baseline['clock_MHz'] or candidate['host'] != baseline['host'] or candidate['geometry'] != baseline['geometry']:
            raise RuntimeError('Topology or independent DDR model differs: ' + label)
        variant = {'receipt': str(path.resolve()), 'receipt_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                   'line': candidate['line'], 'line_yield_cycles': candidate.get('line_yield_cycles', 0),
                   'dma': [], 'combined': [], 'cpu_only': candidate['cpu_port_only'],
                   'source_sha256': candidate['source_sha256']}
        for category, fields in [('cases', ('bytes', 'warm', 'cpu', 'offset', 'b_delay')),
                                 ('combined', ('bytes', 'warm', 'cpu', 'operations'))]:
            left, right = keyed(baseline[category], fields), keyed(candidate[category], fields)
            if left.keys() != right.keys(): raise RuntimeError('Measurement matrix differs: ' + label)
            for key, old in left.items():
                new = right[key]
                record = {'key': dict(zip(fields, key)), 'baseline': old, 'candidate': new,
                          'kernel_speedup': old['cycles'] / new['cycles']}
                row = {'variant': label, 'category': category, **record['key'],
                       'baseline_cycles': old['cycles'], 'candidate_cycles': new['cycles'],
                       'kernel_speedup': record['kernel_speedup']}
                if category == 'combined':
                    if old['cpu_payload_bytes'] != new['cpu_payload_bytes']:
                        raise RuntimeError('Fixed CPU payload differs: ' + label + ' ' + str(key))
                    record['balanced_useful_bytes'] = old['cpu_payload_bytes'] == old['bytes']
                    record['full_speedup'] = old['full_makespan_cycles'] / new['full_makespan_cycles']
                    record['full_axi_bytes_match'] = all(old[k] == new[k] for k in ('full_axi_read_bytes', 'full_axi_write_bytes'))
                    row.update(balanced=record['balanced_useful_bytes'], full_speedup=record['full_speedup'],
                               baseline_full_cycles=old['full_makespan_cycles'], candidate_full_cycles=new['full_makespan_cycles'],
                               full_axi_bytes_match=record['full_axi_bytes_match'])
                for metric in ['cpu_p95', 'cpu_p99', 'cpu_max', 'cpu_worst_offer_blocked']:
                    row['baseline_' + metric] = old[metric]; row['candidate_' + metric] = new[metric]
                variant['combined' if category == 'combined' else 'dma'].append(record); flat.append(row)
        strip = lambda r: {k: v for k, v in r.items() if k != 'line'}
        variant['cpu_only_matches_baseline'] = list(map(strip, baseline['cpu_port_only'])) == list(map(strip, candidate['cpu_port_only']))
        report['variants'][label] = variant
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    fields = list(dict.fromkeys(key for row in flat for key in row))
    with args.output.with_suffix('.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(flat)
    print(args.output.with_suffix('.json').resolve())


if __name__ == '__main__': main()
