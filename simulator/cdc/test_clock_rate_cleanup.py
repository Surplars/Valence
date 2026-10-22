#!/usr/bin/env python3
"""Native controller/adapter contract test; modeled boundary, not physical qualification."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HELPER = HERE / 'test_runtime_epoch_boundary.py'
spec = importlib.util.spec_from_file_location('native_bounded_process', HELPER)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
TB = HERE / 'clock_rate_cleanup_tb.sv'
EMITTER = ROOT / 'src/test/scala/platform/ClockRateCleanupComponentMain.scala'
PASS = 'CLOCK_RATE_CLEANUP_COMPONENT_PASS'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rtl', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--emission-receipt', required=True, type=Path)
    parser.add_argument('--iverilog', default=os.environ.get('IVERILOG', 'iverilog'))
    parser.add_argument('--vvp', default=os.environ.get('VVP', 'vvp'))
    args = parser.parse_args()
    if not os.environ.get('VALENCE_CLOUD_ENV'):
        parser.error('source scripts/cloud/env.sh first')
    rtl, out = args.rtl.resolve(), args.output.resolve()
    if out.exists() or not out.parent.is_dir():
        parser.error('fresh output directory with existing parent required')
    tools = {name: shutil.which(getattr(args, name)) for name in ('iverilog', 'vvp')}
    if not all(tools.values()):
        parser.error('prepared native Icarus/VVP required')
    tools = base.tool_chain(tools)
    tool_hashes = {k: base.sha(p) for k, p in tools.items()}
    emission = json.loads(args.emission_receipt.read_text())
    if emission.get('status') != 'PASS_EMIT_ONLY':
        parser.error('fresh passing emission receipt required')
    sources = dict(emission['source_sha256'])
    expected = {str(p.relative_to(ROOT)) for p in (ROOT/'src/main/scala').rglob('*.scala')}
    expected |= {str(p.relative_to(ROOT)) for p in (ROOT/'src/main/resources').rglob('*.sv')}
    expected |= {str(EMITTER.relative_to(ROOT)), 'build.mill'}
    if not expected <= sources.keys():
        parser.error('emission source inventory incomplete')
    for path, digest in sources.items():
        if base.sha(ROOT/path) != digest:
            parser.error('emission source drift: '+path)
    for p in (TB, EMITTER, HELPER, Path(__file__).resolve(), ROOT/'scripts/cloud/env.sh'):
        sources[str(p.relative_to(ROOT))] = base.sha(p)
    files = sorted(rtl.glob('*.sv'))
    hashes = {p.name: base.sha(p) for p in files}
    if not files or hashes != emission['rtl_sha256']:
        parser.error('emission RTL mismatch')
    text = '\n'.join(p.read_text() for p in files)
    for required in ('module ClockRateCleanupComponent', 'module ClockRateControl',
                     'module CommonClockRateEpochAdapter', '$fatal'):
        if required not in text:
            parser.error('missing actual production module or inline assertion: '+required)
    out.mkdir()
    record = dict(status='RUNNING', scope='actual ClockRateControl and adapter with modeled boundary; no real core/CDC/gate/DRP/physical proof',
                  source_sha256=sources, rtl_sha256=hashes, tools=tools, tool_sha256=tool_hashes,
                  emission_receipt=dict(path=str(args.emission_receipt.resolve()), sha256=base.sha(args.emission_receipt)), cases=[])
    try:
        binary = out/'sim.vvp'
        command = [tools['iverilog'], '-g2012', '-s', 'clock_rate_cleanup_tb', '-o', binary, *files, TB]
        run = base.run(command, out/'compile.log', 120)
        record['cases'].append(dict(name='compile', command=list(map(str, command)), **run))
        if run['returncode']:
            raise RuntimeError('native compile failed')
        for name, plusarg, negative in [('contract', None, False), ('negative-completion', '+wrong-completion', True), ('negative-quiesce', '+wrong-quiesce', True)]:
            command = [tools['vvp'], binary] + ([plusarg] if plusarg else [])
            run = base.run(command, out/(name+'.log'), 90)
            log = (out/(name+'.log')).read_text()
            if negative:
                ok = run['returncode'] != 0 and 'NEGATIVE_ORACLE_REJECTED' in log
            else:
                ok = run['returncode'] == 0 and PASS in log
            ok = ok and not run['timed_out'] and not run['disk_floor_breached']
            record['cases'].append(dict(name=name, command=list(map(str, command)), expected_negative=negative, accepted=ok, **run))
            if not ok:
                raise RuntimeError('unexpected outcome: '+name)
        if any(base.sha(ROOT/p) != h for p, h in sources.items()):
            raise RuntimeError('source drift')
        if {p.name: base.sha(p) for p in rtl.glob('*.sv')} != hashes:
            raise RuntimeError('RTL drift')
        if any(base.sha(tools[k]) != h for k, h in tool_hashes.items()):
            raise RuntimeError('tool drift')
        record['compiled_sha256'] = base.sha(binary)
        record['drift_free'] = True
        record['status'] = 'PASS_NATIVE_CONTROLLER_ADAPTER_COMPONENT_ONLY'
    except Exception as error:
        record['status'] = 'FAIL'
        record['error'] = str(error)
        raise
    finally:
        record['logs_sha256'] = {p.name: base.sha(p) for p in out.glob('*.log')}
        (out/'receipt.json').write_text(json.dumps(record, indent=2)+'\n')


if __name__ == '__main__':
    main()
