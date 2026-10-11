#!/usr/bin/env python3
"""Read-only audit of before/batch/flow/scheduled actual CPU receipts.

This compares separately frozen revisions; it is not same-source replay or STA.
Every saved artifact is rehashed, hardware geometry and retired work must match.
"""
import argparse
import json
from pathlib import Path
import cpu_sv39_bandwidth as bench

def require(value,message):
    if not value:raise RuntimeError(message)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--receipt',type=Path,action='append',required=True)
    ap.add_argument('--output',type=Path,help='fresh generated comparison JSON; stdout if omitted')
    args=ap.parse_args();records={};roots={};bindings={}
    for path in args.receipt:
        path=path.resolve();receipt=json.loads(path.read_text())
        require(receipt['status']=='PASS_ACTUAL_S_MODE_CPU_SV39_BANDWIDTH','not a passed CPU receipt')
        for relative,digest in receipt['artifacts'].items():
            p=(path.parent/relative).resolve()
            require(p.is_relative_to(path.parent),'artifact escapes receipt directory')
            require(bench.sha(p)==digest,'artifact drift: '+str(p))
        require(receipt['geometry']=={'issue':2,'LSU':2,'ROB':16,'PRF':48,'DTLB':8,'ITLB':8,
            'PTE_cache':4,'I_L1_bytes':32768,'D_L1_bytes':32768,'read_MSHR':2,'writeback':2,
            'DDR_shared':4,'DDR_write':2},'geometry drift')
        for label,cases in receipt['cases'].items():
            require(label not in records,'duplicate profile')
            records[label]=cases;roots[label]=path.parent
            bindings[label]={'receipt':str(path),'sha256':bench.sha(path),'toolchain':receipt['toolchain']}
    require(set(records)=={'baseline','batch','flow','scheduled','accepted'},'five profile records required')
    config={label:json.loads((root/label/'profile.json').read_text()) for label,root in roots.items()}
    reference=config['baseline']
    for label,c in config.items():
        require(c['core']==reference['core'],'full core parameters changed')
        require(c['derived']==reference['derived'],'derived dimensions changed')
        require(c['storage']==reference['storage'] and c['tags']==reference['tags'],'storage geometry changed')
        require(bindings[label]['toolchain']==bindings['baseline']['toolchain'],'toolchain drift')
        require(bench.sha(roots[label]/'guest/guest.bin')==bench.sha(roots['baseline']/'guest/guest.bin'),
                'guest executable differs')
        require(set(records[label])==set(records['baseline']),'case set drift')
        for key,row in records[label].items():
            for field in ('retired','pc_hash','loads','stores','bytes','reps','mode','op'):
                require(row[field]==records['baseline'][key][field],'retired work differs: '+field)
    expected_delta={
        ('baseline','batch'):{'dataTlbWriteReadReuse':True,'ddrWriteCollectionFlow':True,
            'lineTransferDispatchFlow':True,'lineReadChannel':True},
        ('batch','flow'):{'translationHitFlow':True,'prefetchCandidateCycles':16},
        ('flow','scheduled'):{'distinctWayRelease':True},
        ('batch','accepted'):{'translationHitFlow':True}}
    for (left,right),expected in expected_delta.items():
        a={'translationHitFlow':False,**config[left]['profile']};b=config[right]['profile']
        delta={key:value for key,value in b.items() if a.get(key)!=value}
        require(delta==expected,'unexpected policy changes: '+str(delta))
        for section,allowed in [('cache',{'prefetchCandidateCycles','distinctWayRelease'}),
                                ('ddr',{'writeCollectionFlow','lineReadChannel'})]:
            x=config[left][section];y=config[right][section]
            require({k for k in x if x[k]!=y[k]}<=allowed,'hidden '+section+' change')
    rows=[]
    for size in (4096,65536):
        for op in range(3):
            for mode in range(2):
                key=f'{size}-{op}-{mode}';base=records['baseline'][key];final=records['accepted'][key]
                rows.append({'bytes':size,'op':op,'mode':mode,
                    'MiBps':{label:records[label][key]['payload_MiBps'] for label in records},
                    'cycles':{label:records[label][key]['cycles'] for label in records},
                    'vs_baseline_percent':100*(base['cycles']/final['cycles']-1),
                    'vs_batch_percent':100*(records['batch'][key]['cycles']/final['cycles']-1),
                    'final_counters':{k:v for k,v in final.items() if k.startswith('event') or k in
                        ('hit_pass','pf_candidates','pf_allocated','pf_useful','cache_owner_peak',
                         'two_cache_owner_cycles','axi_read_peak','ar','aw','r_beats','w_beats')}})
    document=json.dumps({'status':'PASS_FROZEN_CPU_SV39_COMPARISON','scope':__doc__,
        'bindings':bindings,'policy_deltas':{f'{a}->{b}':v for (a,b),v in expected_delta.items()},
        'rows':rows},indent=2)+'\n'
    if args.output:
        with args.output.open('x') as stream:stream.write(document)
        print('PASS_FROZEN_CPU_SV39_COMPARISON '+str(args.output))
    else:print(document,end='')

if __name__=='__main__':main()
