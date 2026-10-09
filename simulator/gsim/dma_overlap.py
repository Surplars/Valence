#!/usr/bin/env python3
"""Source-bound DMA component latency/occupancy study. Bypasses are diagnostics, never coherence proof."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common

EVENTS = {
    'dma_offer_blocked': ('offer', 'dma_accept'),
    'dma_to_home_admission': ('dma_accept', 'home_accept'),
    'home_to_first_tl_a': ('home_accept', 'a_first'),
    'tl_a_span': ('a_first', 'a_last'),
    'tl_a_to_axi_ar': ('a_first', 'ar'),
    'tl_a_to_axi_aw': ('a_first', 'aw'),
    'aw_to_wfirst': ('aw', 'w_first'),
    'w_span': ('w_first', 'w_last'),
    'ar_to_rfirst': ('ar', 'r_first'),
    'r_span': ('r_first', 'r_last'),
    'wlast_to_b': ('w_last', 'b'),
    'rlast_to_dlast': ('r_last', 'd_last'),
    'b_to_dlast': ('b', 'd_last'),
    'tl_d_to_home_response': ('d_last', 'home_response'),
    'home_to_dma_response': ('home_response', 'dma_response'),
    'dma_owner_lifetime': ('dma_accept', 'dma_response'),
    'home_owner_lifetime': ('home_accept', 'home_response'),
    'bridge_slot_lifetime': ('a_first', 'd_last'),
    'axi_read_lifetime': ('ar', 'r_last'),
    'axi_write_lifetime': ('aw', 'b'),
    'oracle_to_dma_response': ('oracle_response', 'dma_response'),
}

def summary(values):
    if not values: return None
    s=sorted(values)
    return {'n':len(s),'min':s[0],'mean':sum(s)/len(s),'p50':s[(len(s)-1)*50//100],
            'p95':s[(len(s)-1)*95//100],'p99':s[(len(s)-1)*99//100],'max':s[-1], 'sum':sum(s)}

def parse(out):
    cases={}; events={}; occupancies={}
    for line in (out/'test.log').read_text().splitlines():
        if not line.startswith(('PIPE_CASE ', 'PIPE_EVENT ', 'PIPE_OCCUPANCY ')): continue
        kind, rest=line.split(' ',1)
        row={k:float(v) if '.' in v else int(v) for k,v in (x.split('=',1) for x in rest.split())}
        key=row['case']
        if kind=='PIPE_CASE': cases[key]=row
        elif kind=='PIPE_EVENT': events.setdefault(key,[]).append(row)
        else: occupancies[key]=row
    for key,case in cases.items():
        trace=events[key]; occupancy=occupancies[key]; case['occupancy']=occupancy; case['latency']={}
        for write,label in [(0,'read'),(1,'write')]:
            rows=[e for e in trace if e['write']==write]
            case['latency'][label]={name:s for name,(a,b) in EVENTS.items()
                if (s:=summary([e[b]-e[a] for e in rows if e[a]>=0 and e[b]>=0])) is not None}
            turns=[trace[i+1]['dma_accept']-e['dma_response'] for i,e in enumerate(trace[:-1]) if e['write']==write]
            case['latency'][label]['next_issue_minus_previous_completion']=summary(turns)
            offers=[trace[i+1]['offer']-e['dma_response'] for i,e in enumerate(trace[:-1]) if e['write']==write]
            case['latency'][label]['next_offer_minus_previous_completion']=summary(offers)
        for event,area in [('dma_owner_lifetime','lineArea'),('home_owner_lifetime','homeArea'),('bridge_slot_lifetime','bridgeArea')]:
            total=sum(case['latency'][kind].get(event,{}).get('sum',0) for kind in ['read','write'])
            if total != occupancy[area]: raise RuntimeError(f'Integrated occupancy mismatch {key} {event}: {total} != {occupancy[area]}')
        if case['mode']<2:
            rd=case['latency']['read']['bridge_slot_lifetime'];wr=case['latency']['write']['bridge_slot_lifetime']
            scale=64*100000000/1048576
            case['latency_capacity_estimates_MiBps']={
                'shared_four_slots_at_observed_mean':4*scale/(rd['mean']+wr['mean']),
                'two_write_slots_at_observed_mean':2*scale/wr['mean'],
                'shared_four_slots_at_observed_min':4*scale/(rd['min']+wr['min']),
                'two_write_slots_at_observed_min':2*scale/wr['min'],
                'warning':'Capacity estimates from isolated observed slot residence; multiowner contention can lengthen residence. Not achieved throughput.'}
        case['occupancy_fraction']={name:occupancy[name]/case['cycles'] for name in ['lineArea','homeArea','bridgeArea','bridgeRArea','bridgeWArea','axiRArea','axiWArea']}
    (out/'events.json').write_text(json.dumps(events, separators=(',',':'))+'\n')
    return list(cases.values())

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--yield-cycles',type=int,choices=[0,4,16],default=0);ap.add_argument('--entries',type=int,choices=[1,2,4],default=2);ap.add_argument('--tag',required=True);ap.add_argument('--reuse',action='store_true');ap.add_argument('--rebuild-driver',action='store_true');ap.add_argument('--smoke',action='store_true')
    args=ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.tag): ap.error('Unsafe tag')
    out=common.BUILD/('dma-overlap-'+args.tag);out.mkdir(parents=True,exist_ok=True)
    sources=sorted((common.ROOT/'src/main/scala').rglob('*.scala'))+[
        common.ROOT/'src/test/scala/ooo/DmaPipelineGsim.scala',Path(__file__),common.HERE/'run.py',
        common.HERE/'harness/dma_overlap.cpp',common.HERE/'harness/dma_overlap_metrics.h',common.HERE/'harness/dma_pipeline_ddr.h',common.HERE/'config/toolchain.json']
    hashes=lambda:{str(p.relative_to(common.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    inventory=hashes()
    report={'status':'RUNNING','line_entries':args.entries,'line_yield_cycles':args.yield_cycles,'clock_MHz':100,'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=common.ROOT,text=True).strip(),
        'git_base_tree':subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=common.ROOT,text=True).strip(),
        'source_sha256':inventory,'scope':'Experimental bounded tagged overlap. Isolated aligned DMA payload through real atomic, cache, mixed home, TL and AXI; alternate paths are component diagnostics only. No CPU execution, physical DDR, board, or timing claim.',
        'modes':{'0':'full real atomic/home/TL/AXI','1':'diagnostic atomic bypass, real home/TL/AXI','2':'diagnostic standalone DMA/ideal line byte oracle','3':'diagnostic DMA/real atomic/ideal line byte oracle'},
        'profiles':{'0':{'R_delay':32,'B_delay':40,'B_ID_extra':{'odd':3,'even':17},'ready_stall_moduli':[7,11,5]},
                    '1':{'R_delay':1,'B_delay':1,'B_ID_extra':0,'ready_stall_moduli':[]},
                    '2':{'R_delay':0,'B_delay':0,'B_ID_extra':0,'ready_stall_moduli':[]},'3':{'R_delay':32,'B_delay':40,'forced_even_line_extra_R':96,'forced_even_line_extra_B':128}},
        'latency_convention':'Handshake cycle differences. Occupancy integrates owners after cycle handshakes. Zero configured AXI delay still requires a subsequent host drive cycle; not combinational memory.',
        'roof_MiBps':{'one_way_64b':8*100000000/1048576,'scalar_shared_request_copy':4*100000000/1048576,'burst_copy_shared_tl_A_and_D':64/9*100000000/1048576},
        'geometry':{'line_bytes':64,'shared_bridge_slots':4,'write_bridge_slots':2,'max_burst_beats':16,'cache_lines':512,'cache_ways':2,'mshrs':2,'writebacks':2,'response_entries':2,'RAM_bytes':2147483648},
        'negative_controls':{}}
    try:
        if args.reuse or args.rebuild_driver:
            previous=json.loads((out/'binary-source.json').read_text())
            allowed=all(previous[k]==v for k,v in inventory.items() if k.startswith('src/')) if args.rebuild_driver else previous==inventory
            if not allowed: raise RuntimeError('Refusing stale generated model reuse')
            prior=json.loads((out/'receipt.json').read_text())
            if prior.get('line_entries')!=args.entries or prior.get('line_yield_cycles',0)!=args.yield_cycles:raise RuntimeError('Refusing model reuse with different line owner count')
            for p,h in prior['artifacts_sha256'].items():
                if p.endswith(('.fir','.h','.cpp')) and hashlib.sha256((out/p).read_bytes()).hexdigest()!=h: raise RuntimeError('Generated artifact hash mismatch')
            if args.rebuild_driver:
                cxx,_=common.compiler();common.run([cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-DDMA_LINE_ENABLED=1','-DDMA_LINE_ENTRIES='+str(args.entries),'-I'+str(out),*sorted(out.glob('DmaPipelineGsim[0-9]*.cpp')),common.HERE/'harness/dma_overlap.cpp','-ldl','-o',out/'run'],log=out/'compile.log')
        else:
            if (out/'run').exists():raise RuntimeError('Choose a fresh tag or request verified reuse')
            gsim,cxx=common.setup(False)
            common.test(gsim,cxx,'dma-overlap-'+args.tag,'ooo.DmaPipelineGsimMain','DmaPipelineGsim','dma_overlap.cpp',parameters=(args.yield_cycles,args.entries),defines={'DMA_LINE_ENABLED':1,'DMA_LINE_ENTRIES':args.entries},runtime_args=('--smoke',) if args.smoke else (),timeout=1200)
        (out/'binary-source.json').write_text(json.dumps(inventory,indent=2)+'\n')
        env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'}
        if args.reuse or args.rebuild_driver:common.run([out/'run',*(['--smoke'] if args.smoke else [])],log=out/'test.log',timeout=1200,env=env)
        if 'DMA_PIPELINE_PASS' not in (out/'test.log').read_text():raise RuntimeError('Missing pass marker')
        report['cases']=parse(out)
        common.run([out/'run','--protocol-only'],log=out/'protocol.log',timeout=600,env=env)
        if 'DMA_PIPELINE_PROTOCOL_PASS' not in (out/'protocol.log').read_text():raise RuntimeError('Missing protocol pass marker')
        for mutation,anchor in [('drop-write','DMA independent destination byte oracle mismatch'),('corrupt-write','DMA independent destination byte oracle mismatch'),('early-ack','DMA completion retained independently tagged owner')]:
            p=subprocess.run([out/'run','--mutate='+mutation],capture_output=True,text=True,timeout=180,env=env)
            (out/('negative-'+mutation+'.log')).write_text(p.stdout+p.stderr)
            if p.returncode==0 or anchor not in p.stdout+p.stderr:raise RuntimeError('Mutation not rejected: '+mutation)
            report['negative_controls'][mutation]={'status':'PASS','rejected':anchor}
        common.run([out/'run','--combined-only'],log=out/'combined.log',timeout=1200,env=env)
        if 'DMA_OVERLAP_COMBINED_PASS' not in (out/'combined.log').read_text():raise RuntimeError('Missing combined-work pass marker')
        report['combined']=[];report['cpu_only']=[]
        for line in (out/'combined.log').read_text().splitlines():
            if line.startswith(('DMA_CPU_COMBINED ', 'CPU_PORT_ONLY ')):
                kind,rest=line.split(' ',1)
                row={k:float(v) if '.' in v else int(v) for k,v in (field.split('=',1) for field in rest.split())}
                report['combined' if kind=='DMA_CPU_COMBINED' else 'cpu_only'].append(row)
        if len(report['combined'])!=12 or len(report['cpu_only'])!=3:raise RuntimeError('Incomplete combined-work comparison')
        if hashes()!=inventory:raise RuntimeError('Source drift during measurement')
        report['status']='PASS'
    except BaseException as e:
        report['status']='FAIL';report['error']=str(e);raise
    finally:
        report['artifacts_sha256']={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file() and p.name!='receipt.json'}
        (out/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'cases':len(report['cases']),'receipt':str(out/'receipt.json')}))
if __name__=='__main__':main()
