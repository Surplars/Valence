#!/usr/bin/env python3
"""Run the independent host oracle and deliberately faulty oracle controls.

No Scala, model generation, GSIM or RTL execution is launched here.
"""

import hashlib
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'contract_oracle.py'
TEST = ROOT / 'test_contract_oracle.py'
MUTANTS = {
    'acceptance_time_base_instead_of_grant': (
        'run = Run(context, reservation, victim_done=not reservation.victim_valid)',
        'run = Run(context, reservation, victim_done=not reservation.victim_valid)\n            run.acceptance_base = self.line(context.line)',
        "grant['expected'] = self.line(self.runs[grant['owner']].context.line)",
        "grant['expected'] = self.runs[grant['owner']].acceptance_base"),
    'late_response_ticket_write': (
        'require(ticket in self.tickets and self.tickets[ticket] == [token, False],', 'require(True,'),
    'reuse_old_cohort_root': ('require(context.root == root,', 'require(True,'),
    'ignore_generation_exhaustion': ('self.exhausted = True', 'self.exhausted = False'),
    'invent_third_acquire_source': ('source in (0, 1) and source not in self.grants', 'source not in self.grants'),
    'probe_before_install': ('or not r.acquired or r.installed', 'or not r.acquired or r.refilled'),
    'release_before_wb_ack': ('run.installed and run.victim_done and self.order[0]', 'run.installed and self.order[0]'),
    'ignore_independent_grant_bytes': ("require(data == grant['expected'],", 'require(True,'),
    'lose_handoff_responsibility': ('require(reported_before_busy and reported_after_busy,', 'require(True,'),
    'recertify_held_context': ('payload == self.prior and epoch == self.epoch', 'payload == self.prior'),
}


def run(directory):
    return subprocess.run([sys.executable, '-m', 'unittest', '-v', TEST.name], cwd=directory,
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'host-results.json')
    args = parser.parse_args()
    original = SOURCE.read_text()
    baseline = run(ROOT)
    report = {'schema': 'new-posted-merge-host-contract-v1',
              'scope': 'host oracle self-tests and mutation sensitivity only; no RTL or executing CPU qualification',
              'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              'test_sha256': hashlib.sha256(TEST.read_bytes()).hexdigest(),
              'baseline_exit': baseline.returncode, 'baseline_output': baseline.stdout, 'mutants': []}
    for name, edits in MUTANTS.items():
        body = original
        for old, new in zip(edits[::2], edits[1::2]):
            if old not in body:
                raise RuntimeError(f'mutant {name} source anchor missing: {old}')
            body = body.replace(old, new)
        with tempfile.TemporaryDirectory(prefix='posted-merge-host-') as temp:
            path = Path(temp)
            (path / SOURCE.name).write_text(body)
            (path / TEST.name).write_bytes(TEST.read_bytes())
            outcome = run(path)
        # A syntax/import error is not evidence that a semantic mutant was caught.
        semantic_failure = outcome.returncode != 0 and 'FAIL:' in outcome.stdout and 'FAILED (' in outcome.stdout
        report['mutants'].append({'name': name, 'detected': semantic_failure,
                                  'exit': outcome.returncode, 'output': outcome.stdout})
    report['passed'] = baseline.returncode == 0 and all(m['detected'] for m in report['mutants'])
    destination = args.output
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'mutants_detected': sum(m['detected'] for m in report['mutants']),
                      'mutants_total': len(MUTANTS), 'report': str(destination)}, indent=2))
    if not report['passed']:
        print(baseline.stdout)
        for mutant in report['mutants']:
            if not mutant['detected']:
                print(mutant['name'], mutant['output'])
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
