#!/usr/bin/env python3
"""Independent synthetic observer calibration; no DUT or Scala is constructed."""
import argparse
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import buffered_third_rank_cpu as common

NEGATIVES = {
    'slot-unowned': 'RETURN_FLOW_SLOT_REPLY_WITHOUT_START',
    'slot-overwrite': 'RETURN_FLOW_LIVE_SLOT_OVERWRITE',
    'slot-early-complete': 'RETURN_FLOW_COMPLETE_BEFORE_SLOT_REPLY',
    'slot-duplicate': 'RETURN_FLOW_DUPLICATE_SLOT_REPLY',
    'slot-tag': 'RETURN_FLOW_COMPLETE_FULL_OWNER',
    'index': 'RETURN_FLOW_RECONSTRUCTED_SLOT', 'raw': 'RETURN_FLOW_RAW_STORED_ZERO',
    'high-tag': 'RETURN_FLOW_FULL_TAG_SOURCE_OWNER', 'source': 'RETURN_FLOW_FULL_TAG_SOURCE_OWNER',
    'unwritten': 'RETURN_FLOW_LIVE_WITHOUT_ALLOCATION', 'dual': 'RETURN_FLOW_DUAL_ALLOCATION_ALIAS',
    'payload': 'RETURN_FLOW_FULL_PAYLOAD_ORDER', 'drop': 'RETURN_FLOW_VALID_CONSERVATION',
    'idle': 'RETURN_FLOW_PREMATURE_AGGREGATE_IDLE', 'fp': 'RETURN_FLOW_FP_EXCLUSIVE_OWNER',
    'credit': 'RETURN_FLOW_OLD_OCCUPANCY_CREDIT',
}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--tool-receipt', type=Path, required=True)
    args = p.parse_args()
    tools = common.epoch.tool_binding(args.tool_receipt)
    root = common.common.ROOT
    header = root / 'simulator/gsim/harness/buffered_return_flow_observer.h'
    source = header.parent / 'test_buffered_return_flow_observer.cpp'
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'valence-buffered-return-flow-observer-v1', 'status': 'RUNNING',
              'header': {'path': str(header.relative_to(root)), 'sha256': common.sha(header)},
              'source': {'path': str(source.relative_to(root)), 'sha256': common.sha(source)},
              'tools': tools, 'negatives': {}}
    save = lambda: common.save(out / 'receipt.json', report)
    save()
    try:
        binary = out / 'run'
        common.common.run([tools['compiler']['command'], '-std=c++20', '-O1', '-g',
            '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I'+str(header.parent),
            source, '-o', binary], log=out/'compile.log', timeout=180)
        common.common.run([binary], env=common.base.runtime_env(), log=out/'positive.log', timeout=30)
        common.need('PASS_SYNTHETIC_OBSERVER_ONLY' in (out/'positive.log').read_text(), 'missing positive calibration')
        import subprocess
        for name, reason in NEGATIVES.items():
            log = out / (name + '.log')
            result = subprocess.run([str(binary), name], text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=30, env=common.base.runtime_env())
            log.write_text(result.stdout)
            common.need(result.returncode == 1 and reason in result.stdout and 'NEGATIVE_NOT_TRIGGERED' not in result.stdout,
                        'specific negative not rejected: ' + name)
            report['negatives'][name] = {'status': 'EXPECTED_REJECTION', 'reason': reason, 'log_sha256': common.sha(log)}
        report['status'] = 'PASS_SYNTHETIC_OBSERVER_ONLY'
    except BaseException as e:
        report.update(status='FAIL', error=str(e)); raise
    finally:
        report['artifacts'] = {str(p.relative_to(out)): common.sha(p) for p in out.iterdir() if p.is_file() and p.name != 'receipt.json'}
        save()
    print(report['status'])

if __name__ == '__main__': main()
