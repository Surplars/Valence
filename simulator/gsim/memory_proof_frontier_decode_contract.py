#!/usr/bin/env python3
"""Small independent active-operand contract for the five authored request classes."""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--original-store-pattern', action='store_true')
a = p.parse_args()
# Class expectations are architectural operand contracts. Full addresses/register
# metadata are intentionally abstract and are not reconstructed from class words.
cases = [
    dict(name='add', instruction=0x13, memory=False, store=False, divide=False, system=False, immediate=True),
    dict(name='load', instruction=0x3003, memory=True, store=False, divide=False, system=False, immediate=True),
    dict(name='store', instruction=0x3023, memory=True, store=True, divide=False, system=False, immediate=a.original_store_pattern),
    dict(name='divide', instruction=(1 << 25) | (26 << 20) | (25 << 15) | (4 << 12) | (24 << 7) | 0x33,
         memory=False, store=False, divide=True, system=False, immediate=False),
    dict(name='csr', instruction=(0x180 << 20) | (31 << 15) | (1 << 12) | 0x73,
         memory=False, store=False, divide=False, system=True, immediate=True),
]
for c in cases:
    opcode = c['instruction'] & 127
    if opcode == 0x23 and c['immediate']:
        raise SystemExit('ordinary store decode requires register rs2 dependency (useImmediate=false)')
    expected = {
        0x13: (False, False, False, False, True),
        0x03: (True, False, False, False, True),
        0x23: (True, True, False, False, False),
        0x33: (False, False, True, False, False),
        0x73: (False, False, False, True, True),
    }[opcode]
    observed = tuple(c[k] for k in ['memory','store','divide','system','immediate'])
    assert observed == expected, (c['name'], observed, expected)
print(json.dumps({'status':'PASS','classes':len(cases),'scope':'active operand/class controls; synthetic operand metadata excluded'}))
