#!/usr/bin/env python3
"""Actual private cache, Mixed home and DMA/AXI transport; independent bytes/owners."""
import argparse
from collections import deque, Counter
import importlib.util
import json
from pathlib import Path
import sys
from ports import INPUTS, OUTPUTS, REQUEST, PROOF, AB, C, D, CHANNELS, monitor
from memory import Memory
_spec = importlib.util.spec_from_file_location('private_cache_contract_adapter', Path(__file__).resolve().parent.parent / 'posted_cache_rebuild/fixture.py')
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)
Contract, Context, Owner, Reservation, Token, Intent, require = (_base.Contract, _base.Context, _base.Owner, _base.Reservation, _base.Token, _base.Intent, _base.require)
word, line_bytes, observed_context, observed_reservation, observed_token, observed_event = (_base.word, _base.line_bytes, _base.observed_context, _base.observed_reservation, _base.observed_token, _base.observed_event)

class Home(_base.Cache):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.memory = Memory(self.backing)
        self.backing = self.memory.bytes
        self.dma_request = None
        self.dma_responses = deque()
        self.hold_dma = False

    def tick(self, **updates):
        values = {'reset': 0, 'posted.seal': 0, 'posted.endEpisode': 0,
                  'posted.contextEpoch': self.model.context_epoch,
                  'holdAcquire': self.hold_a, 'holdCoherentC': self.hold_c,
                  'holdGrantAck': self.hold_e, 'holdReleaseAck': self.hold_ack,
                  'upstream.response.ready': not self.hold_cpu,
                  'upstream.request.valid': self.request is not None,
                  'posted.requestProof.valid': bool(self.request and self.request['proof']),
                  'dma.request.valid': self.dma_request is not None, 'dma.response.ready': not self.hold_dma}
        if self.request:
            q = self.request; intent = q['intent']
            values.update({'upstream.request.bits.' + k: v for k, v in q['bits'].items()})
            proof = dict.fromkeys(PROOF, 0)
            proof.update({'token.tag': intent.token.tag, 'token.index': intent.token.index, 'epoch': intent.epoch,
                          'address': intent.address, 'data': q['bits']['data'], 'mask': q['bits']['mask'], 'size': intent.size})
            if q['proof']:
                proof.update({k: 1 for k in ['headAuthorized', 'physicalPmpAllowed', 'originalPhysical', 'integerOrigin', 'legacyPostedAccepted', 'finalChecked']})
            values.update({'posted.requestProof.bits.' + k: v for k, v in proof.items()})
        if self.dma_request:
            values.update({'dma.request.bits.' + k: v for k, v in self.dma_request.items()})
        values.update(self.memory.inputs(self.cycle))
        values.update(updates)
        a = self.raw(**values)
        s = dict(self.state)
        for ch, fields in CHANNELS.items():
            for field in ['valid','ready',*fields]:
                name = 'tl.' + ch + ('.bits.' if field in fields else '.') + field
                a[name] = a[monitor(ch,field)]
                s[name] = a[name]
        self.memory.sample(a,s,self.cycle)
        if self.enabled:
            if self.model.busy(): require(a['posted.busy'], 'accepted cache responsibility disappeared')
            elif self.fallback_active:
                tail = bool(self.responses or self.acquires or self.release_acks or self.c_burst or
                            (self.probe and self.probe['accepted'] and not self.probe['done']))
                if tail: require(a['posted.busy'], 'fallback lost actual accepted home/WB responsibility')
                if not a['posted.busy']:
                    require(not tail, 'fallback tail cleared early'); self.fallback_active = False
            else: require(not a['posted.busy'], 'unowned posted responsibility')
            require(a['posted.episodeActive'] == int(self.model.episode_root is not None), 'cohort lifetime mismatch')
        channel_checks = [(ch.upper(), a['tl.'+ch+'.valid'], a['tl.'+ch+'.ready'],
                           ['tl.'+ch+'.bits.'+n for n in fields]) for ch,fields in CHANNELS.items()]
        channel_checks += [(label, a[label+'.response.valid'],s[label+'.response.ready'],
                            [label+'.response.bits.'+n for n in ['data','error','pageFault']]) for label in ['upstream','dma']]
        channel_checks += [('AXI-'+ch,a['ddrAxi.'+ch+'.valid'],s['ddrAxi.'+ch+'.ready'],
                            ['ddrAxi.'+ch+'.bits.'+n for n in fields]) for ch,fields in
                           [('ar',['id','addr','len','size','burst']),('aw',['id','addr','len','size','burst']),('w',['data','strb','last'])]]
        for label,valid,ready,fields in channel_checks:
            payload = tuple(a[n] for n in fields)
            if label in self.held: require(valid and payload == self.held[label], label+' held offer changed')
            if valid and not ready: self.held[label] = payload
            else: self.held.pop(label,None)
        self.consume(a,s)
        if self.dma_request and a['dma.request.ready']:
            self.dma_responses.append(self.dma_request)
            self.dma_request = None; self.count['dma_accept'] += 1
        if a['dma.response.valid'] and s['dma.response.ready']:
            require(self.dma_responses, 'unowned real DMA response')
            q = self.dma_responses.popleft()
            expected = 0 if q['write'] else word(self.model.memory,q['address'] & ~7)
            require(a['dma.response.bits.data'] == expected and not a['dma.response.bits.error'] and
                    not a['dma.response.bits.pageFault'], 'real DMA data or error differs from independent coherent image')
            if q['write']:
                changes = {q['address']+i:(q['data']>>(8*i)) & 255 for i in range(8) if q['mask']>>i&1}
                self.model.dma_write(changes)
            self.count['dma_response'] += 1
        return a

    def consume(self,a,s):
        current = self.request
        accepted = bool(current and a['upstream.request.ready'])
        if accepted:
            q = current; intent = q['intent']; bits = q['bits']; address = bits['address']
            expected = 0 if bits['write'] or q['error'] else word(self.model.memory, address & ~7)
            self.responses.append({'data': expected, 'error': int(q['error']), 'pageFault': 0, 'token': intent.token})
            self.count['cpu_accept'] += 1
            if a['accepted.valid']:
                require(q['proof'] and bits['write'] and self.enabled, 'cache fabricated posted authority')
                context = observed_context(a, 'accepted.bits.member.context')
                reservation = observed_reservation(a, 'accepted.bits.reservation')
                require(observed_token(a, 'accepted.bits.member.token') == intent.token, 'full CPU token changed')
                ticket = a['accepted.bits.member.responseTicket']
                self.model.accept(intent, context, reservation, ticket, bool(a['accepted.bits.newLine']))
                self.model.response_complete(ticket, intent.token)
                self.count['posted_accept'] += 1
                self.count['posted_new' if a['accepted.bits.newLine'] else 'posted_join'] += 1
            elif bits['write'] and not q['error']:
                self.model.memory.update(intent.bytes())
                self.dirty.add(address & ~63)
                if address & ~63 in self.model.resident:
                    self.model.resident[address & ~63] = self.model.line(address & ~63)
                self.count['legacy_write'] += 1
            if a['hit']: self.count['cpu_hit'] += 1
            self.request = None
        else:
            require(not a['accepted.valid'], 'owner accepted without actual cache upstream fire')
        if a['fallback.valid']:
            require(accepted and current['proof'], 'fallback detached from actual acceptance')
            require(observed_token(a, 'fallback.bits.token') == current['intent'].token, 'fallback token changed')
            self.model.fallback_accept(current['intent'], a['fallback.bits.responseTicket'])
            self.fallback_active = True
            self.count['fallback'] += 1
        responded = None
        if a['upstream.response.valid'] and s['upstream.response.ready']:
            require(self.responses, 'unowned actual CPU response')
            responded = self.responses.popleft()
            for field in ['data', 'error', 'pageFault']:
                require(a['upstream.response.bits.' + field] == responded[field], 'actual CPU byte/error response differs from authored intent')
            self.count['cpu_response'] += 1
        if a['acknowledged.valid']:
            token = observed_token(a, 'acknowledged.bits.token')
            require(responded and responded['token'] == token, 'ACK was not actual upstream response.fire')
            context = observed_context(a, 'acknowledged.bits.context')
            require(self.model.tokens[token][0] == context, 'ACK full owner changed')
            self.model.ack(token, a['acknowledged.bits.responseTicket'])
            self.count['posted_ack'] += 1
        if a['fallbackAck.valid']:
            token = observed_token(a, 'fallbackAck.bits.token')
            require(responded and responded['token'] == token, 'fallback ACK not actual response.fire')
            self.model.fallback_ack(token, a['fallbackAck.bits.responseTicket'])
        if a['tl.b.ready'] and s['tl.b.valid']:
            require(self.probe is None or self.probe['done'], 'home reused a live probe')
            self.probe = dict(address=s['tl.b.bits.address'], accepted=False, done=False)
            p = self.probe
            p['accepted'] = True
            p['hit'] = p['address'] in self.model.resident
            p['dirty'] = p['hit'] and p['address'] in self.dirty
            p['bytes'] = self.model.line(p['address'])
            self.model.probe(p['address'])
            self.dirty.discard(p['address'])
            self.count['probe'] += 1
        elif s['tl.b.valid']:
            self.count['probe_stall'] += 1
        for label, method in [('attached', self.model.attach_wb), ('sent', self.model.sent_wb), ('completed', self.model.complete_wb)]:
            if a[label + '.valid']:
                context, reservation = observed_event(a, label + '.bits')
                ticket_owner = Owner(a[label + '.bits.ticket.owner.slot'], a[label + '.bits.ticket.owner.generation'])
                require(ticket_owner == context.owner, 'WB detached full owner')
                slot = a[label + '.bits.ticket.slot']
                if label == 'attached': method(context, reservation, slot)
                else:
                    if label == 'sent':
                        require(a['tl.c.valid'] and s['tl.c.ready'] and a['tl.c.bits.source'] == 2 + slot,
                                'WB sent was not real C-last')
                    else:
                        require(s['tl.d.valid'] and a['tl.d.ready'] and s['tl.d.bits.opcode'] == 6 and s['tl.d.bits.source'] == 2 + slot,
                                'WB completion was not real exact ReleaseAck')
                    method(context, reservation, (slot, ticket_owner))
                self.count['wb_' + label] += 1
        if a['cancelled.valid']:
            self.model.cancel_victim(*observed_event(a, 'cancelled.bits'))
            self.count['victim_cancel'] += 1
        if a['tl.a.valid'] and s['tl.a.ready']:
            source = a['tl.a.bits.source']; address = a['tl.a.bits.address']
            require(source in (0, 1) and source not in self.acquires, 'actual physical Acquire source reused or invented')
            require(a['tl.a.bits.opcode'] == 6 and a['tl.a.bits.param'] == 1 and a['tl.a.bits.size'] == 6,
                    'posted cache uses actual N-to-T full data acquisition')
            self.acquires[source] = {'address': address, 'sink': None, 'beat': 0, 'base': None,
                                     'due': self.cycle + self.delay_by_line.get(address, self.grant_delay),
                                     'posted': bool(a['acquired.valid'])}
            if a['acquired.valid']:
                context, reservation = observed_event(a, 'acquired.bits')
                require(context.line == address, 'actual A address differs from full owner')
                self.model.acquire(context, reservation, source)
                self.count['posted_a'] += 1
            self.count['a'] += 1
        else:
            require(not a['acquired.valid'], 'engine enqueue counted as actual A')
        if s['tl.d.valid'] and a['tl.d.ready']:
            d = {field: s['tl.d.bits.' + field] for field in D}
            if d['opcode'] == 6:
                require(self.release_acks and self.release_acks[0]['source'] == d['source'], 'unowned ReleaseAck')
                self.release_acks.popleft(); self.count['release_ack'] += 1
            else:
                g = self.acquires[d['source']]
                if g['beat'] == 0: g['sink'] = d['sink']
                require(g['sink'] == d['sink'], 'real home changed Grant sink')
                if g['posted']:
                    self.model.grant_beat(d['source'], d['data'], d['sink'], error=bool(d['denied']), to_t=d['param'] == 0)
                g['beat'] += 1
                if g['beat'] == 8: self.grant_source = None
                self.count['grant_beat'] += 1
            self.d_offer = None
        if a['tl.e.valid'] and s['tl.e.ready']:
            sink = a['tl.e.bits.sink']
            sources = [source for source, g in self.acquires.items() if g['sink'] == sink]
            require(len(sources) == 1 and self.acquires[sources[0]]['beat'] == 8, 'actual E without complete granted source')
            source = sources[0]
            if self.acquires[source]['posted']: self.model.e(source)
            del self.acquires[source]
            self.count['e'] += 1
        if a['tl.c.valid'] and s['tl.c.ready']:
            opcode, source, address = a['tl.c.bits.opcode'], a['tl.c.bits.source'], a['tl.c.bits.address']
            require(opcode in (4, 5, 6, 7) and a['tl.c.bits.size'] == 6 and not a['tl.c.bits.corrupt'], 'malformed actual C')
            if self.c_burst is None:
                expected = self.model.line(address)
                if opcode in (4, 5):
                    require(self.probe and self.probe['accepted'] and self.probe['address'] == address,
                            'ProbeAck not associated with actual B')
                    require(opcode == (5 if self.probe['dirty'] else 4), 'probe dirty-data obligation lost')
                    require(a['tl.c.bits.param'] == (1 if self.probe['hit'] else 5), 'probe hit/absent permission changed')
                    expected = self.probe['bytes']
                else:
                    require(source in range(2, 2 + self.wb_entries), 'invented Release source')
                self.c_burst = {'opcode': opcode, 'source': source, 'address': address, 'beat': 0, 'expected': expected}
            burst = self.c_burst
            require((opcode, source, address) == (burst['opcode'], burst['source'], burst['address']), 'C burst changed owner')
            data = a['tl.c.bits.data'].to_bytes(8, 'little')
            if opcode in (5, 7):
                require(data == burst['expected'][burst['beat'] * 8:(burst['beat'] + 1) * 8], 'actual SRAM C bytes differ from authored coherent image')
                # AXI W is the only operation that changes the actual backing image.
            burst['beat'] += 1
            if burst['beat'] == (8 if opcode in (5, 7) else 1):
                if opcode in (6, 7):
                    self.model.resident.pop(address, None); self.dirty.discard(address)
                    self.release_acks.append({'source': source, 'due': self.cycle + 9})
                    self.count['release_dirty' if opcode == 7 else 'release_clean'] += 1
                else:
                    self.probe['done'] = True; self.count['probe_complete'] += 1
                self.c_burst = None
        if a['refillValid']:
            data = b''.join(a['refillWord' + str(i)].to_bytes(8, 'little') for i in range(8))
            self.model.refill(*observed_event(a, 'refillEvent'), data)
            self.events.append(('refill', self.cycle, a['refillEvent.context.lineAddress']))
            self.count['posted_refill'] += 1
        if a['lineWrite']:
            address = a['lineWriteAddress']
            data = b''.join(a['installWord' + str(i)].to_bytes(8, 'little') for i in range(8))
            if a['lineWritePosted']:
                require(a['installedValid'], 'posted SRAM write without owner install.fire')
                self.model.install(*observed_event(a, 'installedEvent'), data)
                self.dirty.add(address)
                self.count['posted_install'] += 1
            else:
                require(data == self.model.line(address), 'ordinary SRAM line installation byte mismatch')
                self.model.resident[address] = data
            self.events.append(('install', self.cycle, address))
        else:
            require(not a['installedValid'], 'owner install.fire without true SRAM line write')
        if a['drained.valid']:
            self.model.drain(observed_token(a, 'drained.bits.token'), observed_context(a, 'drained.bits.context'))
            self.count['token_drain'] += 1
        if a['released.valid']:
            self.model.release(*observed_event(a, 'released.bits'))
            self.count['owner_release'] += 1
        if s['posted.endEpisode']:
            self.model.end_episode(held_ingress=bool(current and current['proof']), accepted_same_edge=bool(a['accepted.valid']))
        return a


    def idle(self):
        self.until(lambda: not self.request and not self.responses and not self.model.busy() and not self.acquires and
                   not self.release_acks and self.c_burst is None and not self.dma_request and not self.dma_responses and
                   not self.memory.busy() and (not self.enabled or not self.last['posted.busy']), 'cache/home/AXI drain',8192)
        self.tick()

    def dma_op(self,address,write=False,data=0,mask=255,wait=True):
        require(self.dma_request is None, 'held DMA request overwritten')
        self.dma_request=dict.fromkeys(REQUEST,0)
        self.dma_request.update(address=address,write=int(write),data=data,mask=mask,size=3)
        self.until(lambda: self.dma_request is None,'real DMA acceptance')
        if wait: self.until(lambda: not self.dma_responses,'real DMA response',8192)

    def flush(self):
        self.idle()
        self.state['flushRequest']=1
        self.until(lambda: self.last['flushDone'],'real cache plus home drain',8192)
        require(not self.acquires and not self.release_acks and not self.memory.busy(),'flush skipped accepted transport')
        require(self.memory.bytes == self.model.memory,'real complete AXI backing differs after cache/home flush')
        self.state['flushRequest']=0;self.tick();self.count['full_backing_check'] += 1

    def close(self,success=True):
        result=super().close(success)
        result['axi_events']=dict(self.memory.count)
        return result


def merge(t):
    t.memory.delay=160
    for offset,value,size in [(0,0x1122334455667788,3),(2,0x9999,1),(7,0xA5,0),(8,0xDEADBEEF,2),(32,0x12345678,2)]:
        t.send(4160+offset,write=True,value=value,size=size,proof=True)
        if t.enabled: t.until(lambda: not t.responses,'early response ticket reuse')
        else: t.idle()
    t.idle();t.read_line(4160);t.flush()
    if t.enabled: require(t.count['posted_accept']==5 and t.count['a']==1,'real home merge did not reuse original credits')


def before_a_dma(t):
    t.hold_a=True
    t.send(4160,write=True,value=0xBEEF,size=1,proof=True)
    t.until(lambda: not t.responses,'posted early ACK before A')
    require(t.count['a']==0,'A crossed explicit hold')
    t.dma_op(4160,True,0x8877665544332211)
    t.count['dma_before_a'] += 1
    t.hold_a=False;t.idle();t.read_line(4160);t.flush()


def held_ack_dma(t):
    t.hold_cpu=True
    t.send(4160,write=True,value=0x1234567890ABCDEF,proof=True)
    t.until(lambda: t.count['posted_install']==1,'real home grant and private SRAM install')
    require(t.count['posted_ack']==0,'early ACK was not held')
    t.dma_op(4160)
    require(t.count['probe'] and t.count['probe_complete'],'DMA did not cause real B/C')
    t.dma_op(4160,True,0xFEEDDEADBEEFF00D)
    t.hold_cpu=False;t.idle();t.read_line(4160);t.flush()
    t.count['dma_with_held_posted_ack'] += 1


def victim(t,dirty):
    t.send(4160,write=dirty,value=0x1357);t.idle()
    t.send(4672);t.idle()
    t.hold_ack=True
    t.send(5184,write=True,value=0x2468,proof=True)
    t.until(lambda: t.count['posted_install']==1,'real new line acquired after C-last while ReleaseAck held')
    require(t.release_acks and t.model.busy() and t.count['wb_sent']==1 and t.count['owner_release']==0,
            'owner did not retain exact old WB responsibility')
    t.count['real_c_last_acquire_overlap'] += 1
    t.hold_ack=False;t.idle();t.read_line(5184);t.flush()
    require(t.count['release_dirty' if dirty else 'release_clean']>=1,'required victim kind absent')


def real_fallback_tail(t, poison_context=False):
    for i in range(4):
        t.send(4160+i*64,write=True,value=100+i,proof=True)
        t.end_episode()
    t.send(4672);t.idle()
    t.hold_ack=True
    t.send(5184,write=True,value=0xABCDEF,proof=True)
    t.until(lambda:t.count['fallback']==1 and not t.responses and bool(t.release_acks),
            'real-home fallback CPU ACK before delayed real ReleaseAck')
    require(not t.model.busy() and t.last['posted.busy'] and t.count['release_dirty']==1,
            'real-home fallback lost independent WB tail after CPU ACK')
    t.count['real_fallback_wb_tail'] += 1
    if poison_context:
        t.tick(**{'posted.contextEpoch':t.model.context_epoch+1})
        raise AssertionError('fallback context crossed unacknowledged real home WB')
    t.dma_op(5184)
    require(t.count['probe']==1 and t.count['probe_complete']==1 and t.last['posted.busy'],
            'real home probe did not drain across retained fallback WB')
    t.begin(5248,write=True,value=0xDEAD,proof=True)
    for _ in range(5):t.tick()
    require(t.request is not None and t.count['fallback']==1,'new fallback crossed old WB')
    t.state['flushRequest']=1
    for _ in range(5):t.tick()
    require(not t.last['flushDone'],'flush crossed unacknowledged old WB')
    t.hold_ack=False
    t.until(lambda:t.last['flushDone'],'actual old tail and home flush with younger held proof',8192)
    require(t.request is not None,'younger proof bypassed active flush')
    require(t.memory.bytes==t.model.memory,'old episode complete backing differs at flush')
    t.state['flushRequest']=0
    t.idle();t.end_episode();t.read_line(5248);t.flush()
    require(t.count['posted_accept']==4 and t.count['fallback']==2,'exhausted generation wrapped or lost later fallback')


def main():
    p=argparse.ArgumentParser();p.add_argument('--executable',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--enabled',type=int,required=True);p.add_argument('--generation-bits',type=int,default=64);p.add_argument('--wb-entries',type=int,default=2)
    args=p.parse_args();args.output.mkdir();results=[]
    cases=[('real-home-merge-reuse',merge)]
    if args.enabled: cases += [('real-DMA-before-A',before_a_dma),('real-probe-held-ACK-DMA',held_ack_dma),
                               ('real-clean-victim-overlap',lambda t:victim(t,False)),('real-dirty-victim-overlap',lambda t:victim(t,True))]
    if args.generation_bits==2: cases=[('real-home-exhausted-fallback-tail',real_fallback_tail)]
    for name,fn in cases:
        t=Home(args.executable,args.output,name,enabled=bool(args.enabled),generation_bits=args.generation_bits,wb_entries=args.wb_entries)
        try: fn(t);results.append(t.close())
        except BaseException:
            t.close(False);raise
        (args.output/'progress.json').write_text(json.dumps({'status':'RUNNING','cases':results},indent=2)+'\n')
    if args.generation_bits==2:
        name='real-home-fallback-context-before-ReleaseAck'
        t=Home(args.executable,args.output,name,enabled=True,generation_bits=2,wb_entries=args.wb_entries)
        diagnostic='cache fallback context changed before real coherence drain'
        try:
            real_fallback_tail(t,poison_context=True)
        except _base.DriverFailure as error:
            require(diagnostic in str(error),'unrelated native failure in exact context negative')
            t.close(False)
            require(t.child.returncode != 0,'context poison failed without RTL assertion')
            results.append(dict(name=name,status='EXPECTED_RTL_ASSERTION',diagnostic=diagnostic,
                                exit=t.child.returncode,stimulus={'field':'posted.contextEpoch','original':0,'poisoned':1,
                                'boundary':'CPU ACK complete; actual home-produced ReleaseAck still held'}))
        else:
            t.close(False)
            raise AssertionError('real-home context negative did not assert')
    report=dict(status='PASS',scope='real private cache/Mixed home/DMA/AXI; fixture authority, independent AXI memory; no executing CPU claim',enabled=bool(args.enabled),cases=results)
    (args.output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print('POSTED_HOME_COMPONENT_PASS enabled='+str(args.enabled))

if __name__=='__main__':main()
