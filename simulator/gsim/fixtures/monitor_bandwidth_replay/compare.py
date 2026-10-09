#!/usr/bin/env python3
"""Compare only completed, source-matched GCC14.2 whole-diagnostic replay receipts."""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare import require, sha

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('off',type=Path);p.add_argument('on',type=Path);p.add_argument('--out',required=True,type=Path)
    a=p.parse_args();states=[]
    for flag,path in enumerate((a.off,a.on)):
        x=json.loads(path.read_text())
        require(x['status']=='PASS_WHOLE_MONITOR_BANDWIDTH_REPLAY_GCC142' and x['physical_ingress_flow']==flag,'replay did not fully pass')
        for name,digest in x['products'].items():require(sha(path.parent/name)==digest,'replay product changed')
        for step in x['steps']:require(sha(path.parent/step['log'])==step['log_sha256'],'replay log changed')
        states.append(x)
    off,on=states
    for name in ('model_source_inputs','host_compiler','guest_manifest_sha256','fixture_inputs','shared_dma_profile','source_freeze'):
        require(off[name]==on[name],'comparison input differs: '+name)
    require(on['model_plan']['parameters']==off['model_plan']['parameters']+['--physical-load-ingress-flow'],'unexpected model configuration difference')
    rows=[]
    for name,old in off['result']['intervals'].items():
        new=on['result']['intervals'][name]
        rows.append(dict(name=name,off_actual_ticks=old['actual_ticks'],on_actual_ticks=new['actual_ticks'],
            rate_change_percent=(old['actual_ticks']/new['actual_ticks']-1)*100,
            off=off['result']['pipeline'][name],on=on['result']['pipeline'][name],
            off_ipc=off['result']['ipc'][name],on_ipc=on['result']['ipc'][name]))
    result=dict(status='PASS_SOURCE_MATCHED_ARCHIVED_GCC142_COMPARISON',off_receipt_sha256=sha(a.off),on_receipt_sha256=sha(a.on),
        intervals=rows,limits=off['limits'],board_comparison='Board GCC13.2 hot +1.5% is context only; this replays archived GCC14.2 on a fixed DDR host model.')
    require(not a.out.exists(),'comparison output exists')
    a.out.write_text(json.dumps(result,indent=2)+'\n')
    for row in rows:print(f"{row['name']}: {row['off_actual_ticks']} -> {row['on_actual_ticks']} actual ticks; rate {row['rate_change_percent']:+.3f}%")
    print(result['status'],a.out)

if __name__=='__main__':main()
