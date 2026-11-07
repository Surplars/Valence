"""Read-only binding for the qualified cloud-tools-20261030-r2 profile only.

Pinned receipt bytes are historical evidence, not a new qualification. Paths in
those receipts are remapped explicitly, never rewritten or treated as Git proof.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil

PROFILE = 'cloud-tools-20261030-r2-reset-graph-v1'
REVISION = '93b8cd23edd3228807c4f2a08c19c3936a463cb2'
MANIFEST_SHA256 = 'cea39b6d5214ad67ae48ddb9f543f5edcf6a1e7f63b4aded7d20489a0a9ed605'
RECEIPT_SHA256 = '7df9a7106fde34ba81b6ecf9e78b3ff7321eab427f6aa37aeb14c65889ecef71'
QUALIFICATION_SHA256 = '7f94d658e4b2f1217087d85fddbaf08ab0200f3d1e6366f2bf51f1ea2d7d8785'
HISTORICAL_ROOT = Path('/workspace/scratch/41e4a649bb60/cloud-tools-20261030-r2')
MILL_WRAPPER_SHA256 = '7ea71cdcf36514f48d003b75d3396ab793f0bf24e5e5c8396138ca61b9e28893'
JAVA_SHA256 = '1a7e0b17c39003c75b457d686775ccb032e56fa9c8afe3c492d8eb3715e8951a'
PATCHES = {
    'init-byte-span.patch': 'f17fe768c9b4665b310dc632e64333ae3d4e336521f60981f1ec7faaebc31c11',
    'reset-graph.patch': 'c42144ecfe74ddc231207dea6ebbe5d0f679f4d4cbc6f5edb29e476d67248895',
}


def need(ok, message):
    if not ok:
        raise RuntimeError('reset-graph bundle: ' + message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check(path, expected):
    need(digest(path) == expected, 'bytes changed: ' + str(path))


def pinned_json(path, expected):
    # Parse the same bytes we authenticated, not a second read.
    data = path.read_bytes()
    need(hashlib.sha256(data).hexdigest() == expected, 'receipt/manifest changed: ' + str(path))
    return json.loads(data)


def active(command, path):
    resolved = shutil.which(command)
    need(resolved is not None and Path(resolved).resolve() == path.resolve(),
         'active tool differs: ' + command)


def tool_binding(bundle, repository):
    root = Path(bundle).expanduser().resolve()
    repo = Path(repository).resolve()
    receipt_path = root / 'TOOLCHAIN-RECEIPT.json'
    receipt = pinned_json(receipt_path, RECEIPT_SHA256)
    qualification_path = root / 'gsim/qualification/PASS.json'
    qualification = pinned_json(qualification_path, QUALIFICATION_SHA256)
    manifest_path = repo / 'simulator/gsim/tool_fixes/reset-graph-inputs.json'
    manifest = pinned_json(manifest_path, MANIFEST_SHA256)
    need(manifest['upstream_commit'] == REVISION, 'upstream revision differs')
    need(manifest['patch_order'] == list(PATCHES) and manifest['patch_sha256'] == PATCHES,
         'ordered patch identity differs')
    for name, expected in PATCHES.items():
        check(manifest_path.parent / name, expected)
    source = root / 'gsim/source'
    sources = manifest['final_source_sha256']
    fixtures = manifest['executed_fixture_sha256']
    need(len(sources) == 101 and len(fixtures) == 13, 'incomplete input manifest')
    # Build products are not source inputs. No synthetic .git is required.
    names = {p.relative_to(source).as_posix() for p in source.rglob('*')
             if p.is_file() and p.relative_to(source).parts[0] not in ('build', '.git')}
    need(names == set(sources), 'source inventory differs')
    for name, expected in sources.items():
        check(source / name, expected)
    for name, expected in fixtures.items():
        check(repo / name, expected)

    def recorded_tool(name):
        entry = receipt['tools'][name]
        path = root / Path(entry['path']).relative_to(HISTORICAL_ROOT)
        check(path, entry['sha256'])
        return {'path': str(path), 'sha256': entry['sha256']}

    # Do not inspect or execute unrelated mapping tools present in the receipt.
    bindings = {name: recorded_tool(name) for name in ('gsim', 'clang', 'mill', 'firtool', 'env')}
    build = receipt['gsim_build']
    need(build['source_manifest_sha256'] == MANIFEST_SHA256 and
         build['receipt_sha256'] == QUALIFICATION_SHA256 and
         qualification['source_manifest_sha256'] == MANIFEST_SHA256 and
         qualification['gsim_sha256'] == bindings['gsim']['sha256'], 'qualification binding differs')
    cxx = os.environ.get('GSIM_CXX', 'clang++')
    active(cxx, Path(bindings['clang']['path']))
    wrapper = root / 'generation/bin/mill'
    check(wrapper, MILL_WRAPPER_SHA256)
    active('mill', wrapper)
    java = Path('/usr/lib/jvm/java-21-openjdk-amd64/bin/java')
    check(java, JAVA_SHA256)
    active('java', java)
    if 'JAVA_HOME' in os.environ:
        need(Path(os.environ['JAVA_HOME']).resolve() == java.parent.parent, 'JAVA_HOME differs')
    need(bool(os.environ.get('CHISEL_FIRTOOL_PATH')),
         'CHISEL_FIRTOOL_PATH must select the pinned firtool directory')
    selected_paths = {'GSIM': Path(bindings['gsim']['path']),
                      'VALENCE_GSIM_SOURCE': source,
                      'FIRTOOL': Path(bindings['firtool']['path']),
                      'CHISEL_FIRTOOL_PATH': Path(bindings['firtool']['path']).parent}
    for name, expected in selected_paths.items():
        if name in os.environ:
            need(bool(os.environ[name]) and Path(os.environ[name]).resolve() == expected.resolve(),
                 'conflicting selector: ' + name)
    return {
        'profile': PROFILE,
        'compiler': {**bindings['clang'], 'command': cxx},
        'mill': {**bindings['mill'], 'command': 'mill', 'wrapper_sha256': MILL_WRAPPER_SHA256},
        'java': {'path': str(java), 'sha256': JAVA_SHA256, 'command': 'java'},
        'firtool': bindings['firtool'],
        'gsim': {**bindings['gsim'], 'source': str(source), 'revision': REVISION,
                 'source_sha256': sources, 'patch_order': list(PATCHES), 'patch_sha256': PATCHES,
                 'source_manifest_sha256': MANIFEST_SHA256,
                 'qualification_receipt': str(qualification_path),
                 'qualification_receipt_sha256': QUALIFICATION_SHA256,
                 'bundle_receipt': str(receipt_path), 'bundle_receipt_sha256': RECEIPT_SHA256},
    }
