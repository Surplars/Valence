#!/usr/bin/env python3
"""One real-cache synthetic-manager B-versus-attachment contract; no real home."""
import argparse,json,sys
from collections import Counter
from pathlib import Path
import ports
sys.path.insert(1,str(Path(__file__).resolve().parent.parent/'posted_prefetch_coexist'))
from cache_base import Cache, require

class ProbeGate(Cache):
    def __init__(self,*args,**kwargs):
        self.owner={};self.active={};self.generation=Counter();self.sources={};self.evidence=Counter()
        self.held_request=None;self.held_b=None;self.held_d=None
        super().__init__(*args,**kwargs)
    def begin(self,*args,prefetch=False,**kwargs):
        token=super().begin(*args,**kwargs)
        self.request['bits']['prefetchNextAllowed']=int(prefetch)
        return token
    def tick(self,**updates):
        request=None if self.request is None else dict(self.request['bits'])
        old_accept=self.count['cpu_accept'];a=super().tick(**updates);s=self.state
        o=lambda n:a['pfObservation.'+n]
        fire=self.count['cpu_accept']!=old_accept
        if self.held_request is not None:require(request==self.held_request,'held CPU offer changed or was cancelled')
        self.held_request=request if request and not fire else None
        for name,valid,ready,fields in [('b',s['tl.b.valid'],a['tl.b.ready'],ports.AB),
                                      ('d',s['tl.d.valid'],a['tl.d.ready'],ports.D)]:
            payload=tuple(s['tl.'+name+'.bits.'+f] for f in fields)
            old=getattr(self,'held_'+name)
            if old is not None:require(valid and payload==old,'held manager '+name+' payload changed')
            setattr(self,'held_'+name,payload if valid and not ready else None)
        for slot,key in list(self.active.items()):
            if not (o('mshrLiveMask')&(1<<slot)):
                require(self.owner[key]['filled'],'original MSHR retired without exact refill');del self.active[slot]
        require(o('mshrLiveMask')==sum(1<<slot for slot in self.active),'MSHR live mask lost independent generation')
        for pf,event in [(False,'demandAlloc'),(True,'allocated')]:
            if o(event):
                slot=o('allocatedSlot' if pf else 'demandAllocSlot');address=o('allocatedAddress' if pf else 'demandAllocAddress')&~63
                require(slot not in self.active,'MSHR allocation reused live owner')
                if not pf:require(fire and request['address']&~63==address,'demand allocation lost accepted full address')
                else:require(not o('allocatedStore'),'probe contract unexpectedly used store PF')
                self.generation[slot]+=1;key=(slot,self.generation[slot]);self.active[slot]=key
                self.owner[key]={'address':address,'pf':pf,'a':None,'beats':0,'e':None,'filled':False,'attached':False,
                                 'bytes':self.model.line(address),'tag':None,'error':False}
                self.evidence['pf_alloc' if pf else 'demand_alloc']+=1
        if a['tl.a.valid'] and s['tl.a.ready']:
            source=a['tl.a.bits.source'];address=a['tl.a.bits.address']
            matches=[key for key in self.active.values() if self.owner[key]['address']==address and self.owner[key]['a'] is None]
            require(len(matches)==1 and source not in self.sources,'A lacks unique exact captured generation')
            key=matches[0];self.sources[source]=key;self.owner[key]['a']=self.cycle
        if o('acquireIssued'):
            key=self.active[o('acquireIssuedSlot')];owner=self.owner[key]
            tag=(o('acquireIssuedTagLo'),o('acquireIssuedTagHi'))
            require(o('acquireTagBits')==68 and tag==(key[0],4 if owner['pf'] else 0),'issued immutable transaction tag changed')
            owner['tag']=tag
        if o('demandAttach'):
            require(fire and request and not request['write'] and not request['atomic'] and not request['uncached'],
                    'attachment lacks accepted ordinary demand')
            key=self.active[o('demandAttachSlot')];owner=self.owner[key]
            require(owner['pf'] and owner['a']<self.cycle and not owner['attached'] and not owner['filled'] and
                    request['address']==o('demandAttachAddress') and request['address']&~63==owner['address'],
                    'attachment lost original issued PF identity')
            owner['attached']=True;self.evidence['attach']+=1
        if s['tl.d.valid'] and a['tl.d.ready'] and s['tl.d.bits.opcode']==5:
            owner=self.owner[self.sources[s['tl.d.bits.source']]];beat=owner['beats']
            require(beat<8 and s['tl.d.bits.data']==int.from_bytes(owner['bytes'][beat*8:(beat+1)*8],'little'),
                    'exact D owner bytes changed')
            owner['error']|=bool(s['tl.d.bits.denied'] or s['tl.d.bits.corrupt']);owner['beats']+=1
        if a['tl.e.valid'] and s['tl.e.ready']:
            source=a['tl.e.bits.sink'];require(source in self.sources,'E lacks exact source/sink owner')
            owner=self.owner[self.sources.pop(source)];require(owner['beats']==8 and owner['e'] is None,'E before all D beats')
            owner['e']=self.cycle
        if o('refill'):
            owner=self.owner[self.active[o('refillSlot')]]
            require(owner['e'] is not None and owner['e']<self.cycle and not owner['filled'] and
                    owner['address']==o('refillAddress')&~63 and owner['pf']==bool(o('refillPrefetch')) and
                    owner['attached']==bool(o('refillDemandAttached')) and owner['error']==bool(o('refillError')) and
                    owner['tag']==(o('refillTagLo'),o('refillTagHi')),'refill changed original owner/full address/tag/error')
            owner['filled']=True;self.evidence['pf_refill' if owner['pf'] else 'demand_refill']+=1
        if request and s['tl.b.valid']:
            self.evidence['b_cpu_offer_overlap']+=1
            if not a['tl.b.ready']:self.evidence['b_held_cpu_offer']+=1
            require(not fire and not o('demandAttach'),'B conflict failed to exclude actual CPU attachment')
        if request and a['tl.e.valid'] and not s['tl.e.ready']:self.evidence['held_e_cpu_offer']+=1
        if a['upstream.response.valid'] and not s['upstream.response.ready']:self.evidence['held_cpu_response']+=1
        return a

def scenario(t,no_b=False):
    for address in (4160,4224):t.send(address);t.idle()
    t.send(4160,prefetch=True);t.idle()
    target=4288;t.delay_by_line[target]=64;t.hold_e=True;t.hold_cpu=False
    t.send(4224,prefetch=True)
    t.until(lambda:any(x['address']==target for x in t.acquires.values()),'real issued read PF A')
    pf=[key for key,o in t.owner.items() if o['pf'] and o['address']==target]
    require(len(pf)==1,'one original read PF generation required');pf=pf[0]
    before_accept=t.count['cpu_accept'];before_reply=t.count['cpu_response'];before_a=t.count['a']
    if not no_b:t.start_probe(target)
    token=t.begin(target+24);original=dict(t.request['bits'])
    for _ in range(6):t.tick()
    if no_b:
        require(t.evidence['attach']==1 and t.count['cpu_accept']==before_accept+1,'removing B did not change actual attachment')
        print('ADOPTION_PROBE_NEGATIVE changed_external_b=1 actual_attach=1 actual_accept_delta=1',flush=True)
        raise AssertionError('removed B produced actual attachment, as required by negative control')
    require(t.request and t.request['intent'].token==token and t.request['bits']==original and
            not t.evidence['attach'] and t.count['cpu_accept']==before_accept,'B-held original demand changed/accepted')
    t.until(lambda:t.last['tl.e.valid'],'original PF all D beats to held E')
    for _ in range(5):t.tick()
    require(t.request and t.probe and not t.probe['accepted'] and t.count['cpu_response']==before_reply and
            t.evidence['b_held_cpu_offer']>=6 and t.evidence['held_e_cpu_offer']>=5,'pending B/D/E exclusion absent')
    # The real independent-admission cache may accept a fresh demand as soon
    # as B.fire invalidates the line, while its ProbeAck remains held. Preserve
    # that legal acceptance; the manager holds new A until its old B/C ends.
    t.hold_c=True;t.hold_a=True;t.hold_cpu=True;t.hold_e=False
    t.until(lambda:bool(t.probe['accepted']),'B handshake after PF install')
    for _ in range(5):t.tick()
    require(t.request is None and not t.probe['done'] and not t.evidence['attach'] and
            t.count['cpu_accept']==before_accept+1 and t.count['a']==before_a,
            'post-B independent demand or held fresh A ownership changed')
    t.hold_c=False;t.finish_probe();t.hold_a=False
    t.until(lambda:t.request is None,'same held demand accepts after real B handshake')
    require(t.count['cpu_accept']==before_accept+1 and not t.evidence['attach'],'eventual demand owner changed')
    t.until(lambda:t.last['upstream.response.valid'],'fresh exact demand result')
    for _ in range(5):t.tick()
    require(t.count['cpu_response']==before_reply,'held CPU response escaped backpressure')
    t.hold_cpu=False;t.idle()
    require(t.count['a']==before_a+1 and t.count['cpu_response']==before_reply+1 and t.owner[pf]['filled'] and
            not t.owner[pf]['attached'] and not t.owner[pf]['error'] and t.probe['done'] and not t.sources and
            all(o['filled'] and o['e'] is not None for o in t.owner.values()),'original PF / independent retry owner conservation failed')
    t.flush();t.idle()
    require(t.count['cpu_accept']==t.count['cpu_response'] and not t.active,'final exact owner/response drain failed')

def main():
    p=argparse.ArgumentParser();p.add_argument('--executable',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--negative-no-b',action='store_true');a=p.parse_args();a.output.mkdir()
    t=ProbeGate(a.executable,a.output,'no_b' if a.negative_no_b else 'b_conflict',True,64,2)
    try:
        scenario(t,a.negative_no_b);result=t.close();result['adoption_probe_events']=dict(t.evidence)
        result['scope']='real cache/raw TL synthetic manager only; real Mixed-home B conflict is UNREACHED'
        (a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('ADOPTION_PROBE_PASS cases=1',flush=True)
    except BaseException:
        result=t.close(False);result['adoption_probe_events']=dict(t.evidence)
        (a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');raise
if __name__=='__main__':main()
