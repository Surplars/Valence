"""Pinned bb85+B1 source closure and strict named false-only historical projections.

This bridge certifies executable source/entry compatibility, never dynamic or
physical qualification. The external preparation freeze binds this helper too.
"""
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMPAT = HERE / 'held-alu-source-compat.json'
COMPAT_SHA256 = '8455122022f9df8105c2530c3d076ed70df2f5a7e9ea69846ddb9d5354449b7c'
CORE_TAIL = ['postedYoungerLoadSealDeferral', 'heldAluIssueForwarding']
PROFILE_TAIL = ['triSpeedRawClockHandoff', 'postedYoungerLoadSealDeferral', 'heldAluIssueForwarding']
A_FIELDS = ['fetchAcceptedPrefixValidation', 'alignedFetchSinglePage',
            'factorCheckedNextAllowed', 'localTaggedResponseReady']
ARTIFACT_COMPONENTS = ('.git', 'out', 'build', '__pycache__')
SELF_EXCLUDED = ['fpga/next/held-alu-source-compat.json', 'fpga/next/held_alu_source_bridge.py']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ordered_names(path, name):
    text = path.read_text().split('case class ' + name + '(', 1)[1].split('\n) {', 1)[0]
    return re.findall(r'^\s+(\w+):\s*[^\n=]+=', text, re.M)


def source_paths():
    return sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*')
                  if p.is_file() and not any(x in ARTIFACT_COMPONENTS for x in p.relative_to(ROOT).parts) and p.suffix != '.pyc'
                  and p.relative_to(ROOT).as_posix() not in SELF_EXCLUDED)


def checked_sources():
    if sha(COMPAT) != COMPAT_SHA256:
        raise RuntimeError('unreviewed held ALU source compatibility manifest')
    contract = json.loads(COMPAT.read_text())
    if contract['schema'] != 'held-alu-false-source-compat-v1' or \
            contract['base_commit'] != 'bb85d08bda18121b1b848fbbbd004af50f2cc504' or \
            contract['base_tree'] != 'd1447e5e10179c9cc287c600d9aa36a2239128e2' or \
            contract['core_tail'] != CORE_TAIL or contract['profile_tail'] != PROFILE_TAIL or \
            contract['self_excluded'] != SELF_EXCLUDED or \
            contract['artifact_components'] != list(ARTIFACT_COMPONENTS) or \
            contract['dynamic_qualification'] is not False or contract['physical_qualification'] is not False:
        raise RuntimeError('held ALU compatibility contract changed')
    closure = contract['current_source_sha256']
    if source_paths() != sorted(closure):
        raise RuntimeError('current complete source closure has unknown or missing files')
    for name, digest in closure.items():
        if sha(ROOT / name) != digest:
            raise RuntimeError('current source differs from reviewed per-leaf delta: ' + name)
    base = contract['base_source_sha256']
    changed = contract['changed_sources']
    if set(closure) != set(base) | set(changed):
        raise RuntimeError('base/source compatibility inventory differs')
    for name, digest in closure.items():
        if name not in changed and digest != base[name]:
            raise RuntimeError('unlisted source leaf changed: ' + name)
    for name, row in changed.items():
        if row['old_sha256'] != base.get(name) or row['new_sha256'] != closure[name] or not row['reviewed_delta']:
            raise RuntimeError('invalid per-leaf compatibility delta: ' + name)
    for kind, source, klass in [('core', 'OooParams.scala', 'OooParams'),
                                 ('profile', 'FpgaNextConfig.scala', 'FpgaNextConfig')]:
        names = ordered_names(ROOT / 'src/main/scala/core/ooo' / source, klass)
        if names != contract['current_' + kind + '_names']:
            raise RuntimeError('complete Scala product names/order changed: ' + kind)
    return contract


def validate_historical_sources(manifest, leaves):
    contract = checked_sources()
    name = manifest.relative_to(ROOT).as_posix()
    historical = contract['historical_entries'].get(name)
    if historical is None or sha(manifest) != historical['manifest_sha256'] or leaves != historical['leaves']:
        raise RuntimeError('historical entry identity or source leaves changed')
    mac = json.loads((HERE / 'near-term-a-mac-platform-compat.json').read_text())
    for leaf, old in leaves.items():
        base = contract['base_source_sha256'].get(leaf)
        transition = historical['base_transition'][leaf]
        if transition['historical_sha256'] != old or transition['base_sha256'] != base:
            raise RuntimeError('unreviewed historical-to-young source transition: ' + leaf)
        if old != transition['e4a_sha256']:
            if mac['changed_sources'].get(leaf) != {'old_sha256': old, 'new_sha256': transition['e4a_sha256']}:
                raise RuntimeError('unreviewed pre-e4a MAC source transition: ' + leaf)
        if leaf not in contract['current_source_sha256']:
            raise RuntimeError('unreviewed historical source leaf: ' + leaf)
    return contract


def project_document(document, core_names, profile_names, reference='a'):
    """Validate complete constructed document; never truncate by numeric arity.

    Caller must supply real productElementNames from the same constructor as
    document. The source-only fixtures are separately labeled expected data.
    """
    contract = checked_sources()
    if core_names != contract['current_core_names'] or profile_names != contract['current_profile_names']:
        raise RuntimeError('constructed complete product names/order changed')
    if reference not in ('a', 'exact64'):
        raise RuntimeError('unknown historical projection')
    original_file = ('near-term-a-before-mac-platform.json' if reference == 'a'
                     else 'near-term-a-original-profile.json')
    original = json.loads((HERE / original_file).read_text())
    # JSON roundtrip preserves exact Boolean/scalar types; equality alone would
    # accidentally accept 0 == False and 1 == True in Python.
    current = json.loads(json.dumps(document))
    if set(current) != set(original):
        raise RuntimeError('complete document keys differ')
    for kind, names, additions in [('core', core_names, CORE_TAIL), ('profile', profile_names, PROFILE_TAIL)]:
        values = current[kind]
        if set(values) != set(names):
            raise RuntimeError('missing or extra constructed field: ' + kind)
        tail = (A_FIELDS if reference == 'exact64' else []) + additions
        old_names = contract['historical_' + reference + '_' + kind + '_names']
        if names != old_names + tail:
            raise RuntimeError('unknown, misplaced or reordered compatibility tail')
        if any(values[n] is not False for n in tail):
            raise RuntimeError('only exact named Boolean false fields may project: ' + kind)
        current[kind] = {n: values[n] for n in old_names}
    encode = lambda x: json.dumps(x, sort_keys=True, separators=(',', ':'))
    if encode(current) != encode(original):
        raise RuntimeError('one or more original complete scalar/nested values changed')
    return current
