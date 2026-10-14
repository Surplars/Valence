"""Pinned resident source layer and exact named, typed historical projections.

This layer authenticates the complete corrected held-ALU base without changing
its frozen manifest or helper. Source compatibility conveys no execution or
physical qualification. Constructor names must accompany constructor documents.
"""
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMPAT = HERE / 'resident-memory-source-compat.json'
COMPAT_SHA256 = 'b3390f431f984beddce3ee978f07ed15e3bebe773e210cc909a7b132712dc535'
FIELD = 'residentMemoryPayloadReuse'
FLAG = '--resident-memory-payload-reuse'
BASE_TREE = 'f3dcb88dd4adb981b5cabe605610f8187aaaa0eb'
HELD_MANIFEST_SHA256 = '8455122022f9df8105c2530c3d076ed70df2f5a7e9ea69846ddb9d5354449b7c'
HELD_HELPER_SHA256 = 'bb7098611117700e868aedb717b3f0ea52e8b36fe53cab939139fbe5ff1b3f88'
HELD_PROFILE_SHA256 = 'c36f331b4ad594ab0d46d3f6f4ecfdc9036d302e2f0599073d7ad17d023773e9'
REFERENCE_PROFILE_SHA256 = 'd251587fae19feb796e00f8e80b9cd25649d564f006c221b54f8ab08b9fbfc83'
REFERENCE_ORDER_SHA256 = '5dbfc47d8a8490e99da18c36915964b0f0ded73a8d31d9bb99744750c0d1048f'
CORE_TAIL = ['postedYoungerLoadSealDeferral', 'heldAluIssueForwarding', FIELD]
PROFILE_TAIL = ['triSpeedRawClockHandoff', 'postedYoungerLoadSealDeferral', 'heldAluIssueForwarding', FIELD]
ARTIFACT_COMPONENTS = ('.git', 'out', 'build', '__pycache__')
SELF_EXCLUDED = ['fpga/next/resident-memory-source-compat.json', 'fpga/next/resident_memory_source_bridge.py']


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ordered_fields(path, name):
    text = path.read_text().split('case class ' + name + '(', 1)[1].split('\n) {', 1)[0]
    return [{'name': field, 'type': kind.strip()} for field, kind in
            re.findall(r'^\s+(\w+):\s*([^\n=]+)=', text, re.M)]


def source_paths():
    return sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*')
                  if p.is_file() and not any(x in ARTIFACT_COMPONENTS for x in p.relative_to(ROOT).parts)
                  and p.suffix != '.pyc' and p.relative_to(ROOT).as_posix() not in SELF_EXCLUDED)


def frozen_held_contract():
    path = HERE / 'held-alu-source-compat.json'
    if sha(path) != HELD_MANIFEST_SHA256 or sha(HERE / 'held_alu_source_bridge.py') != HELD_HELPER_SHA256 or \
            sha(HERE / 'held-alu-profile.json') != HELD_PROFILE_SHA256:
        raise RuntimeError('immutable corrected held ALU evidence changed')
    return json.loads(path.read_text())


def expand_source_contract(contract, held):
    """Reconstruct complete maps from an immutable base and reviewed deltas.

    This is lossless source metadata compression. Every resulting path and byte
    remains checked by checked_sources; it does not project hardware values.
    """
    derived = ('base_source_sha256', 'current_source_sha256', 'immutable_manifest_sha256')
    if any(key in contract for key in derived):
        raise RuntimeError('compact resident contract cannot override derived source maps')
    base = dict(held['current_source_sha256'])
    base.update({'fpga/next/held-alu-source-compat.json': HELD_MANIFEST_SHA256,
                 'fpga/next/held_alu_source_bridge.py': HELD_HELPER_SHA256})
    if contract['base_source_closure_sha256'] != hashlib.sha256(canonical(base).encode()).hexdigest():
        raise RuntimeError('compact resident immutable base digest differs')
    closure = dict(base)
    for name, row in contract['changed_sources'].items():
        if set(row) != {'old_sha256', 'new_sha256', 'reviewed_delta'} or \
                row['old_sha256'] != base.get(name) or \
                type(row['new_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', row['new_sha256']) or \
                row['new_sha256'] == base.get(name) or \
                type(row['reviewed_delta']) is not str or not row['reviewed_delta'].strip():
            raise RuntimeError('invalid compact reviewed source delta: ' + name)
        closure[name] = row['new_sha256']
    result = dict(contract)
    result.update(base_source_sha256=base, current_source_sha256=closure,
                  immutable_manifest_sha256={name: digest for name, digest in base.items() if name.endswith('.json')})
    return result


def checked_sources():
    if sha(COMPAT) != COMPAT_SHA256:
        raise RuntimeError('unreviewed resident memory source compatibility manifest')
    contract = json.loads(COMPAT.read_text())
    if contract['schema'] != 'resident-memory-false-source-compat-v2' or \
            contract['base_tree'] != BASE_TREE or contract['core_tail'] != CORE_TAIL or \
            contract['profile_tail'] != PROFILE_TAIL or contract['self_excluded'] != SELF_EXCLUDED or \
            contract['artifact_components'] != list(ARTIFACT_COMPONENTS) or \
            contract['dynamic_qualification'] is not False or contract['physical_qualification'] is not False:
        raise RuntimeError('resident memory compatibility contract changed')
    contract = expand_source_contract(contract, frozen_held_contract())
    closure, base, changed = (contract[key] for key in
                              ('current_source_sha256', 'base_source_sha256', 'changed_sources'))
    if source_paths() != sorted(closure):
        raise RuntimeError('current complete source closure has unknown or missing files')
    for name, digest in closure.items():
        if sha(ROOT / name) != digest:
            raise RuntimeError('current source differs from reviewed per-leaf delta: ' + name)
    if set(closure) != set(base) | set(changed):
        raise RuntimeError('resident base/source compatibility inventory differs')
    for name, digest in closure.items():
        if name not in changed and digest != base[name]:
            raise RuntimeError('unlisted resident source leaf changed: ' + name)
    for name, row in changed.items():
        if row['old_sha256'] != base.get(name) or row['new_sha256'] != closure[name] or \
                type(row['reviewed_delta']) is not str or not row['reviewed_delta'].strip():
            raise RuntimeError('invalid per-leaf resident compatibility delta: ' + name)
    held = frozen_held_contract()
    expected_base = dict(held['current_source_sha256'])
    expected_base.update({'fpga/next/held-alu-source-compat.json': HELD_MANIFEST_SHA256,
                          'fpga/next/held_alu_source_bridge.py': HELD_HELPER_SHA256})
    if base != expected_base or contract['held_manifest_sha256'] != HELD_MANIFEST_SHA256:
        raise RuntimeError('complete corrected held ALU source base differs')
    for kind, source, klass in [('core', 'OooParams.scala', 'OooParams'),
                               ('profile', 'FpgaNextConfig.scala', 'FpgaNextConfig')]:
        fields = ordered_fields(ROOT / 'src/main/scala/core/ooo' / source, klass)
        names = [row['name'] for row in fields]
        if fields != contract['current_' + kind + '_fields'] or \
                fields != contract['base_' + kind + '_fields'] + [{'name': FIELD, 'type': 'Boolean'}] or \
                names != contract['current_' + kind + '_names'] or \
                names != held['current_' + kind + '_names'] + [FIELD] or \
                fields[-1] != {'name': FIELD, 'type': 'Boolean'}:
            raise RuntimeError('complete Scala product names/types/order changed: ' + kind)
    for name, digest in contract['immutable_manifest_sha256'].items():
        if base.get(name) != digest or closure.get(name) != digest:
            raise RuntimeError('historical manifest was changed: ' + name)
    reference = contract['reference']
    profile_file = 'simulator/gsim/resident_memory_integration/reference-young69.json'
    order_file = 'simulator/gsim/resident_memory_integration/reference-young69-field-order.json'
    order = json.loads((ROOT / order_file).read_text())
    if reference != {'name': 'qualified-retained-young69', 'profile_file': profile_file,
                     'profile_sha256': REFERENCE_PROFILE_SHA256, 'field_order_file': order_file,
                     'field_order_sha256': REFERENCE_ORDER_SHA256, 'field_names': order,
                     'execution_release': False} or \
            sha(ROOT / profile_file) != REFERENCE_PROFILE_SHA256 or sha(ROOT / order_file) != REFERENCE_ORDER_SHA256:
        raise RuntimeError('measured Young reference identity changed')
    for kind in ('core', 'profile'):
        expected_names = held['historical_a_' + kind + '_names'] + ['postedYoungerLoadSealDeferral']
        if order[kind] != expected_names:
            raise RuntimeError('measured Young complete field names/order changed')
    identity = contract['source_identity']
    digest = hashlib.sha256(canonical(closure).encode()).hexdigest()
    if identity != {'kind': 'corrected-held-alu-plus-resident-source-only', 'base_tree': BASE_TREE,
                    'closure_sha256': digest, 'self_excluded': SELF_EXCLUDED}:
        raise RuntimeError('resident complete source identity changed')
    return contract


def checked_young_contract():
    """Explicit composed view preserving the frozen bb85 source ancestry."""
    resident = checked_sources()
    held = frozen_held_contract()
    current = dict(held)
    for key in ('current_source_sha256', 'current_core_names', 'current_profile_names'):
        current[key] = resident[key]
    current['resident_source_identity'] = resident['source_identity']
    return current


def validate_historical_sources(manifest, leaves):
    resident = checked_sources()
    held = frozen_held_contract()
    name = Path(manifest).resolve().relative_to(ROOT).as_posix()
    historical = held['historical_entries'].get(name)
    if historical is None or sha(Path(manifest)) != historical['manifest_sha256'] or \
            canonical(leaves) != canonical(historical['leaves']):
        raise RuntimeError('historical entry identity or source leaves changed')
    mac = json.loads((HERE / 'near-term-a-mac-platform-compat.json').read_text())
    for leaf, old in leaves.items():
        transition = historical['base_transition'][leaf]
        if transition['historical_sha256'] != old or transition['base_sha256'] != held['base_source_sha256'].get(leaf):
            raise RuntimeError('unreviewed historical-to-young source transition: ' + leaf)
        if old != transition['e4a_sha256'] and mac['changed_sources'].get(leaf) != \
                {'old_sha256': old, 'new_sha256': transition['e4a_sha256']}:
            raise RuntimeError('unreviewed pre-e4a MAC source transition: ' + leaf)
        if leaf not in resident['base_source_sha256'] or leaf not in resident['current_source_sha256']:
            raise RuntimeError('unreviewed resident historical source leaf: ' + leaf)
    return resident


def project_document(document, core_names, profile_names, reference='a', *,
                     younger_load_seal_deferral=False, raw_clock_handoff=False, held_alu_forwarding=False):
    """Remove only named Boolean-false additions and compare every old value."""
    contract = checked_sources()
    if core_names != contract['current_core_names'] or profile_names != contract['current_profile_names']:
        raise RuntimeError('constructed complete product names/order changed')
    if any(type(value) is not bool for value in
           (younger_load_seal_deferral, raw_clock_handoff, held_alu_forwarding)):
        raise RuntimeError('historical reference switches must be exact Booleans')
    held = frozen_held_contract()
    if reference == 'young':
        path = ROOT / contract['reference']['profile_file']
        if sha(path) != contract['reference']['profile_sha256']:
            raise RuntimeError('measured Young reference profile changed')
        expected = json.loads(path.read_text())
        old_names = contract['reference']['field_names']
    elif reference in ('a', 'exact64', 'raw', 'young-merged', 'held'):
        filename = 'near-term-a-original-profile.json' if reference == 'exact64' else 'near-term-a-before-mac-platform.json'
        expected = json.loads((HERE / filename).read_text())
        key = 'exact64' if reference == 'exact64' else 'a'
        old_names = {kind: list(held['historical_' + key + '_' + kind + '_names']) for kind in ('core', 'profile')}
        if reference == 'raw':
            expected['profile']['triSpeedRawClockHandoff'] = True
            old_names['profile'].append('triSpeedRawClockHandoff')
        if reference in ('young-merged', 'held'):
            expected['core']['postedYoungerLoadSealDeferral'] = younger_load_seal_deferral
            expected['profile']['triSpeedRawClockHandoff'] = raw_clock_handoff
            expected['profile']['postedYoungerLoadSealDeferral'] = younger_load_seal_deferral
            old_names['core'] += ['postedYoungerLoadSealDeferral']
            old_names['profile'] += ['triSpeedRawClockHandoff', 'postedYoungerLoadSealDeferral']
        if reference == 'held':
            for kind in ('core', 'profile'):
                expected[kind]['heldAluIssueForwarding'] = held_alu_forwarding
                old_names[kind].append('heldAluIssueForwarding')
    else:
        raise RuntimeError('unknown historical projection')
    current = json.loads(canonical(document))
    if set(current) != set(expected):
        raise RuntimeError('complete historical document keys differ')
    for kind, names in (('core', core_names), ('profile', profile_names)):
        values = current[kind]
        original_names = old_names[kind]
        if set(values) != set(names) or set(expected[kind]) != set(original_names):
            raise RuntimeError('missing or extra constructed historical field: ' + kind)
        if [name for name in names if name in original_names] != original_names:
            raise RuntimeError('unknown, misplaced or reordered historical fields')
        additions = [name for name in names if name not in original_names]
        if any(values[name] is not False for name in additions):
            raise RuntimeError('only exact named Boolean false fields may project: ' + kind)
        current[kind] = {name: values[name] for name in original_names}
    if canonical(current) != canonical(expected):
        raise RuntimeError('one or more original complete scalar/nested values changed')
    return current


def validate_parameter_types(values, kind, contract):
    """Check all scalar declared types, including integer/Boolean distinction."""
    fields = contract['current_' + kind + '_fields']
    if set(values) != {row['name'] for row in fields}:
        raise RuntimeError('complete parameter type schema keys differ: ' + kind)

    def same_shape(actual, expected):
        if type(actual) is not type(expected):
            return False
        if isinstance(expected, dict):
            return set(actual) == set(expected) and all(same_shape(actual[key], expected[key]) for key in expected)
        if isinstance(expected, list):
            return len(actual) == len(expected) and all(same_shape(a, b) for a, b in zip(actual, expected))
        return True

    for row in fields:
        value, declared = values[row['name']], row['type']
        if declared == 'Boolean':
            valid = type(value) is bool
        elif declared in ('Int', 'BigInt'):
            valid = type(value) is int
        elif declared == 'Option[Int]':
            valid = value is None or type(value) is int
        elif declared == 'FloatingPointConfig':
            reference = json.loads((ROOT / contract['reference']['profile_file']).read_text())
            valid = same_shape(value, reference['core']['floatingPoint'])
        else:
            raise RuntimeError('unreviewed declared parameter type: ' + declared)
        if not valid:
            raise RuntimeError('complete parameter type differs: ' + kind + '.' + row['name'])


def validate_resident_pair(off, on, core_names, profile_names):
    """Prove the complete one-field delta before projecting the OFF reference."""
    contract = checked_sources()
    if core_names != contract['current_core_names'] or profile_names != contract['current_profile_names']:
        raise RuntimeError('constructed complete product names/order changed')
    cleared = json.loads(canonical(on))
    for kind, names in (('core', core_names), ('profile', profile_names)):
        if set(off[kind]) != set(names) or set(on[kind]) != set(names) or \
                off[kind][FIELD] is not False or on[kind][FIELD] is not True:
            raise RuntimeError('resident pair requires exact complete false/true products')
        cleared[kind][FIELD] = False
    if canonical(cleared) != canonical(off):
        raise RuntimeError('resident pair changed another complete scalar/nested value')
    return project_document(off, core_names, profile_names, reference='young')
