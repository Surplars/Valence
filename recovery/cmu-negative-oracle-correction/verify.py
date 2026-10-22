#!/usr/bin/env python3
"""Read-only verification of the archived narrow replay bundle and bound inputs."""
import difflib
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def main():
    manifest = json.loads((HERE / 'manifest.json').read_text())
    summary = json.loads((HERE / 'summary.json').read_text())
    for tag, info in manifest.items():
        archive = HERE / tag / 'replay-r1'
        receipt = json.loads((archive / 'receipt.json').read_text())
        check(receipt['baseline'] == info, tag + ': manifest/receipt mismatch')
        check(receipt['status'] == 'PASS_HISTORICAL_RTL_CORRECTED_MONITOR_REPLAY', tag + ': not passing')
        for path, digest in receipt['input_sha256'].items():
            check(sha(Path(path)) == digest, tag + ': bound input changed: ' + path)
        for name, digest in receipt['logs_sha256'].items():
            check(sha(archive / name) == digest, tag + ': archived log changed: ' + name)
        original = json.loads((ROOT / info['baseline_receipt']).read_text())
        check(sha(ROOT / info['baseline_receipt']) == info['baseline_receipt_sha256'], tag + ': original receipt changed')
        check(sha(HERE / tag / 'baseline_tb.source.sv') == original['source_sha256'][info['baseline_tb_path']], tag + ': original TB mismatch')
        before = (HERE / tag / 'baseline_tb.source.sv').read_text()
        after = (HERE / tag / 'corrected_tb.source.sv').read_text()
        patch = ''.join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                            fromfile=f'{tag}/baseline_tb.source.sv', tofile=f'{tag}/corrected_tb.source.sv'))
        check((HERE / tag / 'monitor-only.patch').read_text() == patch, tag + ': patch mismatch')
        rtl = {p.name: sha(p) for p in Path(receipt['original_rtl_directory']).glob('*.sv')}
        check(rtl == receipt['complete_original_rtl_inventory_sha256'], tag + ': complete RTL inventory drift')
        for name, path in receipt['historical_tools'].items():
            check(sha(Path(path)) == receipt['historical_tool_sha256'][name], tag + ': tool drift: ' + name)
        check(all(c['accepted'] for c in receipt['cases']), tag + ': unaccepted case')
        check(sum(not c['expected_negative'] for c in receipt['cases']) == 1, tag + ': missing matched positive')
        check(sum(c['expected_negative'] for c in receipt['cases']) == (1 if tag == 'r10' else 2), tag + ': missing negative')
        for case in receipt['cases']:
            content = (archive / (case['label'] + '.log')).read_text()
            check(case['required_ordinary_checker_marker'] in content, tag + ': missing ordinary checker marker')
            check(not case['timed_out'] and not case['disk_floor_breached'], tag + ': resource failure')
            check((case['returncode'] != 0) == case['expected_negative'], tag + ': wrong return code')
        check(summary['replays'][tag]['status'] == receipt['status'], tag + ': summary mismatch')
        if tag != 'r11':
            check(sha(ROOT / info['baseline_tb_path']) == info['corrected_tb_sha256'], tag + ': working TB/snapshot drift')
        print(tag + ': VERIFIED manifest, original receipt/TB, patch, runner/helper, emission, complete RTL, tools, and archived logs')
    print('PASS: 3 matched positives and 5 intended ordinary-checker negatives; historical-RTL scope only.')


if __name__ == '__main__':
    main()
