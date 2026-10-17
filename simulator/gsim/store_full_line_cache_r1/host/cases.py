"""Selected cache/Home fixture: independent accepted-byte, owner and AXI ledger."""
import collections,gzip,json,pathlib,subprocess,sys
from memory import Memory,require
BASE=0x80200000;SIZE=1<<31
CTX=['owner.slot','owner.generation','cohortRoot.slot','cohortRoot.generation','epoch','lineAddress']
RES=['mshr','set','way','victimValid','victimDirty','victimAddress']
def fields(a,p,names):return tuple(a[p+'.'+n] for n in names)
def context(a,p):return fields(a,p,CTX)
def reservation(a,p):return fields(a,p,RES)
def token(a,p):return fields(a,p,['index','tag'])
def initial(address):return (((address-BASE)*29+((address-BASE)>>4)*7)^0xa5)&255
class Test:
 def __init__(self,exe,out,target,permission,mutation=None):
  self.out=out;self.log=gzip.open(str(out)+'.jsonl.gz','wt');self.err=open(str(out)+'.stderr','w')
  self.p=subprocess.Popen([str(exe)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.err,text=True,bufsize=1)
  self.inputs={};self.cy=0;self.mem=Memory({},BASE);self.mem.delay=8
  self.image={};self.target=target;self.permission=permission;self.mutation=mutation;self.injected=False
  self.req=None;self.responses={};self.tokens={};self.owners={};self.decisions={};self.acquires={};self.sinks={};self.releases={};self.cburst={}
  self.expected_generation=0;self.accepted=[];self.drained=[];self.count=collections.Counter();self.reads=collections.Counter();self.returned=collections.Counter();self.logical=collections.Counter();self.held={};self.installed=set();self.last={};self.flush=False;self.write_ids={}
  self.tick(reset=1);self.tick(reset=1);self.tick(reset=0)
 def byte(self,a):return self.image.get(a,initial(a))
 def line(self,a):return bytes(self.byte(a+i) for i in range(64))
 def qword(self,a):return int.from_bytes(self.line(a&~63)[a%64:a%64+8],'little')
 def tick(self,**extra):
  v={'reset':0,'posted.contextEpoch':0,'posted.seal':0,'posted.endEpisode':0,'flushRequest':int(self.flush),
     'upstream.request.valid':int(self.req is not None),'upstream.response.ready':1,'dma.request.valid':0,'dma.response.ready':1,
     'dmaLine.request.valid':0,'dmaLine.response.ready':1,'posted.requestProof.valid':int(self.req is not None and self.req['posted']),
     'holdAcquire':0,'holdGrantAck':0,'holdReleaseAck':0,'holdCoherentC':0}
  if self.req:
   q=self.req;v.update({'upstream.request.bits.'+k:x for k,x in q['bits'].items()})
   proof={'token.index':q['token'][0],'token.tag':q['token'][1],'epoch':0,'address':q['bits']['address'],'data':q['bits']['data'],'mask':q['bits']['mask'],'size':q['bits']['size']}
   proof.update({k:int(q['posted']) for k in ['headAuthorized','physicalPmpAllowed','originalPhysical','integerOrigin','legacyPostedAccepted','finalChecked']})
   v.update({'posted.requestProof.bits.'+k:x for k,x in proof.items()})
  v.update(self.mem.inputs(self.cy));v.update(extra);self.inputs.update(v)
  self.p.stdin.write(' '.join(k+'='+str(int(x)) for k,x in self.inputs.items())+'\n');self.p.stdin.flush();line=self.p.stdout.readline();require(line,'driver ended before requested edge');a=json.loads(line);self.cy+=1
  self.log.write(json.dumps({'cycle':self.cy,'inputs':dict(self.inputs),'outputs':a},separators=(',',':'))+'\n')
  if not v['reset']:
   self.sample(a,v)
  self.last=a;return a
 def sample(self,a,v):
  require(not a['failed'],'owner entered fail-stop')
  # Retain every public output offer across backpressure. Pin inputs remain stable until explicit update.
  for label,valid,ready,payload in [('CPU',a['upstream.response.valid'],v['upstream.response.ready'],tuple(a['upstream.response.bits.'+k] for k in ['returnHandle','data','error','pageFault'])),('LINE',a['lineGrantValid'],a['lineGrantReady'],tuple(a['lineGrantBits.'+k] for k in ['source','sink','cap','denied','corrupt']+['data.word'+str(i) for i in range(8)]))]:
   if label in self.held:require(valid and self.held[label]==payload,'changed held '+label)
   if valid and not ready:self.held[label]=payload
   else:self.held.pop(label,None)
  for ch,names in [('A',['Opcode','Param','Size','Source','Address','Mask','Data','Corrupt']),('B',['Opcode','Param','Size','Source','Address']),('C',['Opcode','Param','Size','Source','Address','Data','Corrupt']),('D',['Opcode','Param','Size','Source','Sink','Denied','Data','Corrupt']),('E',['Sink'])]:
   valid=a['mon'+ch+'Valid'];ready=a['mon'+ch+'Ready'];payload=tuple(a['mon'+ch+n] for n in names)
   if ch in self.held:require(valid and payload==self.held[ch],'changed held '+ch)
   if valid and not ready:self.held[ch]=payload
   else:self.held.pop(ch,None)
  q=self.req
  if q and a['upstream.request.ready']:
   b=q['bits'];h=b['returnHandle'];require(h not in self.responses,'return handle reused before response')
   self.responses[h]=(0 if b['write'] else self.qword(b['address']),q['token'],q['posted'])
   if q['posted']:
    require(a['accepted.valid'],'proof-bearing miss did not enter posted owner')
    c=context(a,'accepted.bits.member.context');r=reservation(a,'accepted.bits.reservation');t=token(a,'accepted.bits.member.token');ticket=a['accepted.bits.member.responseTicket']
    require(t==q['token'] and c[-1]==b['address']&~63 and c[4]==0,'accepted intent lineage')
    require(t not in self.tokens and not any(x['ticket']==ticket and not x['ack'] for x in self.tokens.values()),'token/response ticket reuse')
    if a['accepted.bits.newLine']:
     require(c[:2] not in self.owners and c[1]==self.expected_generation,'owner generation reuse/skipped')
     require(r[0]<2 and r[1]==(c[-1]//64)%256 and r[2]<2,'physical reservation')
     require(all(x['res'][0]!=r[0] for x in self.owners.values()),'live MSHR reused')
     self.expected_generation+=1;self.owners[c[:2]]=dict(context=c,res=r,coverage={},members=[],installed=False,e=False,refilled=False)
    o=self.owners[c[:2]];require(o['context']==c and o['res']==r and not o['installed'] and c[:2] not in self.decisions,'join changed or closed owner')
    for i in range(1<<b['size']):o['coverage'][b['address']+i]=(b['data']>>(8*((b['address']&7)+i)))&255
    o['members'].append(t);self.tokens[t]=dict(context=c,ticket=ticket,ack=False,drain=False);self.accepted.append(t);self.count['posted_accept']+=1
   else:require(not a['accepted.valid'],'ordinary request invented posted acceptance')
   self.count['cpu_request']+=1;self.req=None
  else:require(not a['accepted.valid'],'accepted without original CPU fire')
  if a['upstream.response.valid'] and v['upstream.response.ready']:
   h=a['upstream.response.bits.returnHandle'];require(h in self.responses,'unowned CPU response');expected,t,posted=self.responses.pop(h)
   require(not a['upstream.response.bits.error'] and not a['upstream.response.bits.pageFault'] and a['upstream.response.bits.data']==expected,'CPU readback/data error')
   if posted:
    require(a['acknowledged.valid'] and token(a,'acknowledged.bits.token')==t,'CPU response/posted ACK detached')
   self.count['cpu_response']+=1
  if a['acknowledged.valid']:
   t=token(a,'acknowledged.bits.token');require(t in self.tokens and not self.tokens[t]['ack'],'unowned/duplicate ACK');x=self.tokens[t]
   require(context(a,'acknowledged.bits.context')==x['context'] and a['acknowledged.bits.responseTicket']==x['ticket'],'ACK identity changed');x['ack']=True;self.count['posted_ack']+=1
  for i in range(2):
   p='decision'+str(i)
   if a[p+'.valid']:
    c=context(a,p+'.bits.context');r=reservation(a,p+'.bits.reservation');key=c[:2];require(key in self.owners and key not in self.decisions,'unowned/duplicate decision');o=self.owners[key]
    require(o['context']==c and o['res']==r,'decision identity changed');perm=bool(a[p+'.bits.permissionOnly']);require(not perm or len(o['coverage'])==64,'Perm without complete independent byte coverage');require(perm==self.permission,'unexpected decision kind')
    self.decisions[key]=perm;self.count['decision']+=1
  if a['monAValid'] and a['monAReady']:
   src=a['monASource'];addr=a['monAAddress'];op=a['monAOpcode'];require(src not in self.acquires and op in (6,7) and a['monASize']==6 and a['monAParam']==1 and addr%64==0,'A shape/source reuse')
   matches=[k for k,o in self.owners.items() if o['context'][-1]==addr]
   owner=matches[0] if matches else None
   if owner is not None:require(owner in self.decisions and (op==7)==self.decisions[owner],'A not backed by exact accepted decision')
   else:require(op==6,'nonposted Perm')
   self.acquires[src]=dict(address=addr,owner=owner,permission=op==7,data=None,sink=None,e=False,expected=self.line(addr));self.count['a']+=1
  if a['acquired.valid']:
   c=context(a,'acquired.bits.context');require(c[:2] in self.owners and self.owners[c[:2]]['context']==c,'acquire observation identity')
   require(any(x['owner']==c[:2] for x in self.acquires.values()),'acquire observation precedes public A')
  if a['lineGrantValid'] and a['lineGrantReady']:
   src=a['lineGrantBits.source'];require(src in self.acquires,'unowned line grant');x=self.acquires[src];require(not x['permission'] and x['data'] is None,'line data for Perm/duplicate')
   data=b''.join(a['lineGrantBits.data.word'+str(i)].to_bytes(8,'little') for i in range(8));require(data==x['expected'] and a['lineGrantBits.cap']==0 and not a['lineGrantBits.denied'] and not a['lineGrantBits.corrupt'],'line grant payload/cap')
   self.grant(src,a['lineGrantBits.sink'],data);self.count['line_grant']+=1
  if a['monDValid'] and a['monDReady']:
   src=a['monDSource'];op=a['monDOpcode']
   if op==4:
    require(src in self.acquires and self.acquires[src]['permission'] and not a['monDDenied'] and not a['monDCorrupt'] and a['monDParam']==0,'invalid Perm D');self.grant(src,a['monDSink'],b'');self.count['perm_grant']+=1
   elif op==6:
    require(src in self.releases and self.releases[src]['b'],'ReleaseAck before matched B');del self.releases[src];self.count['release_ack']+=1
   else:raise AssertionError('unexpected standard D opcode')
  if a['monEValid'] and a['monEReady']:
   sink=a['monESink'];require(sink in self.sinks,'unowned E');src=self.sinks.pop(sink);x=self.acquires[src];x['e']=True
   if x['owner'] is not None:self.owners[x['owner']]['e']=True
   else:del self.acquires[src]
   self.count['e']+=1
  if a['refillValid']:
   c=context(a,'refillEvent.context');r=reservation(a,'refillEvent.reservation');o=self.owners[c[:2]];require(c==o['context'] and r==o['res'] and o['e'] and not o['refilled'] and not a['refillError'],'refill before E or identity')
   matches=[src for src,x in self.acquires.items() if x['owner']==c[:2]];require(len(matches)==1,'refill source ownership');x=self.acquires.pop(matches[0]);require(x['e'],'refill before E')
   data=b''.join(a['refillWord'+str(i)].to_bytes(8,'little') for i in range(8))
   if not x['permission']:require(data==x['data'],'refill data changed')
   o['refilled']=True;self.count['refill']+=1
  if a['installedValid']:
   c=context(a,'installedEvent.context');r=reservation(a,'installedEvent.reservation');o=self.owners[c[:2]];require(c==o['context'] and r==o['res'] and o['refilled'] and not o['installed'],'install ordering/identity')
   expected=bytearray(self.line(c[-1]));
   for addr,val in o['coverage'].items():expected[addr-c[-1]]=val
   data=b''.join(a['installWord'+str(i)].to_bytes(8,'little') for i in range(8))
   if self.mutation=='install' and not self.injected:data=bytes([data[0]^1])+data[1:];self.injected=True
   require(a['lineWrite'] and a['lineWritePosted'] and a['lineWriteAddress']==c[-1] and data==expected,'installed bytes differ from independent accepted intents')
   self.image.update({c[-1]+i:v for i,v in enumerate(expected)});o['installed']=True;self.installed.add(c[-1]);self.count['install']+=1
  if a['drained.valid']:
   t=token(a,'drained.bits.token');require(t in self.tokens and self.tokens[t]['ack'] and not self.tokens[t]['drain'],'drain without ACK/duplicate');x=self.tokens[t]
   require(context(a,'drained.bits.context')==x['context'] and self.owners[x['context'][:2]]['installed'],'drain before install');require(t==self.accepted[len(self.drained)],'token drain reordered');x['drain']=True;self.drained.append(t);self.count['drain']+=1
  if a['released.valid']:
   c=context(a,'released.bits.context');r=reservation(a,'released.bits.reservation');o=self.owners[c[:2]];require(c==o['context'] and r==o['res'] and o['installed'] and all(self.tokens[t]['drain'] for t in o['members']),'release outstanding responsibility')
   for t in o['members']:del self.tokens[t]
   del self.owners[c[:2]];self.count['release']+=1
  self.coherence_memory(a,v)
 def grant(self,src,sink,data):
  require(sink not in self.sinks and self.acquires[src]['data'] is None,'sink reuse/duplicategrant');self.sinks[sink]=src;self.acquires[src].update(data=data,sink=sink)
 def coherence_memory(self,a,v):
  if a['monBValid'] and a['monBReady']:self.count['probe']+=1
  if a['monCValid'] and a['monCReady']:
   op=a['monCOpcode'];src=a['monCSource'];addr=a['monCAddress'];require(op in (4,5,6,7) and a['monCSize']==6 and not a['monCCorrupt'],'C shape')
   if op in (5,7):
    q=self.cburst.setdefault(src,dict(address=addr,opcode=op,words=[]));require(q['address']==addr and q['opcode']==op and len(q['words'])<8,'C burst changed');q['words'].append(a['monCData'])
    if len(q['words'])==8:
     payload=b''.join(x.to_bytes(8,'little') for x in q['words']);require(payload==self.line(addr),'dirty C differs from independent image');del self.cburst[src]
     if op==7:require(src not in self.releases,'release source reused');self.releases[src]=dict(address=addr,data=payload,b=False)
   elif op==6:self.releases[src]=dict(address=addr,data=None,b=True)
   self.count['c']+=1
  if a['logicalRead']:self.logical[a['logicalReadAddress']]+=64
  # Count target reads over the entire lifetime, including explicit flush/drain.
  for ch in ('ar','aw'):
   p='ddrAxi.'+ch
   if a[p+'.valid'] and v[p+'.ready']:
    addr=BASE+a[p+'.bits.addr'];n=(a[p+'.bits.len']+1)*8;require(BASE<=addr and addr+n<=BASE+SIZE,'AXI escaped RAM aperture')
    for i in range(n):self.mem.bytes.setdefault(addr+i,initial(addr+i))
    if ch=='ar':self.reads[addr]+=n
    else:
     matches=[x for x in self.releases.values() if x['address']==addr and x['data'] is not None and not x['b']];require(len(matches)==1 and n==64,'AW without complete dirty C owner')
  if v['ddrAxi.r.valid'] and a['ddrAxi.r.ready']:
   q=self.mem.reads[v['ddrAxi.r.bits.id']];self.returned[q['address']]+=8
  if a['ddrAxi.w.valid'] and v['ddrAxi.w.ready']:
   q=self.mem.writes[0];matches=[x for x in self.releases.values() if x['address']==q['address'] and x['data'] is not None and not x['b']];require(len(matches)==1,'W without dirty owner');require(a['ddrAxi.w.bits.strb']==255 and a['ddrAxi.w.bits.data'].to_bytes(8,'little')==matches[0]['data'][q['beat']*8:q['beat']*8+8],'W changed dirty payload')
  if v['ddrAxi.b.valid'] and a['ddrAxi.b.ready']:
   bid=v['ddrAxi.b.bits.id'];require(self.mem.acks and self.mem.acks[0]['id']==bid,'B ID pairing');addr=self.write_ids.pop(bid);matches=[x for x in self.releases.values() if x['address']==addr and not x['b']];require(len(matches)==1,'B missing dirty owner');matches[0]['b']=True
  if a['ddrAxi.aw.valid'] and v['ddrAxi.aw.ready']:self.write_ids[a['ddrAxi.aw.bits.id']]=BASE+a['ddrAxi.aw.bits.addr']
  self.mem.sample(a,v,self.cy)
  if self.permission:require(self.reads[self.target]==0 and self.returned[self.target]==0 and self.logical[self.target]==0,'Perm target backing read')
 def until(self,p,limit=5000):
  for _ in range(limit):
   if p():return
   self.tick()
  raise AssertionError('bounded wait expired')
 def store(self,offset,size,value,tag):
  require(self.req is None,'held request replaced');self.req=dict(token=(tag%16,tag),posted=True,bits=dict(returnHandle=4+(tag%2),atomic=0,atomicOp=0,address=self.target+offset,write=1,size=size,data=(value<<(8*(offset&7)))&((1<<64)-1),mask=((1<<(1<<size))-1)<<(offset&7),virtualized=0,precheckedLoad=0,translationEpoch=0,prefetchNextAllowed=0,uncached=0))
  self.until(lambda:self.req is None);self.until(lambda:not self.responses)
 def read(self,offset):
  require(self.req is None,'held request replaced');self.req=dict(token=(0,0),posted=False,bits=dict(returnHandle=0,atomic=0,atomicOp=0,address=self.target+offset,write=0,size=3,data=0,mask=255,virtualized=0,precheckedLoad=0,translationEpoch=0,prefetchNextAllowed=0,uncached=0))
  self.until(lambda:self.req is None);self.until(lambda:not self.responses)
 def finish(self):
  self.until(lambda:not self.owners and not self.tokens and not self.responses and not self.last['posted.busy'])
  for i in range(8):self.read(i*8)
  self.tick(**{'posted.endEpisode':1});self.flush=True;self.until(lambda:self.last.get('flushDone',0));self.tick();self.flush=False
  for _ in range(20):self.tick()
  require(not self.owners and not self.tokens and not self.acquires and not self.sinks and not self.releases and not self.cburst and not self.mem.busy() and not self.write_ids,'final responsibilities not drained')
  require(not self.last['mshrMask'] and not self.last['postedMask'] and not self.last['responseMask'] and not self.last['wbMask'] and not self.last['prefetchBusy'],'final cache resource masks not drained')
  require(self.reads[self.target]==(0 if self.permission else 64) and self.returned[self.target]==self.reads[self.target] and self.logical[self.target]==self.reads[self.target],'target read budget')
  require(bytes(self.mem.bytes[self.target+i] for i in range(64))==self.line(self.target),'final backing image')
  require(self.count['decision']==self.count['install']==self.count['release']==1 and self.count['posted_accept']==self.count['posted_ack']==self.count['drain'],'nonvacuous posted conservation')
  self.p.stdin.write('quit\n');self.p.stdin.flush();require(self.p.wait(timeout=10)==0,'driver failed');self.log.close();self.err.close()
  return dict(cycles=self.cy,counts=dict(self.count),reads=dict(self.reads),returned=dict(self.returned),logical=dict(self.logical),axi=dict(self.mem.count),target=self.target)
def main():
 exe=pathlib.Path(sys.argv[1]);out=pathlib.Path(sys.argv[2]);out.mkdir(exist_ok=True);results={}
 mutation=len(sys.argv)>3 and sys.argv[3]=='--mutation'
 for mode in (('full',) if mutation else ('full','partial_seal','partial_timeout')):
  t=Test(exe,out/mode,BASE+0x1000,mode=='full','install' if mutation else None)
  try:
   for i in range(8 if mode=='full' else 7):t.store(i*8,3,0x123456789abcdef0+i*0x101,1+i)
   if mode!='full':
    for i in range(7):t.store(56+i,0,0x80+i,8+i)
   if mode=='partial_seal':t.tick(**{'posted.seal':1})
   t.until(lambda:t.target in t.installed);results[mode]=t.finish()
  except AssertionError as e:
   if t.p.poll() is None:t.p.kill();t.p.wait()
   t.log.close();t.err.close()
   if mutation and t.injected and str(e)=='installed bytes differ from independent accepted intents':
    print('B1_EXPECTED_INSTALL_ORACLE_MUTATION');raise SystemExit(1)
   raise
  finally:
   if t.p.poll() is None:t.p.kill();t.p.wait()
   t.log.close();t.err.close()
 if mutation:raise AssertionError('mutation unexpectedly passed')
 (out/'RESULTS.json').write_text(json.dumps(results,indent=2)+'\n');print('B1_INITIAL_POSITIVE_PASS',json.dumps(results))
if __name__=='__main__':main()
