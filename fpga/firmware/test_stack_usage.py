#!/usr/bin/env python3
"""Metadata binding and independently exercised semantic stack-audit negative tests."""
import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
from audit_stack_usage import analyze, validate_snapshot


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True, help='existing qualified build_stack_usage output')
    args = ap.parse_args()
    original = args.out.resolve() / 'full'
    validate_snapshot(original)
    baseline = analyze(original)
    assert baseline['bounds']['boot_recover']['bytes'] == 1280
    results = []
    cases = ['rom-drift', 'metadata-drift', 'dynamic-frame', 'missing-frame',
             'budget-exact', 'budget-over', 'self-jal', 'self-jalr', 'internal-jump']
    for case in cases:
        with tempfile.TemporaryDirectory(prefix='stack-audit-test-') as temp:
            full = Path(temp)
            for f in [original/'bootrom.bin', original/'disasm.txt', *original.glob('bootrom.elf-*.su')]:
                shutil.copy2(f, full / f.name)
            if case == 'rom-drift':
                path = full/'bootrom.bin'
                data = bytearray(path.read_bytes()); data[-1] ^= 1; path.write_bytes(data)
            elif case in ('metadata-drift', 'dynamic-frame', 'missing-frame'):
                path = full/'bootrom.elf-crc32.su'
                text = path.read_text()
                path.write_text('' if case == 'missing-frame' else
                                text.replace('\t0\t', '\t1\t') if case == 'metadata-drift' else
                                text.replace('static', 'dynamic'))
            elif case.startswith('budget-'):
                path = full/'bootrom.elf-bootrom.su'
                text = path.read_text()
                # Normal bound1280 includes recovery frame32; replacing it by6944 gives exactly8192.
                text, n = re.subn(r'(:boot_recover\t)32\t',
                                 lambda m: m[1] + str(6944 + (case == 'budget-over')) + '\t', text)
                assert n == 1
                path.write_text(text)
            else:
                path = full/'disasm.txt'; text = path.read_text()
                word, mnemonic = {'self-jal': ('000000ef', 'jal'),
                                  'self-jalr': ('000080e7', 'jalr'),
                                  'internal-jump': ('0000006f', 'j')}[case]
                text, n = re.subn(r'(^[0-9a-f]+ <firmware_crc_update>:\n)',
                                 lambda m: m[1] + f'    800027f0: {word} {mnemonic} 800027f0 <firmware_crc_update>\n',
                                 text, flags=re.M)
                assert n == 1
                path.write_text(text)
            # Binding tests use the production gate. Semantic tests deliberately bypass
            # only that gate through the internal analyzer, never a production CLI option.
            expected = {'rom-drift': 'unqualified ROM', 'metadata-drift': 'unqualified stack',
                        'dynamic-frame': 'dynamic', 'missing-frame': 'firmware_crc_update',
                        'budget-over': 'stack budget exceeded', 'self-jal': 'recursion',
                        'self-jalr': 'recursion'}.get(case)
            try:
                result = validate_snapshot(full) if case in ('rom-drift', 'metadata-drift') else analyze(full)
            except AssertionError as error:
                assert expected and expected in str(error), (case, str(error))
                results.append(dict(case=case, rejected=True, gate='binding' if case.endswith('drift') else 'semantic'))
            else:
                assert expected is None, case
                if case == 'budget-exact': assert result['bounds']['boot_recover']['bytes'] == 8192
                else: assert result['bounds'] == baseline['bounds']
                results.append(dict(case=case, rejected=False, expected_pass=True))
    print(json.dumps(results, indent=2))

if __name__ == '__main__':
    main()
