"""Strict source bridge for historical OFF entries on the frozen seal candidate.

These bindings preserve original manifests and option vectors. They establish
source identity only, never inherited component, CPU, or physical qualification.
The complete production tree binding includes leaves absent from old manifests.
"""
import hashlib
import json
from pathlib import Path
import importlib.util

FLAG = '--posted-younger-load-seal-deferral'
MANIFEST_SHA256 = {
    'near-term-a-profile.json': '46b9d6139d4001fbbb4723ec3684484ca2c32d4d1cf01a19122fe5cb4ed23738',
    'timing-batch-locality64-profile.json': 'ae447852ef451916ab5c23df769b9dc5e2adb5b8911d7a0401ee21b8294e760d',
}
# Every old value must be present unchanged in each original manifest. Every new
# value is fixed by the reviewed young-load-seal source freeze, never read as trust.
REPLACEMENTS = {
    'src/main/scala/core/ooo/BoardSocTop.scala': (
        '62c49f684c5f495ab0ddc52d034d24a7de51a4f1e4572739b9733640d2ee6b01',
        'bbb1418155c8ce2a56266c3c63640d9e17a4fa9311b81628bd89049c59b080d9'),
    'src/main/scala/core/ooo/FpgaNextConfig.scala': (
        '59f527d313fee7f46526c315a6a9b319a14d601d9878ff5f0c05896267594db1',
        'c9c611a1dcb6e58d1e36237eceff15468ced43e75795686483636e1ca19cb925'),
    'src/main/scala/core/ooo/IntegerBackend.scala': (
        'd14a5a7ab4b8e547a0209ffb2eade6c58ca66a01196ada9c27f58c72934b45c8',
        '172886d84f3c80d901ef69e2033de09c6d533b40c502db71466126fa431f27c6'),
    'src/main/scala/core/ooo/OooParams.scala': (
        '2b2879dc5f440a3239fd7aab0c0a490881b0b45eeb8d0eaee46b49d5aa45488c',
        '8e515e86f8fc993befe5b37ddfcb91507392f1e71111e60ca438fb64685b5d81'),
}
ADDED_LEAVES = {
    'src/main/scala/core/ooo/PostedYoungerLoadSeal.scala':
        '59f95a08ba98ef0a96e057dd0efd4993a8ae34b94fdb3099c8d392ebd0ec0dfe',
}
PRODUCTION_ROOTS = ('src/main/scala', 'src/main/resources',
                    'third_party/berkeley-hardfloat/src/main/scala')
# SHA256 of sorted compact JSON {repository-relative path: SHA256(file bytes)}.
# Exact combined production set, including the preserved MAC leaves; count is not trusted.
PRODUCTION_TREE_SHA256 = '1f783cbfc18a64c4be713533f7ed87cfecbc9b2bd35cfe3a8479a42385c5714d'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def production_tree_sha256(root):
    files = {path.relative_to(root).as_posix(): sha256(path.read_bytes())
             for folder in PRODUCTION_ROOTS for path in (root / folder).rglob('*') if path.is_file()}
    return sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())


def validate_legacy_sources(root, manifest_path, profile, options):
    """Validate only the original 64/68-option OFF views of this frozen source."""
    root = Path(root)
    manifest_path = Path(manifest_path)
    if any(option == FLAG or option.startswith(FLAG + '=') for option in options):
        raise RuntimeError('historical entry requires younger-load seal deferral false')
    expected_manifest = MANIFEST_SHA256.get(manifest_path.name)
    blob = manifest_path.read_bytes()
    if expected_manifest is None or sha256(blob) != expected_manifest or json.loads(blob) != profile:
        raise RuntimeError('original historical manifest identity or digest differs')
    expected_options = profile.get('native_options')
    if expected_options is None:
        expected_options = profile['retained59_options'] + profile['additional_options']
    if list(options) != expected_options:
        raise RuntimeError('exact historical ordered OFF options differ')
    leaves = profile['production_leaf_sha256']
    if not set(REPLACEMENTS).issubset(leaves) or set(ADDED_LEAVES).intersection(leaves):
        raise RuntimeError('exact source replacement/addition set differs from the original manifest')
    for name, (old_digest, new_digest) in REPLACEMENTS.items():
        if leaves[name] != old_digest or old_digest == new_digest:
            raise RuntimeError('source replacement old digest differs from the original manifest: ' + name)
    mac = load_mac_bridge(root).checked_sources()
    if set(mac) != set(MAC_PLATFORM_REPLACEMENTS):
        raise RuntimeError("MAC platform bridge replacement set differs")
    for name, row in mac.items():
        if (row["old_sha256"], row["new_sha256"]) != REPLACEMENTS.get(name):
            raise RuntimeError("MAC and younger-load bridge composition differs: " + name)
    replaced = set()
    for name, old_digest in leaves.items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts:
            raise RuntimeError('unsafe historical production leaf: ' + name)
        actual = sha256((root / path).read_bytes())
        expected = REPLACEMENTS[name][1] if name in REPLACEMENTS else old_digest
        if actual != expected:
            raise RuntimeError('historical source bridge production leaf differs: ' + name)
        if actual != old_digest:
            replaced.add(name)
    if replaced != set(REPLACEMENTS):
        raise RuntimeError('actual source replacement set differs')
    for name, digest in ADDED_LEAVES.items():
        if sha256((root / name).read_bytes()) != digest:
            raise RuntimeError('historical source bridge added leaf differs: ' + name)
    if production_tree_sha256(root) != PRODUCTION_TREE_SHA256:
        raise RuntimeError('frozen complete production source tree differs')
    return {'schema': 'young-load-seal-e4a-historical-source-bridge-v1',
            'triSpeedRawClockHandoff': False,
            'postedYoungerLoadSealDeferral': False, 'qualificationInherited': False,
            'fullCpuQualification': False, 'physicalQualification': False}


# Both source layers are independently bound. The original MAC manifest and
# complete A snapshot stay immutable; these substitutions chain only its two
# exact platform leaves to the reviewed merged source. No arity-based inference.
MAC_PLATFORM_REPLACEMENTS = {'src/main/scala/core/ooo/BoardSocTop.scala': ('55dc9bb7724532f6d235e114c21324771b64d16c60d68ffec082d24ebfb107ba',
                                               'bbb1418155c8ce2a56266c3c63640d9e17a4fa9311b81628bd89049c59b080d9'),
 'src/main/scala/core/ooo/FpgaNextConfig.scala': ('18bc78f275ea8d742f6c33621a2991e80a21377517d8adcbaa6da1dd19b4c4ab',
                                                  'c9c611a1dcb6e58d1e36237eceff15468ced43e75795686483636e1ca19cb925')}
MAC_RAW_MANIFEST_SHA256 = 'a5c2b4c9d18d61bbc44059d8a65be115f8f82b9f78d520e5c20209fb85a4cd86'
MAC_RAW_REPLACEMENTS = {'fpga/next/board_near_term_a.py': ('a5b9ab6dc923b3d0c1e342adeeeb50284cdb921e87e0a72cd8f0dc263b2f81e8',
                                    '9bff19320fe52163e7e1d2b78ab668ae5a6e0ac1a4b56e09952f785ab97d7382'),
 'fpga/next/board_near_term_a_raw_handoff.py': ('6ff24766376d283bdac2dc9277ea814c9aadc0afc682cebe0b144600d7a52bf9',
                                                '889d827851d522c46506b73108c54b19b6cb320d02f092b8c2be63d1299801c6'),
 'fpga/next/board_timing64.py': ('c9eb6c74b7d1870b7e0d480e0d0746d48903fdf9a02c458961c8bbddd420d0da',
                                 '24ecfb82390de433b5c6c2523c1546c795b9827e7ec8e5954f8ad618acffa9c9'),
 'fpga/next/export.py': ('17f18ef261f9e169f50dc40994236fb85dacd4fb28efddae616714dd975c94cf',
                         '339e8cf135c2e661ae5fb07712caa18c219cd57a5a234291ad98041fd1bab0a6'),
 'fpga/next/mac_platform_source_bridge.py': ('1b077276f38acd66676bff7b7d4c042281d7729bd2fb74c7e5bb62d18c27eef5',
                                             '6def3bf7996acee33a73202ca1106ab706ef177bfde3fc23658ff0f34d13436f'),
 'src/main/scala/core/ooo/BoardSocTop.scala': ('55dc9bb7724532f6d235e114c21324771b64d16c60d68ffec082d24ebfb107ba',
                                               'bbb1418155c8ce2a56266c3c63640d9e17a4fa9311b81628bd89049c59b080d9'),
 'src/main/scala/core/ooo/FpgaNextConfig.scala': ('18bc78f275ea8d742f6c33621a2991e80a21377517d8adcbaa6da1dd19b4c4ab',
                                                  'c9c611a1dcb6e58d1e36237eceff15468ced43e75795686483636e1ca19cb925'),
 'src/main/scala/core/ooo/IntegerBackend.scala': ('d14a5a7ab4b8e547a0209ffb2eade6c58ca66a01196ada9c27f58c72934b45c8',
                                                  '172886d84f3c80d901ef69e2033de09c6d533b40c502db71466126fa431f27c6'),
 'src/main/scala/core/ooo/OooParams.scala': ('2b2879dc5f440a3239fd7aab0c0a490881b0b45eeb8d0eaee46b49d5aa45488c',
                                             '8e515e86f8fc993befe5b37ddfcb91507392f1e71111e60ca438fb64685b5d81'),
 'src/test/scala/ooo/FpgaNextProfileMain.scala': ('09a5f3c4f775d63cf853784f88f8b356243658de19f3ecdc6e019b7fcfe49a2a',
                                                  'f7707393a5ef9584c85f7f8619fb6a8720e89b70b927d1ec207fc7b51f73ec0f'),
 'src/test/scala/ooo/MacRawHandoffEntry.scala': ('83d9fc27db26b41c87c3ce30f73bd3543ad4851399c06ce8f5edbb5e8381be49',
                                                 '24dcb82f42cab0b6629ddad2d66371b7aec6b25985b5000965b7883a36e3627d'),
 'src/test/scala/ooo/NearTermAProfile.scala': ('c090ed693466b969b92217c26e2e2be26729836fcec8430bbd4cea29d6eabb0e',
                                               '7432b0c15c07f2f2981745abafd9a4c5f8e6311b2c39f24b9c90c09de5c06ab4'),
 'src/test/scala/ooo/PlacedTimingProfileBridge.scala': ('299b8b1e28f3386374b0a49813b0500de23ed86161c520b9d6fe34ab46979bd6',
                                                        '55afcae39acd35c72e6b427b1fcd7a70a6bfe7a7badeea4c192aa15dfacf8dc0'),
 'src/test/scala/ooo/R3ReadLocalityProfile.scala': ('2222b76ae78fb4799800898115b5b9b646b8e8ef3781e6e77ed20bcfc0a9e733',
                                                    '38e865044f744fb71fda7f89b86970fabe41f5d2a7abff8271ac2b592f25ca00')}

def load_mac_bridge(root):
    path = Path(root) / 'fpga/next/mac_platform_source_bridge.py'
    spec = importlib.util.spec_from_file_location('composed_mac_platform_bridge', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def current_mac_platform_digest(name, historical_mac_digest):
    if name not in MAC_PLATFORM_REPLACEMENTS or MAC_PLATFORM_REPLACEMENTS[name][0] != historical_mac_digest:
        raise RuntimeError('exact historical MAC platform digest differs: ' + name)
    return MAC_PLATFORM_REPLACEMENTS[name][1]

def mac_raw_source_digest(name, historical_mac_digest):
    if name not in MAC_RAW_REPLACEMENTS:
        return historical_mac_digest
    old, current = MAC_RAW_REPLACEMENTS[name]
    if old != historical_mac_digest:
        raise RuntimeError('exact historical raw entry digest differs: ' + name)
    return current

def validate_mac_raw_contract(root, manifest_path, profile):
    path = Path(manifest_path)
    if path.name != 'near-term-a-raw-handoff-profile.json' or sha256(path.read_bytes()) != MAC_RAW_MANIFEST_SHA256:
        raise RuntimeError('original MAC raw entry manifest identity differs')
    if json.loads(path.read_bytes()) != profile:
        raise RuntimeError('original MAC raw entry manifest values differ')
    if any(o == FLAG or o.startswith(FLAG + '=') for o in profile['native_options']):
        raise RuntimeError('historical MAC raw entry requires younger-load seal deferral false')
    if not set(MAC_RAW_REPLACEMENTS).issubset(profile['production_leaf_sha256']):
        raise RuntimeError('MAC raw entry source replacement set differs')
    load_mac_bridge(root).checked_sources()
    if production_tree_sha256(Path(root)) != PRODUCTION_TREE_SHA256:
        raise RuntimeError('frozen complete production source tree differs')
