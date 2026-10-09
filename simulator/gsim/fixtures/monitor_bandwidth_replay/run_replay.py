#!/usr/bin/env python3
"""Source-closed whole monitor ELF replay. Default is preflight; --run links/runs serially."""
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
require, sha = prepare.require, prepare.sha


def fields(model):
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
                 'get_cpuFlowPhysicalAuth', 'get_perfSupply', 'get_perfEvents', 'get_perfCacheEvents',
                 'get_backendSlot0Tag', 'get_backendSlot1Tag', 'get_dataPathReply4Data'):
        require(name+'(' in header, 'missing source-bound public accessor: '+name)
    require('get_backendSlot2Tag(' not in header, 'requires frozen two-entry LSU')
    return required


def parse(text):
    result = {'intervals': {}, 'pipeline': {}, 'ipc': {}, 'loops': {}, 'rdtime': [], 'uart': []}
    for line in text.splitlines():
        prefix, _, rest = line.partition(' ')
        if prefix in ('MONITOR_INTERVAL', 'MONITOR_PIPELINE', 'BOARD_IPC', 'MONITOR_LOOP', 'MONITOR_REPLAY_PASS', 'MONITOR_RDTIME'):
            record = dict(item.split('=', 1) for item in rest.split())
            record = {k:int(v) if v.isdigit() else v for k,v in record.items()}
            if prefix == 'MONITOR_REPLAY_PASS': result['pass'] = record
            elif prefix == 'MONITOR_RDTIME': result['rdtime'].append(record)
            else:
                target = {'MONITOR_INTERVAL':'intervals','MONITOR_PIPELINE':'pipeline','BOARD_IPC':'ipc','MONITOR_LOOP':'loops'}[prefix]
                name = record.pop('name');require(name not in result[target], 'duplicate result name');result[target][name] = record
        if line.startswith('BW '): result['uart'].append(line)
    require('pass' in result and len(result['intervals']) == 11 and len(result['rdtime']) == 18 and len(result['uart']) == 7,
            'incomplete actual replay result')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model-repo', required=True, type=Path, help='Immutable matching integration checkout, not current candidate')
    p.add_argument('--model-receipt', required=True, type=Path)
    p.add_argument('--prepared', required=True, type=Path)
    p.add_argument('--physical-flow', required=True, type=int, choices=(0,1))
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--cxx', default=os.environ.get('GSIM_CXX', 'clang++-19'))
    p.add_argument('--run', action='store_true', help='Explicitly link one existing model and execute positive plus three negatives')
    a = p.parse_args()
    repo, receipt, prepared, out = (x.resolve() for x in (a.model_repo,a.model_receipt,a.prepared,a.out))
    require(not out.exists(), 'use a fresh replay output directory')
    pins = json.loads((HERE/'pins.json').read_text())
    require(sha(receipt) == pins['model_receipts'][str(a.physical_flow)], 'explicit frozen model receipt signature mismatch')
    require(subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip() == pins['production_freeze'],
            'model checkout is not the declared production freeze')
    sys.path.insert(0,str(repo/'simulator/gsim'))
    import run as common
    import fpga_next_board as board
    import cpu_bandwidth_flow_board as validation
    require(common.ROOT == repo, 'model helper import escaped frozen checkout')
    os.environ['GSIM_CXX'] = a.cxx
    cxx, compiler = common.compiler()
    cxx_path = Path(shutil.which(cxx) or cxx)
    require(cxx_path.is_file(), 'supported installed compiler missing')
    # Keep clang++ spelling for invocation; realpath is only used for identity/hash.
    host = dict(argv0=cxx, path=str(cxx_path.resolve()), version=compiler, sha256=sha(cxx_path))
    inputs = board.source_inventory()
    shared = dict(dma_line_transfers=True,dma_line_entries=4,dma_line_yield_cycles=0)
    model_state, model, objects = validation.validate_model(receipt,a.physical_flow,inputs,compiler,**shared)
    schema = fields(model)
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
    fixture = {p.name:sha(p) for p in HERE.iterdir() if p.is_file() and p.suffix in ('.cpp','.h','.S','.ld','.py','.json','.md')}
    frozen = {receipt:sha(receipt), prepared/'manifest.json':sha(prepared/'manifest.json'),
              cxx_path:sha(cxx_path), Path(validation.__file__):sha(validation.__file__), Path(prepare.__file__):sha(prepare.__file__)}
    out.mkdir(parents=True)
    header = '\n'.join('#define '+macro+' '+str(manifest['launcher_symbols'][name])+'ULL' for macro,name in
        [('LAUNCHER_RETURNED','launcher_returned'),('LAUNCHER_DONE','launcher_done'),('LAUNCHER_FAIL','launcher_fail')])
    header += '\n#define LAUNCHER_ROM_END '+str(0x80000000+(prepared/'launcher.bin').stat().st_size)+'ULL\n'
    (out/'launcher_contract.h').write_text(header)
    state = dict(schema=prepare.SCHEMA,status='PREFLIGHT',physical_ingress_flow=a.physical_flow,model_repo=str(repo),
        model_receipt=str(receipt),model_receipt_sha256=sha(receipt),model_source_inputs=inputs,model_plan=model_state['plan'],
        model_git_at_build=model_state['git_head'],source_freeze=pins['production_freeze'],model_register_schema=schema,
        model_artifacts=model_state['artifacts'],host_compiler=host,guest_manifest_sha256=sha(prepared/'manifest.json'),
        guest=manifest,fixture_inputs=fixture,shared_dma_profile=shared,steps=[],products={'launcher_contract.h':sha(out/'launcher_contract.h')},
        limits=['GCC14.2 archived ELF only; real board GCC13.2 object unavailable. Not exact board reproduction.',
                'Fixed independent DDR host model, not physical DDR/MIG/PHY/CDC bandwidth.',
                'No guest recompilation, benchmark patch, model rebuild, source edit, NEMU, FPGA, Vivado or board access.',
                'Initial monitor cache history is not reproduced; the original in-diagnostic UART/flush/cache history is preserved.',
                'Raw traffic and inclusive retirement windows keep speculation, UART and all overhead. Actual guest rdtime is reported separately.',
                'Negatives corrupt checker-side observations only, never guest/model traffic.'])
    def save(): (out/'receipt.json').write_text(json.dumps(state,indent=2)+'\n')
    def guard():
        for path,digest in frozen.items(): require(sha(path)==digest,'frozen replay input changed: '+str(path))
        require(board.source_inventory()==inputs,'frozen integration source closure changed')
        validation.validate_model(receipt,a.physical_flow,inputs,compiler,**shared)
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
    flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
        '-DUART_DIVISOR=1','-DBOARD_CPU_HZ=100000000','-DBOARD_UART_BAUD=460800','-DUART_EXTRA_STOP_BITS=0',
        '-DDDR_MODEL=1','-DBOARD_DDR_BYTES=2147483648ULL','-DDDR_MULTI_ID_MODEL=1','-DDDR_BENCHMARK_MODEL=1',
        '-DDDR_READ_CREDITS=8','-DDDR_READ_LATENCY=32','-DDDR_READ_BEAT_GAP=1','-DBOARD_CYCLE_LIMIT=12000000ULL',
        '-DPHYSICAL_INGRESS_FLOW='+str(a.physical_flow),'-I'+str(model),'-I'+str(repo/'simulator/gsim/harness'),'-I'+str(out)]
    state['compile_flags']=flags;save();guard()
    if not a.run:
        state['status']='PASS_REPLAY_PREFLIGHT_ONLY_NOT_EXECUTED';save();print(state['status'],out/'receipt.json');return
    try:
        state['status']='RUNNING';save()
        step('link',[cxx,*flags,HERE/'replay.cpp',*objects,'-ldl','-o',out/'replay'],0,products=['replay'])
        base=[out/'replay',archive/'firmware/monitor-diagnostic.bin',prepared/'launcher.bin']
        text=step('positive',[*base,out/'positive-traffic.tsv'],0,'MONITOR_REPLAY_PASS',products=['positive-traffic.tsv'])
        state['result']=parse(text);save()
        negatives=[('data','monitor independent physical RAM reply mismatch'),('token','monitor CPU reply full-token mismatch'),('marker','monitor rdtime marker sequence mismatch')]
        for name,anchor in negatives:
            step('negative-'+name,[*base,out/('negative-'+name+'-traffic.tsv'),'--inject-'+name],1,anchor,products=['negative-'+name+'-traffic.tsv'])
        guard();state['status']='PASS_WHOLE_MONITOR_BANDWIDTH_REPLAY_GCC142'
    except BaseException as error:
        state['status']='FAIL';state['error']=str(error);save();raise
    save();print(state['status'],out/'receipt.json')


if __name__ == '__main__': main()
