"""B0 host: actual public pin driver, independent byte memory and protocol oracle.
No synthetic CPU/cache claims. Runtime requires a separate reviewed release.
"""
import collections,json,pathlib,subprocess,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent.parent))
from protocol_oracle_r2 import Oracle,require

BASE=4096
class Test:
    def __init__(self, executable, log, expected, b_delay=30):
        self.log=open(log,'w');self.err=open(str(log)+'.stderr','w')
        self.p=subprocess.Popen([str(executable)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                stderr=self.err,text=True,bufsize=1)
        self.inputs={};self.cycle=0;self.o=Oracle();self.o.expect_reads(expected)
        self.mem=bytearray(((i*29+(i>>4)*7)^0xa5)&255 for i in range(4096))
        self.rd={};self.rheld=None;self.awq=collections.deque();self.wq=collections.deque();self.w=[]
        self.bq=collections.deque();self.bheld=None;self.b_delay=b_delay
        self.done={};self.expected_data={};self.a_seen={};self.grants={};self.acks=[]
        self.events=collections.Counter();self.data_writes=[]
        self.set(reset=1)
        for _ in range(4):self.tick(check=False)
        self.set(reset=0,**{'response.ready':1,'releaseAck.ready':1,
                            'axi.ar.ready':1,'axi.aw.ready':1,'axi.w.ready':1})
        for _ in range(2):self.tick()
    def set(self,**kw):self.inputs.update(kw)
    def word(self,addr):return int.from_bytes(self.mem[addr-BASE:addr-BASE+8],'little')
    def line(self,addr):return [self.word(addr+8*i) for i in range(8)]
    def memory_inputs(self):
        if self.rheld is None:
            candidates=[i for i,r in self.rd.items() if r['due']<=self.cycle]
            if candidates:
                i=min(candidates);r=self.rd[i]
                self.rheld=(i,self.word(r['address']+8*r['beat']),r['beat']==7)
        if self.bheld is None and self.bq and self.bq[0][1]<=self.cycle:
            self.bheld=self.bq.popleft()[0]
        self.set(**{'axi.r.valid':int(self.rheld is not None),'axi.b.valid':int(self.bheld is not None)})
        if self.rheld:
            i,data,last=self.rheld
            self.set(**{'axi.r.bits.id':i,'axi.r.bits.data':data,'axi.r.bits.last':int(last),'axi.r.bits.resp':0})
        if self.bheld is not None:self.set(**{'axi.b.bits.id':self.bheld,'axi.b.bits.resp':0})
    def tick(self,check=True):
        self.memory_inputs();self.cycle+=1;require(self.cycle<10000,'host cycle timeout')
        sent=dict(self.inputs)
        self.p.stdin.write(' '.join(f'{k}={v}' for k,v in sent.items())+'\n');self.p.stdin.flush()
        text=self.p.stdout.readline()
        require(bool(text),'model stopped before expected completion')
        z=json.loads(text)
        self.log.write(json.dumps({'cycle':self.cycle,'inputs':sent,'outputs':z})+'\n');self.log.flush()
        if not check:return z
        get=lambda n:z[n]
        payload=lambda n:tuple((k,v) for k,v in sorted(z.items()) if k.startswith(n+'.bits.'))
        for n in ('a','d','c','e','line'):
            self.o.offer(n,bool(get(n+'Offered')),bool(get(n+'.valid')),payload(n))
        for n in ('ar','aw','w'):
            self.o.offer('axi.'+n,bool(get('axi.'+n+'.valid')),bool(sent.get('axi.'+n+'.ready',0)),payload('axi.'+n))
        self.o.offer('response',bool(get('response.valid')),bool(sent.get('response.ready',0)),payload('response'))
        if sent.get('request.valid',0) and get('request.ready'):
            tag=sent['request.bits.tag'];addr=sent['request.bits.address'];perm=sent['request.bits.permissionOnly']
            self.o.request(tag,addr,bool(perm));self.expected_data[tag]=None if perm else self.line(addr)
            self.events['request']+=1
        if get('a.valid'):
            self.o.a(get('a.bits.source'),get('a.bits.address'),get('a.bits.opcode'),get('a.bits.param'),get('a.bits.size'))
            self.a_seen[get('a.bits.address')]=self.cycle;self.events['a']+=1
        for n,internal in [('d',False),('line',True)]:
            if get(n+'.valid') and (internal or get(n+'.bits.opcode')!=6):
                src=get(n+'.bits.source');a=self.o.acquire[src]
                if internal:
                    words=[get('line.bits.data.word'+str(i)) for i in range(8)]
                    require(words==self.expected_data[a['tag']],'internal full payload mismatch')
                elif not a['perm']:
                    require(get('d.bits.data')==self.expected_data[a['tag']][a['beats']],'standard D payload mismatch')
                else:require(get('d.bits.data')==0 and not get('d.bits.corrupt'),'permission Grant shape')
                self.o.grant(src,get(n+'.bits.sink'),5 if internal else get('d.bits.opcode'),6 if internal else get('d.bits.size'),
                             get(n+'.bits.cap') if internal else get('d.bits.param'),bool(get(n+'.bits.denied')),bool(get(n+'.bits.corrupt')),internal)
                if not internal and sent.get('deniedD',0):self.o.engine_denied_shim(src)
                self.grants[a['address']]=self.cycle;self.events['grant']+=1
        if get('e.valid'):self.o.e(get('e.bits.sink'));self.events['e']+=1
        if get('c.valid'):
            src=get('c.bits.source');beat=self.o.release[src]['beats'] if src in self.o.release else 0
            require((get('c.bits.opcode'),get('c.bits.param'),get('c.bits.size'),get('c.bits.corrupt'))==(7,1,6,0),'C header')
            self.o.c(src,get('c.bits.address'),beat,beat==7,get('c.bits.data'));self.events['c']+=1
        if get('read.valid'):self.o.line_read(get('read.bits.address'));self.events['logical_read']+=1
        if get('axi.ar.valid') and sent.get('axi.ar.ready',0):
            i=get('axi.ar.bits.id');addr=BASE+get('axi.ar.bits.addr')
            require(i not in self.rd,'memory AR ID reused')
            self.o.axi_ar(i,get('axi.ar.bits.addr'),get('axi.ar.bits.len'),get('axi.ar.bits.size'),get('axi.ar.bits.burst'))
            self.rd[i]=dict(address=addr,beat=0,due=self.cycle+3);self.events['ar']+=1
        if sent.get('axi.r.valid',0) and get('axi.r.ready'):
            i,data,last=self.rheld;self.o.axi_r(i,last);r=self.rd[i]
            require(data==self.word(r['address']+8*r['beat']),'memory read data changed')
            if last:del self.rd[i]
            else:r['beat']+=1
            self.rheld=None;self.events['r']+=1
        if get('axi.aw.valid') and sent.get('axi.aw.ready',0):
            i=get('axi.aw.bits.id');addr=BASE+get('axi.aw.bits.addr')
            self.o.axi_aw(i,get('axi.aw.bits.addr'),get('axi.aw.bits.len'),get('axi.aw.bits.size'),get('axi.aw.bits.burst'))
            self.awq.append((i,addr));self.events['aw']+=1
        if get('axi.w.valid') and sent.get('axi.w.ready',0):
            data=get('axi.w.bits.data');last=bool(get('axi.w.bits.last'))
            self.o.axi_w(data,get('axi.w.bits.strb'),last);self.w.append(data)
            if last:self.wq.append(self.w);self.w=[]
            self.events['w']+=1
        while self.awq and self.wq:
            i,addr=self.awq.popleft();words=self.wq.popleft()
            for j,w in enumerate(words):self.mem[addr-BASE+8*j:addr-BASE+8*j+8]=w.to_bytes(8,'little')
            self.data_writes.append((addr,words));self.bq.append((i,self.cycle+self.b_delay))
        if sent.get('axi.b.valid',0) and get('axi.b.ready'):
            self.o.axi_b(self.bheld,0);self.bheld=None;self.events['b']+=1
        if get('releaseAck.valid') and sent.get('releaseAck.ready',0):
            require(not get('releaseAck.bits.denied') and not get('releaseAck.bits.corrupt'),'ReleaseAck error')
            src=get('releaseAck.bits.source');self.o.release_ack(src);self.acks.append((src,self.cycle));self.events['ack']+=1
        if get('response.valid') and sent.get('response.ready',0):
            tag=get('response.bits.tag');has=bool(get('response.bits.hasData'));error=bool(get('response.bits.error'))
            self.o.result(tag,has,error)
            words=[get('response.bits.data.word'+str(i)) for i in range(8)]
            require(words==(self.expected_data[tag] if has else [0]*8),'complete payload mismatch')
            require(get('response.bits.cap')==0,'completion cap')
            require(tag not in self.done,'duplicate caller completion');self.done[tag]=(self.cycle,error);self.events['result']+=1
        return z
    def until(self,predicate,limit=1000):
        for _ in range(limit):
            z=self.tick()
            if predicate(z):return z
        raise AssertionError('bounded witness timeout')
    def request(self,tag,addr,perm):
        self.set(**{'request.valid':1,'request.bits.address':addr,'request.bits.tag':tag,'request.bits.grow':1,'request.bits.permissionOnly':int(perm)})
        self.until(lambda z:z['request.ready']);self.set(**{'request.valid':0})
    def acquire(self,tag,addr,perm):
        self.request(tag,addr,perm);self.until(lambda z:tag in self.done)
    def cbeats(self,source,addr,first,last,words):
        for i in range(first,last):
            self.set(**{'release.valid':1,'release.bits.opcode':7,'release.bits.param':1,'release.bits.size':6,
                        'release.bits.source':source,'release.bits.address':addr,'release.bits.data':words[i],'release.bits.corrupt':0})
            self.until(lambda z:z['release.ready'])
        self.set(**{'release.valid':0})
    def finish(self):
        self.set(drain=1)
        self.until(lambda z:z['drained'] and not self.o.acquire and not self.o.release)
        for _ in range(12):self.tick()  # include trailing deferred work, then reconcile
        self.o.drained();require(not(self.rd or self.rheld or self.awq or self.wq or self.w or self.bq or self.bheld),'backing memory not drained')
        self.p.stdin.write('quit\n');self.p.stdin.flush();require(self.p.wait(timeout=5)==0,'model exit')
        self.log.close();self.err.close()
        return dict(cycles=self.cycle,events=dict(self.events),read_bytes=self.o.target_read_bytes,done=self.done)


def positive(exe,out):
    out.mkdir(exist_ok=True);results={}
    t=Test(exe,out/'basic.jsonl',{4096:0,4160:64})
    t.set(holdD=1,holdE=1);t.request(1,4096,True)
    t.until(lambda z:z['dOffered']);[t.tick() for _ in range(4)]
    t.set(holdD=0);t.until(lambda z:4096 in t.grants);[t.tick() for _ in range(4)]
    require(1 not in t.done,'completion before E')
    t.set(holdE=0);t.until(lambda z:1 in t.done)
    t.set(holdLine=1);t.request(2,4160,False);t.until(lambda z:z['lineOffered']);[t.tick() for _ in range(4)]
    t.set(holdLine=0);t.until(lambda z:2 in t.done)
    results['basic']=t.finish()
    t=Test(exe,out/'denied_shim.jsonl',{4096:0})
    t.set(deniedD=1);t.acquire(3,4096,True)
    require(t.done[3][1] and 4096 in t.o.directory,'engine denial must not rewrite Home grant outcome')
    results['denied_shim']=t.finish()
    t=Test(exe,out/'mixed_held.jsonl',{4096:64,4160:0})
    t.set(holdD=1,holdLine=1)
    t.request(4,4096,False);t.request(5,4160,True)
    t.until(lambda z:z['dOffered'] or z['lineOffered'])
    for _ in range(12):t.tick()
    t.set(holdD=0,holdLine=0)
    t.until(lambda z:4 in t.done and 5 in t.done)
    results['mixed_held']=t.finish()
    for late_e in (False,True):
        name='future_e_late' if late_e else 'future_b_late'
        t=Test(exe,out/(name+'.jsonl'),{4096:0,4608:0,5120:0,4160:64},b_delay=40)
        t.acquire(10,4096,True);t.acquire(11,4608,True)
        words=[(0x9182736455aa0000+i*0x10101010101)&((1<<64)-1) for i in range(8)]
        t.cbeats(4,4096,0,3,words)
        t.request(12,5120,True);t.until(lambda z:5120 in t.a_seen)
        for _ in range(8):t.tick();require(5120 not in t.grants,'future grant before C-last')
        # Unrelated data owner must progress while future directory is blocked.
        t.acquire(13,4160,False)
        if late_e:t.set(holdE=1)
        t.cbeats(4,4096,3,8,words)
        if late_e:
            t.until(lambda z:bool(t.acks));require(12 not in t.done,'held E completion')
            t.set(holdE=0);t.until(lambda z:12 in t.done)
        else:
            t.until(lambda z:12 in t.done);require(not t.acks,'expected independent delayed old B')
            t.until(lambda z:bool(t.acks))
        require(t.line(4096)==words,'dirty writeback bytes differ')
        require(5120 in t.o.directory,'old B/ReleaseAck erased reused directory')
        results[name]=t.finish()
    for name,rec in results.items():
        requests=1 if name=='denied_shim' else (4 if name.startswith('future_') else 2)
        reads=0 if name=='denied_shim' else 1
        releases=int(name.startswith('future_'))
        expected=dict(request=requests,a=requests,grant=requests,e=requests,result=requests,
                      logical_read=reads,ar=reads,r=8*reads,c=8*releases,aw=releases,w=8*releases,b=releases,ack=releases)
        require(all(rec['events'].get(k,0)==v for k,v in expected.items()), 'exact nonvacuous event counts '+name)
        require(all(bool(v[1])==(name=='denied_shim') for v in rec['done'].values()), 'unexpected completion error '+name)
    (out/'RESULTS.json').write_text(json.dumps(results,indent=2)+'\n')
    print('B0_POSITIVE_PASS',json.dumps(results))


def negative(exe,out,mode):
    fields={'corrupt':'corruptD','opcode':'wrongOpcodeD','cap':'badCapD'}
    require(mode in fields,'unknown negative')
    t=Test(exe,out,{4096:0});t.set(**{fields[mode]:1});t.request(99,4096,True)
    try:t.until(lambda z:99 in t.done)
    finally:
        if t.p.poll() is None:t.p.kill();t.p.wait()
        t.log.close();t.err.close()
    raise AssertionError('negative unexpectedly completed')

if __name__=='__main__':
    if sys.argv[1]=='positive':positive(pathlib.Path(sys.argv[2]),pathlib.Path(sys.argv[3]))
    else:negative(pathlib.Path(sys.argv[2]),pathlib.Path(sys.argv[3]),sys.argv[1])
