#!/usr/bin/env python3
"""Offline observer controls on immutable actual RTL traces; no hardware stimulus mutation."""
import argparse
from collections import Counter, deque
import copy
import hashlib
import json
from pathlib import Path
import subprocess

from fixture import Home, Contract, Token, Intent, require
from memory import Memory
from ports import INPUTS, REQUEST

sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


class TraceMemory(Memory):
    """Check recorded AXI input offers against independent byte/ID ownership."""
    def __init__(self, image, replay):
        super().__init__(image)
        self.replay = replay

    def inputs(self, cycle):
        s = self.replay.record['input']
        if s['ddrAxi.r.valid']:
            offered = {k:s['ddrAxi.r.bits.'+k] for k in ['id','data','resp','last']}
            require(offered['id'] in self.reads, 'recorded AXI R lacks accepted AR')
            q = self.reads[offered['id']]
            expected = int.from_bytes(q['bytes'][q['beat']*8:(q['beat']+1)*8],'little')
            require(offered['data']==expected and offered['resp']==0 and
                    offered['last']==int(q['beat']==q['beats']-1),'recorded AXI R differs from independent memory')
            if self.r is not None:require(offered==self.r,'recorded held AXI R changed')
            self.r=offered
        else:require(self.r is None,'recorded held AXI R withdrawn')
        if s['ddrAxi.b.valid']:
            require(self.acks and s['ddrAxi.b.bits.id']==self.acks[0]['id'] and s['ddrAxi.b.bits.resp']==0,
                    'recorded B lacks exact accepted AW/W owner')
        return {k:v for k,v in s.items() if k.startswith('ddrAxi.')}


class Replay(Home):
    def __init__(self, records, enabled=True, generation_bits=64):
        # Same independent observer, with no subprocess and no simulated DUT.
        image={a:(a*29+11)&255 for a in range(4096,8192)}
        self.enabled=enabled;self.wb_entries=2
        self.model=Contract(image,generation_bits=generation_bits,wb_entries=2)
        self.memory=TraceMemory(image,self);self.backing=self.memory.bytes
        self.dirty=set();self.state=dict.fromkeys(INPUTS,0)
        self.request=None;self.responses=deque();self.bypass=deque();self.acquires={};self.release_acks=deque()
        self.d_offer=None;self.grant_source=None;self.probe=None;self.c_burst=None;self.held={}
        self.count=Counter();self.events=[];self.tag=0;self.grant_delay=24;self.delay_by_line={}
        self.hold_a=self.hold_c=self.hold_e=self.hold_cpu=self.hold_ack=self.hold_dma=False
        self.fallback_active=False;self.dma_request=None;self.dma_responses=deque()
        require(len(records)>=3 and records[0]['input']['reset'] and records[1]['input']['reset'], 'trace reset prefix')
        self.cycle=3;self.last=records[2]['actual'];self.state=dict(records[2]['input'])
        self.records=records;self.record=None

    def raw(self,**updates):
        self.state=dict(self.record['input']);a=copy.deepcopy(self.record['actual']);self.cycle+=1
        require(a['cycle']==self.cycle,'offline cycle sequence changed')
        self.last=a
        return a

    def replay(self):
        for record in self.records[3:]:
            self.record=record;s=record['input'];require(not s['reset'],'unexpected reset in trace')
            for attr,port in [('hold_a','holdAcquire'),('hold_c','holdCoherentC'),('hold_e','holdGrantAck'),
                              ('hold_ack','holdReleaseAck')]:setattr(self,attr,bool(s[port]))
            self.hold_cpu=not s['upstream.response.ready'];self.hold_dma=not s['dma.response.ready']
            if s['upstream.request.valid']:
                bits={k:s['upstream.request.bits.'+k] for k in REQUEST}
                token=Token(s['posted.requestProof.bits.token.tag'],s['posted.requestProof.bits.token.index'])
                intent=Intent(token,bits['address'],bits['data']>>(8*(bits['address']&7)),bits['size'],
                              s['posted.requestProof.bits.epoch'])
                q=dict(bits=bits,intent=intent,proof=bool(s['posted.requestProof.valid']),error=False)
                if self.request is not None:require(q==self.request,'recorded upstream held intent changed')
                self.request=q
            else:require(self.request is None,'recorded upstream held intent withdrawn')
            if s['dma.request.valid']:
                q={k:s['dma.request.bits.'+k] for k in REQUEST}
                if self.dma_request is not None:require(q==self.dma_request,'recorded DMA held intent changed')
                self.dma_request=q
            else:require(self.dma_request is None,'recorded DMA held intent withdrawn')
            self.tick(**{'posted.contextEpoch':s['posted.contextEpoch'], 'posted.seal':s['posted.seal'],
                         'posted.endEpisode':s['posted.endEpisode'], 'flushRequest':s['flushRequest']})
        require(not self.model.busy() and not self.acquires and not self.release_acks and not self.memory.busy(),
                'positive trace ended with accepted obligations')
        require(self.memory.bytes==self.model.memory,'positive trace complete backing differs')
        return dict(events=dict(self.count),axi_events=dict(self.memory.count),cycles=self.cycle)


def main():
    p=argparse.ArgumentParser();p.add_argument('--attempt',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();require(not args.output.exists(),'fresh offline control directory required');args.output.mkdir()
    receipt_path=args.attempt/'receipt.json';receipt=json.loads(receipt_path.read_text())
    require(receipt['status']=='PASS_REAL_CACHE_HOME_DMA_AXI_COMPONENT','source trace gate was not PASS')
    for model in receipt['models'].values():
        for path,digest in model['artifacts'].items():require(sha(args.attempt/path)==digest,'source model/trace artifact drift')
    root=Path(__file__).resolve().parents[3]
    # Hardware files, compiled wrapper and build input remain exactly the tested bytes.
    for name,digest in receipt['inputs'].items():
        if name.startswith('src/') or name in ['build.mill','.mill-version']:
            require(sha(root/name)==digest,'hardware input differs from recorded model: '+name)
    before={p:sha(p) for p in args.attempt.rglob('*') if p.is_file()}
    report=dict(status='RUNNING',scope='offline mutation of observation records only; original RTL inputs, model and traces unchanged',
                model_receipt_sha256=sha(receipt_path),source_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
                observer_sha256={name:sha(Path(__file__).parent/name) for name in ['replay_controls.py','fixture.py','memory.py','ports.py']},
                positives=[],mutants=[])
    records_by_name={}
    for model_name,metadata in receipt['models'].items():
        cases=args.attempt/model_name/'cases';result=json.loads((cases/'result.json').read_text())
        for case in result['cases']:
            require(case['status']=='PASS','this offline gate expects positive traces only')
            path=cases/(case['name']+'.jsonl');records=[json.loads(x) for x in path.read_text().splitlines()]
            observed=Replay(records,enabled=metadata['enabled'],generation_bits=metadata['generation_bits']).replay()
            schedule_only={'full_backing_check','dma_before_a','dma_with_held_posted_ack','real_c_last_acquire_overlap'}
            require(set(case['events'])-set(observed['events']) <= schedule_only, 'unreplayed protocol event counter')
            expected_events={k:v for k,v in case['events'].items() if k in observed['events']}
            require(all(observed['events'][k]==v for k,v in expected_events.items()),'positive observer event census drift')
            require(observed['axi_events']==case['axi_events'] and observed['cycles']==case['cycles'],'positive AXI/cycle census drift')
            report['positives'].append(dict(name=model_name+'/'+case['name'],trace_sha256=sha(path),**observed))
            records_by_name[case['name']]=records
    records=records_by_name['real-dirty-victim-overlap']
    first=lambda predicate:next(i for i,r in enumerate(records) if predicate(r['actual']))
    c_index=first(lambda a:a['monCValid'] and a['monCReady'] and a['monCOpcode']==7)
    a_index=first(lambda a:a['acquired.valid'])
    wb_index=first(lambda a:a['completed.valid'])
    specs=[('wrong-dirty-byte',c_index,'monCData',records[c_index]['actual']['monCData']^1,
            'actual SRAM C bytes differ from authored coherent image'),
           ('wrong-full-generation',a_index,'acquired.bits.context.owner.generation',
            records[a_index]['actual']['acquired.bits.context.owner.generation']^1,'unknown or released full owner'),
           ('wrong-owner-slot',a_index,'acquired.bits.context.owner.slot',
            records[a_index]['actual']['acquired.bits.context.owner.slot']^1,'unknown or released full owner'),
           ('missing-WB-completion-association',wb_index,'completed.valid',0,'resource release preceded token/WB drain'),
           ('early-WB-completion-association',wb_index-1,'completed.valid',1,'WB completion was not real exact ReleaseAck')]
    for name,index,field,value,diagnostic in specs:
        mutated=copy.deepcopy(records);original=mutated[index]['actual'][field];mutated[index]['actual'][field]=value
        if name.startswith('early-'):
            for k,v in records[wb_index]['actual'].items():
                if k.startswith('completed.bits.'):mutated[index]['actual'][k]=v
        require(all(x['input']==y['input'] for x,y in zip(records,mutated)),'offline mutant changed DUT stimulus')
        try:Replay(mutated).replay()
        except AssertionError as error:
            require(str(error)==diagnostic,'unrelated rejection: '+str(error))
            report['mutants'].append(dict(name=name,status='EXPECTED_OFFLINE_OBSERVER_REJECTION',cycle=index+1,
                                         field=field,original=original,poisoned=value,diagnostic=diagnostic))
        else:raise AssertionError('offline observer failed to detect '+name)
    require(before=={p:sha(p) for p in before},'offline analysis changed original artifacts')
    report['status']='PASS_OFFLINE_OBSERVER_CONTROLS'
    (args.output/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status'],len(report['positives']),'positive replays',len(report['mutants']),'exact rejected mutants')

if __name__=='__main__':main()
