#!/usr/bin/env python3
"""Fetch-prefix V2: unchanged whole monitor ELF, fixed fetch history ON, older-prefix OFF/ON. Default preflight only."""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prepare
from compress_debug import load_helper
require, sha = prepare.require, prepare.sha


def fields(model,fetch_previous_packet):
    header = (model/'BoardSocGsim.h').read_text()
    required = {
        'board$platform$core$core$core$backend$orderCheckValid': (1, None),
        'board$platform$core$core$core$backend$replayPendingValid': (1, None),
        'board$platform$core$core$core$backend$payload_1$pcBank0': (64, 8),
        'board$platform$core$core$core$backend$payload_1$pcBank1': (64, 8),
        'board$platform$core$core$core$backend$systemUnit$state': (3, None),
        'board$platform$core$core$core$backend$systemUnit$result$$completion$$token$$tag': (64, None),
        'board$platform$core$core$core$backend$systemUnit$result$$completion$$token$$index': (4, None),
        'board$platform$core$core$core$backend$systemUnit$result$$completion$$nextPc': (64, None),
        'board$platform$core$core$core$backend$systemUnit$result$$completion$$data': (64, None),
        'board$platform$core$core$core$backend$systemUnit$result$$completion$$exception': (1, None),
        'board$platform$core$core$core$backend$ledger$io$$commit$$bits$$token$$tag_0': (64, None),
        'board$platform$core$core$core$backend$ledger$io$$commit$$bits$$token$$tag_1': (64, None),
    }
    for name, (width, count) in required.items():
        pattern = r'\b'+re.escape(name)+(r'\['+str(count)+r'\]' if count else '')+r'; // width = '+str(width)+','
        require(re.search(pattern, header), 'frozen generated register schema mismatch: '+name)
    for name in ('get_cpuFlowEvents', 'get_cpuFlowIngressAuth', 'get_cpuFlowCheckedAuth',
                 'get_cpuFlowPhysicalAuth', 'get_io$$fetchPc', 'get_perfSupply', 'get_perfRename', 'get_perfEvents', 'get_perfCacheEvents',
                 'get_backendSlot0Tag', 'get_backendSlot1Tag', 'get_dataPathReply4Data'):
        require(name+'(' in header, 'missing source-bound public accessor: '+name)
    
    for name in ('get_backendSlotCount','get_backendSlotIndicesHi','get_backendSlotStateHi','get_backendSlot2Tag','get_backendSlot3Tag'):
        require(name+'(' in header, 'missing four-owner accessor: '+name)
    stage=json.loads((HERE/'stage_schema.json').read_text())
    for name,(width,count) in stage.items():
        pattern=r'\b'+re.escape(name)+(r'\['+str(count)+r'\]' if count else '')+r'; // width = '+str(width)+','
        require(re.search(pattern,header),'stage register schema mismatch: '+name)
    required.update(stage)
    if fetch_previous_packet:
        history=json.loads((HERE/'history_schema.json').read_text())
        require(history.get('qualified') is True,'history generated-field schema awaits actual ON header')
        for name,(width,count) in history['fields'].items():
            pattern=r'\b'+re.escape(name)+(r'\['+str(count)+r'\]' if count else '')+r'; // width = '+str(width)+','
            require(re.search(pattern,header),'history register schema mismatch: '+name)
        required.update(history['fields'])
    return required


def parse(text):
    result={k:{} for k in ('intervals','pipeline','ipc','loops','distributions','buckets','stage_states','stage_histograms')}
    result.update(rdtime=[],uart=[])
    targets={'MONITOR_INTERVAL':'intervals','MONITOR_PIPELINE':'pipeline','BOARD_IPC':'ipc','MONITOR_LOOP':'loops','MONITOR_DISTRIBUTION':'distributions'}
    single={'MONITOR_REPLAY_PASS':'pass','MONITOR_STAGE_PASS':'stage_summary','MONITOR_FRONTEND_PASS':'frontend_summary'}
    for line in text.splitlines():
        prefix,_,rest=line.partition(' ')
        if prefix in {*targets,*single,'MONITOR_RDTIME','MONITOR_BUCKET','MONITOR_STAGE_STATE','MONITOR_STAGE_HIST'}:
            items=[item.split('=',1) for item in rest.split()]
            require(all(len(item)==2 for item in items),'malformed report field')
            record=dict(items);require(len(record)==len(items),'duplicate report field')
            record={k:int(v) if v.isdigit() else v for k,v in record.items()}
            if prefix in single:
                target=single[prefix];require(target not in result,'duplicate singleton report');result[target]=record
            elif prefix=='MONITOR_RDTIME':result['rdtime'].append(record)
            elif prefix=='MONITOR_BUCKET':
                name=record.pop('name');category=record.pop('category');require(set(record)=={'cycles'},'bucket schema drift')
                group=result['buckets'].setdefault(name,{})
                require(category not in group,'duplicate cycle bucket');group[category]=record['cycles']
            elif prefix in ('MONITOR_STAGE_STATE','MONITOR_STAGE_HIST'):
                name=record.pop('name');target='stage_states' if prefix=='MONITOR_STAGE_STATE' else 'stage_histograms';key='owner_cycles' if prefix=='MONITOR_STAGE_STATE' else 'histogram'
                require(set(record)=={key} and name not in result[target],'duplicate/malformed stage report');result[target][name]=record[key]
            else:
                target=targets[prefix];name=record.pop('name');require(name not in result[target],'duplicate named report');result[target][name]=record
        if line.startswith('BW '):result['uart'].append(line)
    require('pass' in result and len(result['intervals'])==11 and len(result['rdtime'])==18 and len(result['uart'])==7,'incomplete actual replay result')
    require(result.get('stage_summary',{}).get('hot_retired_loads')==1024,'mandatory scalar-loop stage coverage absent')
    return result

def compile_flags(model,repo,out,older_prefix):
    return ['-std=c++20','-O1','-g','-DBACKEND_OWNER_COUNT=4','-fsanitize=address,undefined','-fno-sanitize-recover=all',
        '-DUART_DIVISOR=1','-DBOARD_CPU_HZ=100000000','-DBOARD_UART_BAUD=460800','-DUART_EXTRA_STOP_BITS=0',
        '-DDDR_MODEL=1','-DBOARD_DDR_BYTES=2147483648ULL','-DDDR_MULTI_ID_MODEL=1','-DDDR_BENCHMARK_MODEL=1',
        '-DDDR_READ_CREDITS=8','-DDDR_READ_LATENCY=32','-DDDR_READ_BEAT_GAP=1','-DBOARD_CYCLE_LIMIT=12000000ULL',
        '-DPHYSICAL_INGRESS_FLOW=1','-DOLDER_PREFIX_ENABLED='+str(older_prefix),'-DFETCH_PREVIOUS_PACKET=1','-I'+str(model),'-I'+str(repo/'simulator/gsim/harness'),'-I'+str(out)]

def production_anchor(repo,anchor):
    observer_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    production_tree=subprocess.check_output(['git','rev-parse',anchor+':src/main'],cwd=repo,text=True).strip()
    require(subprocess.check_output(['git','rev-parse','HEAD:src/main'],cwd=repo,text=True).strip()==production_tree,'production src/main tree differs from model anchor')
    require(subprocess.run(['git','diff','--quiet',anchor,'--','src/main'],cwd=repo).returncode==0,'uncommitted production resource/source drift')
    expected_files=set(subprocess.check_output(['git','ls-tree','-r','--name-only',anchor,'--','src/main'],cwd=repo,text=True).splitlines())
    require({str(path.relative_to(repo)) for path in (repo/'src/main').rglob('*') if path.is_file()}==expected_files,'production source/resource file set drift')
    return observer_head,production_tree

def external_sources(repo,compressed):
    names=['simulator/gsim/cpu_retire_prefix_board.py']
    if compressed:names.append('simulator/gsim/elf_debug_compression.py')
    return {name:sha(repo/name) for name in names}

def compression_command(repo,out):
    return [sys.executable,'-B',str(HERE/'compress_debug.py'),'--helper',str(repo/'simulator/gsim/elf_debug_compression.py'),
            '--before',str(out/'replay.uncompressed'),'--after',str(out/'replay'),'--receipt',str(out/'debug-compression.json')]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model-repo', required=True, type=Path, help='Source-matched current LSU4 checkout')
    p.add_argument('--model-receipt', required=True, type=Path)
    p.add_argument('--prepared', required=True, type=Path)
    p.add_argument('--older-prefix', required=True, type=int, choices=(0,1))
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--cxx', default=os.environ.get('GSIM_CXX', 'clang++-19'))
    p.add_argument('--compress-debug',action='store_true',help='Opt in to verified debug compression of the newly linked host executable; retain both binaries')
    p.add_argument('--run', action='store_true', help='Explicitly link one existing model and execute positive plus four negatives')
    a = p.parse_args()
    repo, receipt, prepared, out = (x.resolve() for x in (a.model_repo,a.model_receipt,a.prepared,a.out))
    require(not out.exists(), 'use a fresh replay output directory')
    pins = json.loads((HERE/'fetch-prefix-pins.json').read_text())
    original=repo.parent/'Valence-cpu-retire-prefix-next/simulator/gsim/fixtures/monitor_bandwidth_replay'
    for name,digest in pins['original_fixture_files'].items():require(sha(original/name)==digest,'qualified original fixture changed: '+name)
    require(set(pins['model_receipts'])=={'0','1'},'model receipt pins await terminal OFF/ON builds')
    require(sha(receipt) == pins['model_receipts'][str(a.older_prefix)], 'explicit frozen model receipt signature mismatch')
    observer_head,production_tree=production_anchor(repo,pins['model_source_head'])
    sys.path.insert(0,str(repo/'simulator/gsim'))
    import run as common
    import fpga_next_board as board
    import cpu_retire_prefix_board as validation
    require(common.ROOT == repo, 'model helper import escaped frozen checkout')
    os.environ['GSIM_CXX'] = a.cxx
    cxx, compiler = common.compiler()
    cxx_path = Path(shutil.which(cxx) or cxx)
    require(cxx_path.is_file(), 'supported installed compiler missing')
    # Keep clang++ spelling for invocation; realpath is only used for identity/hash.
    host = dict(argv0=cxx, path=str(cxx_path.resolve()), version=compiler, sha256=sha(cxx_path))
    inputs = board.source_inventory()
    shared = dict(dma_line_transfers=True,dma_line_entries=4,dma_line_yield_cycles=0,lsu_entries=4,load_order_older_retire=bool(a.older_prefix),fetch_previous_packet=True)
    model_state, model, objects = validation.validate_model(receipt,1,inputs,compiler,**shared)
    schema = fields(model,1)
    require(sha(prepared/'manifest.json')==pins['prepared_manifest_sha256'],'prepared payload is not qualified original static-r1')
    manifest = json.loads((prepared/'manifest.json').read_text())
    require(manifest['schema'] == prepare.SCHEMA and manifest['status'] == 'PASS_STATIC_ARCHIVE_AND_LAUNCHER', 'preparation did not pass')
    archive, source = Path(manifest['archive']), Path(manifest['source'])
    fresh = prepare.archive_check(archive,source)
    for name, value in fresh.items(): require(manifest[name] == value, 'preparation/archive mapping changed: '+name)
    for name, digest in manifest['artifacts'].items(): require(sha(prepared/name) == digest, 'prepared artifact changed: '+name)
    for name, digest in manifest['fixture_sources'].items(): require(sha(HERE/name) == digest, 'launcher source changed: '+name)
    for tool in manifest['tools'].values(): require(sha(tool['path']) == tool['sha256'], 'preparation tool changed')
    require(prepare.elf((prepared/'launcher.elf').read_bytes())['symbols']['launcher_done'] == manifest['launcher_symbols']['launcher_done'],
            'launcher ELF symbol mismatch')
    helper_path=repo/'simulator/gsim/elf_debug_compression.py'
    helper=load_helper(helper_path) if a.compress_debug else None
    compression_tools=helper.installed_tools() if helper else {}
    external=external_sources(repo,a.compress_debug)
    fixture = {p.name:sha(p) for p in HERE.iterdir() if p.is_file() and p.suffix in ('.cpp','.h','.S','.ld','.py','.json','.md')}
    frozen = {receipt:sha(receipt), prepared/'manifest.json':sha(prepared/'manifest.json'),
              cxx_path:sha(cxx_path), Path(validation.__file__):sha(validation.__file__), Path(prepare.__file__):sha(prepare.__file__)}
    if helper:
        frozen[helper_path]=sha(helper_path)
        for tool in compression_tools.values():frozen[Path(tool['path'])]=tool['sha256']
    out.mkdir(parents=True)
    header = '\n'.join('#define '+macro+' '+str(manifest['launcher_symbols'][name])+'ULL' for macro,name in
        [('LAUNCHER_RETURNED','launcher_returned'),('LAUNCHER_DONE','launcher_done'),('LAUNCHER_FAIL','launcher_fail')])
    header += '\n#define LAUNCHER_ROM_END '+str(0x80000000+(prepared/'launcher.bin').stat().st_size)+'ULL\n'
    (out/'launcher_contract.h').write_text(header)
    state = dict(schema='valence-whole-monitor-fetch-prefix-v2',status='PREFLIGHT',physical_ingress_flow=1,fetch_previous_packet=1,older_prefix=a.older_prefix,prechecked_data_flow=0,lsu_entries=4,model_repo=str(repo),
        model_receipt=str(receipt),model_receipt_sha256=sha(receipt),model_source_inputs=inputs,model_plan=model_state['plan'],
        model_git_at_build=model_state['git_head'],source_freeze=pins['model_source_head'],production_source_tree=production_tree,observer_git_head=observer_head,model_register_schema=schema,
        model_artifacts=model_state['artifacts'],host_compiler=host,guest_manifest_sha256=sha(prepared/'manifest.json'),
        guest=manifest,fixture_inputs=fixture,compress_debug=a.compress_debug,external_fixture_inputs=external,debug_compression_tools=compression_tools,shared_dma_profile={k:shared[k] for k in ('dma_line_transfers','dma_line_entries','dma_line_yield_cycles')},steps=[],products={'launcher_contract.h':sha(out/'launcher_contract.h')},
        limits=['GCC14.2 archived ELF only; real board GCC13.2 object unavailable. Not exact board reproduction.',
                'Older-prefix OFF/ON with fixed history ON is a same-source oneflag comparison; prior LSU2/LSU4 measurements are cross-checkpoint context.',
                'Stage ready/done/pending timestamps are registered-state visibility; no exact ALU-completion handshake is claimed.',
                'Fixed independent DDR host model, not physical DDR/MIG/PHY/CDC bandwidth.',
                'No guest recompilation, benchmark patch, model rebuild, source edit, NEMU, FPGA, Vivado or board access.',
                'Initial monitor cache history is not reproduced; the original in-diagnostic UART/flush/cache history is preserved.',
                'Raw traffic and inclusive retirement windows keep speculation, UART and all overhead. Actual guest rdtime is reported separately.',
                'Negatives corrupt checker-side observations only, never guest/model traffic.'])
    def save(): (out/'receipt.json').write_text(json.dumps(state,indent=2)+'\n')
    def guard():
        if helper:require(helper.installed_tools()==compression_tools,'compression tool executable/version changed during replay')
        require(production_anchor(repo,pins['model_source_head'])[1]==production_tree,'production anchor changed during replay')
        for name,digest in pins['original_fixture_files'].items():require(sha(original/name)==digest,'qualified original fixture changed during v2')
        for path,digest in frozen.items(): require(sha(path)==digest,'frozen replay input changed: '+str(path))
        require(board.source_inventory()==inputs,'frozen integration source closure changed')
        validation.validate_model(receipt,1,inputs,compiler,**shared)
        prepare.archive_check(archive,source)
        for name,digest in fixture.items(): require(sha(HERE/name)==digest,'fixture changed during replay: '+name)
        for name,digest in manifest['artifacts'].items(): require(sha(prepared/name)==digest,'prepared artifact changed: '+name)
        for name,digest in state['products'].items(): require(sha(out/name)==digest,'output artifact changed: '+name)
        for step in state['steps']: require(sha(out/step['log'])==step['log_sha256'],'prior step log changed')
    def step(name,cmd,expected,anchor=None,products=()):
        guard()
        with (out/(name+'.log')).open('w') as stream:
            completed=subprocess.run(list(map(str,cmd)),cwd=repo,stdout=stream,stderr=subprocess.STDOUT,
                timeout=1800 if name=='positive' else 600,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        text=(out/(name+'.log')).read_text()
        state['steps'].append(dict(name=name,command=list(map(str,cmd)),exit=completed.returncode,log=name+'.log',log_sha256=sha(out/(name+'.log'))))
        save()
        require(completed.returncode==expected and (anchor is None or anchor in text),name+' failed:\n'+text[-5000:])
        require(expected==0 or 'MONITOR_REPLAY_PASS' not in text,'negative incorrectly passed')
        guard()
        for item in products: state['products'][item]=sha(out/item)
        save(); print(name+': '+text[-500:],flush=True)
        return text
    flags=compile_flags(model,repo,out,a.older_prefix)
    state['compile_flags']=flags;save();guard()
    if not a.run:
        state['status']='PASS_REPLAY_PREFLIGHT_ONLY_NOT_EXECUTED';save();print(state['status'],out/'receipt.json');return
    try:
        state['status']='RUNNING';save()
        linked='replay.uncompressed' if a.compress_debug else 'replay'
        step('link',[cxx,*flags,HERE/'replay.cpp',*objects,'-ldl','-o',out/linked],0,products=[linked])
        if a.compress_debug:
            step('debug-compression',compression_command(repo,out),0,'MONITOR_DEBUG_COMPRESSION_PASS',products=['replay','debug-compression.json'])
            proof=helper.validate_compression_receipt(out/'replay.uncompressed',out/'replay',out/'debug-compression.json')
            require(proof['tools']==compression_tools and proof['tool_sha256']==external[str(helper_path.relative_to(repo))],'compression proof source/tool binding mismatch')
        base=[out/'replay',archive/'firmware/monitor-diagnostic.bin',prepared/'launcher.bin']
        text=step('positive',[*base,out/'positive-traffic.tsv',out/'positive-hot-stage.tsv',out/'positive-frontend.tsv'],0,'MONITOR_REPLAY_PASS',products=['positive-traffic.tsv','positive-hot-stage.tsv','positive-frontend.tsv'])
        state['result']=parse(text);save()
        negatives=[('data','monitor independent physical RAM reply mismatch'),('token','monitor CPU reply full-token mismatch'),('marker','monitor rdtime marker sequence mismatch'),('stage-token','hot stage start lacks full-token ROB owner')]
        for name,anchor in negatives:
            step('negative-'+name,[*base,out/('negative-'+name+'-traffic.tsv'),out/('negative-'+name+'-hot-stage.tsv'),out/('negative-'+name+'-frontend.tsv'),'--inject-'+name],1,anchor,products=['negative-'+name+'-traffic.tsv'])
        guard();state['status']='PASS_WHOLE_MONITOR_FETCH_PREFIX_V2'
    except BaseException as error:
        state['status']='FAIL';state['error']=str(error);save();raise
    save();print(state['status'],out/'receipt.json')


if __name__ == '__main__': main()
