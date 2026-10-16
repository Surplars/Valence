"""Versioned guarded-BOTH diagnostic identity; no legacy export qualification."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import shutil

SCHEMA = 'combined-network-diagnostic-mac-v1'
PARAMS = ('NATIVE_MAC_LOCAL_PAD_RESET_RELEASE', 'NATIVE_MAC_REGISTER_SELECTED_HALF')
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def safe(root, name):
    part = PurePosixPath(name)
    if not name or '\\' in name or ':' in name or part.is_absolute() or '..' in part.parts or part.as_posix() != name:
        raise ValueError('Unsafe source path')
    p = root.joinpath(*part.parts)
    if p.is_symlink() or not p.resolve().is_relative_to(root.resolve()) or not p.is_file(): raise ValueError('Missing/escaped source')
    return p

def sources(root):
    result=[]
    for name in ('synthesis-files.f', 'board-synthesis-files.f'):
        for line in safe(root,name).read_text().splitlines():
            line=line.strip()
            if not line or line.startswith('#'): continue
            safe(root,line)
            if line in result: raise ValueError('Duplicate synthesis source')
            result.append(line)
    required={"board/soc_top_fpga_next_ddr.sv", "board/native_gmac_pad_reset_clock.sv", "board/native_rx_falling_pair.sv"}
    if not required.issubset(result): raise ValueError("Missing required BOTH board source")
    return result

def guard(root):
    text=safe(root,'board/soc_top_fpga_next_ddr.sv').read_text()
    for name in PARAMS:
        if text.count('parameter '+name+' = 1') != 1: raise ValueError('Guarded BOTH requires defaults1/1')
    expected='initial if (NATIVE_MAC_LOCAL_PAD_RESET_RELEASE != 1 || NATIVE_MAC_REGISTER_SELECTED_HALF != 1) $fatal(1,"PAD candidate requires t1-selected serializer 1/1");'
    if text.count(expected)!=1: raise ValueError('Missing exact incompatible-override guard')
    if 'ENABLE_PAD_DOMAIN_RESET(1)' not in text or 'ENABLE_FALLING_PAIR(1)' not in text: raise ValueError('BOTH modules required')

def verify(root):
    root=Path(root).resolve(); p=root/'board/native-mac-mode.json'; m=json.loads(p.read_text())
    if m['schema']!=SCHEMA or m['t1']!=1 or m['selected']!=1 or m['physicalQualification'] is not False: raise ValueError('Wrong diagnostic mode')
    guard(root)
    if m['synthesisSources']!=sources(root): raise ValueError('Source list mismatch')
    required=set(m['synthesisSources'])|{'synthesis-files.f','board-synthesis-files.f','board/native_mac_contract.py','board/native-mac-mode.tcl','board/native_mac_roles.tcl','board/native_mac_session.tcl'}
    required |= {p.relative_to(root).as_posix() for p in (root/'board').iterdir() if p.suffix in ('.tcl', '.xdc')}
    if set(m['files'])!=required: raise ValueError('Diagnostic closure mismatch')
    for name,digest in m['files'].items():
        if sha(safe(root,name))!=digest: raise ValueError('Changed diagnostic input: '+name)
    return sha(p)

def stage(source_root, root):
    source_root=Path(source_root).resolve();root=Path(root).resolve();guard(root)
    names=sources(root)
    spec=importlib.util.spec_from_file_location('reviewed_t1',source_root/'fpga/next/board_t1.py'); legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    board=root/'board'
    for name in ('native_mac_roles.tcl','native_mac_session.tcl'): shutil.copy(source_root/'fpga/next'/name,board/name)
    shutil.copy(Path(__file__).resolve(),board/'native_mac_contract.py')
    # Unknown source control equivalence is deliberately false. Mapped role audit remains required.
    (board/'native-mac-mode.tcl').write_text(legacy.consumer_tcl(True,True,False,names) + '\nproc valence_native_mac_checkpoint {args} {error {Diagnostic flow requires external stage receipts; no legacy checkpoint writes permitted}}\n')
    files=set(names)|{'synthesis-files.f','board-synthesis-files.f','board/native_mac_contract.py'}
    files|={p.relative_to(root).as_posix() for p in board.iterdir() if p.suffix in ('.tcl', '.xdc')}
    record=dict(schema=SCHEMA,t1=1,selected=1,physicalQualification=False,synthesisSources=names,
        files={n:sha(safe(root,n)) for n in sorted(files)},
        sourceConsumerSha256=sha(source_root/'fpga/next/board_t1.py'),
        controlLemma=False, status='DIAGNOSTIC_SOURCE_IDENTITY_ONLY')
    (board/'native-mac-mode.json').write_text(json.dumps(record,indent=2)+'\n')
    return verify(root)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage', nargs=2, metavar=('SOURCE_ROOT','EXPORT'))
    p.add_argument('--session-identity', type=Path)
    a=p.parse_args()
    if a.stage: print(stage(*a.stage))
    elif a.session_identity: print(verify(a.session_identity))
    else: p.error('Only diagnostic staging/session identity supported; use diagnostic stage receipts for checkpoints')
