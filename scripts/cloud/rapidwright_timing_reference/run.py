#!/usr/bin/env python3
"""Bounded local-only primitive-delay reference; never a full-path STA result."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

LOCKS = {
    'downloads/rapidwright-2025.1.3-standalone-lin64.jar': 'bc39264c090bfaedd0ac7d9cb1f73d66d9f532e07fa478a247bb7a495bfa78a4',
    'rapidwright/timing/ultrascaleplus/intrasite_delay_terms.txt': 'ff08ce9041da649f2bf886d900f033dd23de8ad54eb4db55d37ce032dc0ec0a0',
    'rapidwright/timing/ultrascaleplus/intersite_delay_terms.txt': '3b122837c4a1b5f3c212fc6353bee3a0854a204f2f69e2bc1cac4a2a1f9d7333',
}

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()

def require(condition, message):
    if not condition:
        raise ValueError(message)

def contained(root, relative):
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and path.is_file(), 'Missing/outside bundle: ' + relative)
    return path

def parse_paths(report, selections):
    blocks = re.split(r'(?=^Slack \()', report, flags=re.M)
    logic, nets, checks, matched = [], [], [], []
    labels = set()
    for spec in selections:
        label, source, dest = (spec[k] for k in ('label', 'source', 'destination'))
        require(label not in labels and re.fullmatch(r'[A-Za-z0-9_-]+', label), 'Duplicate/invalid label')
        labels.add(label)
        hits = [b for b in blocks if re.search(r'^\s*Source:\s+' + re.escape(source) + r'\s*$', b, re.M)
                and re.search(r'^\s*Destination:\s+' + re.escape(dest) + r'\s*$', b, re.M)]
        if 'report_block_sha256' in spec:
            hits = [b for b in hits if hashlib.sha256(b.encode()).hexdigest() == spec['report_block_sha256']]
        require(len(hits) == 1, 'Expected exactly one report path: ' + label)
        lines = hits[0].splitlines()
        starts = [i for i, line in enumerate(lines) if 'SLICE_' in line and re.search(r'\s' + re.escape(source) + r'(?:\s+\(IS_INVERTED\))?\s*$', line)]
        require(len(starts) == 1, 'Ambiguous/missing data start: ' + label)
        start = starts[0]
        stops = [i for i in range(start + 1, len(lines)) if 'SLICE_' in lines[i] and lines[i].split()[-1] == dest]
        require(len(stops) == 1, 'Ambiguous/missing data end: ' + label)
        input_cell, input_pin = source.rsplit('/', 1)
        previous_output, pending_net = None, None
        path_logic, path_nets = [], []
        for line in lines[start + 1:stops[0] + 1]:
            hit = re.search(r'^\s+SLICE_\S+\s+(?:FD\w+\s+)?[rf]\s+(\S+)/(I\d+|D|CLR|PRE)$', line)
            if hit:
                input_cell, input_pin = hit.groups()
                require(pending_net is not None, 'Missing connecting net: ' + label)
                path_nets.append([label, *pending_net, input_cell, input_pin])
                pending_net = None
            hit = re.search(r'^\s+([\d.]+)\s+[\d.]+\s+[rf]\s+(\S+)/(Q|O)$', line)
            if hit:
                delay, cell, output_pin = hit.groups()
                require(cell == input_cell, 'Input/output cell mismatch: ' + label)
                path_logic.append([label, cell, input_pin, output_pin, str(round(float(delay) * 1000))])
                previous_output = (cell, output_pin)
            hit = re.search(r'net \(fo=\d+, (?:estimated|routed)\)\s+([\d.]+)\s+[\d.]+\s+(\S+)', line)
            if hit:
                delay, name = hit.groups()
                require(previous_output is not None and pending_net is None, 'Unmatched net: ' + label)
                pending_net = [name, *previous_output, str(round(float(delay) * 1000))]
        require(len(path_logic) == spec['logic_arcs'] and len(path_nets) == len(path_logic), 'Incomplete/unsupported path parse: ' + label)
        require('/'.join((input_cell, input_pin)) == dest and pending_net is None, 'Endpoint mismatch')
        header = re.search(r'Data Path Delay:\s+([\d.]+)ns\s+\(logic\s+([\d.]+)ns', hits[0])
        require(header is not None, 'Missing report logic total')
        require(sum(int(x[4]) for x in path_logic) == round(float(header[2]) * 1000), 'Logic sum does not match report')
        logic.extend(path_logic)
        nets.extend(path_nets)
        checks.append([label, input_cell, input_pin])
        matched.append(dict(spec, vivado_logic_ps=round(float(header[2]) * 1000), vivado_data_ps=round(float(header[1]) * 1000)))
    require(bool(logic), 'No selected paths')
    return logic, nets, checks, matched

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle-root', 'tool-root', 'java-home', 'output-root', 'paths'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('dcp', 'edif', 'report'):
        parser.add_argument('--' + name, required=True, help='Exact relative path inside bundle')
    args = parser.parse_args()
    bundle, tool, jdk, output = (getattr(args, x).resolve() for x in ('bundle_root', 'tool_root', 'java_home', 'output_root'))
    require(bundle.is_dir() and output.is_dir(), 'Bundle/output roots must exist')
    require(not output.is_relative_to(bundle), 'Output must be outside input bundle')
    paths = {key: contained(bundle, getattr(args, key)) for key in ('dcp', 'edif', 'report')}
    for name, digest in LOCKS.items():
        require((tool / name).is_file() and sha(tool / name) == digest, 'Tool/model hash mismatch: ' + name)
    for name in ('java', 'javac'):
        require((jdk / 'bin' / name).is_file(), 'Missing explicit JDK executable: ' + name)
    # Hash every file, including the original checksum/provenance files.
    original = {str(p.relative_to(bundle)): sha(p) for p in sorted(bundle.rglob('*')) if p.is_file()}
    selections_raw = args.paths.read_bytes()
    selections = json.loads(selections_raw)
    run = Path(tempfile.mkdtemp(prefix='timing-reference-', dir=output))
    print(run, flush=True)
    receipt = {'status': 'FAILED', 'inputs_preserved': False, 'input_hashes': original,
               'tool_locks': LOCKS, 'scope': 'primitive arcs only; no full-path timing qualification'}
    start_time = time.monotonic()
    snapshots = {}
    try:
        inp = run / 'inputs'
        inp.mkdir()
        for name, source in paths.items():
            target = inp / (name + source.suffix)
            shutil.copyfile(source, target)
            require(sha(target) == original[str(source.relative_to(bundle))], 'Snapshot mismatch')
            target.chmod(0o444)
            snapshots[name] = target
        (run / 'path-selection.json').write_bytes(selections_raw)
        source_dir = run / 'source'
        source_dir.mkdir()
        for name in ('run.py', 'TimingReference.java'):
            shutil.copyfile(Path(__file__).resolve().parent / name, source_dir / name)
        receipt['source_hashes'] = {p.name: sha(p) for p in source_dir.iterdir()}
        receipt['jdk_hashes'] = {name: sha(jdk / 'bin' / name) for name in ('java', 'javac')}
        receipt['device_hashes'] = {str(p.relative_to(tool)): sha(p) for p in (tool / 'rapidwright/data').rglob('*') if p.is_file()}
        logic, nets, checks, matched = parse_paths(snapshots['report'].read_text(), selections)
        for name, rows in (('logic-input.tsv', logic), ('net-input.tsv', nets), ('checks-input.tsv', checks)):
            with (run / name).open('w') as stream:
                csv.writer(stream, delimiter='\t', lineterminator='\n').writerows(rows)
        (run / 'matched-paths.json').write_text(json.dumps(matched, indent=2) + '\n')
        jar = tool / next(iter(LOCKS))
        env = os.environ.copy()
        env['RAPIDWRIGHT_PATH'] = str(tool / 'rapidwright')
        for name in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS'):
            env.pop(name, None)
        classes = run / 'classes'
        classes.mkdir()
        with (run / 'compile.log').open('w') as stream:
            subprocess.run([str(jdk / 'bin/javac'), '-cp', str(jar), '-d', str(classes), str(source_dir / 'TimingReference.java')], env=env, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=90)
        command = [str(jdk / 'bin/java'), '-Xmx4g', '-XX:ActiveProcessorCount=2', '-cp', str(jar) + os.pathsep + str(classes), 'TimingReference', str(snapshots['dcp']), str(snapshots['edif']), str(run / 'logic-input.tsv'), str(run / 'net-input.tsv'), str(run / 'checks-input.tsv')]
        (run / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
        with (run / 'run.log').open('w') as stream:
            subprocess.run(command, cwd=run, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=600)
        with (run / 'logic-results.tsv').open() as stream:
            results = list(csv.DictReader(stream, delimiter='\t'))
        require(len(results) == len(logic) and all(x['status'] == 'SUPPORTED' and int(x['rw_ps']) >= 0 for x in results), 'Incomplete/unsupported primitive arcs; no logic aggregate')
        summary = {'full_path_estimate_valid': False, 'paths': {}}
        for spec in matched:
            rows = [x for x in results if x['path'] == spec['label']]
            require(len(rows) == spec['logic_arcs'], 'Incomplete primitive path')
            rw = sum(int(x['rw_ps']) for x in rows)
            summary['paths'][spec['label']] = dict(spec, rw_logic_ps=rw, observed_difference_ps=rw - spec['vivado_logic_ps'])
        (run / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        receipt['status'] = 'COMPLETE_PRIMITIVE_REFERENCE'
    except Exception as error:
        receipt['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        after = {str(p.relative_to(bundle)): sha(p) for p in sorted(bundle.rglob('*')) if p.is_file()}
        receipt['inputs_preserved'] = original == after
        receipt['snapshots_preserved'] = all(sha(p) == original[str(paths[key].relative_to(bundle))] for key, p in snapshots.items())
        if not receipt['inputs_preserved'] or not receipt['snapshots_preserved']:
            receipt['status'] = 'FAILED_INPUT_INTEGRITY'
        receipt['elapsed_seconds'] = time.monotonic() - start_time
        receipt['outputs'] = {str(p.relative_to(run)): sha(p) for p in run.rglob('*') if p.is_file()}
        (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        require(receipt['inputs_preserved'] and receipt['snapshots_preserved'], 'Input integrity changed')

if __name__ == '__main__':
    main()
