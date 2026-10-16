#!/usr/bin/env python3
"""Focused independent CPU/C-byte oracle and fixed-service store/victim overlap trace.
Synthetic manager; no executing CPU, board bandwidth or physical RAM timing claim.
"""
import argparse
import json
import hashlib
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'simulator/gsim/cache_write_data'))
from cache_write_data_fixture import WriteDataCache
from contract_oracle import require, Contract

BASE=0x80200000
VICTIM=BASE+256
SECOND=VICTIM+16384
THIRD=VICTIM+32768
TARGET=BASE+512

class TraceCache(WriteDataCache):
    def __init__(self, *a, **kw):
        self.offered = []
        self.accepted = []
        self.previous_capture = False
        super().__init__(*a, **kw)
        epoch=self.model.context_epoch
        memory={a:(a*29+11)&255 for a in range(BASE,BASE+65536)}
        self.model=Contract(memory,generation_bits=64,cache_sets=256,wb_entries=2)
        self.model.context_epoch=epoch
        self.backing=dict(memory)
    def tick(self, **kw):
        current = self.request
        prior = self.previous_capture
        a = super().tick(**kw)
        self.previous_capture = bool(a['readSelectionWbCapture'])
        if current:
            event = dict(cycle=self.cycle, address=current['bits']['address'], write=current['bits']['write'],
                         accepted=bool(a['upstream.request.ready']), hit=bool(a['hit']),
                         victim_read=bool(a['readSelectionWbCapture'] and a['readSelectionWbDirty']),
                         queued_read=bool(a['readSelectionWbCapture'] and not a['readSelectionWbDirect']),
                         victim_capture=prior, response_mask=a['responseMask'], wb_mask=a['wbMask'],
                         line_write=bool(a['lineWrite']), probe_offer=bool(self.state['tl.b.valid']))
            self.offered.append(event)
            if event['accepted']: self.accepted.append(event)
        return a
    def report(self):
        return dict(offered=self.offered, accepted=self.accepted,
            stores_during_victim_read=sum(x['write'] and x['hit'] and x['victim_read'] for x in self.accepted),
            stores_during_victim_capture=sum(x['write'] and x['hit'] and x['victim_capture'] for x in self.accepted))

def seed(t):
    # Two distinct tags in set zero, then a disjoint resident store target.
    for a, v in [(VICTIM, 0x1122334455667788), (SECOND, 0x8877665544332211), (TARGET, 0x123456789ABCDEF0)]:
        t.send(a, write=True, value=v)
        t.idle()

def direct_capture(t, target=TARGET):
    seed(t)
    before = len(t.offered)
    start = t.cycle
    t.send(THIRD)  # dirty set-zero demand victim, normal two-credit response ownership
    require(t.last['readSelectionWbCapture'] and t.last['readSelectionWbDirty'],
            'direct dirty victim setup did not produce real SRAM read')
    t.send(target, write=True, value=0xDEADC0DE01234567)
    t.idle()
    end = t.cycle
    events = t.offered[before:]
    t.read_line(target)
    t.start_probe(target); t.finish_probe(); t.idle()
    t.flush()
    return dict(roi_start=start, roi_end=end, roi_cycles=end-start, offers=events)

def prefetch_stream(t, masked=False, stall=False):
    seed(t)
    # Read the predecessor of a third set-zero tag. No posted proof is supplied.
    # The same externally authored 24-cycle A-to-first-D service is used on both sides.
    # Warm both predecessor lines without allowing speculative requests.
    t.send(THIRD-128); t.idle()
    t.send(THIRD-64); t.idle()
    t.send(THIRD-128, write=True, value=0xFACE0001)
    t.begin(THIRD-64, write=True, value=0xFACE0002)
    t.request['bits']['prefetchNextAllowed']=1
    t.until(lambda: t.request is None, 'permitted sequential hit')
    t.tick()  # candidate allocation, one edge before queued dirty victim read
    start = t.cycle
    before = len(t.offered)
    # Full-duty fixed sequence; request N+1 is offered after N actually accepts.
    for n in range(64):
        if stall:
            t.hold_c = n < 12
            t.hold_e = n < 12
        value=0x1020304050607080 ^ (n * 0x0101010101010101)
        if masked:
            t.begin_masked(TARGET + 8*(n%8), value, (0 if n == 1 else 255 if n == 2 else (0x96 ^ (1 << (n%8))) & 255))
            t.until(lambda: t.request is None, 'masked store acceptance')
        else:
            t.send(TARGET + 8 * (n % 8), write=True, value=value)
    t.hold_c=t.hold_e=False
    last = t.cycle
    t.idle()
    end = t.cycle
    events = t.offered[before:]
    t.read_line(TARGET)
    t.start_probe(TARGET); t.finish_probe(); t.idle()
    t.flush()
    return dict(roi_start=start, roi_last_accept=last, roi_end=end, acceptance_cycles=last-start,
                roi_cycles=end-start, payload_bytes=512, offers=events)

def warm_stream(t):
    t.send(TARGET, write=True, value=123); t.idle()
    before=len(t.offered); start=t.cycle
    for n in range(64): t.send(TARGET+8*(n%8),write=True,value=n)
    last=t.cycle
    t.until(lambda: not t.responses, 'warm response drain')
    end=t.cycle
    t.read_line(TARGET); t.flush()
    return dict(roi_start=start,roi_end=end,roi_cycles=end-start,acceptance_cycles=last-start,
                offers=t.offered[before:])

def victim_exclusion(t):
    seed(t); start=t.cycle; before=len(t.offered)
    t.send(THIRD)
    t.begin(VICTIM,write=True,value=0xFF00FFAA88997766)
    a=t.tick()
    require(not a['upstream.request.ready'],'store hit crossed live victim identity')
    t.until(lambda: t.request is None,'victim store waits for writeback and safe reacquire')
    t.idle(); end=t.cycle
    t.read_line(VICTIM); t.flush()
    return dict(roi_start=start,roi_end=end,roi_cycles=end-start,offers=t.offered[before:])

def response_exclusion(t):
    seed(t); start=t.cycle; before=len(t.offered)
    t.hold_cpu=True
    t.send(THIRD)
    t.send(TARGET,write=True,value=0x123)
    t.begin(TARGET+8,write=True,value=0x456)
    for _ in range(5):
        a=t.tick()
        require(not a['upstream.request.ready'] and a['responseMask']==3,
                'full response rows admitted another store')
    t.hold_cpu=False
    t.until(lambda: t.request is None,'response-credit release')
    t.idle(); end=t.cycle
    t.read_line(TARGET); t.flush()
    return dict(roi_start=start,roi_end=end,roi_cycles=end-start,offers=t.offered[before:])

def probe_exclusion(t):
    seed(t); start=t.cycle; before=len(t.offered)
    t.send(THIRD)
    t.start_probe(TARGET)
    t.begin(TARGET,write=True,value=0xAABBCCDD99887766)
    a=t.tick()
    require(not a['upstream.request.ready'],'store crossed probe priority')
    t.until(lambda: t.request is None,'store after probe')
    t.finish_probe(); t.idle(); end=t.cycle
    t.read_line(TARGET); t.flush()
    return dict(roi_start=start,roi_end=end,roi_cycles=end-start,offers=t.offered[before:])

def main():
    p=argparse.ArgumentParser(); p.add_argument('--executable', required=True); p.add_argument('--output', type=Path, required=True); p.add_argument('--overlap', type=int, choices=[0,1], required=True)
    args=p.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    results=[]
    for name, fn in [('direct-capture', direct_capture), ('same-set-other-way', lambda t:direct_capture(t,SECOND)),
                     ('prefetch-stream', prefetch_stream), ('masked-backpressure', lambda t:prefetch_stream(t,True,True)),
                     ('warm-control', warm_stream), ('victim-exclusion', victim_exclusion),
                     ('response-exclusion', response_exclusion), ('probe-exclusion', probe_exclusion)]:
        t=TraceCache(args.executable, args.output, name)
        try:
            metrics=fn(t); trace=t.report(); result=t.close()
        except BaseException:
            t.close(False); raise
        if name in ('direct-capture','same-set-other-way'):
            require(trace['stores_during_victim_capture']==args.overlap,
                    'direct victim capture overlap positive/negative witness missing')
        if name in ('prefetch-stream','masked-backpressure'):
            require(trace['stores_during_victim_read']==args.overlap and
                    trace['stores_during_victim_capture']==args.overlap,
                    'queued victim read/capture overlap positive/negative witness missing')
            refill_blocks=[x for x in metrics['offers'] if x['line_write'] and x['write']]
            require(refill_blocks and all(not x['accepted'] for x in refill_blocks),
                    'refill write-port exclusion missing')
        if name=='warm-control':
            require(metrics['acceptance_cycles']==64 and metrics['roi_cycles']==65,
                    'ordinary hit throughput/latency changed')
        if not args.overlap:
            require(not trace['stores_during_victim_read'] and not trace['stores_during_victim_capture'],
                    'OFF unexpectedly accepted victim overlap')
        result.update(metrics=metrics, trace=trace)
        results.append(result)
    paths=[Path(__file__).resolve(), ROOT/'src/main/scala/core/ooo/NonBlockingCoherentLineCache.scala',
           ROOT/'src/test/scala/ooo/DisjointEvictionStoreGsim.scala',
           ROOT/'src/test/scala/ooo/ThreeProofRowNativeProfile.scala',
           ROOT/'simulator/gsim/posted_cache_rebuild/fixture.py',
           ROOT/'simulator/gsim/posted_merge_rebuild/contract_oracle.py',
           ROOT/'simulator/gsim/cache_write_data/cache_write_data_fixture.py',
           Path(args.executable),Path(args.executable).parent/'DisjointEvictionStoreGsim.fir']
    binding={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (args.output/'source-binding.json').write_text(json.dumps(dict(overlap=args.overlap, hashes=binding,
        base=BASE,aperture_bytes=2**31,lines=512,ways=2,sets=256,read_mshrs=2,response_rows=2,
        writeback_rows=2,return_handles=[4,5],grant_delay=24,grant_beat_gap=1),indent=2)+'\n')
    (args.output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    print('DISJOINT_EVICTION_STORE_PASS', json.dumps([{k:v for k,v in x.items() if k not in ('trace','metrics')} for x in results]))
if __name__=='__main__': main()
