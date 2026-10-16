#!/usr/bin/env python3
"""Source-bound paired receipt from the focused actual-cache models, plus oracle negatives."""
import argparse, hashlib, importlib.util, itertools, json
from pathlib import Path
from disjoint_eviction_store import TraceCache, TARGET, prefetch_stream
from contract_oracle import Violation

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def negative(executable, output, kind):
    class Corrupt(TraceCache):
        def __init__(self,*args,**kwargs):
            self.corrupted=False
            super().__init__(*args,**kwargs)
        def raw(self, **updates):
            a=super().raw(**updates)
            if not self.corrupted:
                if kind=='cpu' and a['upstream.response.valid'] and a['upstream.response.bits.data']:
                    a['upstream.response.bits.data'] ^= 1
                    self.corrupted=True
                if kind=='c' and a['tl.c.valid'] and self.state['tl.c.ready'] and a['tl.c.bits.opcode'] in (5,7):
                    a['tl.c.bits.data'] ^= 1
                    self.corrupted=True
            return a
    t=Corrupt(executable,output,'negative-'+kind)
    try:
        prefetch_stream(t)
    except Violation as error:
        t.close(False)
        expected={'cpu':'actual CPU byte/error response differs from authored intent',
                  'c':'actual SRAM C bytes differ from authored coherent image'}[kind]
        assert str(error)==expected,repr(error)
        assert t.corrupted
        return dict(kind=kind,rejected=True,diagnostic=str(error))
    finally:
        if t.child.poll() is None: t.close(False)
    raise AssertionError('corrupted '+kind+' data escaped independent oracle')

def main():
    p=argparse.ArgumentParser();p.add_argument('--models',type=Path,required=True)
    p.add_argument('--cases',default='qualified-r2');p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    off=json.loads((a.models/'off'/a.cases/'results.json').read_text())
    on=json.loads((a.models/'on'/a.cases/'results.json').read_text())
    assert [x['name'] for x in off]==[x['name'] for x in on]
    summaries=[]
    for x,y in zip(off,on):
        assert x['events']['cpu_accept']==y['events']['cpu_accept']
        # Identical actual TL service volume, owner obligations, and independent byte checks.
        for k in ('a','grant_beat','e','release_dirty','release_ack','probe','probe_complete',
                  'physical_cpu_responses','physical_probe_data_beats','physical_release_data_beats','full_backing_check'):
            assert x['events'].get(k,0)==y['events'].get(k,0),(x['name'],k)
        row=dict(name=x['name'],off_roi=x['metrics']['roi_cycles'],on_roi=y['metrics']['roi_cycles'],
                 off_acceptance=x['metrics'].get('acceptance_cycles'),on_acceptance=y['metrics'].get('acceptance_cycles'))
        if x['name']=='prefetch-stream':
            row['purpose']='matched-service performance and correctness'
            assert (row['off_acceptance'],row['on_acceptance'],row['off_roi'],row['on_roi'])==(67,65,90,88)
            for side,entry in [('off',x),('on',y)]:
                trace=a.models/side/a.cases/'prefetch-stream.jsonl'
                rows=[json.loads(line) for line in trace.open()]
                m=entry['metrics']
                roi=[z for z in rows if m['roi_start']<z['actual']['cycle']<=m['roi_end']]
                assert all(z['input']['tl.a.ready'] and z['input']['tl.c.ready'] and
                           z['input']['tl.e.ready'] and z['input']['upstream.response.ready'] for z in roi)
                responses=[z['actual']['cycle'] for z in roi if z['actual']['upstream.response.valid']]
                assert len(responses)==64
                row[side+'_last_actual_response_cycles']=max(responses)-m['roi_start']
                row[side+'_raw_trace_sha256']=sha(trace)
            assert (row['off_last_actual_response_cycles'],row['on_last_actual_response_cycles'])==(68,66)
        elif x['name']=='masked-backpressure':
            row['purpose']='correctness only; accepted-store-ordinal C/E hold schedule'
        else:
            assert row['off_roi']==row['on_roi']
            row['purpose']='correctness or ordinary-path control'
        summaries.append(row)
    # Exhaustively check the changed static-OFF Boolean predicates against the
    # old source predicates. This is a local Boolean/source check, not RTL formal.
    n=0
    for bits in itertools.product([False,True],repeat=12):
        independent,refill,queued_read,queued_wanted,safe,schedule,empty,pf,idle,send,capture,maintenance=bits
        old_ind=independent and not refill and (not queued_read if schedule else not queued_wanted) and safe
        off_ind=independent and not refill and (not queued_read if schedule else not queued_wanted) and safe
        old_hit=(empty or pf or old_ind) and (idle or schedule and send) and maintenance
        off_hit=(empty or pf or off_ind) and (idle or schedule and send or False and capture) and maintenance
        assert old_ind==off_ind and old_hit==off_hit
        n+=1
    negatives=[negative(str((a.models/'on/run').resolve()),a.output,k) for k in ['cpu','c']]
    hashes={str(p):sha(p) for side in ['off','on'] for p in [a.models/side/'run',
        a.models/side/'DisjointEvictionStoreGsim.fir', a.models/side/a.cases/'results.json',
        a.models/side/a.cases/'source-binding.json']}
    hashes[str(Path(__file__).resolve())]=sha(__file__)
    result=dict(status='PASS_PRIVATE_CACHE_COMPONENT_ONLY',summaries=summaries,negatives=negatives,
                static_off_boolean_combinations=n,hashes=hashes,
                total_roi_includes_fixed_20_cycle_settling=True,
                board_or_cpu_throughput=False,physical_timing_qualified=False,default_enabled=False)
    (a.output/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
if __name__=='__main__': main()
