#!/usr/bin/env python3
"""Fail-closed emitted-shape checks for the guarded natural main DTA PMP.

This is a generated connectivity/Boolean-shape audit, not functional equivalence,
area/delay evidence, or a claim that arbitrary raw inputs retain old behavior.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from registered_raw_certified_cones import Cones, IDENT, Uncertain, require, split


def parse(expr):
    expr = expr.strip()
    m = re.fullmatch(r'UInt<(\d+)>\((?:0h([0-9a-fA-F]+)|(\d+))\)', expr)
    if m: return ('lit', int(m[1]), int(m[2], 16) if m[2] else int(m[3]))
    if re.fullmatch(r'\d+', expr): return ('num', int(expr))
    m = re.fullmatch(rf'({IDENT})\((.*)\)', expr)
    if m: return (m[1], *(parse(x) for x in split(m[2])))
    require(re.fullmatch(rf'{IDENT}(?:\.{IDENT}|\[\d+\])*', expr), 'unsupported expression: '+expr)
    return ('ref', expr)


class Expressions:
    def __init__(self, module):
        self.nodes, self.connections = {}, {}
        for indent, line, number in module.body:
            n = re.fullmatch(rf'node ({IDENT}) = (.+)', line)
            if n: self.nodes[n[1]] = parse(n[2])
            if line.startswith('connect '):
                dest, value = split(line[8:])
                self.connections.setdefault(dest, []).append((indent, parse(value), number))

    def final(self, name):
        require(name in self.connections, 'missing emitted driver: '+name)
        rows = self.connections[name]
        require(rows[-1][0] == 4, 'final driver must be unconditional: '+name)
        return rows[-1][1]

    def expand(self, value, stop=(), active=()):
        if value[0] == 'ref':
            name = value[1]
            if name in stop: return value
            replacement = self.nodes.get(name)
            if replacement is None and name in self.connections:
                replacement = self.final(name)
            if replacement is None: return value
            require(name not in active, 'cyclic emitted expression: '+name)
            return self.expand(replacement, stop, active+(name,))
        if value[0] in ('lit', 'num'): return value
        return (value[0], *(self.expand(x, stop, active) for x in value[1:]))


def refs(expr):
    if expr[0] == 'ref': return {expr[1]}
    if expr[0] in ('lit','num'): return set()
    return set().union(*(refs(x) for x in expr[1:]))


def evaluate(expr, values):
    op, *args = expr
    if op == 'ref':
        require(expr[1] in values, 'unbound proof input: '+expr[1]); return values[expr[1]]
    if op == 'lit': return expr[2], expr[1]
    def a(i): return evaluate(args[i], values)
    if op in ('eq','neq','and','or','xor'):
        x, wx = a(0); y, wy = a(1)
        if op == 'eq': return int(x == y), 1
        if op == 'neq': return int(x != y), 1
        return {'and':x&y,'or':x|y,'xor':x^y}[op], max(wx,wy)
    if op == 'not':
        x,w = a(0); return ((1<<w)-1)^x,w
    if op == 'mux':
        condition = a(0)[0]; x, wx = a(1); y, wy = a(2)
        return (x if condition else y), max(wx, wy)
    if op == 'bits':
        x,w = a(0); require(args[1][0] == args[2][0] == 'num', 'nonliteral bits')
        hi,lo = args[1][1],args[2][1]
        require(0<=lo<=hi<w, 'invalid bits proof'); return (x>>lo)&((1<<(hi-lo+1))-1),hi-lo+1
    if op == 'cat':
        x,wx = a(0);y,wy = a(1); return (x<<wy)|y,wx+wy
    raise Uncertain('unsupported proof primitive: '+op)


def negative(expr):
    return ('eq',expr,('lit',1,0))


def conjuncts(expr):
    if expr[0] == 'and': return conjuncts(expr[1])+conjuncts(expr[2])
    return [expr]


def review_text(text):
    cone = Cones(text)
    root = cone.root
    adapter = cone.modules[cone.instances[root]]
    ex = Expressions(adapter)
    pmps = [p for p,m in cone.instances.items() if re.fullmatch(r'PmpChecker(?:_\d+)?',m)]
    main = root+'.legacyPmp'
    require(main in pmps, 'missing original main checker')
    nextline = [p for p,m in cone.instances.items() if re.fullmatch(r'NextLineAuthorization(?:_\d+)?',m)]
    require(len(nextline)==1 and len(pmps)==2 and any(p.startswith(nextline[0]+'.') for p in pmps),
            'main/next-line checker count changed')
    require(not any('PmpGenericRange' in m for m in cone.instances.values()), 'factored helper combined unexpectedly')
    checker = cone.modules[cone.instances[main]]
    checker_ex = Expressions(checker)
    require(checker_ex.nodes.get('end') == parse('or(start, lastOffset)'), 'main checker is not natural endpoint OR')
    require(not any(re.search(r'\b(?:add|sub|mul|div|rem)\(', line) for _,line,_ in checker.body),
            'main checker retains endpoint arithmetic')
    require(not any('lowerEqual' in name or 'between' in name for name in checker_ex.nodes),
            'shared-bound specialization enabled unexpectedly')
    checker_cone = Cones(text, root_module=checker.name, prefix='main')
    require(not checker_cone.registers and not checker_cone.memories,
            'main checker gained storage')
    address = ('ref','head.request.address'); size = ('ref','head.request.size')
    normalized = ex.expand(ex.final('legacyPmp.io.address'), stop=(address[1],size[1]))
    require(normalized[0]=='cat' and normalized[1]==('bits',address,('num',63),('num',3)),
            'checker changes original high address bits')
    low = normalized[2]
    require(low[0]=='and' and low[1]==('bits',address,('num',2),('num',0)) and low[2][0]=='not',
            'checker normalization must only mask original low3 bits')
    mask=low[2][1]
    require(refs(mask)=={size[1]}, 'normalization mask uses non-size authority')
    for s in range(4):
        value,width=evaluate(mask,{size[1]:(s,2)})
        require((value,width)==((1<<s)-1,3), 'normalization mask wrong for size '+str(s))
    require(ex.expand(ex.final('legacyPmp.io.size'),stop=(size[1],))==size,'checker size changed')
    checked=[p[len(root)+1:] for p,m in cone.instances.items() if p.startswith(root+'.') and
             re.fullmatch(r'checked(?:_checked)?',p[len(root)+1:])]
    require(len(checked)==1,'missing exact checked queue'); checked=checked[0]
    fields=(checked+'.io.enq.bits.request.address',checked+'.io.enq.bits.request.size')
    guard=ex.expand(ex.final('guardedCheckedAlignmentFault'),stop=fields)
    require(refs(guard)==set(fields),'guard must use exact selected original address/size only')
    # Source address is used only through low3 in the actual emitted guard.
    def address_slices(e,parent=None):
        if e==('ref',fields[0]): require(parent==('bits',2,0),'guard inspects unproved address domain')
        if e[0] not in ('ref','lit','num'):
            for j,x in enumerate(e[1:]):
                address_slices(x,('bits',e[2][1],e[3][1]) if e[0]=='bits' and j==0 else None)
    address_slices(guard)
    for s in range(4):
        for low_bits in range(8):
            value,width=evaluate(guard,{fields[0]:(low_bits,64),fields[1]:(s,2)})
            require((value,width)==(int(low_bits%(1<<s)!=0),1),'emitted selected guard differs from divisibility')
    shape_stop=fields+('fault','identityOffer','physicalIngressOffer','guardedCheckedAlignmentFault','nextAllowed')
    fault=ex.expand(ex.final(checked+'.io.enq.bits.fault'),stop=shape_stop)
    require(fault[0]=='or' and any(ex.expand(x,stop=fields+('fault','identityOffer','physicalIngressOffer','nextAllowed'))==guard for x in fault[1:]),
            'selected malformed guard not ORed after final fault driver')
    hint=ex.expand(ex.final(checked+'.io.enq.bits.request.prefetchNextAllowed'),stop=shape_stop)
    require(hint[0]=='and' and any(ex.expand(x,stop=fields+('fault','identityOffer','physicalIngressOffer','nextAllowed'))==negative(guard) for x in hint[1:]),
            'captured hint not suppressed by selected guard')
    next_rel=nextline[0][len(root)+1:]
    hint_fault=ex.expand(ex.final(next_rel+'.io.fault'),stop=shape_stop)
    require(hint_fault[0]=='or' and any(ex.expand(x,stop=fields+('fault','identityOffer','physicalIngressOffer','nextAllowed'))==guard for x in hint_fault[1:]),
            'next-line identity bypass can clear alignment fault')
    captured_fault=checked+'.io.enq.bits.fault'
    cert=ex.expand(ex.final('certificate.valid'),stop=tuple(ex.connections))
    require(negative(('ref',captured_fault)) in conjuncts(cert), 'canonical valid lacks captured-fault veto')
    reached=cone.reachable([main+'.io.address'])
    payload=('address','size','mask','data','write','atomic','atomicOp','virtualized','precheckedLoad','translationEpoch','uncached')
    require(not any(root+'.'+checked+'.io.enq.bits.request.'+f in reached for f in payload),
            'normalized checker input feeds real request payload')
    return {'status':'PASS_GUARDED_NATURAL_PMP_STRUCTURE','adapterPath':root,'mainChecker':main,
            'nextLineCheckerCount':1,'mainCheckers':1,'mainEndpoint':'OR, no add/sub','sharedAlignedBounds':False,
            'guardTruthTableCases':32,'checkerMaskCases':4,'originalPayloadNotDrivenByNormalizedInput':True,
            'registers':len(cone.registers),'memories':cone.memories,
            'limits':['Emitted shape/connectivity and local Boolean identities, not general functional proof',
                      'Standalone misaligned raw requests intentionally acquire access errors',
                      'No mapped area, delay, Fmax or board qualification']}


def review(path):
    path=Path(path);result=review_text(path.read_text());result['firSha256']=hashlib.sha256(path.read_bytes()).hexdigest();return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('fir',type=Path);p.add_argument('--out',type=Path);a=p.parse_args()
    rendered=json.dumps(review(a.fir),indent=2)+'\n'
    if a.out:a.out.write_text(rendered)
    print(rendered,end='')
