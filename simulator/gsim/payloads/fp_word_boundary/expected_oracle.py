#!/usr/bin/env python3
"""Exact-rational fixed-vector audit. No DUT/HardFloat constants or host FP arithmetic."""
from fractions import Fraction
import json
from pathlib import Path

def evaluate(c):
    eb, fb = (8, 23) if c['format'] == 's' else (11, 52)
    raw = int(c['bits'], 16)
    sign = raw >> (eb + fb)
    exponent = (raw >> fb) & ((1 << eb) - 1)
    fraction = raw & ((1 << fb) - 1)
    signed = c['operation'] == 'w'
    lo, hi = (-(1 << 31), (1 << 31)-1) if signed else (0, (1 << 32)-1)
    invalid = exponent == (1 << eb)-1
    if invalid:
        # RISC-V NaN saturates to the positive endpoint, including a sign-bit-1 NaN.
        value = hi if fraction or not sign else lo
        flags = 16
    else:
        mantissa = fraction + ((1 << fb) if exponent else 0)
        shift = (exponent if exponent else 1) - ((1 << (eb-1))-1) - fb
        exact = Fraction(mantissa * (-1 if sign else 1))
        exact = exact * (1 << shift) if shift >= 0 else exact / (1 << -shift)
        floor = exact.numerator // exact.denominator
        rem = exact - floor
        mode = c['rounding']
        if mode == 'rtz': value = int(exact)
        elif mode == 'rdn': value = floor
        elif mode == 'rne': value = floor + int(rem > Fraction(1,2) or (rem == Fraction(1,2) and floor % 2))
        else: raise AssertionError(mode)
        if not lo <= value <= hi:
            value = min(hi, max(lo, value)); flags = 16
        else: flags = int(Fraction(value) != exact)
    word = value & ((1 << 32)-1)
    result = word | (0xffffffff00000000 if word & (1 << 31) else 0)
    return result, flags

def main():
    cases = json.loads((Path(__file__).with_name('cases.json')).read_text())
    for c in cases:
        actual = evaluate(c)
        expected = (int(c['expected'],16), c['fflags'])
        assert actual == expected, (c['id'],c['reason'],actual,expected)
    print(f'FP_LITERAL_RATIONAL_ORACLE_PASS cases={len(cases)}')
if __name__ == '__main__': main()
