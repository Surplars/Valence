#!/usr/bin/env python3
"""Bounded four-state proof of real APLIC-to-IMSIC MSI admission and terminal drain.

Uses existing compiled classes and explicit native tools. No DUT RTL rewrite,
forced register, generated interrupt producer, clock gating, or physical claim.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from bringup import Guard, classpath_manifest, verify_classpath_unchanged
import run as common


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--classpath', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    for tool in ('java', 'firtool', 'iverilog', 'vvp'):
        parser.add_argument('--' + tool, type=Path, required=True)
    # Include executables behind a distribution wrapper, e.g. ivl/ivlpp/vvp.tgt.
    parser.add_argument('--tool-input', action='append', type=Path, default=[])
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    cp, manifest = classpath_manifest(args.classpath, 'ip.MsiAdmissionBarrierNativeMain')
    guard = Guard(args.output)
    sources = [common.ROOT / name for name in (
        'AGENTS.md', 'build.mill', 'scripts/cloud/env.sh',
        'src/main/scala/ip/bus/RegisterPort.scala',
        'src/main/scala/ip/bus/TwoMasterRegisterArbiter.scala',
        'src/main/scala/ip/interrupt/Aplic.scala', 'src/main/scala/ip/interrupt/Imsic.scala',
        'src/main/scala/platform/CommonInterruptFabric.scala',
        'src/main/scala/ip/interrupt/MsiAdmissionBarrier.scala',
        'src/test/scala/ip/MsiAdmissionBarrierNative.scala',
        'simulator/gsim/harness/msi_admission_barrier.sv',
        'simulator/gsim/bringup.py', 'simulator/gsim/run.py')]
    sources += [Path(__file__).resolve()]
    hashes = lambda: {str(path.relative_to(common.ROOT)): sha(path) for path in sources}
    tools = [getattr(args, tool).resolve() for tool in ('java', 'firtool', 'iverilog', 'vvp')]
    tools += [path.resolve() for path in args.tool_input]
    tool_hashes = lambda: {str(path): sha(path) for path in tools}
    report = dict(status='RUNNING', source_sha256=hashes(), tool_sha256=tool_hashes(), classpath=manifest,
        scope='Actual CommonInterruptFabric APLIC pair, MSI barrier, and Imsic; one synchronous reset epoch',
        no_claim=['CDC', 'whole-AON acknowledgement', 'DRP', 'clock gating', 'routed timing', 'board behavior'],
        oracle='Independent accepted/issued/consumed FIFO plus software-specified IMSIC CSR pending and claims',
        semantics='One owed MSI per distinct configured source episode; persistent high level is not a pulse train; pending edges may coalesce',
        cases=['pre/post-stop events', 'advertised request stability', 'request/reply/terminal backpressure',
               'accepted-owner drain while held', 'APLIC architectural pending retention', 'M/S arbitration',
               'pending-but-unaccepted does not block idle', 'persistent level high', 'exactly-once identities',
               'repeated stop/resume/cancel-like decisions', 'bounded admission credits', 'coordinated reset',
               'cold-reset supervisor-first request'], negatives={})
    try:
        target = args.output / 'rtl'
        guard.run('emit', [args.java, '-Xmx1g', '-XX:ActiveProcessorCount=2',
            f'-Dchisel.project.root={common.ROOT}', '-cp', cp, 'ip.MsiAdmissionBarrierNativeMain', target])
        rtl = target / 'MsiAdmissionBarrierNative.sv'
        guard.run('lower', [args.firtool, target / 'MsiAdmissionBarrierNative.fir',
            '--disable-all-randomization', '--strip-debug-info', '--verification-flavor=if-else-fatal',
            '--default-layer-specialization=enable',
            '--lowering-options=disallowLocalVariables,disallowPackedArrays', '-o', rtl])
        # Generate only top-level declarations and deterministic input setup.
        # The original DUT and all generated assertions are compiled unchanged.
        header = re.search(r'module MsiAdmissionBarrierNative\((.*?)\);', rtl.read_text(), re.S).group(1)
        header = re.sub(r'//[^\n]*', '', header)
        direction = width = ''
        declarations, initializers = [], []
        for entry in header.split(','):
            entry = entry.strip()
            match = re.match(r'(input|output)\s*(\[[^]]+\])?\s*(\w+)$', entry)
            if match:
                direction, width, name = match.group(1), match.group(2) or '', match.group(3)
            else:
                assert re.fullmatch(r'\w+', entry), entry
                name = entry
            declarations.append(f"    {'reg' if direction == 'input' else 'wire'} {width} {name};")
            if direction == 'input':
                initializers.append(f"        {name} = '0;")
        (target / 'signals.svh').write_text('\n'.join(declarations) + '\n    MsiAdmissionBarrierNative dut (.*);\n')
        (target / 'initialize.svh').write_text('\n'.join(initializers) + '\n')
        binary = args.output / 'run.vvp'
        guard.run('compile', [args.iverilog, '-g2012', '-s', 'tb', '-I', target, '-o', binary, rtl,
            common.HERE / 'harness/msi_admission_barrier.sv'])
        positive = guard.run('positive', [args.vvp, binary])
        assert 'MSI_ADMISSION_REAL_APLIC_IMSIC_PASS' in positive, positive
        for case, anchor in (
            ('negative_ledger', 'negative owner ledger oracle mismatch'),
            ('negative_payload', 'MSI ordered payload oracle mismatch'),
            ('negative_pending', 'IMSIC architectural pending oracle mismatch')):
            output = guard.run(case, [args.vvp, binary, '+' + case], expected=1)
            assert anchor in output and 'MSI_ADMISSION_REAL_APLIC_IMSIC_PASS' not in output, output
            report['negatives'][case] = dict(status='EXPECTED_REJECTION', anchor=anchor)
        verify_classpath_unchanged(manifest)
        assert hashes() == report['source_sha256'], 'source drift during proof'
        assert tool_hashes() == report['tool_sha256'], 'tool drift during proof'
        report.update(status='PASS_REAL_APLIC_IMSIC_MSI_ADMISSION', source_drift=False, tool_drift=False)
    except BaseException as error:
        report.update(status='FAIL', error=str(error))
        raise
    finally:
        report['commands'] = guard.records
        report['output_sha256'] = {str(path.relative_to(args.output)): sha(path)
            for path in args.output.rglob('*') if path.is_file() and path.name != 'receipt.json'}
        (args.output / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    print(report['status'])


if __name__ == '__main__':
    main()
