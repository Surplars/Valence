"""Source-only exact-profile/checkpoint checks, independent of DUT observations."""
import hashlib
import json
from pathlib import Path
import re
import subprocess


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def exact(actual, expected):
    """JSON equality with Boolean/integer types preserved."""
    return json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


def expected_plan(older_prefix):
    require(type(older_prefix) is bool, 'older-prefix option must be Boolean')
    return {
        'parameters': ['--selected', '--dma-line-transfers', '--dma-line-entries=4',
                       '--lsu-entries=4', '--physical-load-ingress-flow'] +
                      (['--load-order-older-retire'] if older_prefix else []) +
                      ['--fetch-previous-packet'],
        'fetch_previous_packet': True, 'smoke_only': True,
        'passive_probes': True, 'guest_suite': ['rv64gc'],
    }


def production_anchor(repo, production, host=None, expected_tree=None):
    repo = Path(repo).resolve()
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()
    tree = git('rev-parse', production + ':src/main')
    if expected_tree is not None:
        require(tree == expected_tree, 'production anchor tree drift')
    require(git('rev-parse', 'HEAD:src/main') == tree, 'production source tree drift')
    require(subprocess.run(['git', 'diff', '--quiet', production, '--', 'src/main'],
                           cwd=repo).returncode == 0, 'production worktree content drift')
    entries = list((repo / 'src/main').rglob('*'))
    require(not any(p.is_symlink() for p in entries), 'production symlink inventory drift')
    tracked = set(git('ls-tree', '-r', '--name-only', production, '--', 'src/main').splitlines())
    actual = {p.relative_to(repo).as_posix() for p in entries if p.is_file()}
    require(actual == tracked, 'production worktree file inventory drift')
    if host is not None:
        require(subprocess.run(['git', 'merge-base', '--is-ancestor', host, 'HEAD'],
                               cwd=repo).returncode == 0, 'unrelated host checkout')
    return {'production_commit': production, 'production_tree': tree,
            'qualified_host_commit': host, 'host_head': git('rev-parse', 'HEAD')}


def contained(root, name):
    require(type(name) is str and bool(name), 'invalid artifact path')
    relative = Path(name)
    require(not relative.is_absolute() and relative.as_posix() == name and
            all(part not in ('.', '..') for part in relative.parts),
            'noncanonical artifact path: ' + name)
    path = root / relative
    require(all(not root.joinpath(*relative.parts[:count]).is_symlink()
                for count in range(1, len(relative.parts) + 1)),
            'symlink model artifact: ' + name)
    require(path.resolve().is_relative_to(root.resolve()), 'artifact escapes checkpoint: ' + name)
    return path


def model_files(root, artifacts):
    """Require the whole generated directory, not just globbed cpp/o subsets."""
    model = root / 'model'
    require(model.is_dir() and not model.is_symlink(), 'missing or symlink model directory')
    entries = list(model.rglob('*'))
    require(all(p.is_file() and not p.is_symlink() for p in entries),
            'unexpected nonregular model entry')
    actual = {p.relative_to(root).as_posix() for p in entries}
    units = sorted(p for p in entries if re.fullmatch(r'BoardSocGsim[0-9]+\.cpp', p.name))
    require(units, 'missing model translation unit set')
    indices = sorted(int(p.stem.removeprefix('BoardSocGsim')) for p in units)
    require(indices == list(range(len(units))) and
            all(p.stem == 'BoardSocGsim' + str(int(p.stem.removeprefix('BoardSocGsim'))) for p in units),
            'noncanonical model translation unit set')
    objects = [p.with_suffix('.o') for p in units]
    required = {'model/BoardSocGsim.h', 'model/BoardSocGsim.fir',
                *(p.relative_to(root).as_posix() for p in [*units, *objects])}
    declared = {name for name in artifacts if name.startswith('model/')}
    require(actual == required == declared, 'complete model file set mismatch')
    return model, objects


def validate_model(path, inputs, compiler, lock, *, older_prefix):
    path = Path(path).resolve()
    require(path.is_file(), 'missing explicitly reusable model receipt: ' + str(path))
    state = json.loads(path.read_text())
    require(state.get('schema') == 'valence-fpga-next-board-evidence-v1' and
            state.get('status') == 'PASS_FPGA_NEXT_BOARD_SMOKE',
            'model is not a completed board smoke checkpoint')
    require(exact(state.get('inputs'), inputs), 'model source inventory drift')
    require(exact(state.get('plan'), expected_plan(older_prefix)), 'model profile drift')
    require(exact(state.get('toolchain'), {**lock, 'compiler': compiler}),
            'model toolchain/profile drift')
    artifacts = state.get('artifacts')
    require(type(artifacts) is dict and artifacts, 'missing model artifact inventory')
    model, objects = model_files(path.parent, artifacts)
    for name, digest in artifacts.items():
        item = contained(path.parent, name)
        require(type(digest) is str and re.fullmatch('[0-9a-f]{64}', digest),
                'malformed model artifact hash: ' + name)
        require(item.is_file(), 'missing model artifact: ' + name)
        require(sha(item) == digest, 'model artifact content drift: ' + name)
    return state, model, objects
