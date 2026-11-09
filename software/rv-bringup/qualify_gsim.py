#!/usr/bin/env python3
"""Run the actual boot binary on a hash-bound, previously qualified GSIM system."""
from pathlib import Path
import argparse, hashlib, json, os, subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--image-dir', type=Path, required=True)
parser.add_argument('--model-dir', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
a = parser.parse_args()
root = Path(__file__).resolve().parents[2]
image_dir, model, out = (p.resolve() for p in (a.image_dir, a.model_dir, a.output))
assert out.is_relative_to(root / 'build')
out.mkdir(parents=True, exist_ok=False)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
record = {'status': 'RUNNING', 'commands': [], 'scope': 'RV boot image, CPU, caches, AXI fabric and CMU; PS hard IP is not simulated'}
def save():
    (out / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
def run(argv, name, code=0, marker=''):
    argv = list(map(str, argv))
    record['commands'].append({'argv': argv, 'log': name})
    save()
    with (out / name).open('w') as log:
        result = subprocess.run(argv, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
    text = (out / name).read_text()
    assert result.returncode == code and marker in text, (name, result.returncode, text[-4000:])
    print(name, 'PASS', flush=True)
    return text
try:
    proof = json.loads((model / 'receipt.json').read_text())
    assert all(sha(model / name) == expected for name, expected in proof['model_sha256'].items())
    functional = json.loads((model.parent / 'functional-final-receipt.json').read_text())
    assert functional['status'] == 'PASS_FINAL_H_GUEST_SYSTEM_AND_CMU_DIRECTED'
    image = json.loads((image_dir / 'receipt.json').read_text())
    assert image['status'] == 'PASS_RV64_REAL_DDR_SELFTEST_IMAGE_BUILT'
    assert all(sha(image_dir / name) == expected for name, expected in image['artifact_sha256'].items())
    driver = root / 'simulator/gsim/harness/i1_ps_rpu_handoff.cpp'
    memory = root / 'simulator/gsim/harness/i1_axi_memory_reference.h'
    assert sha(memory) == functional['test_sources'][str(memory.relative_to(root))]
    record.update(model_receipt_sha256=sha(model / 'receipt.json'),
                  qualified_function_receipt_sha256=sha(model.parent / 'functional-final-receipt.json'),
                  image_receipt_sha256=sha(image_dir / 'receipt.json'),
                  source_sha256={str(p.relative_to(root)): sha(p) for p in (driver, memory, Path(__file__))})
    flags = ['clang++-19', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
    run([*flags, '-I' + str(model), *sorted(model.glob('I1SpinorManagedSystem[0-9]*.o')),
         driver, '-o', out / 'run'], 'compile.log')
    args = [out / 'run', image_dir / 'rv-selftest.bin', str(image['image_crc32']),
            str(image['symbols']['__i1_breakpoint_probe'])]
    positive = run(args, 'positive.log', marker='I1_PS_RPU_HANDOFF_PASS')
    assert positive.count('I1_PS_RPU_HANDOFF_PASS') == 8
    run([*args, '--inject-result'], 'negative.log', code=1, marker='independent RPU/RV DDR result oracle')
    record.update(status='PASS_REAL_RV_IMAGE_PUBLISH_RESULT_AND_PRECISE_TRAP', cases=8,
                  independent_negative_oracles=1, positive=positive)
except BaseException as error:
    record.update(status='FAIL', error=repr(error))
    raise
finally:
    record['artifacts_sha256'] = {p.name: sha(p) for p in out.glob('*.log')}
    save()
print(record['status'], flush=True)
