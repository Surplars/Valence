"""Explicit deterministic GSIM initialization epoch; never mutate the old tool."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

REVISION = '93b8cd23edd3228807c4f2a08c19c3936a463cb2'
PATCH_SHA256 = 'f17fe768c9b4665b310dc632e64333ae3d4e336521f60981f1ec7faaebc31c11'
OLD = 'memset(&_var_start, 0, &_var_end - &_var_start);'
NEW = 'memset(&_var_start, 0, reinterpret_cast<uintptr_t>(&_var_end) - reinterpret_cast<uintptr_t>(&_var_start));'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(ok, message):
    if not ok: raise RuntimeError(message)
def tool_binding(receipt_path):
    path=Path(receipt_path).resolve(); r=json.loads(path.read_text())
    need(r['status']=='PASS' and r['revision']==REVISION and r['mode']=='deterministic', 'unqualified initialization epoch')
    need(r['patch']['sha256']==PATCH_SHA256, 'unexpected initialization patch')
    for filename, expected in r['artifacts_sha256'].items():
        need(sha(filename)==expected, 'epoch artifact changed: '+filename)
    for key in ('compiler','mill','java'):
        b=r['binding'][key]
        active=os.environ.get('GSIM_CXX',b['command']) if key=='compiler' else b['command']
        resolved=shutil.which(active)
        need(resolved is not None and Path(resolved).resolve()==Path(b['path']), 'active tool differs: '+key)
        need(sha(b['path'])==b['sha256'], 'tool changed: '+key)
    g=r['binding']['gsim']; src=Path(g['source']); original=Path(r['original_source'])
    def git(*args): return subprocess.check_output(['git','-C',str(original),*args])
    need(git('rev-parse','HEAD').decode().strip()==REVISION, 'original revision changed')
    need(not git('status','--porcelain','--untracked-files=all').strip(), 'original source not clean')
    names=[line.split('\t',1)[1] for line in git('ls-tree','-r',REVISION).decode().splitlines() if line.split()[1]=='blob']
    expected={}
    for name in names:
        content=git('show',REVISION+':'+name)
        if name=='src/cppEmitter.cpp':
            need(content.count(OLD.encode())==2, 'unexpected emitter anchors')
            content=content.replace(OLD.encode(),NEW.encode())
        expected[name]=hashlib.sha256(content).hexdigest()
        need(sha(src/name)==expected[name], 'nonminimal source change: '+name)
    need(expected==g['source_sha256'], 'source manifest mismatch')
    need(sha(g['path'])==g['sha256'], 'repaired binary changed')
    result=r['binding']
    result['gsim']={**g,'epoch_receipt':str(path),'epoch_receipt_sha256':sha(path)}
    return result
