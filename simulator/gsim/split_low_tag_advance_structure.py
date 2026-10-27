#!/usr/bin/env python3
"""Fail-closed actual Ledger CHIRRTL arithmetic-only delta audit.

Not a timing/area proof. No constant propagation, Boolean sensitization, or
assumed unreachable admission states. The separate formal runner proves values.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from registered_raw_certified_cones import read_modules, require
from guarded_natural_pmp_structure import parse, refs


def normalized_annotations(text):
    # Quoted diagnostics are opaque; strip only actual source locator tokens.
    return re.sub(r'"(?:\\.|[^"\\])*"| @\[[^\]\n]*\]',
                  lambda m: m[0] if m[0].startswith('"') else '', text)


def review(control, candidate):
    ct, cm = read_modules(normalized_annotations(control))
    st, sm = read_modules(normalized_annotations(candidate))
    require(ct == st == 'RenameRob', 'require actual untapped RenameRob top')
    require(cm.keys() == sm.keys(), 'module inventory changed')
    c, s = cm[ct], sm[st]
    for module in (c, s):
        names = [m[1] for _, line, _ in module.body
                 if (m := re.fullmatch(r'node ([A-Za-z_][A-Za-z_0-9$]*) = (.+)', line))]
        require(len(names) == len(set(names)), 'duplicate emitted node name')
    def nodes(module):
        return {m[1]:m[2] for _,line,_ in module.body
                if (m := re.fullmatch(r'node ([A-Za-z_][A-Za-z_0-9$]*) = (.+)', line))}
    cn, sn = nodes(c), nodes(s)
    require(cn.get('advancedTag') == 'add(nextTag, allocatedCount)', 
            'control arithmetic is not the qualified full-width add')
    require('advancedTag' in sn, 'missing candidate advancedTag')
    expected = parse('cat(mux(bits(add(bits(nextTag, 1, 0), allocatedCount), 2, 2), '
        'add(bits(nextTag, 63, 2), UInt<1>(0h1)), '
        'cat(UInt<1>(0h0), bits(nextTag, 63, 2))), '
        'bits(add(bits(nextTag, 1, 0), allocatedCount), 1, 0))')
    def expand(value, active=()):
        if value[0] == 'ref':
            name = value[1]
            if name in ('nextTag', 'allocatedCount'): return value
            require(name in sn and name not in active, 'unknown/cyclic helper dependency: '+name)
            return expand(parse(sn[name]), active+(name,))
        if value[0] in ('lit','num'): return value
        return (value[0], *(expand(x, active) for x in value[1:]))
    actual = expand(parse(sn['advancedTag']))
    require(actual == expected, 'candidate emitted arithmetic is not exact low2 carry/high62 preincrement')
    # Remove only private combinational nodes reachable from advancedTag. Inputs
    # are intentionally cut at actual count and register; no control is removed.
    removed = set()
    def visit(name):
        if name in ('nextTag', 'allocatedCount'): return
        require(name in sn, 'unexpected helper dependency: '+name)
        if name in removed: return
        removed.add(name)
        for dep in refs(parse(sn[name])): visit(dep)
    visit('advancedTag')
    def normalized(mod, candidate=False):
        result = []
        for indent, line, _ in mod.body:
            m = re.fullmatch(r'node ([A-Za-z_][A-Za-z_0-9$]*) = (.+)', line)
            if candidate and m and m[1] in removed:
                if m[1] == 'advancedTag':
                    result.append((indent, 'node advancedTag = add(nextTag, allocatedCount)'))
                continue
            result.append((indent, line))
        return result
    require(normalized(c) == normalized(s, True),
            'Ledger changed beyond the private combinational advancedTag expression')
    for name in cm:
        if name != ct:
            require(normalized(cm[name]) == normalized(sm[name]), 'other module changed: '+name)
    registers = [line for _,line,_ in s.body if re.match(r'reg(?:reset)? ', line)]
    require('regreset nextTag : UInt<64>, clock, reset, UInt<64>(0h0)' in registers,
            '64-bit nextTag reset storage changed')
    require('regreset exhausted : UInt<1>, clock, reset, UInt<1>(0h0)' in registers,
            'exhaustion reset storage changed')
    # Exact whole-module comparison also retains update count/recovery gates,
    # lane base+lane carries, prefix admission, credit logic and exhaustion hold.
    return {'status':'PASS_EXACT_EMITTED_ARITHMETIC_ONLY_DELTA',
        'top':'RenameRob','private_combinational_nodes':sorted(removed),
        'register_declarations':len(registers), 'state_delta':0,
        'high_increment_inputs':['nextTag[63:2]'],
        'late_count_enters':['low2_add','high_selection','unchanged_update_enable'],
        'limits':['CHIRRTL structural audit, not mapped timing or Fmax',
                  'count dependence is preserved in selection and update enable']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--control',type=Path,required=True)
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    result=review(a.control.read_text(),a.candidate.read_text())
    result['inputs']={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in (a.control,a.candidate)}
    result['checker_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    a.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__': main()
