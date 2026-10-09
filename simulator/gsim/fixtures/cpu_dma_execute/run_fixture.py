#!/usr/bin/env python3
"""Strict source-matched executed CPU/copy-DMA replay; never builds a model or installs tools."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
HERE=Path(__file__).resolve().parent
def require(ok,message):
    if not ok: raise RuntimeError(message)
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def check_schema(model):
    header=(model/'BoardSocGsim.h').read_text()
    fields={'dma$busy':1,'dma$done':1,'dma$failed':1,'dma$source':64,'dma$destination':64,
            'dma$length':64,'dma$readsSent':29,'dma$writesDone':29,'dma$held':1,
            'privateCache$probeState':2,'privateCache$probeDirty':1,'privateCache$probeAddress':64,
            'privateCache$probeBeat':3}
    for field,width in fields.items():
     pattern=r'\bboard\$platform\$'+re.escape(field)+r'; // width = '+str(width)+r','
     if not re.search(pattern,header): raise SystemExit('Generated model field/schema mismatch: '+field)
    for field,count,width in [('dma$phases',4,2),('privateCache$probeWords',8,64)]:
     pattern=r'\bboard\$platform\$'+re.escape(field)+r'\['+str(count)+r'\]; // width = '+str(width)+r','
     if not re.search(pattern,header): raise SystemExit('Generated model array/schema mismatch: '+field)
    for accessor in ['get_cpuFlowEvents','get_cpuFlowIngressAuth','get_cpuFlowCheckedAuth',
                     'get_cpuFlowPhysicalAuth','get_backendSlot0Tag','get_backendSlot1Tag']:
     if accessor not in header: raise SystemExit('Missing complete CPU flow/token accessor: '+accessor)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=HERE.parents[3])
    p.add_argument('--model-receipt',type=Path,required=True)
    p.add_argument('--guest',type=Path)
    p.add_argument('--out',type=Path)
    p.add_argument('--physical-flow',type=int,choices=[0,1],required=True)
    p.add_argument('--cxx',default=os.environ.get('GSIM_CXX','clang++-19'))
    p.add_argument('--schema-only',action='store_true',help='Nonqualifying header inspection; permits RUNNING models')
    a=p.parse_args(); repo=a.repo.resolve(); receipt=a.model_receipt.resolve()
    require(receipt.is_file(),'Explicit model receipt required')
    model=receipt.parent/'model'
    check_schema(model)
    if a.schema_only:
        status=json.loads(receipt.read_text()).get('status','unknown')
        print('PASS_HEADER_SCHEMA_ONLY model_status='+status+' qualification=NONE source_profile_toolchain_NOT_VALIDATED')
        return
    require(a.guest is not None and a.out is not None,'--guest and --out required for a qualifying run')
    guest=a.guest.resolve(); out=a.out.resolve()
    sys.path.insert(0,str(repo/'simulator/gsim'))
    import run as common
    import fpga_next_board as board
    import cpu_bandwidth_flow_board as validation
    import build_cpu_hot_bandwidth as helper
    import build_guest as build
    require(common.ROOT==repo and build.HERE==HERE,'Imported repository/fixture mismatch')
    os.environ['GSIM_CXX']=a.cxx
    cxx,compiler=common.compiler()
    compiler_path=Path(shutil.which(cxx) or cxx).resolve()
    require(compiler_path.is_file(),'Existing supported host compiler required')
    compiler_sha=sha(compiler_path)
    tools,tool_versions=helper.toolchain()
    shared={'dma_line_transfers':True,'dma_line_entries':4,'dma_line_yield_cycles':0}
    inputs=board.source_inventory()
    model_state,model,objects=validation.validate_model(receipt,a.physical_flow,inputs,compiler,**shared)
    receipt_sha=sha(receipt)
    manifest_path=guest/'manifest.json'; manifest_sha=sha(manifest_path)
    manifest=json.loads(manifest_path.read_text())
    require(manifest.get('schema')==build.SCHEMA and manifest.get('status')==build.STATUS,'Invalid guest manifest')
    require(manifest.get('profile')==build.PROFILE,'Guest profile drift')
    require(manifest.get('toolchain')==tool_versions,'Guest compiler/binutils executable/version drift')
    require(manifest.get('toolchain_helper_sha256')==sha(helper.__file__),'Guest toolchain helper drift')
    require(manifest.get('gsim_lock')==common.LOCK,'Guest/repository toolchain lock drift')
    require(manifest.get('builder_sha256')==sha(build.__file__),'Guest builder drift')
    require(set(manifest.get('sources',{}))==set(build.SOURCES),'Guest source inventory mismatch')
    require(set(manifest.get('artifacts',{}))==set(build.ARTIFACTS),'Guest artifact inventory mismatch')
    require(set(manifest.get('symbols',{}))==build.SYMBOLS,'Guest symbol inventory mismatch')
    require(len(manifest.get('commands',[]))==4 and
            {item.get('log') for item in manifest['commands']}=={'assemble.log','link.log','binary.log','symbols.log'} and
            all(item.get('exit')==0 for item in manifest['commands']),'Guest build step/log inventory mismatch')
    require((guest/'symbols.txt').read_text()==build.symbol_text(manifest['symbols']),'Guest symbols/text mismatch')
    paths=[HERE/name for name in ('cpu_dma_execute.S','cpu_dma_execute.ld','cpu_dma_execute.cpp','build_guest.py','run_fixture.py','README.md')]
    paths += [Path(validation.__file__),Path(helper.__file__),repo/'simulator/gsim/config/toolchain.json']
    frozen={path:sha(path) for path in paths}
    require(not out.exists(),'Use a fresh result directory')
    out.mkdir(parents=True)
    state={'schema':'valence-executed-cpu-dma-replay-v1','status':'RUNNING','physical_ingress_flow':a.physical_flow,
           'shared_dma_profile':shared,'model_receipt_sha256':receipt_sha,'model_plan':model_state['plan'],
           'model_inputs':inputs,'host_compiler':{'name':compiler_path.name,'version':compiler,'sha256':compiler_sha},
           'guest_manifest_sha256':manifest_sha,'guest_toolchain':tool_versions,
           'fixture_inputs':{path.name:sha(path) for path in paths[:6]},'runs':[],'products':{},
           'limits':['Actual executed CPU and coherent MemoryCopyDma only; packet DMA/MAC/CDC/NEMU/FPGA/board unqualified.',
                     'Private registered probe transitions identify accepted dirty C beats; observations do not drive DUT traffic.',
                     'Checker negatives mutate observer expectations only; denied R in positive is actual AXI error injection.']}
    def save(): (out/'receipt.json').write_text(json.dumps(state,indent=2)+'\n')
    def guard():
        require(sha(receipt)==receipt_sha,'Model receipt changed')
        require(sha(manifest_path)==manifest_sha,'Guest manifest changed')
        require(sha(compiler_path)==compiler_sha,'Host compiler executable changed')
        for path,digest in frozen.items(): require(sha(path)==digest,'Fixture/validator input drift: '+str(path))
        require(board.source_inventory()==inputs,'Current model source inventory changed')
        _,checked_model,checked_objects=validation.validate_model(receipt,a.physical_flow,inputs,compiler,**shared)
        require(checked_model==model and checked_objects==objects,'Model artifact set changed')
        for name,path in tools.items(): require(sha(path)==tool_versions[name]['sha256'],'Guest toolchain executable changed')
        for name,digest in manifest['sources'].items():
            require(sha(HERE/name)==digest and sha(guest/'sources'/name)==digest,'Guest source changed: '+name)
        for name,digest in manifest['artifacts'].items(): require(sha(guest/name)==digest,'Guest artifact changed: '+name)
        for item in manifest['commands']:
            require(sha(guest/item['log'])==item['log_sha256'],'Guest build log changed')
        for name,digest in state['products'].items(): require(sha(out/name)==digest,'Produced replay artifact changed: '+name)
        for item in state['runs']: require(sha(out/item['log'])==item['log_sha256'],'Produced replay log changed')
    def step(name,command,expected,anchor=None,products=()):
        guard()
        with (out/(name+'.log')).open('w') as stream:
            result=subprocess.run(list(map(str,command)),cwd=repo,stdout=stream,stderr=subprocess.STDOUT,timeout=300,
                                  env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        text=(out/(name+'.log')).read_text()
        state['runs'].append({'name':name,'command':list(map(str,command)),'exit':result.returncode,
                              'log':name+'.log','log_sha256':sha(out/(name+'.log'))})
        save()
        require(result.returncode==expected and (not anchor or anchor in text),name+' failed:\n'+text[-6000:])
        guard()
        for name in products: state['products'][name]=sha(out/name)
        save(); print(text[-1200:])
    flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
           '-DUART_DIVISOR=1','-DBOARD_CPU_HZ=100000000','-DBOARD_UART_BAUD=460800','-DUART_EXTRA_STOP_BITS=0',
           '-DDDR_MODEL=1','-DBOARD_DDR_BYTES=2147483648ULL','-DDDR_MULTI_ID_MODEL=1','-DDDR_BENCHMARK_MODEL=1',
           '-DDDR_READ_CREDITS=8','-DDDR_READ_LATENCY=32','-DDDR_READ_BEAT_GAP=1','-DBOARD_CYCLE_LIMIT=300000ULL',
           '-DPHYSICAL_INGRESS_FLOW='+str(a.physical_flow),'-I'+str(model),'-I'+str(repo/'simulator/gsim/harness')]
    try:
        step('link',[cxx,*flags,HERE/'cpu_dma_execute.cpp',*objects,'-ldl','-o',out/'run'],0,products=['run'])
        base=[out/'run',guest/'guest.bin',guest/'symbols.txt']
        step('positive',base,0,'EXEC_CPU_DMA_PASS')
        for mode,anchor in [('destination','independent DMA destination generation mismatch'),
                            ('route','physical ingress route prediction mismatch'),
                            ('return-token','backend return full-token lineage corruption'),
                            ('read-region','unexpected guest RAM read region')]:
            step('negative-'+mode,[*base,'--inject-'+mode],1,anchor)
        guard(); state['status']='PASS_EXECUTED_CPU_COHERENT_COPY_DMA'
    except BaseException as error:
        state['status']='FAIL';state['error']=str(error);save();raise
    save(); print(state['status'],out/'receipt.json')
if __name__=='__main__': main()
