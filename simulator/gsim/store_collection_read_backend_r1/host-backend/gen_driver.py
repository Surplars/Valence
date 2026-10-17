#!/usr/bin/env python3
"""Pure FIR/header/source binding; never compiles, imports or executes the DUT."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
CLASS = 'CollectionReadBackendGsim'


def need(ok, why):
    if not ok:
        raise RuntimeError(why)


def fir_schema(path):
    chunks = path.read_text().split('public module ' + CLASS + ' :', 1)
    need(len(chunks) == 2, 'EXACT_TOP_MODULE')
    all_ports = {'reset': (1, True)}
    for root in ('io', 'observation'):
        line = next(x for x in chunks[1].splitlines() if x.strip().startswith('output ' + root + ' :'))
        raw = line.split('output ' + root + ' :', 1)[1].split(' @[')[0]
        tokens = re.findall(r'[A-Za-z_][A-Za-z_0-9]*|\d+|[{}<>\[\]:,]', raw)
        pos = 0

        def take(want=None):
            nonlocal pos
            need(pos < len(tokens), 'FIR_TRUNCATED_TYPE')
            v = tokens[pos]; pos += 1
            need(want is None or v == want, 'FIR_TOKEN: ' + v)
            return v

        def parse(inp):
            result = {}
            if tokens[pos] == '{':
                take('{')
                while tokens[pos] != '}':
                    flip = tokens[pos] == 'flip'
                    if flip:
                        take('flip')
                    name = take(); take(':')
                    for suffix, value in parse(inp ^ flip).items():
                        result[name + ('.' + suffix if suffix else '')] = value
                    if tokens[pos] == ',':
                        take(',')
                    else:
                        need(tokens[pos] == '}', 'FIR_BUNDLE_SEPARATOR')
                take('}')
            else:
                take('UInt'); take('<'); bits = int(take()); take('>')
                result[''] = (bits, inp)
            if pos < len(tokens) and tokens[pos] == '[':
                take('['); count = int(take()); take(']')
                result = {str(n) + ('.' + suffix if suffix else ''): value
                          for n in range(count) for suffix, value in result.items()}
            return result

        result = parse(False)
        need(pos == len(tokens), 'FIR_TRAILING_TYPE')
        all_ports.update({root + '.' + n: value for n, value in result.items()})
    return {'inputs': {n: w for n, (w, inp) in all_ports.items() if inp},
            'outputs': {n: w for n, (w, inp) in all_ports.items() if not inp}}


def binding(name, bits, direction, declarations):
    parts = name.split('.')
    indices = [int(p) for p in parts if p.isdigit()]
    need(len(indices) <= 1, 'ARRAY_RANK: ' + name)
    accessor = ('set_' if direction == 'input' else 'get_') + '$$'.join(p for p in parts if not p.isdigit())
    need(accessor in declarations, 'MISSING_PUBLIC_API: ' + accessor)
    signature = declarations[accessor]
    ctype = re.search(r'uint(?:8|16|32|64)_t|unsigned _BitInt\(128\)', signature).group()
    match = re.search(r'\[(\d+)\]', signature)
    size = int(match.group(1)) if match else None
    if indices:
        need(size is not None and indices[0] < size, 'VECTOR_INDEX: ' + name)
        want = ('void ' + accessor + '(const ' + ctype + ' (&val)[' + str(size) + ']);'
                if direction == 'input' else 'const ' + ctype + ' (&' + accessor + '() const)[' + str(size) + '];')
    else:
        need(size is None, 'MISSING_VECTOR_INDEX: ' + name)
        want = 'void ' + accessor + '(' + ctype + ' val);' if direction == 'input' else ctype + ' ' + accessor + '();'
    need(signature == want, 'EXACT_PUBLIC_SIGNATURE: ' + name + ' ' + signature)
    capacity = 128 if '_BitInt' in ctype else int(re.search(r'\d+', ctype).group())
    need(bits <= capacity and (direction != 'input' or bits <= 64), 'PUBLIC_TYPE_CAPACITY: ' + name)
    return dict(name=name, width=bits, direction=direction, accessor=accessor,
                signature=signature, ctype=ctype, index=indices[0] if indices else None, length=size)


def generate(header):
    outputs = [HERE / n for n in ('driver.cpp', 'SCHEMA.json', 'API_RECEIPT.json')]
    need(not any(p.exists() for p in outputs), 'PRESERVE_EXISTING_GENERATED_SOURCE')
    for p in HERE.glob('*.py'):
        ast.parse(p.read_text(), filename=str(p))
    schema = fir_schema(header.with_suffix('.fir'))
    text = header.read_text()
    need(re.findall(r'^class (S\w+) \{', text, re.M) == ['S' + CLASS], 'EXACT_MODEL_CLASS')
    declarations = {}
    for line in text.splitlines():
        match = re.search(r'\b((?:set|get)_[A-Za-z0-9_$]+)\(', line)
        if match:
            need(match.group(1) not in declarations, 'DUPLICATE_ACCESSOR')
            declarations[match.group(1)] = line.strip()
    bindings = [binding(n, w, d, declarations) for d, key in [('input', 'inputs'), ('output', 'outputs')]
                for n, w in schema[key].items()]
    expected = {b['accessor'] for b in bindings} | {'set_clock'}
    need(set(declarations) == expected, 'COMPLETE_API: ' + repr(set(declarations) ^ expected))
    request = {n.split('io.memory.request.bits.', 1)[1]: w for n, w in schema['outputs'].items()
               if n.startswith('io.memory.request.bits.')}
    need(sum(request.values()) == 184 and schema['outputs']['io.collectionHeadRead'] == 1 and
         schema['outputs']['observation.start.bits.collectionHeadRead'] == 1, 'COLLECTION_REQUEST_ABI')
    arrays = {b['accessor']: b for b in bindings if b['direction'] == 'input' and b['index'] is not None}
    identifiers = {accessor: 'array_' + str(n) for n, accessor in enumerate(arrays)}
    array_declarations = ['    ' + b['ctype'] + ' ' + identifiers[a] + '[' + str(b['length']) + '] = {};'
                          for a, b in arrays.items()]
    array_calls = ['      d.' + a + '(' + identifiers[a] + ');' for a in arrays]
    setters, getters = [], []
    for b in bindings:
        n, a = b['name'], b['accessor']
        if b['direction'] == 'input':
            assign = identifiers[a] + '[' + str(b['index']) + '] = v;' if b['index'] is not None else 'd.' + a + '(v);'
            guard = 'if (v >= (uint64_t(1) << ' + str(b['width']) + ')) throw std::runtime_error("input width: ' + n + '"); ' if b['width'] < 64 else ''
            setters.append('    setters.emplace("' + n + '", [&](uint64_t v) { ' + guard + assign + ' });')
        else:
            expr = 'd.' + a + '()' + ('[' + str(b['index']) + ']' if b['index'] is not None else '')
            getters.append('      std::cout << ",\\"' + n + '\\":" << decimal(' + expr + ');')
    source = r'''#include "CollectionReadBackendGsim.h"
#include <algorithm>
#include <cstdint>
#include <functional>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
static std::string decimal(unsigned _BitInt(128) v) {
  std::string s;
  do { s.push_back(char('0' + unsigned(v % 10))); v /= 10; } while (v);
  std::reverse(s.begin(), s.end()); return s;
}
int main() {
  try {
    SCollectionReadBackendGsim d;
ARRAYS
    std::unordered_map<std::string, std::function<void(uint64_t)>> setters;
SETTERS
    std::string line; unsigned cycle = 0;
    while (std::getline(std::cin, line)) {
      if (line == "quit") break;
      if (++cycle > 1024) throw std::runtime_error("backend cycle budget exceeded");
      std::unordered_set<std::string> assigned;
      std::istringstream input(line); std::string item;
      while (input >> item) {
        const auto equal = item.find('=');
        if (equal == std::string::npos) throw std::runtime_error("malformed input");
        const auto name = item.substr(0, equal);
        if (!setters.count(name)) throw std::runtime_error("unknown input: " + name);
        if (!assigned.insert(name).second) throw std::runtime_error("duplicate input: " + name);
        size_t consumed = 0; const auto text = item.substr(equal + 1);
        if (text.empty() || text[0] == '-') throw std::runtime_error("unsigned input required");
        const auto value = std::stoull(text, &consumed, 0);
        if (consumed != text.size()) throw std::runtime_error("trailing input data");
        setters.at(name)(value);
      }
      if (assigned.size() != setters.size()) throw std::runtime_error("incomplete scalar frame");
ARRAY_CALLS
      d.step();
      std::cout << "{\"cycle\":" << cycle;
GETTERS
      std::cout << "}\n" << std::flush;
    }
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "COLLECTION_BACKEND_DRIVER_FAIL " << e.what() << "\n"; return 1;
  }
}
'''
    for name, rows in [('ARRAYS', array_declarations), ('SETTERS', setters), ('ARRAY_CALLS', array_calls), ('GETTERS', getters)]:
        source = source.replace(name, '\n'.join(rows))
    need(set(re.findall(r'\bd\.((?:set|get)_[A-Za-z0-9_$]+)\s*\(', source)) == expected - {'set_clock'}, 'GENERATED_PUBLIC_CALL_SET')
    schema['request'] = request
    outputs[0].write_text(source)
    outputs[1].write_text(json.dumps(schema, indent=2) + '\n')
    files = [header, header.with_suffix('.fir'), *sorted(p for p in HERE.iterdir() if p.is_file() and p.name != 'API_RECEIPT.json')]
    report = dict(status='PASS', scope='source AST and exact public FIR/header scalar/vector API binding',
                  dut_executed=False, compiled=False, inputs=len(schema['inputs']), outputs=len(schema['outputs']),
                  request_bits=184, unsigned_65_bit_pmp_region_preserved=True, accessors=bindings,
                  clock_note='set_clock intentionally unused; established GSIM step protocol',
                  bindings=[dict(path=str(p.resolve()), bytes=p.stat().st_size,
                                 sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files])
    outputs[2].write_text(json.dumps(report, indent=2) + '\n')
    need(sum(p.stat().st_size for p in HERE.iterdir() if p.is_file()) <= 512 * 1024, 'SOURCE_BUDGET')
    print(json.dumps({k: report[k] for k in ('status', 'inputs', 'outputs', 'request_bits', 'dut_executed', 'compiled')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('header', type=Path)
    generate(parser.parse_args().header.resolve())
