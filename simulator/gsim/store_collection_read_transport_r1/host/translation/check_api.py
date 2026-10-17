#!/usr/bin/env python3
"""Static source/header validation only; never imports or invokes the DUT."""
import ast
import hashlib
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True
from ports import INPUTS, OUTPUTS, REQUEST_WIDTHS, method

HERE = Path(__file__).resolve().parent
HEADER = HERE.parent / 'translation-on/CollectionReadTranslationGsim.h'
for source in HERE.glob('*.py'):
    ast.parse(source.read_text(), filename=str(source))
text = HEADER.read_text()
declared = set(re.findall(r'\b((?:set|get)_[A-Za-z0-9_$]+)\s*\(', text))
expected = {method('set_', n) for n in INPUTS if not n.startswith(('pmpCfg.', 'pmpAddr.'))}
expected |= {method('get_', n) for n in OUTPUTS}
expected |= {'set_io$$pmpCfg', 'set_io$$pmpAddr', 'set_clock'}
if declared != expected:
    raise RuntimeError('API_SCHEMA_MISMATCH: ' + repr({'missing': sorted(expected - declared),
                                                     'unexpected': sorted(declared - expected)}))
for signature in ['void set_io$$pmpCfg(const uint8_t (&val)[16]);',
                  'void set_io$$pmpAddr(const uint64_t (&val)[16]);']:
    if signature not in text:
        raise RuntimeError('ARRAY_SIGNATURE_MISMATCH: ' + signature)
if sum(REQUEST_WIDTHS.values()) != 184:
    raise RuntimeError('REQUEST_ABI_WIDTH')
driver = HERE / 'driver.cpp'
if not driver.exists():
    raise RuntimeError('GENERATED_DRIVER_MISSING')
called = set(re.findall(r'\bd\.((?:set|get)_[A-Za-z0-9_$]+)\s*\(', driver.read_text()))
if called != expected - {'set_clock'}:
    raise RuntimeError('GENERATED_DRIVER_API_MISMATCH: ' + repr({
        'missing': sorted((expected - {'set_clock'}) - called),
        'unexpected': sorted(called - expected)}))
report = {'status': 'PASS', 'scope': 'Python AST and exact generated public setter/getter set only',
          'dut_executed': False, 'inputs': len(INPUTS), 'outputs': len(OUTPUTS),
          'request_bits': sum(REQUEST_WIDTHS.values()),
          'clock_note': 'set_clock intentionally unused; established driver protocol calls step once per frame',
          'bindings': [{'path': str(p), 'bytes': p.stat().st_size,
                        'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                       for p in [HEADER, HERE / 'ports.py', HERE / 'gen_driver.py', driver,
                                 HERE / 'cases.py', HERE / 'ORACLE_PLAN.md', Path(__file__).resolve()]]}
print(json.dumps(report, indent=2))
