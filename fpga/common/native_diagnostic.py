#!/usr/bin/env python3
"""Small native-only diagnostic runner; never a signoff or recovery seal producer."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
STATUS = 'DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM'
STAGES = ('fresh', 'raw', 'synthesized', 'optimized-raw', 'optimized', 'placed', 'physical', 'routed')
PHASES = ('post_synth', 'post_opt', 'preplace', 'pre_route')
# Every supported start stage ends in the same routed-report phase, including
# report-only routed resume. Do not demand intermediate-stage reports.
ROUTED_REPORTS = ('timing.rpt', 'coverage.rpt', 'clocks.rpt', 'route.rpt',
                  'drc.rpt', 'cdc.rpt', 'bus-skew.rpt', 'utilization.rpt')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def checked_spec(spec):
    """Resolve explicit input paths. No old baseline, run STATUS, or synthesized seal."""
    if not all(isinstance(spec.get(k), str) and spec[k] for k in ('origin', 'part', 'top', 'vivado_version')):
        raise ValueError('origin, part, top and vivado_version are required')
    if type(spec.get('threads')) is not int or spec['threads'] < 8:
        raise ValueError('threads must be at least 8 (not a claim of active workers)')
    spec = json.loads(json.dumps(spec))
    spec.setdefault('phys_opt', False)
    if type(spec['phys_opt']) is not bool:
        raise ValueError('phys_opt must be an explicit boolean')
    root = Path(spec['root']).resolve(strict=True)
    spec['root'] = str(root)
    inputs = set()

    def path(value):
        p = Path(value)
        p = (root / p).resolve(strict=True)
        if not p.is_file():
            raise ValueError('Not an input file: ' + str(p))
        inputs.add(str(p))
        return str(p)

    for key in ('sources', 'rtl', 'pre_synth_xdc'):
        if not isinstance(spec.get(key), list) or not spec[key]:
            raise ValueError('Nonempty explicit ' + key + ' list required')
        spec[key] = [path(p) for p in spec[key]]
    spec['late_synth_xdc'] = [path(p) for p in spec.get('late_synth_xdc', [])]
    if not isinstance(spec.get('clock_requirements'), list) or not spec['clock_requirements']:
        raise ValueError('Explicit clock pin/period requirements required')
    for clock in spec['clock_requirements']:
        if not isinstance(clock.get('pin'), str) or not clock['pin'] or type(clock.get('period_ns')) not in (int, float) or not 0 < clock['period_ns'] < 1e6:
            raise ValueError('Invalid clock requirement')
    for phase in PHASES:
        if phase not in spec or not isinstance(spec[phase], list):
            raise ValueError('Explicit constraint phase required: ' + phase)
        for entry in spec[phase]:
            if entry.get('kind') not in ('tcl', 'xdc'):
                raise ValueError('Constraint kind must be tcl or xdc')
            entry['path'] = path(entry['path'])
    if not spec['post_synth']:
        raise ValueError('Post-synthesis constraints must be explicit, not assumed')
    if not isinstance(spec.get('ips'), list) or not spec['ips']:
        raise ValueError('Existing IP XCI and DCP inputs required')
    for ip in spec['ips']:
        for key in ('xci', 'dcp'):
            ip[key] = path(ip[key])
        if Path(ip['xci']).suffix.lower() != '.xci' or Path(ip['dcp']).suffix.lower() != '.dcp' or not Path(ip['dcp']).stat().st_size:
            raise ValueError('Nonempty existing IP DCP and XCI required')
        # Include XCI companion output products (including HDL/XDC/ROM init).
        # The caller must list every relevant generated-product directory.
        if not ip.get('product_dirs'):
            raise ValueError('IP generated product_dirs required')
        directories = []
        for directory in ip['product_dirs']:
            directory = (root / directory).resolve(strict=True)
            if not directory.is_dir():
                raise ValueError('Not an IP product directory')
            directories.append(str(directory))
            for product in sorted(directory.rglob('*')):
                if product.is_file():
                    path(product)
        ip['product_dirs'] = directories
    for key in ('defines', 'include_dirs'):
        if not isinstance(spec.get(key, []), list):
            raise ValueError(key + ' must be a list')
    spec['include_dirs'] = [str((root / p).resolve(strict=True)) for p in spec.get('include_dirs', [])]
    # Included headers and sourced helper scripts belong in sources. This is an
    # explicit source inventory, not a claim of automatically proven closure.
    return spec, {p: sha(p) for p in sorted(inputs)}


def prepare(spec_path, manifest_path):
    spec, inputs = checked_spec(json.loads(Path(spec_path).read_text(encoding='utf-8')))
    record = dict(schema='native-diagnostic-inputs-v1', status=STATUS, qualification=False,
                  spec=spec, inputs_sha256=inputs)
    write_json(manifest_path, record)
    return record


def verify(manifest_path):
    record = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if record.get('schema') != 'native-diagnostic-inputs-v1' or record.get('status') != STATUS or record.get('qualification') is not False:
        raise ValueError('Not a native diagnostic input manifest')
    spec, inputs = checked_spec(record['spec'])
    if inputs != record['inputs_sha256'] or spec != record['spec']:
        raise ValueError('Source/IP/constraint input changed since prepare')
    return record


def word(value):
    """A single Tcl word, including Windows paths, without command substitution."""
    value = str(value)
    if '\x00' in value or '\n' in value or '\r' in value:
        raise ValueError('Tcl values must be single-line strings')
    return '"' + ''.join('\\' + c if c in '\\"$[]' else c for c in value) + '"'


def config(spec, checkpoint, stage):
    lines = []
    for key in ('root', 'part', 'top', 'threads', 'vivado_version'):
        lines.append('set native(%s) %s' % (key, word(spec[key])))
    for key in ('rtl', 'pre_synth_xdc', 'late_synth_xdc', 'defines', 'include_dirs'):
        lines.append('set native(%s) [list %s]' % (key, ' '.join(word(x) for x in spec.get(key, []))))
    lines.append('set native(phys_opt) ' + str(int(spec['phys_opt'])))
    for phase in PHASES:
        entries = ' '.join('[list %s %s]' % (word(e['kind']), word(e['path'])) for e in spec[phase])
        lines.append('set native(%s) [list %s]' % (phase, entries))
    clocks = ' '.join('[list %s %s]' % (word(c['pin']), word(c['period_ns'])) for c in spec['clock_requirements'])
    lines.append('set native(clock_requirements) [list %s]' % clocks)
    entries = ' '.join('[list %s %s]' % (word(ip['xci']), word(ip['dcp'])) for ip in spec['ips'])
    lines += ['set native(ips) [list %s]' % entries,
              'set native(checkpoint) ' + word(checkpoint or ''), 'set native(stage) ' + word(stage)]
    return '\n'.join(lines) + '\n'


def run(manifest, output, vivado, checkpoint=None, stage='fresh', expected=None):
    manifest = Path(manifest).resolve(strict=True)
    record = verify(manifest)
    if stage not in STAGES or (stage == 'fresh') != (checkpoint is None):
        raise ValueError('Resume requires checkpoint, explicit completed stage and SHA256')
    if checkpoint is not None:
        checkpoint = Path(checkpoint).resolve(strict=True)
        if not expected or sha(checkpoint) != expected:
            raise ValueError('Resume checkpoint SHA256 missing or changed')
    elif expected is not None:
        raise ValueError('Unexpected checkpoint SHA256 for fresh synthesis')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    invocation = dict(status=STATUS, qualification=False, manifest=str(manifest),
                      manifest_sha256=sha(manifest), start_stage=stage,
                      input_checkpoint=str(checkpoint) if checkpoint else None,
                      input_checkpoint_sha256=expected,
                      checkpoint_stage_basis='explicit operator selection; not a qualification seal',
                      tools_sha256={p.name: sha(p) for p in (HERE/'native_diagnostic.py', HERE/'native_diagnostic.tcl')})
    write_json(output/'invocation.json', invocation)
    (output/'config.tcl').write_text(config(record['spec'], checkpoint, stage), encoding='utf-8')
    command = [vivado, '-mode', 'batch', '-source', str(HERE/'native_diagnostic.tcl'),
               '-tclargs', str(output/'config.tcl')]
    try:
        with (output/'console.log').open('x', encoding='utf-8') as log:
            result = subprocess.run(command, cwd=output, stdout=log, stderr=subprocess.STDOUT, check=False)
        if result.returncode:
            raise ValueError('Vivado failed with exit code %s; preserved checkpoints remain diagnostic-only' % result.returncode)
        if sha(manifest) != invocation['manifest_sha256'] or verify(manifest) != record:
            raise ValueError('Inputs changed while Vivado was running')
        if checkpoint and sha(checkpoint) != expected:
            raise ValueError('Resume input changed while Vivado was running')
        if any(sha(HERE/name) != digest for name, digest in invocation['tools_sha256'].items()):
            raise ValueError('Runner changed while Vivado was running')
        if not (output/'native-complete.txt').is_file() or not (output/'routed-unqualified.dcp').is_file():
            raise ValueError('Native completion/checkpoint missing')
        for name in ROUTED_REPORTS:
            report = output/name
            if not report.is_file() or not report.stat().st_size:
                raise ValueError('Required routed report missing or empty: ' + name)
        write_json(output/'outputs.json', dict(status=STATUS, qualification=False,
                   native_commands_returned=True, timing_pass_not_asserted=True,
                   files_sha256={p.name: sha(p) for p in sorted(output.iterdir()) if p.suffix in ('.dcp', '.rpt')}))
    except (OSError, ValueError) as exc:
        write_json(output/'failure.json', dict(status=STATUS, qualification=False, error=str(exc)))
        raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    p = sub.add_parser('prepare'); p.add_argument('spec'); p.add_argument('manifest')
    p = sub.add_parser('check'); p.add_argument('manifest')
    p = sub.add_parser('run'); p.add_argument('manifest'); p.add_argument('output')
    p.add_argument('--vivado', default='vivado'); p.add_argument('--checkpoint')
    p.add_argument('--stage', choices=STAGES, default='fresh'); p.add_argument('--sha256')
    args = parser.parse_args()
    try:
        if args.mode == 'prepare': prepare(args.spec, args.manifest)
        elif args.mode == 'check': verify(args.manifest)
        else: run(args.manifest, args.output, args.vivado, args.checkpoint, args.stage, args.sha256)
        print(STATUS)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
