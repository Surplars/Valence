"""Additional arms only; original qualified host/cases.py remains immutable."""
from cases import Test,require,pathlib,json,sys

def positive(exe,out,internal=False,future_only=False):
    out.mkdir(exist_ok=True);results={}
    if not future_only:
        t=Test(exe,out/'basic.jsonl',{4096:0,4160:64})
        t.set(holdD=1,holdE=1);t.request(1,4096,True)
        t.until(lambda z:z['dOffered']);[t.tick() for _ in range(4)]
        t.set(holdD=0);t.until(lambda z:4096 in t.grants);[t.tick() for _ in range(4)]
        require(1 not in t.done,'completion before E')
        t.set(holdE=0);t.until(lambda z:1 in t.done)
        t.set(holdD=1);t.request(2,4160,False);t.until(lambda z:z['dOffered']);[t.tick() for _ in range(4)]
        t.set(holdD=0);t.until(lambda z:2 in t.done)
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
        t=Test(exe,out/(name+'.jsonl'),{4096:0,4608:0,5120:64,4160:64},b_delay=40)
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
        require(t.o.target_read_bytes.get(5120,0)==0,'Perm target read before explicit reacquire')
        new_words=[(0x1234abcd55aa6600+i*0x987654321)&((1<<64)-1) for i in range(8)]
        t.cbeats(4,5120,0,8,new_words)
        t.until(lambda z:len(t.acks)==2)
        require(t.line(5120)==new_words,'new target dirty release payload')
        t.acquire(14,5120,False)
        results[name]=t.finish()
    for name,rec in results.items():
        requests=1 if name=='denied_shim' else (5 if name.startswith('future_') else 2)
        reads=0 if name=='denied_shim' else (2 if name.startswith('future_') else 1)
        releases=2*int(name.startswith('future_'))
        expected=dict(request=requests,a=requests,grant=requests+(0 if internal else 7*reads),e=requests,result=requests,
                      logical_read=reads,ar=reads,r=8*reads,c=8*releases,aw=releases,w=8*releases,b=releases,ack=releases)
        require(all(rec['events'].get(k,0)==v for k,v in expected.items()), 'exact nonvacuous event counts '+name)
        require(all(bool(v[1])==(name=='denied_shim') for v in rec['done'].values()), 'unexpected completion error '+name)
    (out/'RESULTS.json').write_text(json.dumps(results,indent=2)+'\n')
    print('B0_INTERNAL_SUPPLEMENT_PASS' if internal else 'B0_STANDARD_POSITIVE_PASS',json.dumps(results))


def off_positive(exe,out):
    out.mkdir(exist_ok=True)
    t=Test(exe,out/'off_block.jsonl',{4096:64})
    t.set(holdLine=1);t.request(100,4096,False)
    t.until(lambda z:z['lineOffered']);[t.tick() for _ in range(4)]
    t.set(holdLine=0);t.until(lambda z:100 in t.done)
    rec=t.finish()
    expected=dict(request=1,a=1,grant=1,e=1,result=1,logical_read=1,ar=1,r=8)
    require(rec['events']==expected and not rec['done'][100][1],'OFF normal Block counts/error')
    (out/'RESULTS.json').write_text(json.dumps(rec,indent=2)+'\n')
    print('B0_OFF_BLOCK_PASS',json.dumps(rec))

def disabled(exe,out):
    t=Test(exe,out,{4096:0})
    try:
        t.request(101,4096,True);t.until(lambda z:101 in t.done)
    finally:
        if t.p.poll() is None:t.p.kill();t.p.wait()
        t.log.close();t.err.close()
    raise AssertionError('disabled Perm unexpectedly completed')

if __name__=='__main__':
    mode=sys.argv[1];exe=pathlib.Path(sys.argv[2]);out=pathlib.Path(sys.argv[3])
    if mode=='standard':positive(exe,out)
    elif mode=='supplement':positive(exe,out,internal=True,future_only=True)
    elif mode=='off':off_positive(exe,out)
    elif mode=='disabled':disabled(exe,out)
    else:raise AssertionError('unknown arm')
