#!/usr/bin/env python3
"""Run focused checks from an authentic compiled classpath without Mill's optional runtime launcher."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'fpga/common'))
import scala_compile_receipt as receipt_tools
sys.path.insert(0, str(ROOT / 'simulator/gsim'))
import run as common


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--mode', choices=('contracts', 'compact', 'predictor'), required=True)
    parser.add_argument('--tag', default='combined-w11-direct')
    args = parser.parse_args()
    receipt = receipt_tools.verify_receipt(args.receipt, ROOT)
    cp = os.pathsep.join(receipt['runClasspathEntries'])
    java = ['java', '-Dchisel.project.root=' + str(ROOT), '-cp', cp]
    original_run = common.run
    suites = ['ooo.CombinedA1OptimizationSpec', 'ooo.FpgaIssueStorageSpec',
              'ooo.BankedIndirectStorageSpec', 'platform.CommonFabricDmaExperimentSpec',
              'platform.CommonFabricDmaAcquireSpec', 'platform.CommonFabricDmaProbeAcquireSpec']

    def direct_run(command, **kwargs):
        words = list(map(str, command))
        if words[:3] == ['mill', '-i', 'IonSoC.test.runMain']:
            command = java + words[3:]
        elif words[:3] == ['mill', '-i', 'IonSoC.test.testOnly']:
            command = java + ['org.scalatest.tools.Runner', '-o']
            for suite in words[3:]:
                command += ['-s', suite]
        original_run(command, **kwargs)

    common.run = direct_run
    if args.mode == 'contracts':
        direct_run(['mill', '-i', 'IonSoC.test.testOnly', *suites])
    elif args.mode == 'compact':
        import compact_issue_immediate
        sys.argv = [str(compact_issue_immediate.__file__), '--tag', args.tag, '--build-run', '--skip-contracts']
        compact_issue_immediate.main()
    else:
        import banked_indirect_storage
        banked_indirect_storage.run = direct_run
        banked_indirect_storage.main()
    receipt_tools.verify_receipt(args.receipt, ROOT)
    print('VERIFIED_COMPILED_CLASSPATH_FOCUSED_PASS ' + args.mode)


if __name__ == '__main__':
    main()
