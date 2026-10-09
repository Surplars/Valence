#!/usr/bin/env python3
"""Portable source-only guest build with the repository's existing toolchain helper."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SCHEMA = 'valence-executed-cpu-order-guest-v1'
STATUS = 'PASS_GUEST_ASSEMBLY_ONLY'
PROFILE = {'march':'rv64im_zicsr_zifencei','mabi':'lp64','rom_base':0x80000000,
           'replay_address':0x80400000,'cold_base':0x80401000,'cold_lines':4,
           'signature_address':0x80600000,'ddr_read_latency':32}
SOURCES = ('cpu_order_replay.S','cpu_order_replay.ld')
ARTIFACTS = ('guest.o','guest.elf','guest.bin','symbols.txt')
SYMBOLS = {'_start','warmup_load','replay_div','replay_older','replay_younger','branch_div','branch_taken',
           'wrong0','wrong1','wrong2','wrong3','branch_target','survivor0','survivor1',
           'survivor2','survivor3','signature_store','replay_done'}

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(ok,message):
    if not ok: raise RuntimeError(message)
def symbol_text(symbols): return ''.join(f'{key} {symbols[key]:x}\n' for key in sorted(symbols))
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=HERE.parents[3])
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(); repo=a.repo.resolve(); out=a.out.resolve()
    sys.path.insert(0,str(repo/'simulator/gsim'))
    import build_cpu_hot_bandwidth as helper
    require(helper.common.ROOT==repo,'toolchain helper repository mismatch')
    tools,versions=helper.toolchain()
    files=[HERE/Path(__file__).name,*[HERE/name for name in SOURCES],Path(helper.__file__),
           repo/'simulator/gsim/run.py',repo/'simulator/gsim/config/toolchain.json']
    frozen={path:sha(path) for path in files}
    require(not out.exists(),'Use a fresh guest output directory')
    out.mkdir(parents=True); (out/'sources').mkdir()
    for name in SOURCES: shutil.copyfile(HERE/name,out/'sources'/name)
    state={'schema':SCHEMA,'status':'RUNNING','profile':PROFILE,'toolchain':versions,
           'toolchain_helper_sha256':sha(helper.__file__), 'gsim_lock':helper.common.LOCK,
           'builder_sha256':sha(__file__),'sources':{name:sha(HERE/name) for name in SOURCES},
           'commands':[],'artifacts':{},'symbols':{},'limits':['Guest assembly only; no model or runtime qualification.']}
    def save(): (out/'manifest.json').write_text(json.dumps(state,indent=2)+'\n')
    def guard():
        for path,digest in frozen.items(): require(sha(path)==digest,'Builder/source drift: '+str(path))
        for name in SOURCES: require(sha(out/'sources'/name)==state['sources'][name],'Copied guest source drift')
        for name,path in tools.items(): require(sha(path)==versions[name]['sha256'],'Guest toolchain executable drift')
        for name,digest in state['artifacts'].items(): require(sha(out/name)==digest,'Produced guest artifact drift: '+name)
        for item in state['commands']: require(sha(out/item['log'])==item['log_sha256'],'Guest build log drift')
    def step(name,command,products=()):
        guard()
        with (out/(name+'.log')).open('w') as stream:
            result=subprocess.run(list(map(str,command)),cwd=out,stdout=stream,stderr=subprocess.STDOUT,
                                  timeout=60,env={**os.environ,'SOURCE_DATE_EPOCH':'0','LC_ALL':'C'})
        state['commands'].append({'command':[Path(command[0]).name,*map(str,command[1:])],
                                  'exit':result.returncode,'log':name+'.log','log_sha256':sha(out/(name+'.log'))})
        save(); require(result.returncode==0,'Guest build failed: '+name)
        guard()
        for product in products: state['artifacts'][product]=sha(out/product)
        save()
        return (out/(name+'.log')).read_text()
    flags=['-march='+PROFILE['march'],'-mabi='+PROFILE['mabi'],'-mno-relax']
    try:
        step('assemble',[tools['cc'],*flags,'-c','sources/cpu_order_replay.S','-o','guest.o'],['guest.o'])
        step('link',[tools['cc'],*flags,'-nostdlib','-nostartfiles','-Wl,--no-relax','-Wl,--build-id=none',
                     '-T','sources/cpu_order_replay.ld','guest.o','-o','guest.elf'],['guest.elf'])
        step('binary',[tools['objcopy'],'-O','binary','guest.elf','guest.bin'],['guest.bin'])
        symbols={}
        for line in step('symbols',[tools['nm'],'-n','guest.elf']).splitlines():
            fields=line.split()
            if len(fields)==3 and fields[2] in SYMBOLS:
                require(fields[2] not in symbols,'Duplicate guest symbol'); symbols[fields[2]]=int(fields[0],16)
        require(set(symbols)==SYMBOLS and symbols['_start']==PROFILE['rom_base'],'Guest symbol layout mismatch')
        require(0<(out/'guest.bin').stat().st_size<=128*1024,'Guest ROM size mismatch')
        require(all(PROFILE['rom_base']<=v<PROFILE['rom_base']+(out/'guest.bin').stat().st_size for v in symbols.values()),
                'Guest symbol outside binary')
        require(symbols['branch_div']//64==symbols['wrong3']//64, 'DIVUW/branch/four loads crossed instruction line')
        require(symbols['replay_div']//64==symbols['replay_younger']//64, 'Replay instructions crossed line')
        (out/'symbols.txt').write_text(symbol_text(symbols)); state['symbols']=symbols
        state['artifacts']['symbols.txt']=sha(out/'symbols.txt'); guard()
        state['status']=STATUS
    except BaseException as error:
        state['status']='FAIL';state['error']=str(error);save();raise
    save(); print(STATUS,out/'manifest.json')
if __name__=='__main__': main()
