#!/usr/bin/env python3
"""Read-only package/hash and generated-source closure check. No hardware tools."""
from pathlib import Path
import bisect
import difflib
import hashlib
import json
import lzma
import re

ROOT = Path(__file__).resolve().parents[1]
sha = lambda data: hashlib.sha256(data).hexdigest()
read = lambda path: json.loads((ROOT / path).read_text())

def check(condition, detail):
    if not condition:
        raise SystemExit('FAIL: ' + detail)

def blocks(text):
    matches = list(re.finditer(r'^  (?:public )?(?:ext)?module (\w+).*$', text, re.M))
    check(len(matches) == len({m[1] for m in matches}), 'duplicate FIR module')
    return {m[1]: text[m.start():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
            for i, m in enumerate(matches)}

def rtl_closure(filelist, base, top, expected):
    names = (base / filelist).read_text().splitlines()
    check(len(names) == expected and len(set(names)) == expected, 'filelist size/duplicates')
    modules, uses = {}, []
    for name in names:
        path = Path(name)
        check(not path.is_absolute() and '..' not in path.parts, 'nonportable filelist')
        full = base / path
        check(full.is_file() and not full.is_symlink(), 'missing RTL or symlink')
        text = full.read_text()
        clean = re.sub(r'/\*[\s\S]*?\*/|//[^\n]*', '', text)
        definitions = re.findall(r'^module\s+(\w+)\s*\(', clean, re.M)
        check(len(definitions) == 1, 'expected one generated module per file: ' + name)
        module = definitions[0]
        check(module not in modules, 'duplicate RTL module: ' + module)
        modules[module] = name
        # Generated CIRCT files use unparameterized named module instances.
        instances = re.findall(r'^[ \t]*(\w+)[ \t]+(\w+)[ \t]*\(', clean, re.M)
        uses.extend((kind, instance, name) for kind, instance in instances if kind not in {'module', 'else', 'end'})
        check(not re.search(r'^\s*\w+\s*#\s*\(', clean, re.M), 'unhandled parameterized instance')
        check('`include' not in clean and '$readmem' not in clean, 'external source/data dependency')
    unresolved = [row for row in uses if row[0] not in modules]
    check(not unresolved, 'unresolved instance types: ' + repr(unresolved[:10]))
    check(top in modules, 'missing top: ' + top)
    edges = {module: set() for module in modules}
    reverse = {name: module for module, name in modules.items()}
    for kind, _, name in uses:
        edges[reverse[name]].add(kind)
    reached, todo = set(), [top]
    while todo:
        node = todo.pop()
        if node not in reached:
            reached.add(node)
            todo.extend(edges[node])
    return {'files': len(names), 'modules': len(modules), 'instances': len(uses),
            'top': top, 'reachable_modules': len(reached), 'unreachable_modules': sorted(set(modules) - reached)}

manifest = read('MANIFEST.json')
actual_files = {str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file()}
check(actual_files == set(manifest['files']) | {'MANIFEST.json'}, 'unmanifested/missing files')
for path, expected in manifest['files'].items():
    file = ROOT / path
    check(not file.is_symlink(), 'symlink: ' + path)
    data = file.read_bytes()
    check(sha(data) == expected['sha256'] and len(data) == expected['bytes'], 'hash/size: ' + path)
    check((b'workspace' + b'/scratch/') not in data and (b'/' + b'home/' + b'agent/') not in data, 'private path: ' + path)
    check((b'-----BEGIN ' + b'PRIVATE KEY-----') not in data, 'secret marker: ' + path)

for path, row in read('PROVENANCE.json')['files'].items():
    if path == 'fir/CommonA1CapacityGsim.fir':
        continue  # Streamed and checked below without extracting a file.
    data = (ROOT / path).read_bytes()
    check(sha(data) == row['published_sha256'], 'provenance hash: ' + path)
    text = data.decode()
    token = re.compile(r'source_refs/[^\s\[\]"{}(),:]+\.scala(?=[: ]\d)')
    matches = list(token.finditer(text))
    if path.endswith('.fir'):
        spans = [m.span() for m in re.finditer(r'@\[[^\]\n]*\]', text)]
    elif path.endswith('.sv'):
        lex = re.compile(r'"(?:\\.|[^"\\])*"|/\*[\s\S]*?\*/|//[^\n]*')
        spans = [m.span() for m in lex.finditer(text) if m[0].startswith('//')]
    else:
        spans = []
    starts = [a for a, _ in spans]
    for match in matches:
        index = bisect.bisect_right(starts, match.start()) - 1
        check(index >= 0 and match.end() <= spans[index][1], 'normalization outside SourceInfo/comment')
    check(len(matches) == row['source_location_paths_rewritten'], 'normalization count: ' + path)
    masked = token.sub('<SOURCE_LOCATION_PATH>', text)
    check(sha(masked.encode()) == row['protected_text_sha256'], 'protected bytes: ' + path)

ordinary = rtl_closure('rtl.f', ROOT, 'CommonA1CpuTile', 173)
component = rtl_closure('rtl.f', ROOT / 'component', 'PredictionTrainingGsim', 5)
meta = read('FIR_SOURCE.json')
chain = read('SOURCE_CHAIN.json')
check(meta['compression'] == 'xz', 'unexpected FIR compression')
compressed = ROOT / meta['compressed_path']
check(sha(compressed.read_bytes()) == meta['compressed_sha256'], 'compressed FIR hash')
row = read('PROVENANCE.json')['files'][meta['logical_source_path']]
old = (ROOT / 'baseline/IndirectTargetPredictor.fir').read_bytes()
full_hash, protected_hash, reverse_hash = (hashlib.sha256() for _ in range(3))
fb, instances, target_lines = set(), [], []
size = normalized_count = 0
in_target = False
token = re.compile(r'source_refs/[^\s\[\]"{}(),:]+\.scala(?=[: ]\d)')
with lzma.open(compressed, 'rb') as stream:
    for line in stream:
        full_hash.update(line)
        size += len(line)
        text = line.decode('utf-8')
        locations = list(token.finditer(text))
        spans = [m.span() for m in re.finditer(r'@\[[^\]\n]*\]', text)]
        for loc in locations:
            check(any(a <= loc.start() and loc.end() <= b for a, b in spans), 'FIR normalization outside SourceInfo')
        normalized_count += len(locations)
        protected_hash.update(token.sub('<SOURCE_LOCATION_PATH>', text).encode())
        module = re.match(r'^  (?:public )?(?:ext)?module (\w+)', text)
        if module:
            check(module[1] not in fb, 'duplicate FIR module')
            fb.add(module[1])
            in_target = module[1] == 'IndirectTargetPredictor'
            if in_target:
                reverse_hash.update(old)
        instances.extend(re.findall(r'^\s*inst\s+\w+\s+of\s+(\w+)', text))
        if in_target:
            target_lines.append(text)
        else:
            reverse_hash.update(line)
check(size == meta['decompressed_bytes'], 'decompressed FIR size')
check(full_hash.hexdigest() == meta['decompressed_sha256'] == row['published_sha256'] == chain['w14_fir_published_sha256'], 'decompressed FIR identity')
check(protected_hash.hexdigest() == row['protected_text_sha256'], 'FIR protected metadata bytes')
check(normalized_count == row['source_location_paths_rewritten'], 'FIR normalization count')
check(set(instances) <= fb, 'missing FIR module references')
check('CommonA1CapacityGsim' in fb and len(fb) == chain['fir_modules'], 'FIR top or module count')
comp = blocks((ROOT / 'component/PredictionTrainingGsim.fir').read_text())
check(comp['IndirectTargetPredictor'] == ''.join(target_lines), 'graft/component module mismatch')
check(reverse_hash.hexdigest() == chain['w13_fir_published_normalization_sha256'], 'reverse W14-to-W13 graft')
a = (ROOT / 'component/baseline/BranchPredictor.scala').read_text()
b = (ROOT / 'component/src/BranchPredictor.scala').read_text()
patch = ''.join(difflib.unified_diff(a.splitlines(True), b.splitlines(True),
    fromfile='component/baseline/BranchPredictor.scala', tofile='component/src/BranchPredictor.scala'))
check(patch == (ROOT / 'component/BranchPredictor.patch').read_text(), 'Scala patch')
check((ROOT / 'component/rtl/IndirectTargetPredictor.sv').read_bytes() ==
      (ROOT / 'rtl/IndirectTargetPredictor.sv').read_bytes(), 'component table RTL mismatch')
check((ROOT / 'component/rtl/ta_16x64.sv').read_bytes() ==
      (ROOT / 'rtl/ta_16x64.sv').read_bytes(), 'component memory leaf mismatch')
print(json.dumps({'status': 'PASS_LIGHTWEIGHT_SNAPSHOT_CHECKS', 'ordinary': ordinary,
    'component': component, 'fir_modules': len(fb), 'fir_instances': len(instances),
    'manifested_files': len(manifest['files']), 'reverse_graft': 'PASS',
    'hardware_simulation_or_mapping_executed': False}, indent=2))
