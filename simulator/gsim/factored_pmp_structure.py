#!/usr/bin/env python3
"""Fail-closed structural audit of emitted generic PMP range arithmetic.

Uses the existing conservative CHIRRTL parser for connectivity. A deliberately
narrow unsigned width interpreter then audits each reachable production range
module; mutants are not production identities. This proves a generated shape,
not equivalence, mapped area/delay or frequency.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from registered_raw_certified_cones import Cones, IDENT, Uncertain, read_modules, require, split


def widths(typ, prefix):
    typ = typ.strip()
    vector = re.fullmatch(r'(.*)\[(\d+)\]', typ)
    if vector:
        n = int(vector[2]); require(0 < n <= 16, 'unsupported width vector')
        return {k: v for i in range(n) for k, v in widths(vector[1], prefix + f'[{i}]').items()}
    if typ.startswith('{') and typ.endswith('}'):
        out = {}
        for field in split(typ[1:-1]):
            m = re.fullmatch(rf'(?:flip\s+)?({IDENT})\s*:\s*(.+)', field)
            require(m is not None, 'unsupported width field')
            for k, v in widths(m[2], prefix + '.' + m[1]).items():
                require(k not in out, 'duplicate width field'); out[k] = v
        return out
    m = re.fullmatch(r'UInt<(\d+)>', typ)
    if m:
        w = int(m[1]); require(w > 0, 'zero width unsupported'); return {prefix: w}
    require(typ in ('Clock', 'Reset'), 'unsupported/uninferred type width: ' + typ)
    return {prefix: 1}


class WidthAudit:
    def __init__(self, module):
        self.known, self.nodes, self.ops, self.connects = {}, {}, [], []
        for _, line, number in module.body:
            m = re.fullmatch(rf'(input|output|wire) ({IDENT})\s*:\s*(.+)', line)
            if m:
                self.known.update(widths(m[3], m[2])); continue
            m = re.fullmatch(rf'node ({IDENT}) = (.+)', line)
            if m:
                require(m[1] not in self.nodes, 'duplicate width node')
                self.nodes[m[1]] = m[2]; continue
            if line.startswith('connect '):
                pair = split(line[8:]); require(len(pair) == 2, 'invalid width connect')
                self.connects.append((pair, number)); continue
            raise Uncertain('range module must be straight-line combinational UInt logic: ' + line)
        self.active = set()
        for name in self.nodes:
            self.infer(name)
        for (dest, value), line in self.connects:
            self.infer(dest); self.infer(value, 'connect:' + dest, line)

    def infer(self, expression, owner=None, line=None):
        if expression in self.known:
            return self.known[expression]
        if expression in self.nodes:
            require(expression not in self.active, 'cyclic width node')
            self.active.add(expression)
            w = self.infer(self.nodes[expression], expression, line)
            self.active.remove(expression); self.known[expression] = w
            return w
        literal = re.fullmatch(r'UInt<(\d+)>\((?:0[hbo][0-9a-fA-F_]+|\d+|"[hbo][0-9a-fA-F_]+")\)', expression)
        if literal:
            require(int(literal[1]) > 0, 'invalid literal width'); return int(literal[1])
        call = re.fullmatch(rf'({IDENT})\((.*)\)', expression)
        require(call is not None, 'unsupported width reference: ' + expression)
        op, args = call[1], split(call[2])
        def arg(i): return self.infer(args[i], owner, line)
        def integer(i):
            require(re.fullmatch(r'\d+', args[i]), 'nonconstant width parameter')
            return int(args[i])
        if op in ('add', 'sub', 'and', 'or', 'xor', 'lt', 'leq', 'gt', 'geq', 'eq', 'neq'):
            require(len(args) == 2, 'binary arity')
            aw = [arg(0), arg(1)]
            result = max(aw) + 1 if op in ('add', 'sub') else (1 if op in ('lt', 'leq', 'gt', 'geq', 'eq', 'neq') else max(aw))
            if op in ('add', 'sub'):
                self.ops.append(dict(op=op, args=args, widths=aw, resultWidth=result, owner=owner, expression=expression))
            return result
        if op in ('not', 'orr', 'andr', 'xorr', 'asUInt'):
            require(len(args) == 1, 'unary arity'); w = arg(0)
            return 1 if op.endswith('r') else w
        if op == 'cat':
            require(len(args) >= 2, 'cat arity'); return sum(arg(i) for i in range(len(args)))
        if op == 'mux':
            require(len(args) == 3 and arg(0) == 1, 'mux selector/arity')
            return max(arg(1), arg(2))
        if op == 'bits':
            require(len(args) == 3, 'bits arity'); w, hi, lo = arg(0), integer(1), integer(2)
            require(0 <= lo <= hi < w, 'bits outside width'); return hi - lo + 1
        if op in ('tail', 'head', 'pad'):
            require(len(args) == 2, 'width primitive arity'); w, n = arg(0), integer(1)
            if op == 'pad': return max(w, n)
            require(0 < n < w if op == 'tail' else 0 < n <= w, 'invalid head/tail width')
            return w - n if op == 'tail' else n
        raise Uncertain('unsupported width primitive: ' + op)


def review_text(text):
    top, modules = read_modules(text)
    instances, parents = [], {}
    def walk(name, path, stack):
        require(name in modules and name not in stack, 'unknown/recursive hierarchy')
        if re.fullmatch(r'PmpGenericRangeComparisons(?:_\d+)?', name):
            instances.append((name, path))
            if stack and re.fullmatch(r'PmpChecker(?:_\d+)?', stack[-1]):
                parent = modules[stack[-1]]
                require(not any(re.search(r'\b(?:add|sub|mul|div|rem|dshl|dshr)\(', line)
                                for _, line, _ in parent.body),
                        'factored parent checker retains arithmetic outside range module')
                children = [line for _, line, _ in parent.body if
                            re.fullmatch(rf'inst ({IDENT}) of PmpGenericRangeComparisons(?:_\d+)?', line)]
                require(len(children) == 1, 'factored parent must have exactly one range child')
                parents[stack[-1]] = dict(directArithmetic=0, rangeChildren=1)
            return
        for _, line, _ in modules[name].body:
            m = re.fullmatch(rf'inst ({IDENT}) of ({IDENT})', line)
            if m: walk(m[2], path + '.' + m[1], stack + [name])
    walk(top, top, [])
    require(instances, 'no reachable production generic range module')
    reports = {}
    for name, _ in instances:
        if name in reports: continue
        cone = Cones(text, root_module=name, prefix='range')
        require(not cone.registers and not cone.memories and len(cone.instances) == 1,
                'range module contains state or child modules')
        audit = WidthAudit(modules[name])
        entries = len([v for v in audit.known if re.fullmatch(r'io\.regionLow\[\d+\]', v)])
        require(0 < entries <= 16, 'missing exact range entry count')
        expected = {'clock': 1, 'reset': 1, 'io.address': 64, 'io.size': 3}
        for i in range(entries):
            expected.update({f'io.{field}[{i}]': w for field,w in (
                ('regionLow',65),('regionEnd',65),('regionActive',1),('overlap',1),('covers',1))})
        require(all(audit.known.get(k) == v for k,v in expected.items()) and
                {k for k in audit.known if k.startswith('io.')} == {k for k in expected if k.startswith('io.')},
                'range interface width mismatch')
        request = {'range.io.address', 'range.io.size'}
        reached = cone.reachable(request)
        adds = [op for op in audit.ops if op['op'] == 'add']
        subs = [op for op in audit.ops if op['op'] == 'sub']
        require(len(adds) == 1 and adds[0]['widths'] == [7,7] and adds[0]['resultWidth'] == 8,
                'expected exactly one low7+offset7 request addition')
        require(adds[0]['owner'] is not None and 'range.' + adds[0]['owner'] in reached,
                'low add is not request-dependent')
        require(len(subs) == 2 * entries, 'expected one predecessor subtraction per bound')
        bound_use = {}
        for op in subs:
            require(op['widths'] == [58,58] and op['resultWidth'] == 59 and op['owner'] is not None,
                    'predecessor arithmetic width mismatch')
            require('range.' + op['owner'] not in reached, 'request drives bound predecessor subtraction')
            normalized = audit.known[op['owner']] == 58 or any(
                expression == 'tail(' + op['owner'] + ', 1)' and audit.known[node] == 58
                for node, expression in audit.nodes.items())
            require(normalized, 'predecessor truncation does not retain exact58 bits')
            sources = [v for v in expected if re.fullmatch(r'io\.region(?:Low|End)\[\d+\]', v) and
                       'range.' + op['owner'] in cone.reachable(['range.' + v])]
            require(len(sources) == 1, 'predecessor is not owned by one state bound')
            bound_use[sources[0]] = bound_use.get(sources[0], 0) + 1
        require(len(bound_use) == 2 * entries and all(v == 1 for v in bound_use.values()),
                'duplicate or missing bound predecessor')
        outputs = []
        for i in range(entries):
            for field in ('overlap','covers'):
                sink = f'range.io.{field}[{i}]'; outputs.append(sink)
                require(sink in cone.assigned and sink in reached, 'missing or constant range predicate')
                require(sink in cone.reachable(['range.' + adds[0]['owner']]),
                        'range output bypasses audited low addition')
                for source in ('io.address','io.size',f'io.regionLow[{i}]',f'io.regionEnd[{i}]'):
                    require(sink in cone.reachable(['range.' + source]), 'range predicate missing required input: ' + source)
                active = f'range.io.regionActive[{i}]'
                require((sink in cone.reachable([active])) == (field == 'overlap'),
                        'active mask must affect only overlap')
        require(not any(v.endswith('$NEXT') for v in cone.vertices), 'unexpected sequential graph vertex')
        reports[name] = dict(entries=entries, stateElements=0, childModules=0,
            arithmetic=audit.ops, outputs=len(outputs), requestDependentWideArithmetic=0)
    return dict(status='PASS_FACTORED_PMP_GENERATED_STRUCTURE',
        instances=[dict(module=n,path=p) for n,p in instances], modules=reports, factoredParents=parents,
        limits=['Conservative emitted CHIRRTL shape only, not functional equivalence',
                'No mapped resource, delay, routing or achievable-frequency claim',
                'State-only predecessor arithmetic may itself affect update timing/resources'])


def review(path):
    path = Path(path); text = path.read_text()
    result = review_text(text)
    result['firSha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fir',type=Path); parser.add_argument('--out',type=Path)
    args=parser.parse_args(); result=review(args.fir)
    rendered=json.dumps(result,indent=2)+'\n'
    if args.out: args.out.write_text(rendered)
    print(rendered,end='')


if __name__ == '__main__': main()
