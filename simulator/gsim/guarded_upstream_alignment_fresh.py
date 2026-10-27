#!/usr/bin/env python3
"""Two unchanged small producer fixtures; not full-CPU misalignment coverage."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import run as common
import a1_common_cpu_retirement as base
import gsim_initialization_epoch as epoch


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--gsim', required=True, type=Path)
    ap.add_argument('--compile-receipt', required=True, type=Path)
    ap.add_argument('--tool-receipt', required=True, type=Path)
    args = ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        raise ValueError('safe fresh tag required')
    spec = importlib.util.spec_from_file_location('compile_gate', common.ROOT / 'fpga/common/scala_compile_receipt.py')
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    gate.verify_receipt(args.compile_receipt, common.ROOT)
    tools = epoch.tool_binding(args.tool_receipt)
    if args.gsim.resolve() != Path(tools['gsim']['path']).resolve():
        raise ValueError('pinned GSIM required')
    sources = sorted((common.ROOT / 'src/main/scala').rglob('*.scala')) + sorted((common.ROOT / 'src/test/scala').rglob('*.scala'))
    sources += [Path(epoch.__file__).resolve(), Path(__file__).resolve(), Path(base.__file__).resolve(), common.ROOT / 'fpga/common/scala_compile_receipt.py',
                common.HERE / 'run.py', common.HERE / 'harness/load_ready_direct.cpp',
                common.HERE / 'harness/fp_memory_pipeline.cpp']
    before = {str(p.relative_to(common.ROOT)): base.sha(p) for p in sources}
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'guarded-pmp-upstream-alignment-repaired-epoch-v1', 'status': 'RUNNING', 'sources': before,
              'tools_before': tools, 'tool_receipt_sha256': base.sha(args.tool_receipt), 'compile_receipt_sha256': base.sha(args.compile_receipt), 'checks': {},
              'scope': 'Existing direct LSU registerStart false/true and one FP memory pipeline; no DTA or full CPU. Misaligned ordinary load/store and FP32/64 load/store cause/tval/no-request checks. AMO misalignment and fast-store rejection remain source-audit only.'}
    def save():
        (out / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    save()
    try:
        cases = [
            ('lsu', 'ooo.LoadReadyDirectGsimMain', 'LoadReadyDirectGsim', 'load_ready_direct.cpp', ('0',),
             ('--enabled=0',), ('--enabled=0', '--mutate-store-initial-cause'), 'LOAD_READY_DIRECT_PASS',
             'LOAD_READY_DIRECT_FAIL', 'ACTUAL_CORRUPTION kind=host-sampled-observation'),
            ('fp', 'ooo.FpMemoryPipelineGsimMain', 'FpMemoryPipelineGsim', 'fp_memory_pipeline.cpp', (), (),
             ('--inject-mismatch',), 'FP_MEMORY_PIPELINE_PASS', 'FP memory boundary oracle mismatch', None),
        ]
        for name, main_class, top, host, parameters, runtime, negative, marker, diagnostic, reached in cases:
            gate.verify_receipt(args.compile_receipt, common.ROOT)
            model = common.test(args.gsim, tools['compiler']['command'], args.tag + '/' + name,
                                main_class, top, host, parameters=parameters, runtime_args=runtime,
                                defines={}, timeout=120)
            log = (model / 'test.log').read_text()
            if marker not in log:
                raise ValueError('missing result marker: ' + name)
            result = subprocess.run([str(model / 'run'), *negative], env=base.runtime_env(),
                                    capture_output=True, text=True, timeout=120)
            text = result.stdout + result.stderr
            (model / 'negative.log').write_text(text)
            if result.returncode != 1 or diagnostic not in text or (reached and reached not in text):
                raise ValueError('negative did not reach independent oracle: ' + name)
            if 'ERROR: AddressSanitizer' in text or 'runtime error:' in text:
                raise ValueError('negative sanitizer error')
            report['checks'][name] = {'log': log.strip(), 'negative_exit': result.returncode,
                'negative_kind': 'observation/oracle sensitivity, not RTL mutation',
                'artifacts': {str(p.relative_to(out)): base.sha(p) for p in model.rglob('*') if p.is_file()}}
            save()
        gate.verify_receipt(args.compile_receipt, common.ROOT)
        report['status'] = 'PASS_EXISTING_UPSTREAM_ALIGNMENT_FIXTURES'
    except BaseException as error:
        report.update(status='FAIL', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        report['sources_unchanged'] = before == {str(p.relative_to(common.ROOT)): base.sha(p) for p in sources}
        report['tools_unchanged'] = tools == epoch.tool_binding(args.tool_receipt)
        if not report['sources_unchanged'] or not report['tools_unchanged']:
            report['status'] = 'FAIL_SOURCE_OR_TOOL_DRIFT'
        save()
    if report['status'] != 'PASS_EXISTING_UPSTREAM_ALIGNMENT_FIXTURES':
        raise ValueError(report['status'])
    print(report['status'])


if __name__ == '__main__':
    main()
