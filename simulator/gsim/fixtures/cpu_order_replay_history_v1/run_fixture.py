#!/usr/bin/env python3
"""R7 order gate with fixed fetch history ON and older-prefix OFF/ON; explicit models only."""
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
import strict_validation as validation
PRODUCTION='2288c7f008e9d6440e8a28e339da28152b54892a'
HOST='46b061977ad4189bd71d084dcb63e873a7f0c740'
NEGATIVES={
    'selector':'missing selector to pending boundary',
    'pending':'missing pending witness',
    'generation':'selector full-token mismatch',
    'recovery':'missing accepted replay recovery',
    'cancellation':'accepted recovery omitted LSU cancellation',
    'canceled-retirement':'canceled full generation retired',
    'read-data':'independent known-memory response mismatch',
    'data':'committed register data mismatch',
    'final-data':'committed register data mismatch',
    'terminal-axi':'terminal pre-callback AXI state not empty',
    'pc':'committed PC sequence mismatch',
    'drain':'terminal pending owner/reply drain failure',
}
def require(ok,message):
    if not ok: raise RuntimeError(message)
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def schema(model,older_prefix):
    text=(model/'BoardSocGsim.h').read_text()
    fields={'replayPendingValid':1,'replayPendingValid$NEXT':1,
            'replayPending$$token$$index':4,'replayPending$$token$$index$NEXT':4,
            'replayPending$$token$$tag':64,'replayPending$$token$$tag$NEXT':64,
            'orderCheckValid':1,'orderCheckIndex':4,'orderCheckBeat':61,'orderCheckLanes':8,
            'ordinaryLocalRedirectAccepted':1,'localCandidate$$valid':1,
            'localCandidate$$bits$$token$$tag':64,'localCandidate$$bits$$token$$index':4,
            'lsu$slots_0$cancelled':1,'lsu$slots_1$cancelled':1,'lsu$slots_2$cancelled':1,'lsu$slots_3$cancelled':1,
            'ledger$acceptHeadSystem':1,'ledger$nextTag':64,'ledger$io$$commit$$bits$$token$$tag_0':64,
            'ledger$io$$commit$$bits$$token$$tag_1':64}
    if older_prefix:fields['orderCheckTag']=64
    for name,width in fields.items():
        require(re.search(r'\bboard\$platform\$core\$core\$core\$backend\$'+re.escape(name)+r'; // width = '+str(width)+',',text),'generated scalar schema mismatch: '+name)
    for name,count,width in [('payload_1$pcBank0',8,64),('payload_1$pcBank1',8,64),('queue$$renamed$$token$$tag',16,64),
                             ('queue$$renamed$$token$$index',16,4),('ledger$committed',32,6),
                             ('physicalFile$initialized',64,1),('physicalFile$owner',64,1),
                             ('physicalFile$banks_0',64,64),('physicalFile$banks_1',64,64)]:
        require(re.search(r'\bboard\$platform\$core\$core\$core\$backend\$'+re.escape(name)+r'\['+str(count)+r'\]; // width = '+str(width)+',',text),'generated array schema mismatch: '+name)
    for accessor in ('get_backendSlotCount','get_backendSlot2Tag','get_backendSlot3Tag','get_cpuFlowEvents','get_cpuFlowCheckedAuth','get_cpuFlowPhysicalAuth'):
        require(accessor in text,'missing complete owner/flow accessor: '+accessor)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=HERE.parents[3])
    p.add_argument('--off-receipt',type=Path,required=True)
    p.add_argument('--on-receipt',type=Path,required=True)
    p.add_argument('--guest',type=Path,required=True)
    p.add_argument('--out',type=Path)
    p.add_argument('--validate-only',action='store_true')
    p.add_argument('--compress-debug',action='store_true',help='Compress only newly linked debug sections, retaining the uncompressed proof input')
    p.add_argument('--cxx',default=os.environ.get('GSIM_CXX','clang++-19'))
    a=p.parse_args();repo=a.repo.resolve();guest=a.guest.resolve()
    sys.path.insert(0,str(repo/'simulator/gsim'))
    import run as common
    import fpga_next_board as board
    import build_cpu_hot_bandwidth as helper
    import build_guest as build
    import elf_debug_compression as compression
    require(common.ROOT==repo and build.HERE==HERE,'imported repository/fixture mismatch')
    pins=json.loads((HERE/'r7_lineage.json').read_text())
    require(pins['production_commit']==PRODUCTION and pins['host_commit']==HOST,'fixture anchor drift')
    source_binding=validation.production_anchor(repo,PRODUCTION,HOST,pins['production_tree'])
    for name,digest in pins['retained_fixture_sha256'].items():
        require(sha(HERE/name)==digest,'qualified R7 source drift: '+name)
    os.environ['GSIM_CXX']=a.cxx;cxx,compiler=common.compiler()
    compiler_path=Path(shutil.which(cxx) or cxx).resolve();compiler_sha=sha(compiler_path)
    tools,tool_versions=helper.toolchain();inputs=board.source_inventory()
    shared={'dma_line_transfers':True,'dma_line_entries':4,'dma_line_yield_cycles':0,'lsu_entries':4}
    receipts={'off':a.off_receipt.resolve(),'on':a.on_receipt.resolve()}
    require(receipts['off']!=receipts['on'],'OFF and ON require distinct explicit receipts')
    models={};model_hashes={}
    for label,receipt in receipts.items():
        require(sha(receipt)==pins['qualified_model_receipts'][label]['sha256'],
                'explicit model receipt differs from qualified current checkpoint: '+label)
        result=validation.validate_model(receipt,inputs,compiler,common.LOCK,older_prefix=label=='on')
        models[label]=result;model_hashes[label]=sha(receipt);schema(result[1],label=='on')
    manifest_path=guest/'manifest.json';manifest_sha=sha(manifest_path);manifest=json.loads(manifest_path.read_text())
    require(manifest.get('schema')==build.SCHEMA and manifest.get('status')==build.STATUS,'invalid guest manifest')
    require(validation.exact(manifest.get('profile'),build.PROFILE),'guest profile drift')
    require(manifest.get('artifacts')==pins['guest_artifacts'],'qualified R7 guest artifact drift')
    require(manifest.get('symbols')==pins['guest_symbols'],'qualified R7 guest symbol drift')
    require(manifest.get('toolchain')==tool_versions,'guest toolchain executable/version drift')
    require(manifest.get('toolchain_helper_sha256')==sha(helper.__file__),'guest toolchain helper drift')
    require(manifest.get('gsim_lock')==common.LOCK,'guest toolchain lock drift')
    require(manifest.get('builder_sha256')==sha(build.__file__),'guest builder drift')
    require(set(manifest.get('sources',{}))==set(build.SOURCES),'guest source inventory mismatch')
    require(set(manifest.get('artifacts',{}))==set(build.ARTIFACTS),'guest artifact inventory mismatch')
    require(set(manifest.get('symbols',{}))==build.SYMBOLS,'guest symbol inventory mismatch')
    require(len(manifest.get('commands',[]))==4 and {x.get('log') for x in manifest['commands']}=={'assemble.log','link.log','binary.log','symbols.log'} and all(x.get('exit')==0 for x in manifest['commands']),'guest build command inventory mismatch')
    require((guest/'symbols.txt').read_text()==build.symbol_text(manifest['symbols']),'guest symbol text drift')
    paths=sorted(x for x in HERE.iterdir() if x.is_file() and x.suffix in ('.py','.h','.cpp','.S','.ld','.md','.json'))
    paths += [Path(helper.__file__),repo/'simulator/gsim/config/toolchain.json']
    if a.compress_debug: paths += [Path(compression.__file__)]
    frozen={path:sha(path) for path in paths}
    state={'schema':'valence-executed-cpu-order-replay-history-v1','status':'RUNNING','production_commit':PRODUCTION,'source_binding':source_binding,
           'r7_lineage':pins,
           'shared_profile':{**shared,'physical_ingress_flow':True,'virtual_precheck':False,'prechecked_flow':False,'fetch_previous_packet':True},
           'model_receipts':{k:{'path':str(v),'sha256':model_hashes[k],'plan':models[k][0]['plan']} for k,v in receipts.items()},
           'model_inputs':inputs,'fixture_inputs':{str(x.relative_to(repo)):sha(x) for x in paths},
           'host_compiler':{'name':compiler_path.name,'version':compiler,'sha256':compiler_sha},
           'guest_manifest_sha256':manifest_sha,'guest_toolchain':tool_versions,'runs':[],'products':{},
           'compress_debug':a.compress_debug,'debug_compression':{},
           'limits':['Bounded executing guest and observation sensitivity; no RTL mutation, NEMU, FPGA, board or timing qualification.',
                     'Unchanged external DDR schedule: read latency 32, beat gap 1, credits 8; DMA remains idle.',
                     'Fetch history remains ON; only older-prefix differs across exact-source OFF/ON checkpoints.']}
    out=a.out.resolve() if a.out else None
    def save():
        if out:(out/'receipt.json').write_text(json.dumps(state,indent=2)+'\n')
    def guard():
        require(validation.production_anchor(repo,PRODUCTION,HOST,pins['production_tree'])==source_binding,
                'production/host binding changed during qualification')
        require(sha(manifest_path)==manifest_sha,'guest manifest drift')
        require(sha(compiler_path)==compiler_sha,'host compiler drift')
        require(board.source_inventory()==inputs,'current model source inventory drift')
        for path,digest in frozen.items():require(sha(path)==digest,'fixture/validator source drift: '+str(path))
        for label,receipt in receipts.items():
            require(sha(receipt)==model_hashes[label],'model receipt drift: '+label)
            _,model,objects=validation.validate_model(receipt,inputs,compiler,common.LOCK,older_prefix=label=='on')
            require((model,objects)==models[label][1:],'model object set drift')
        for name,path in tools.items():require(sha(path)==tool_versions[name]['sha256'],'guest tool executable drift')
        for name,digest in manifest['sources'].items():require(sha(HERE/name)==digest and sha(guest/'sources'/name)==digest,'guest source drift: '+name)
        for name,digest in manifest['artifacts'].items():require(sha(guest/name)==digest,'guest artifact drift: '+name)
        for item in manifest['commands']:require(sha(guest/item['log'])==item['log_sha256'],'guest build log drift')
        for name,digest in state['products'].items():require(sha(out/name)==digest,'output artifact drift')
        for item in state['runs']:require(sha(out/item['log'])==item['log_sha256'],'output log drift')
    guard()
    if a.validate_only:print('PASS_SOURCE_PROFILE_MODEL_TOOL_GUEST_BINDING_ONLY execution=0');return
    require(out is not None and not out.exists(),'fresh --out required')
    out.mkdir(parents=True);save()
    def step(name,command,expected=0,anchor=None,products=()):
        guard()
        with (out/(name+'.log')).open('w') as stream:
            result=subprocess.run(list(map(str,command)),cwd=repo,stdout=stream,stderr=subprocess.STDOUT,timeout=300,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        text=(out/(name+'.log')).read_text()
        state['runs'].append({'name':name,'command':list(map(str,command)),'exit':result.returncode,'log':name+'.log','log_sha256':sha(out/(name+'.log'))});save()
        require(result.returncode==expected and (not anchor or anchor in text),name+' failed:\n'+text[-6000:])
        if name.startswith('negative-'):require('OBSERVATION_NEGATIVE fired=1' in text,'negative failed without firing: '+name)
        guard()
        for name in products:state['products'][name]=sha(out/name)
        save();print(text[-1600:])
    flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
           '-DBACKEND_OWNER_COUNT=4','-DPHYSICAL_INGRESS_FLOW=1','-DFETCH_PREVIOUS_PACKET=1','-DUART_DIVISOR=1','-DBOARD_CPU_HZ=100000000',
           '-DBOARD_UART_BAUD=460800','-DUART_EXTRA_STOP_BITS=0','-DDDR_MODEL=1','-DBOARD_DDR_BYTES=2147483648ULL',
           '-DDDR_MULTI_ID_MODEL=1','-DDDR_BENCHMARK_MODEL=1','-DDDR_READ_CREDITS=8','-DDDR_READ_LATENCY=32',
           '-DDDR_READ_BEAT_GAP=1','-DBOARD_CYCLE_LIMIT=20000ULL','-I'+str(repo/'simulator/gsim/harness')]
    try:
        step('host-link',[cxx,'-std=c++20','-O0','-Wall','-Wextra','-Werror',HERE/'test_oracle.cpp','-o',out/'host'],products=['host'])
        step('host-oracle',[out/'host',guest/'guest.bin',guest/'symbols.txt'],anchor='PASS_HOST_ONLY')
        for label,(_,model,objects) in models.items():
            linked=label+'.uncompressed' if a.compress_debug else label
            step(label+'-link',[cxx,*flags,'-DOLDER_PREFIX='+str(int(label=='on')),'-I'+str(model),HERE/'cpu_order_replay.cpp',*objects,'-ldl','-o',out/linked],products=[linked])
            if a.compress_debug:
                proof=out/(label+'.debug-compression.json')
                state['debug_compression'][label]=compression.compress_new(out/linked,out/label,proof)
                for product in (label,proof.name):state['products'][product]=sha(out/product)
                save();compression.validate_compression_receipt(out/linked,out/label,proof);guard()
            base=[out/label,guest/'guest.bin',guest/'symbols.txt']
            step(label+'-positive',base,anchor='EXECUTED_CPU_ORDER_PASS')
            for negative,anchor in NEGATIVES.items():step('negative-'+label+'-'+negative,[*base,'--inject-'+negative],expected=1,anchor=anchor)
        guard();state['status']='PASS_EXECUTED_CPU_ORDER_REPLAY_HISTORY_ON_PREFIX_OFF_ON'
    except BaseException as error:
        state['status']='FAIL';state['error']=str(error);save();raise
    save();print(state['status'],out/'receipt.json')
if __name__=='__main__':main()
