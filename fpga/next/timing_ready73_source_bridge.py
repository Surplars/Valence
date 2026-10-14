"""Exact source-only closure for the named timing entry; no historical projection."""
import hashlib
import importlib.util
import json
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMPAT_SHA256 = '88a430c43f25b150da70d449384045794561fb7de41ac18d0375abc884348356'
SELF_EXCLUDED = ['fpga/next/timing_ready73_source_bridge.py', 'fpga/next/timing-ready73-source-compat.json']

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def helper():
    spec = importlib.util.spec_from_file_location('timing_frozen_resident', HERE / 'resident_memory_source_bridge.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def checked_sources():
    path = HERE / 'timing-ready73-source-compat.json'
    if sha(path) != COMPAT_SHA256:
        raise RuntimeError('timing closure manifest changed')
    c = json.loads(path.read_text())
    if c['schema'] != 'timing-ready73-source-v1' or c['self_excluded'] != SELF_EXCLUDED or c['physical_qualification'] is not False:
        raise RuntimeError('timing source contract changed')
    for name, digest in c['base_contract_sha256'].items():
        if sha(ROOT / name) != digest:
            raise RuntimeError('immutable source ancestry changed: ' + name)
    prior = helper()
    base = prior.expand_source_contract(json.loads(prior.COMPAT.read_text()), prior.frozen_held_contract())['current_source_sha256']
    base.update(c['base_contract_sha256'])
    if hashlib.sha256(canonical(base).encode()).hexdigest() != c['base_closure_sha256']:
        raise RuntimeError('complete prior source closure differs')
    closure = dict(base)
    for name, row in c['changed_sources'].items():
        if set(row) != {'old_sha256', 'new_sha256'} or row['old_sha256'] != base.get(name) or row['new_sha256'] == base.get(name):
            raise RuntimeError('invalid exact source delta: ' + name)
        closure[name] = row['new_sha256']
    names = sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()
        and not any(x in prior.ARTIFACT_COMPONENTS for x in p.relative_to(ROOT).parts)
        and p.suffix != '.pyc' and p.relative_to(ROOT).as_posix() not in SELF_EXCLUDED)
    if names != sorted(closure):
        raise RuntimeError('unknown or missing complete timing source leaf')
    for name, digest in closure.items():
        if sha(ROOT / name) != digest:
            raise RuntimeError('timing source leaf changed: ' + name)
    for kind, leaf, cls, count in [('core', 'OooParams.scala', 'OooParams', 177),
                                  ('profile', 'FpgaNextConfig.scala', 'FpgaNextConfig', 94)]:
        fields = prior.ordered_fields(ROOT / 'src/main/scala/core/ooo' / leaf, cls)
        if fields != c['current_' + kind + '_fields'] or len(fields) != count:
            raise RuntimeError('complete current ordered names/types differ: ' + kind)
        c['current_' + kind + '_names'] = [x['name'] for x in fields]
    c['current_source_sha256'] = closure
    c['source_identity'] = {'kind': 'timing-ready73-source-only',
        'closure_sha256': hashlib.sha256(canonical(closure).encode()).hexdigest(), 'self_excluded': SELF_EXCLUDED}
    return c

def validate_parameter_types(values, kind, contract):
    helper().validate_parameter_types(values, kind, contract)
