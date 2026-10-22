#!/usr/bin/env python3
"""Bounded native two-clock CommonFixedDomainEpochQualifier acceptance.

Independent public-interface ledger; localIdle/linkReady are test-owned inputs,
not real DDR queues or a timer. Fresh production RTL and central source/RTL
emission receipt required. No Mill invocation, installation, DUT mutation,
Verilator, Vivado, upload, or physical signoff. Negative controls corrupt monitor
observations only and must fail the same ordinary ledger checks as positives.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shlex
import shutil
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FLOOR = 4 * 1024**3
PASS = 'FIXED_EPOCH_QUALIFIER_PASS'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def guard(path):
    free = shutil.disk_usage(path).free
    if free < FLOOR:
        raise RuntimeError(f'4 GiB free-space floor: {free} bytes available')
    return free


def run(command, path, timeout):
    started = time.monotonic()
    minimum = guard(path.parent)
    timed_out = breached = killed = False

    def no_core():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    with path.open('w') as log:
        process = subprocess.Popen(list(map(str, command)), stdout=log,
                                   stderr=subprocess.STDOUT, cwd=ROOT,
                                   start_new_session=True, preexec_fn=no_core)
        while True:
            minimum = min(minimum, shutil.disk_usage(path.parent).free)
            breached |= minimum < FLOOR
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid:
                process.returncode = os.waitstatus_to_exitcode(status)
                break
            timed_out |= time.monotonic() - started > timeout
            if (timed_out or breached) and not killed:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                killed = True
            time.sleep(0.02)
    return dict(returncode=process.returncode, seconds=time.monotonic()-started,
                maxrss_kib=usage.ru_maxrss, minimum_free_bytes=minimum,
                timed_out=timed_out, disk_floor_breached=breached,
                process_group_killed=killed)


def tool_chain(tools):
    chain = dict(tools)
    compiler = Path(tools['iverilog'])
    if compiler.read_bytes().startswith(b'#!'):
        for line in compiler.read_text().splitlines():
            if line.startswith('exec '):
                words = shlex.split(line)
                if len(words) > 1 and Path(words[1]).is_file():
                    chain['iverilog_engine'] = words[1]
                if '-B' in words:
                    directory = Path(words[words.index('-B') + 1])
                    for engine in ('ivl', 'ivlpp', 'vvp.tgt', 'vvp.conf'):
                        if (directory/engine).is_file():
                            chain[engine] = str(directory/engine)
    return chain


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rtl', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--iverilog', default=os.environ.get('IVERILOG', 'iverilog'))
    parser.add_argument('--vvp', default=os.environ.get('VVP', 'vvp'))
    parser.add_argument('--timeout', type=int, default=90)
    parser.add_argument('--emission-receipt', type=Path, required=True)
    args = parser.parse_args()
    rtl, output = args.rtl.resolve(), args.output.resolve()
    if output.exists() or not output.parent.is_dir():
        parser.error('fresh output directory with existing parent required')
    tools = {name: shutil.which(value) for name, value in
             (('iverilog', args.iverilog), ('vvp', args.vvp))}
    if not all(tools.values()):
        parser.error('existing Icarus/VVP required; no installation or fallback')
    files = sorted(rtl.glob('*.sv'))
    modules = set()
    for path in files:
        content = path.read_text()
        modules.update(re.findall(r'^\s*module\s+(\w+)', content, re.M))
        if 'automatic logic' in content or re.search(r'^\s*bind\b', content, re.M):
            parser.error('emit inline assertions/disallowLocalVariables; no DUT rewrite allowed')
    if not {'CommonFixedDomainEpochQualifier', 'CdcMailbox', 'CdcResetRelease', 'CdcLevel'} <= modules:
        parser.error('missing production fixed qualifier or production CDC helpers')
    fixture = HERE/'fixed_epoch_qualifier_tb.sv'
    sources = sorted((ROOT/'src/main/scala').rglob('*.scala'))
    sources += [ROOT/'src/test/scala/platform/CommonFixedDomainEpochQualifierMain.scala',
                fixture, Path(__file__).resolve()]
    if any(not path.is_file() for path in sources):
        parser.error('source/emitter files must exist to bind RTL evidence')
    emission = json.loads(args.emission_receipt.read_text())
    if emission.get('status') != 'PASS_EMIT_ONLY':
        parser.error('passing central emission receipt required')
    emitted_sources = emission.get('source_sha256', {})
    emitted_rtl = emission.get('rtl_sha256', {})
    if not emitted_sources or not emitted_rtl:
        parser.error('emission receipt must bind source inventory and RTL hashes')
    for name, digest in emitted_sources.items():
        path = Path(name) if Path(name).is_absolute() else ROOT/name
        if not path.is_file() or sha(path) != digest:
            parser.error('emitted source drift: '+name)
    if {path.name: sha(path) for path in files} != emitted_rtl:
        parser.error('emitted RTL inventory or content drift')
    production_names = {str(path.relative_to(ROOT)) for path in (ROOT/'src/main/scala').rglob('*.scala')}
    production_names.add('src/test/scala/platform/CommonFixedDomainEpochQualifierMain.scala')
    normalized_names = {str(Path(name).relative_to(ROOT)) if Path(name).is_absolute() else name
                        for name in emitted_sources}
    if not production_names <= normalized_names:
        parser.error('emission source inventory omits production Scala or boundary emitter')
    sources = sorted(set(sources + [Path(name) if Path(name).is_absolute() else ROOT/name
                                  for name in emitted_sources]))
    inputs = files + [fixture, Path(__file__).resolve()]
    if args.emission_receipt:
        inputs += [args.emission_receipt.resolve()]
    input_hashes = {str(path): sha(path) for path in inputs}
    source_hashes = {str(path.relative_to(ROOT)): sha(path) for path in sources}
    chain = tool_chain(tools)
    tool_hashes = {name: sha(path) for name, path in chain.items()}
    guard(output.parent)
    output.mkdir()
    for directory, paths in (('rtl', files), ('fixture', [fixture, Path(__file__).resolve()]),
                             ('source', sources)):
        for path in paths:
            relative = path.relative_to(ROOT) if directory == 'source' else path.name
            destination = output/'inputs'/directory/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    if args.emission_receipt:
        shutil.copy2(args.emission_receipt, output/'inputs'/'emission-receipt.json')
    receipt = dict(status='RUNNING', scope='production fixed-domain qualification and consumed-retirement helper; independent fabric/fixed test inputs only',
        source_binding='validated central emission source inventory and RTL hashes; preserved source/RTL/fixture/tool snapshots',
        emission_receipt=str(args.emission_receipt.resolve()), emission_source_sha256=emitted_sources,
        real_core=False, real_home_or_ddr=False, physical_cdc_qualified=False,
        clock_gating_qualified=False, drp_qualified=False, board_qualified=False,
        single_sided_reset_supported=False, modules=sorted(modules),
        input_sha256=input_hashes, source_sha256=source_hashes,
        tools=chain, tool_sha256=tool_hashes, disk_floor_bytes=FLOOR,
        free_before_bytes=guard(output), commands=[], resources=[],
        positive_cases={}, negative_oracle_checks={})
    binary = output/'fixed-epoch-qualifier.vvp'
    started = time.monotonic()
    try:
        flags = ['-g2012', '-DSTOP_COND=1', '-DASSERT_VERBOSE_COND=1']
        preprocessed = output/'production-preprocessed.sv'
        command = [tools['iverilog'], *flags, '-E', '-o', str(preprocessed), *map(str, files)]
        receipt['commands'].append(command)
        result = run(command, output/'preprocess.log', args.timeout)
        receipt['resources'].append({'label': 'preprocess', **result})
        if result['returncode'] or result['timed_out'] or result['disk_floor_breached']:
            raise RuntimeError('production preprocessing failed; inspect preprocess.log')
        text = preprocessed.read_text()
        if re.search(r'^\s*bind\b', text, re.M):
            raise RuntimeError('production assertions contain unsupported external bind')
        required_assertions = ('fixed epoch retired before terminal consumption and observation drain',
                               'fabric epoch retired before fixed-domain consumed retirement receipt')
        if not all(message in text for message in required_assertions) or not re.search(r'\$fatal\b', text):
            raise RuntimeError('required production terminal/retirement assertions were not enabled')
        receipt['production_assertions'] = dict(inline_fatal_sites=len(re.findall(r'\$fatal\b', text)),
            preprocessed_sha256=sha(preprocessed), definitions=flags[1:])
        command = [tools['iverilog'], *flags, '-s', 'fixed_epoch_qualifier_tb', '-o', str(binary),
                   *map(str, files), str(fixture)]
        receipt['commands'].append(command)
        result = run(command, output/'compile.log', args.timeout)
        receipt['resources'].append({'label': 'compile', **result})
        if result['returncode'] or result['timed_out'] or result['disk_floor_breached']:
            raise RuntimeError('component compile failed; inspect compile.log')
        receipt['compiled_sha256'] = sha(binary)
        ratios = [('fabric-fast', 3, 11, 1300), ('fixed-fast', 11, 2, 2700),
                  ('near-ratio', 5, 7, 1700), ('fixed-slow', 2, 17, 900)]
        cases = [(0, 'qualification-revocation-receipts'), (1, 'early-cancel-without-qualification'),
                 (2, 'pause-before-qualification-cancel'), (3, 'pause-before-retirement'),
                 (4, 'coordinated-reset'), (5, 'stale-completion-fails-closed'),
                 (6, 'busy-prepare-fails-closed'), (7, 'cancel-late-proof'),
                 (8, 'changed-terminal-fails-closed'), (9, 'post-resume-traffic-does-not-block-retirement'),
                 (10, 'epoch-wrap-replay-fails-closed')]
        for ratio, fabric, fixed, phase in ratios:
            for case, name in cases:
                label = ratio+'-'+name
                command = [tools['vvp'], str(binary), f'+case={case}', f'+fabric_half={fabric}',
                           f'+fixed_half={fixed}', f'+phase_ps={phase}']
                receipt['commands'].append(command)
                log = output/(label+'.log')
                result = run(command, log, args.timeout)
                receipt['resources'].append({'label': label, **result})
                content = log.read_text()
                if result['returncode'] or result['timed_out'] or result['disk_floor_breached'] or PASS not in content:
                    raise RuntimeError(label+' failed: '+content[-5000:])
                events = [line for line in content.splitlines() if line.startswith('FIXED_')]
                receipt['positive_cases'][label] = dict(fabric_half_ns=fabric, fixed_half_ns=fixed,
                    phase_ps=phase, events=events, log_sha256=sha(log))
        for fault, marker in [(1, 'FIXED_ORACLE_EPOCH'), (2, 'FIXED_ORACLE_RECEIPT')]:
            label = 'negative-'+str(fault)
            command = [tools['vvp'], str(binary), '+case=0', f'+negative={fault}']
            receipt['commands'].append(command)
            log = output/(label+'.log')
            result = run(command, log, args.timeout)
            receipt['resources'].append({'label': label, **result})
            content = log.read_text()
            if (result['returncode'] == 0 or result['timed_out'] or result['disk_floor_breached'] or
                    marker not in content or PASS in content):
                raise RuntimeError('negative oracle did not fail at its intended check: '+label)
            receipt['negative_oracle_checks'][label] = dict(expected_failure=marker,
                mutation='monitor observation only; ordinary oracle unchanged; no DUT RTL mutation', log_sha256=sha(log))
        receipt['status'] = 'PASS_NATIVE_FIXED_EPOCH_QUALIFIER_ONLY'
    except BaseException as error:
        receipt.update(status='FAILED', failure=str(error))
        raise
    finally:
        receipt['seconds'] = time.monotonic()-started
        receipt['input_sha256_after'] = {str(path): sha(path) for path in inputs}
        receipt['source_sha256_after'] = {str(path.relative_to(ROOT)): sha(path) for path in sources}
        receipt['tool_sha256_after'] = {name: sha(path) for name, path in chain.items()}
        receipt['compiled_sha256_after'] = sha(binary) if binary.exists() else None
        production_after = {str(path.relative_to(ROOT)) for path in (ROOT/'src/main/scala').rglob('*.scala')}
        production_after.add('src/test/scala/platform/CommonFixedDomainEpochQualifierMain.scala')
        receipt['source_inventory_unchanged'] = production_after == production_names
        receipt['rtl_inventory_unchanged'] = sorted(path.name for path in rtl.glob('*.sv')) == sorted(path.name for path in files)
        receipt['drift_free'] = (receipt['source_inventory_unchanged'] and receipt['rtl_inventory_unchanged'] and
            receipt['input_sha256_after'] == input_hashes and
            receipt['source_sha256_after'] == source_hashes and
            receipt['tool_sha256_after'] == tool_hashes and
            receipt.get('compiled_sha256') == receipt['compiled_sha256_after'])
        if not receipt['drift_free']:
            receipt.update(status='FAILED', failure='input/source/tool/compiled artifact drift')
        receipt['free_after_bytes'] = shutil.disk_usage(output).free
        (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    if receipt['status'] != 'PASS_NATIVE_FIXED_EPOCH_QUALIFIER_ONLY':
        raise RuntimeError(receipt.get('failure', 'component acceptance failed'))
    print(receipt['status']+' receipt='+str(output/'receipt.json'))


if __name__ == '__main__':
    main()
