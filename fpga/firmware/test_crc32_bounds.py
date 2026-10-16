#!/usr/bin/env python3
"""Sanitized CRC bounds, independent bitwise oracle, and two rejected mutations."""
from pathlib import Path
import json, os, subprocess, tempfile
SOURCE = Path(__file__).resolve().parent

def main():
    source = (SOURCE / 'crc32.c').read_text()
    cases = [
        ('slice2', source, True),
        ('wrong-table', source.replace('crc32_table[256+(crc&255)]', 'crc32_table[(crc&255)]'), False),
        ('tail-overread', source.replace('while(n>=2) {', 'while(n>=1) {'), False),
    ]
    results = []
    with tempfile.TemporaryDirectory(prefix='crc-bounds-') as temp:
        root = Path(temp)
        for name, text, success in cases:
            path, binary = root / (name + '.c'), root / name
            path.write_text(text)
            command = [os.environ.get('CC', 'cc'), '-O1', '-g', '-fsanitize=address,undefined',
                       '-fno-omit-frame-pointer', '-fno-sanitize-recover=all', '-DFIRMWARE_CRC_MODE=3', '-I' + str(SOURCE),
                       str(SOURCE / 'test_crc32_bounds.c'), str(path), '-o', str(binary)]
            subprocess.run(command, check=True)
            result = subprocess.run([str(binary)], text=True, capture_output=True,
                                    env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
            if success:
                assert result.returncode == 0, result.stderr
                assert 'CRC_BOUNDS_PASS cases=32784' in result.stdout
            elif name == 'tail-overread':
                assert result.returncode != 0 and 'use-after-poison' in result.stderr, result.stderr
            else:
                assert result.returncode != 0 and 'Assertion' in result.stderr, result.stderr
            results.append(dict(name=name, exit=result.returncode, expected_success=success))
    print(json.dumps(results))

if __name__ == '__main__':
    main()
