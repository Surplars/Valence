"""Default setup migration for the repaired epoch, separate from frozen receipts."""
import os
from pathlib import Path
import subprocess
import gsim_initialization_epoch as epoch


def canonical_output(common):
    return common.ROOT / 'build/gsim-tools' / ('init-byte-span-' + epoch.PATCH_SHA256[:16])


def prepare_pristine(common, cxx):
    source = common.SOURCE
    if not (source / '.git').exists():
        if source.exists() and any(source.iterdir()):
            raise RuntimeError('refusing to overwrite nonempty GSIM source: ' + str(source))
        source.mkdir(parents=True, exist_ok=True)
        common.run(['git', 'init', source])
        common.run(['git', 'remote', 'add', 'origin', common.LOCK['repository']], cwd=source)
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=source, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    try:
        revision = git('rev-parse', 'HEAD')
    except subprocess.CalledProcessError:
        revision = ''
    if not revision:
        common.run(['git', 'fetch', '--depth=1', 'origin', epoch.REVISION], cwd=source)
        common.run(['git', 'checkout', '--detach', 'FETCH_HEAD'], cwd=source)
        revision = git('rev-parse', 'HEAD')
    if revision != epoch.REVISION or common.LOCK['revision'] != epoch.REVISION:
        raise RuntimeError('pristine GSIM source does not match initialization repair pin')
    if git('status', '--porcelain', '--untracked-files=all'):
        raise RuntimeError('pristine GSIM source must be clean; refusing to change it')
    # Only the regression negative control uses this executable. Preserve any
    # existing binary and objects, even when rebuilding might be convenient.
    original = source / 'build/gsim/gsim'
    if not original.exists():
        common.run(['make', '-j' + os.environ.get('GSIM_BUILD_JOBS', '2'),
                    'CXX=' + cxx, 'build-gsim'], cwd=source,
                   log=common.BUILD / 'pristine-diagnostic-build.log')
    if not original.is_file():
        raise RuntimeError('pristine diagnostic executable missing: ' + str(original))


def build_fresh(common, output):
    if output.exists():
        raise RuntimeError('incomplete repaired epoch directory exists; preserve it for diagnosis '
                           'and move it aside before retrying make gsim-setup: ' + str(output))
    cxx, _ = common.compiler()
    common.BUILD.mkdir(parents=True, exist_ok=True)
    prepare_pristine(common, cxx)
    fixes = common.HERE / 'tool_fixes'
    env = os.environ.copy()
    env['GSIM_CXX'] = cxx
    common.run(['bash', fixes / 'build_init_byte_span.sh', common.SOURCE, output],
               env=env, timeout=1800)
    common.run(['python3', fixes / 'record_init_byte_span.py', '--output', output,
                '--original', common.SOURCE], env=env, timeout=300)


def setup(fetch, common):
    explicit = os.environ.get('VALENCE_GSIM_INIT_RECEIPT')
    output = canonical_output(common)
    receipt = Path(explicit).expanduser().resolve() if explicit else output / 'receipt.json'
    if explicit or receipt.exists():
        # A missing/tampered explicit or canonical receipt fails, never falls back.
        binding = epoch.tool_binding(receipt)
    else:
        if not fetch:
            raise RuntimeError('verified repaired GSIM epoch missing; run make gsim-setup '
                               'or set VALENCE_GSIM_INIT_RECEIPT to a qualified receipt')
        build_fresh(common, output)
        binding = epoch.tool_binding(receipt)
    cxx, _ = common.compiler()
    return Path(binding['gsim']['path']), cxx
