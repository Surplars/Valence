#!/usr/bin/env python3
"""Reproduce the first A1 cold-DDR assertion with read-only hierarchical taps."""
import argparse
import json
from pathlib import Path
from cpu_boot_native import guard, run, sha

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--failed-run', required=True, type=Path)
    args = parser.parse_args()
    prior = args.failed_run.resolve()
    receipt = json.loads((prior/'receipt.json').read_text())
    if receipt['status'] != 'FAIL' or receipt['profile'] != 'a1':
        parser.error('requires the retained failed A1 performance run')
    if 'TileLink bank response has no matching source' not in (prior/'positive.log').read_text():
        parser.error('requires the specific production owner assertion')
    for path, digest in receipt['rtl_sha256'].items():
        if sha(path) != digest:
            parser.error('RTL changed: '+path)
    base = prior/'cpu_perf_tb.sv'
    if sha(base) != receipt['artifact_sha256']['cpu_perf_tb.sv']:
        parser.error('original testbench changed')
    out = args.output.resolve()
    if out.exists() or not out.parent.is_dir():
        parser.error('fresh evidence directory required')
    guard(out.parent); out.mkdir()
    fragment = HERE/'cpu_perf_trace.sv'
    tb = out/'cpu_perf_tb.sv'
    tb.write_text(base.read_text().replace('\nendmodule', '\n'+fragment.read_text()+'\nendmodule', 1))
    record = dict(status='RUNNING', base_receipt_sha256=sha(prior/'receipt.json'),
                  base_testbench_sha256=sha(base), trace_sha256=sha(fragment),
                  runner_sha256=sha(__file__), rtl_sha256=receipt['rtl_sha256'],
                  commands=[], results=[], scope='Read-only taps; unchanged guest, service law, RTL and assertions; 132.1 us simulation bound')
    def save():
        (out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    try:
        command = receipt['commands'][0][:]
        command[command.index('-o')+1] = str(out/'run.vvp'); command[-1] = str(tb)
        record['commands'].append(command); save()
        result = run(command, out/'compile.log', 60); record['results'].append(result); save()
        if result['returncode'] or result['timed_out'] or result['disk_floor_breached']:
            raise RuntimeError('diagnostic compilation failed')
        command = receipt['commands'][1][:]; command[2] = str(out/'run.vvp')
        record['commands'].append(command); save()
        result = run(command, out/'diagnostic.log', 90); record['results'].append(result)
        log = (out/'diagnostic.log').read_text()
        if (not result['returncode'] or result['timed_out'] or result['disk_floor_breached'] or
                'TileLink bank response has no matching source' not in log):
            raise RuntimeError('specific production assertion not reproduced')
        record['status'] = 'REPRODUCED_PRODUCTION_ASSERTION'
    except BaseException as error:
        record.update(status='INCONCLUSIVE', error=repr(error)); raise
    finally:
        record['artifact_sha256'] = {p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='receipt.json'}
        save()
        print(record['status']+' receipt='+str(out/'receipt.json'), flush=True)


if __name__ == '__main__':
    main()
