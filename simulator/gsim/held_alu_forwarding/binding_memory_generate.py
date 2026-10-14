#!/usr/bin/env python3
"""Read-only retained-model event extraction, proven against exact FIR and header.

This is a deliberately bounded FIR-to-C++ reader, not a simulation model. It
follows semantic connects and nodes to retained public C++ members, rejecting
unproved paths. Header naming is accepted only with matching declaration line,
parsed FIR type/width, and instance hierarchy. No NEXT member is sampled.
"""
import argparse, hashlib, json, re
from pathlib import Path
from dataclasses import dataclass
HERE=Path(__file__).resolve().parent
BACKEND='board.platform.core.core.core.backend'

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def split(s,sep=','):
    depth=0;start=0;out=[]
    for i,c in enumerate(s):
        if c in '({[<': depth+=1
        elif c in ')}]>': depth-=1
        elif c==sep and depth==0: out.append(s[start:i].strip());start=i+1
    out.append(s[start:].strip());return out

def typ(s):
    s=s.strip().removeprefix('const ')
    m=re.fullmatch(r'(.*)\[(\d+)\]',s)
    if m:return ('vec',int(m[2]),typ(m[1]))
    if s.startswith('{'):
        return ('bundle',{x.split(':',1)[0].strip().removeprefix('flip '):typ(x.split(':',1)[1]) for x in split(s[1:-1])},{x.split(':',1)[0].strip().removeprefix('flip '):x.strip().startswith('flip ') for x in split(s[1:-1])})
    m=re.fullmatch(r'(UInt|SInt)<(\d+)>',s)
    if m:return ('signed' if m[1]=='SInt' else 'uint',int(m[2]))
    if s in ('Clock','Reset','AsyncReset'):return ('uint',1)
    if s in ('UInt','SInt'):return ('uint',0)
    raise ValueError(('unsupported type',s))
def width(t):
    if t[0]=='vec':return t[1]*width(t[2])
    if t[0]=='bundle':return sum(width(x) for x in t[1].values())
    return t[1]
def parts(r):
    out=[];i=0
    while i<len(r):
        if r[i]=='.':i+=1;continue
        if r[i]=='[':
            start=i;depth=1;i+=1
            while i<len(r) and depth:
                if r[i]=='[':depth+=1
                elif r[i]==']':depth-=1
                i+=1
            out.append(r[start:i]);continue
        start=i
        while i<len(r) and r[i] not in '.[':i+=1
        out.append(r[start:i])
    return out
def select(t,ps):
    for p in ps:
        t=t[2] if p.startswith('[') else t[1][p]
    return t

class Unbound(Exception): pass
@dataclass
class Value:
    code:str
    width:int
    proof:list

class Binder:
    def __init__(self, model):
        self.model=model;self.lines=(model/'BoardSocGsim.fir').read_text().splitlines()
        self.modules={};self.instances={};self.headers={};self.cache={};self.active=set()
        current=None;stack=[]
        for n,line in enumerate(self.lines,1):
            body=line.strip().split(' @[')[0];ind=len(line)-len(line.lstrip())
            mm=re.match(r'(?:public )?module (\w+) :',body)
            if mm:
                current={'decl':{},'nodes':{},'connect':[],'inst':{},'name':mm[1]};self.modules[mm[1]]=current;stack=[];continue
            if not current:continue
            popped=[]
            while stack and stack[-1][0]>=ind:popped.append(stack.pop())
            m=re.match(r'when (.*) :',body)
            if m:stack.append((ind,m[1],n));continue
            if body.startswith('else '):
                prior=next((x for x in popped if x[0]==ind),None)
                if not prior:raise ValueError(('unmatched else',n))
                stack.append((ind,'not('+prior[1]+')',n));continue
            m=re.match(r'inst (\S+) of (\S+)',body)
            if m:current['inst'][m[1]]=m[2];continue
            m=re.match(r'(input|output|wire|reg|regreset|cmem|smem) (\S+) : (.*)',body)
            if m:
                typename=split(m[3])[0]
                current['decl'][m[2]]={'kind':m[1],'type':typ(typename),'line':n};continue
            m=re.match(r'read mport (\S+) = (.*), clock',body)
            if m:
                mem=parts(m[2])[0];dt=current['decl'][mem]['type'][2]
                current['decl'][m[1]]={'kind':'mport','type':dt,'line':n}
                current['nodes'][m[1]]=(m[2],n);continue
            m=re.match(r'node (\S+) = (.*)',body)
            if m:current['nodes'][m[1]]=(m[2],n);continue
            m=re.match(r'connect ([^,]+), (.*)',body)
            if m:current['connect'].append((m[1],m[2],[(x[1],x[2]) for x in stack],n))
        # Root identity comes from circuit and the matching root module.
        circuit=next(re.match(r'circuit (\w+) :',s.strip())[1] for s in self.lines if re.match(r'circuit (\w+) :',s.strip()))
        def visit(path,module):
            self.instances[path]=self.modules[module]
            for inst,mod in self.modules[module]['inst'].items():visit(path+'.'+inst if path else inst,mod)
        visit('',circuit)
        p=re.compile(r'^(.+?) ([A-Za-z_$][\w$]*)(\[[^;]+\])?; // width = (\d+), lineno = (\d+)$')
        for n,line in enumerate((model/'BoardSocGsim.h').read_text().splitlines(),1):
            m=p.match(line)
            if m:
                ctype,sym,dims,w,origin=m.groups()
                self.headers[sym]={'symbol':sym,'type':ctype,'dimensions':list(map(int,re.findall(r'\[(\d+)\]',dims or ''))),'width':int(w),'header_line':n,'fir_line':int(origin)}
    def proof(self,path,line,law):return {'instance':path,'module':self.instances[path]['name'],'fir_line':line,'fir':self.lines[line-1].strip(),'law':law}
    def locate(self,path,ref):
        p=parts(ref)
        while p and p[0] in self.instances[path]['inst']:
            path=path+'.'+p.pop(0) if path else p.pop(0)
        return path,p
    def declared(self,path,ref):
        path,p=self.locate(path,ref);d=self.instances[path]['decl'].get(p[0])
        return path,p,d,select(d['type'],p[1:]) if d else None
    def direct(self,path,ref):
        path,ps,d,t=self.declared(path,ref);mod=self.instances[path]
        if d is None:
            if len(ps)!=1 or ps[0] not in mod['nodes']:return None
            line=mod['nodes'][ps[0]][1];w=None
        else:line=d['line'];w=width(t)
        prefix=(path.replace('.','$')+'$') if path else ''
        fields=[p for p in ps if not p.startswith('[')];indexes=[p[1:-1] for p in ps if p.startswith('[')]
        if any(not x.isdigit() for x in indexes):return None
        base=prefix+'$$'.join(fields)
        # Both GSIM forms are accepted only after the exact declaration, shape,
        # index bounds and width have been checked. NEXT is never a candidate.
        candidates=[(base,indexes)]
        if indexes:candidates.append((base+''.join('_'+x for x in indexes),[]))
        for sym,ix in candidates:
            h=self.headers.get(sym)
            if not h or h['fir_line']!=line or len(ix)!=len(h['dimensions']):continue
            if any(int(i)>=n for i,n in zip(ix,h['dimensions'])):continue
            if w is not None and w and h['width']!=w:continue
            member='m.'+sym+''.join('['+i+']' for i in ix)
            code='u128('+member+')' if h['width']<=128 else member
            return Value(code,h['width'],[dict(h,law='exact instance/declaration/type/member identity',semantic_ref=ref,instance=path)])
        # GSIM can bit-pack a UInt<1> vector. Its logical index is its exact
        # UInt-vector bit position, never an inferred Bundle field position.
        if d and len(ps)==2 and ps[1].startswith('[') and d['type'][0]=='vec' and d['type'][2]==('uint',1):
            h=self.headers.get(base)
            if h and h['fir_line']==line and not h['dimensions'] and h['width']==d['type'][1]:
                return Value(f'((u128(m.{base}) >> {indexes[0]}) & 1)',1,[dict(h,law='FIR UInt<1> vector packing',semantic_ref=ref,instance=path)])
        # Scalar splits carry explicit absolute bit ranges and share the exact
        # FIR declaration. Reconstruct only this typed scalar, not a Bundle.
        if t and t[0] in ('uint','signed') and width(t)<=128:
            chunks=[]
            for sym,h in self.headers.items():
                mm=re.fullmatch(re.escape(base)+r'\$(\d+)_(\d+)',sym)
                if mm and h['fir_line']==line and not h['dimensions']:
                    hi,lo=map(int,mm.groups())
                    if h['width']!=hi-lo+1 or hi>=width(t):continue
                    chunks.append((hi,lo,h))
            coverage=set()
            for hi,lo,h in chunks:coverage.update(range(lo,hi+1))
            if coverage==set(range(width(t))) and sum(hi-lo+1 for hi,lo,h in chunks)==width(t):
                return Value('('+' | '.join(f'(u128(m.{h["symbol"]}) << {lo})' for hi,lo,h in chunks)+')',width(t),[dict(h,law='exact scalar fragment range',hi=hi,lo=lo,instance=path,semantic_ref=ref) for hi,lo,h in chunks])
        return None
    def infer(self,path,expr):
        m=re.fullmatch(r'(?:UInt|SInt)<(\d+)>\(.*\)',expr)
        if m:return int(m[1])
        m=re.fullmatch(r'(\w+)\((.*)\)',expr)
        if m:
            op=m[1];aa=split(m[2])
            if op=='bits':return int(aa[1])-int(aa[2])+1
            if op=='tail':return self.infer(path,aa[0])-int(aa[1])
            if op=='head':return int(aa[1])
            if op in ('eq','neq','lt','leq','gt','geq','orr','andr','xorr'):return 1
            if op=='mux':return max(self.infer(path,x) for x in aa[1:])
            if op=='cat':return sum(self.infer(path,x) for x in aa)
            if op in ('and','or','xor'):return max(self.infer(path,x) for x in aa)
            if op in ('add','sub'):return max(self.infer(path,x) for x in aa)+1
            if op=='pad':return max(self.infer(path,aa[0]),int(aa[1]))
            if op in ('asUInt','not'):return self.infer(path,aa[0])
        pp=parts(expr);mod=self.instances[path]
        if len(pp)==1 and pp[0] in mod['nodes']:return self.infer(path,mod['nodes'][pp[0]][0])
        rp,ps,d,t=self.declared(path,expr)
        if t:return width(t)
        if rp!=path:return self.infer(rp,self.join(ps))
        return self.resolve(path,expr).width
    def sliced(self,path,expr,hi,lo):
        w=hi-lo+1
        if not (0<=lo<=hi and w<=128):raise Unbound('invalid requested slice')
        m=re.fullmatch(r'(?:UInt|SInt)<(\d+)>\(0h([0-9a-f]+)\)',expr)
        if m:
            v=(int(m[2],16)>>lo)&((1<<w)-1)
            return self.resolve(path,f'UInt<{w}>(0h{v:x})')
        if '(' not in expr:
            rp,ps,d,t=self.declared(path,expr)
            if d and t and t[0] in ('uint','signed'):
                base=(rp.replace('.','$')+'$' if rp else '')+'$$'.join(p for p in ps if not p.startswith('['))
                pieces=[];coverage=set()
                for sym,h in self.headers.items():
                    mm=re.fullmatch(re.escape(base)+r'\$(\d+)_(\d+)',sym)
                    if not mm or h['fir_line']!=d['line'] or h['dimensions']:continue
                    a,b=map(int,mm.groups());l=max(lo,b);u=min(hi,a)
                    if h['width']!=a-b+1 or a>=width(t) or u<l:continue
                    pieces.append((f'((u128(m.{sym} >> {l-b}) & mask({u-l+1})) << {l-lo})',dict(h,law='exact FIR scalar bit slice into retained absolute fragment',hi=u,lo=l,instance=rp,semantic_ref=expr)))
                    coverage.update(range(l,u+1))
                if coverage==set(range(lo,hi+1)) and pieces:return Value('('+' | '.join(x[0] for x in pieces)+')',w,[x[1] for x in pieces])
        # A retained scalar/chunk is always preferred to a reconstructed cone.
        direct=self.direct(path,expr) if not '(' in expr else None
        if direct:
            return Value(f'(u128({direct.code} >> {lo}) & mask({w}))',w,direct.proof)
        mod=self.instances[path]
        rp,ps,decl,tt=self.declared(path,expr)
        if decl and decl['kind'] in ('reg','regreset','cmem','smem') and not any(p.startswith('[') and not p[1:-1].isdigit() for p in ps):
            raise Unbound('current state has no retained exact member '+rp+':'+self.join(ps))
        if expr in mod['nodes']:
            raw,n=mod['nodes'][expr];v=self.sliced(path,raw,hi,lo)
            return Value(v.code,w,v.proof+[self.proof(path,n,f'exact FIR bits projection [{hi}:{lo}]')])
        m=re.fullmatch(r'(\w+)\((.*)\)',expr)
        if m:
            op=m[1];aa=split(m[2])
            if op=='bits':return self.sliced(path,aa[0],int(aa[2])+hi,int(aa[2])+lo)
            if op in ('tail','asUInt'):return self.sliced(path,aa[0],hi,lo)
            if op=='cat':
                offset=0;terms=[];proof=[]
                for a in reversed(aa):
                    aw=self.infer(path,a)
                    l=max(lo,offset);h=min(hi,offset+aw-1)
                    if h>=l:
                        v=self.sliced(path,a,h-offset,l-offset);terms.append(f'({v.code} << {l-lo})');proof+=v.proof
                    offset+=aw
                if hi>=offset:raise Unbound('slice beyond concat')
                return Value('('+' | '.join(terms)+')',w,proof)
            if op in ('and','or','xor'):
                vv=[self.sliced(path,a,hi,lo) for a in aa]
                return Value('('+(' '+{'and':'&','or':'|','xor':'^'}[op]+' ').join(v.code for v in vv)+')',w,sum([v.proof for v in vv],[]))
            if op=='mux':
                c=self.resolve(path,aa[0]);x=self.sliced(path,aa[1],hi,lo);y=self.sliced(path,aa[2],hi,lo)
                return Value(f'({c.code} ? {x.code} : {y.code})',w,c.proof+x.proof+y.proof)
        if '(' not in expr:
            rp,ps,d,t=self.declared(path,expr)
            if rp!=path:return self.sliced(rp,self.join(ps),hi,lo)
            if d and d['kind'] in ('reg','regreset','cmem','smem'):
                raise Unbound('current state has no retained exact slice '+path+':'+expr)
        # Follow exact unconditional alias before admitting a scalar expression.
        matches=[(src,n) for dst,src,g,n in mod['connect'] if dst==expr and not g]
        if matches:
            src,n=matches[-1];v=self.sliced(path,src,hi,lo)
            return Value(v.code,w,v.proof+[self.proof(path,n,'exact slice through connect')])
        v=self.resolve(path,expr)
        return Value(f'(({v.code} >> {lo}) & mask({w}))',w,v.proof)
    def resolve(self,path,expr):
        key=(path,expr)
        if key in self.cache:return self.cache[key]
        if key in self.active:raise Unbound('alias cycle '+path+':'+expr)
        self.active.add(key)
        try:v=self._resolve(path,expr);self.cache[key]=v;return v
        finally:self.active.remove(key)
    def _resolve(self,path,expr):
        m=re.fullmatch(r'(?:UInt|SInt)<(\d+)>\(0([hbd])([0-9a-f]+)\)',expr)
        if m:
            w=int(m[1]);x=int(m[3],{'h':16,'b':2,'d':10}[m[2]])
            if w>128:raise Unbound('literal >128 bits')
            return Value(f'u128(0x{x:x}ULL)' if w<=64 else f'((u128(0x{x>>64:x}ULL)<<64)|u128(0x{x&((1<<64)-1):x}ULL))',w,[])
        m=re.fullmatch(r'(\w+)\((.*)\)',expr)
        if m:
            op=m[1];args=split(m[2])
            if op=='bits':return self.sliced(path,args[0],int(args[1]),int(args[2]))
            static=op in ('bits','head','tail','pad','shl','shr')
            vs=[self.resolve(path,a) for a in (args[:1] if static else args)]
            c=[v.code for v in vs];ws=[v.width for v in vs];pr=sum([v.proof for v in vs],[])
            w=max(ws);code=None
            if op=='bits':w=int(args[1])-int(args[2])+1;code=f'(({c[0]} >> {args[2]}) & mask({w}))'
            elif op=='tail':w=ws[0]-int(args[1]);code=f'({c[0]} & mask({w}))'
            elif op=='head':w=int(args[1]);code=f'({c[0]} >> {ws[0]-w})'
            elif op in ('asUInt','asClock','asAsyncReset'):code=c[0]
            elif op=='pad':w=max(w,int(args[1]));code=c[0]
            elif op=='mux':w=max(ws[1:]);code=f'({c[0]} ? {c[1]} : {c[2]})'
            elif op=='cat':
                w=sum(ws);code=c[0]
                for a,b in zip(c[1:],ws[1:]):code=f'(({code} << {b}) | {a})'
            elif op in ('eq','neq','lt','leq','gt','geq'):
                w=1;code=f'({c[0]} '+{'eq':'==','neq':'!=','lt':'<','leq':'<=','gt':'>','geq':'>='}[op]+f' {c[1]})'
            elif op in ('and','or','xor','add','sub','mul'):
                w=max(ws)+(1 if op in ('add','sub') else 0) if op!='mul' else sum(ws)
                code=f'({c[0]} '+{'and':'&','or':'|','xor':'^','add':'+','sub':'-','mul':'*'}[op]+f' {c[1]})'
            elif op=='not':code=f'(~{c[0]} & mask({w}))'
            elif op=='orr':w=1;code=f'({c[0]} != 0)'
            elif op=='andr':w=1;code=f'({c[0]} == mask({ws[0]}))'
            elif op in ('shl','shr'):
                n=int(args[1]);w=ws[0]+n if op=='shl' else max(ws[0]-n,1);code=f'({c[0]} '+('<<' if op=='shl' else '>>')+f' {n})'
            elif op in ('dshr','dshl'):
                w=ws[0] if op=='dshr' else ws[0]+(1<<ws[1])-1;code=f'({c[1]} >= 128 ? u128(0) : ({c[0]} '+('>>' if op=='dshr' else '<<')+f' unsigned({c[1]})))'
            if code is None or w>128:raise Unbound('unsupported or wide expression '+expr[:180])
            return Value(f'({code} & mask({w}))',w,pr)
        direct=self.direct(path,expr)
        if direct:
            if direct.width>128:raise Unbound('wide value needs explicit FIR slice '+path+':'+expr)
            return direct
        mod=self.instances[path]
        rp,ps,decl,tt=self.declared(path,expr)
        if decl and decl['kind'] in ('reg','regreset','cmem','smem') and not any(p.startswith('[') and not p[1:-1].isdigit() for p in ps):
            raise Unbound('current state has no retained exact member '+rp+':'+self.join(ps))
        if expr in mod['nodes']:
            val,n=mod['nodes'][expr];r=self.resolve(path,val)
            return Value(r.code,r.width,r.proof+[self.proof(path,n,'exact FIR node expression')])
        # Distribute a field selector through an explicitly typed aggregate
        # node alias/mux. This uses exact FIR field names, never Bundle offsets.
        pp=parts(expr)
        if len(pp)>1 and pp[0] in mod['nodes']:
            raw,n=mod['nodes'][pp[0]];suffix=expr[len(pp[0]):]
            mux=re.fullmatch(r'mux\((.*)\)',raw)
            if mux:
                aa=split(mux[1]);r=self.resolve(path,'mux('+aa[0]+', '+aa[1]+suffix+', '+aa[2]+suffix+')')
            elif re.fullmatch(r'[\w.$\[\]]+',raw):r=self.resolve(path,raw+suffix)
            else:raise Unbound('aggregate node projection unsupported '+path+':'+expr)
            return Value(r.code,r.width,r.proof+[self.proof(path,n,'exact aggregate field projection')])
        # Last connect wins. An aggregate connect appends the proven typed
        # suffix; dynamic aggregate selection is handled separately below.
        matches=[]
        for dst,src,guards,n in mod['connect']:
            if expr==dst or expr.startswith(dst+'.') or expr.startswith(dst+'['):
                suffix=expr[len(dst):]
                if suffix and '(' in src:continue
                try:
                    _,_,_,tt=self.declared(path,dst);flip=False
                    for pp in parts(suffix):
                        if pp.startswith('['):tt=tt[2]
                        else:flip ^= tt[2][pp];tt=tt[1][pp]
                    if flip:continue
                except (KeyError,IndexError,TypeError):pass
                matches.append((src+suffix,guards,n))
        # Aggregate connect reverses flipped leaves such as Decoupled.ready.
        for dst,src,guards,n in mod['connect']:
            if expr.startswith(src+'.') or expr.startswith(src+'['):
                suffix=expr[len(src):]
                try:
                    _,_,_,tt=self.declared(path,dst);flip=False
                    for pp in parts(suffix):
                        if pp.startswith('['):tt=tt[2]
                        else:flip ^= tt[2][pp];tt=tt[1][pp]
                    if flip:matches.append((dst+suffix,guards,n))
                except (KeyError,IndexError,TypeError):pass
        matches.sort(key=lambda x:x[2])
        if matches:
            # Discard earlier writes before the final unconditional assignment.
            last_uncond=max((i for i,x in enumerate(matches) if not x[1]),default=-1)
            if last_uncond<0:raise Unbound('no unconditional default for '+path+':'+expr)
            result=None;proof=[]
            for src,guards,n in matches[last_uncond:]:
                v=self.resolve(path,src);proof+=v.proof+[self.proof(path,n,'FIR last-connect priority')]
                if guards:
                    g=[self.resolve(path,x[0]) for x in guards];proof+=sum([x.proof for x in g],[])
                    result=Value('(('+' && '.join(x.code for x in g)+') ? '+v.code+' : '+result.code+')',max(v.width,result.width),[])
                else:result=v
            return Value(result.code,result.width,proof)
        # Constant-index vector selection can be expanded against retained
        # current fields. Runtime index uses a defined mux, not an unchecked read.
        dynamic=None
        off=0
        for part in parts(expr):
            if part.startswith('[') and not part[1:-1].isdigit():
                start=expr.find(part,off);dynamic=(part[1:-1],start,start+len(part));break
            off+=len(part)
        if dynamic:
            before=expr[:dynamic[1]];after=expr[dynamic[2]:]
            _,_,_,t=self.declared(path,before)
            if not t or t[0]!='vec':raise Unbound('dynamic index non-vector '+expr)
            ix=self.resolve(path,dynamic[0]);vals=[self.resolve(path,before+f'[{i}]'+after) for i in range(t[1])]
            code=vals[-1].code
            for i,v in reversed(list(enumerate(vals[:-1]))):code=f'({ix.code} == {i} ? {v.code} : {code})'
            return Value(code,vals[0].width,ix.proof+sum([v.proof for v in vals],[]))
        # Traverse child outputs, or parent drives for input/flipped ports.
        rpath,ps=self.locate(path,expr)
        if rpath!=path:return self.resolve(rpath,self.join(ps))
        if expr.startswith('io.') and path:
            parent,_,inst=path.rpartition('.')
            return self.resolve(parent,inst+'.'+expr)
        raise Unbound('no retained member or resolvable exact alias '+path+':'+expr)
    @staticmethod
    def join(ps):return ''.join(p if p.startswith('[') or i==0 else '.'+p for i,p in enumerate(ps))

def specification():
    fields=[]
    def add(target,expr,guard='',required=True,path=BACKEND):fields.append(dict(target=target,expr=expr,guard=guard,required=required,path=path))
    def token(target,expr,guard='',required=True):
        for f in ('index','tag'):add(target+'.'+f,expr+'.'+f,guard,required)
    for name,inst in [('memory','lsu'),('multiplier','multiplier'),('divider','mulDiv')]:
        add(f's.{name}.fire',f'and({inst}.io.start.valid, {inst}.io.start.ready)')
        g=f's.{name}.fire';token(f's.{name}.token',f'{inst}.io.start.bits.token',g)
        if name=='memory':
            for dest,src in [('address','address'),('data','data'),('store','store'),('virtualized','virtualized'),('prechecked','precheckedLoad'),('accessDenied','accessDenied'),('size','size'),('epoch','translationEpoch')]:add(f's.{name}.{dest}',f'{inst}.io.start.bits.{src}',g)
            add('s.memory.destination','lsu.io.issueDestination.bits',g)
        else:
            for f in ('left','right'):add(f's.{name}.{f}',f'{inst}.io.start.bits.{f}',g)
    for target,ref in [('rawLsu','lsu'),('rawDivider','mulDiv'),('rawMultiplier','multiplier'),('rawSystem','systemUnit')]:add('s.'+target,ref+'.io.complete.valid')
    for i in range(4):
        target=f's.lsuOwners[{i}]';slot=f'lsu.slots_{i}'
        add(target+'.live',f'lsu.io.live[{i}]')
        g=target+'.live'
        token(target+'.token',f'lsu.io.owner[{i}]',g)
        for dest,ref in [('phase',f'lsu.io.phase[{i}]'),('cancel',f'lsu.io.cancel[{i}]'),('discard',slot+'.io.discarded'),('complete',f'and({slot}.io.complete.valid, {slot}.io.complete.ready)'),('savedDestinationValid',f'lsu.owners[{i}].valid'),('savedDestination',f'lsu.owners[{i}].bits'),('store',slot+'.operation.store'),('parallel',f'lsu.parallel[{i}]'),('certifiedStore',f'lsu.certifiedStoreClass[{i}]'),('requestAccepted',f'lsu.requestAccepted[{i}]')]:add(target+'.'+dest,ref,g)
        # The per-slot handle is encoded by the exact request assignment to
        # io.memory.request.bits.returnHandle, not guessed from a PA or token.
    for i in range(2):
        t=f's.storePrepare[{i}]';g=t+'.grant'
        add(g,f'orr(and(earlyStorePayloads_1_{i}, grants))')
        token(t+'.token',f'earlyStorePayloads_2[{i}].token',g)
        for f in ('base','immediate','data','dataReady'):add(t+'.'+f,f'earlyStorePayloads_2[{i}].'+f,g)
    add('s.system.fire','and(systemUnit.io.start.valid, systemUnit.io.start.ready)')
    token('s.system.token','systemUnit.io.start.bits.token','s.system.fire')
    for f in ('pc','instruction','operand'):add('s.system.'+f,'systemUnit.io.start.bits.'+f,'s.system.fire')
    add('s.systemProtected','systemProtected');token('s.systemOwner','systemOwner','s.systemProtected')
    add('s.headValid','ledger.io.headValid');add('s.headDone','ledger.io.headDone','s.headValid')
    token('s.head','ledger.io.headSystem.headToken','s.headValid')
    add('s.recovering','ledger.io.recovering')
    for target,base in [('pendingMask','pending'),('preparedMask','storePrepared'),('killedMask','killed')]:add('s.'+target,'cat('+', '.join(f'{base}[{i}]' for i in reversed(range(16)))+')')
    add('s.recovery.accepted','ledger.io.recoveryAccepted')
    token('s.recovery.token','ledger.io.recover.bits.token','s.recovery.accepted')
    add('s.recovery.inclusive','ledger.io.recover.bits.inclusive','s.recovery.accepted')
    add('s.recovery.target','io.redirect.bits.target','s.recovery.accepted')
    for target,ref in [('trap','io.trap'),('pendingException','ledger.io.pendingException')]:
        add('s.'+target+'.valid',ref+'.valid');g='s.'+target+'.valid'
        token('s.'+target+'.token',ref+'.bits.token',g)
        for f in ('pc','cause','tval'):add('s.'+target+'.'+f,ref+'.bits.'+f,g)
    for i in range(2):
        t=f's.retire[{i}]';ref=f'io.commit[{i}]';add(t+'.valid',ref+'.valid');g=t+'.valid'
        token(t+'.token',ref+'.bits.token',g)
        for f,src in [('writes','writesRd'),('pc','pc'),('instruction','instruction'),('data','data'),('nextPc','nextPc'),('rd','rd'),('destination','destination')]:add(t+'.'+f,ref+'.bits.'+src,g,required=(f!='data'))
    # Choose the actual LSU request/response boundary: owners are authoritative
    # here, even when a registered backend request queue delays external traffic.
    for target,ref in [('request','lsu.io.memory.request'),('response','lsu.io.memory.response')]:
        for f in ('valid','ready'):add('s.'+target+'.'+f,ref+'.'+f)
        g='s.'+target+'.valid'
        fs=[('handle','returnHandle'),('data','data')]
        fs += [('write','write'),('atomic','atomic'),('virtualized','virtualized'),('prechecked','precheckedLoad'),('size','size'),('mask','mask'),('address','address'),('epoch','translationEpoch')] if target=='request' else [('error','error'),('pageFault','pageFault')]
        for f,src in fs:add('s.'+target+'.'+f,ref+'.bits.'+src,g)
    add('s.request.ownerValid','lsu.io.requestOwner.valid','s.request.valid')
    token('s.request.token','lsu.io.requestOwner.bits','s.request.valid && s.request.ownerValid')
    for f in ('valid','ready','write','handle','size','address','data'):
        add('s.physicalRequest.'+f,'cpuTagged.physical.'+f,'' if f in ('valid','ready') else 's.physicalRequest.valid',False,path='')
    add('s.physicalRequest.mask','io.physical.request.bits.mask','s.physicalRequest.valid',False,path='board.platform.core.adapter')
    for dest,expr in [('epoch','io.loadPrecheck.epoch'),('contextFlush','io.vmFlush'),('pmpChanged','io.pmpRawChanged'),('satp','io.vmState.satp'),('dataPrivilege','io.vmState.dataPrivilege'),('sum','io.vmState.sum'),('mxr','io.vmState.mxr')]:add('s.'+dest,expr,required=False)
    for i in range(16):
        add(f's.pmpAddress[{i}]',f'io.pmpState.addr[{i}]',required=False)
        add(f's.pmpConfig[{i}]',f'io.pmpState.cfg[{i}]',required=False)
    # Standalone raw event fields retain the reserve/start distinction and saved
    # store-pipeline boundary. Consumers must check their own validity fields.
    for name,ref in [('reserve_memory','reserveMemory'),('reserve_muldiv','reserveMulDiv'),('m_start','mStart'),('head_trap_accepted','ledger.io.headTrap.accepted'),('head_system_accepted','ledger.io.headSystem.accepted'),('ordinary_local_accepted','ordinaryLocalRedirectAccepted'),('local_inclusive','localInclusive'),('memory_busy','io.memoryBusy'),('lsu_busy','lsu.io.busy'),('memory_protected','memoryProtected'),('system_context_barrier','systemContextBarrier')]:add('r.'+name,ref,required=False)
    for i in range(2):
        add(f'r.store_grant_mask_{i}',f'preparedOwners[{i}]',required=False)
        add(f'r.store_captured_mask_{i}',f'capturedOwners[{i}]',required=False)
        for f in ('token.index','token.tag','base','immediate','data','dataReady'):
            add(f'r.store_captured_{i}_'+f.replace('.','_'),f'captured[{i}].'+f,f'r.store_captured_mask_{i} != 0',False)
    return fields

def generate(model):
    b=Binder(model);spec=specification();out=[]
    for f in spec:
        try:
            v=b.resolve(f['path'],f['expr'])
            evidence={json.dumps(x,sort_keys=True):x for x in v.proof}
            out.append(dict(f,status='PROVEN',width=v.width,cpp=v.code,proof=list(evidence.values())))
        except (Unbound,KeyError,ValueError,IndexError) as e:out.append(dict(f,status='UNBOUND',reason=str(e)))
    result={'schema':'b1-retained-a-memory-binding-v1','header_sha256':sha(model/'BoardSocGsim.h'),'fir_sha256':sha(model/'BoardSocGsim.fir'),'generator_sha256':sha(Path(__file__)), 'unobserved_scopes':['Current ROB retirement data (field-specific failure recorded)', 'Final physical full token: requires accepted-handle lineage ledger', 'Pending/canonical/frozen proof lifecycle: deferred by narrowed D1 binding scope; original proof/tagged/PMP gates retained'],'model':str(model),'fields':out,'scope':'Read-only retained-A semantic event binding; source-only. No model/Scala/native build or simulation. Guarded pre-edge snapshot; no NEXT fields. Unbound is never optimized-away evidence.','physical_owner':'Not assigned by binding. Physical adapter handle is sampled; full-token lineage must come from the independent accepted-handle ledger, never PA.', 'request_boundary':'ParallelLoadStoreUnit.io.memory plus its exact io.requestOwner. This is upstream of backend registered request queues; final physical boundary is separately identified.'}
    return result

def emit(result):
    good=[x for x in result['fields'] if x['status']=='PROVEN'];bad=[x for x in result['fields'] if x['status']!='PROVEN' and x['required']]
    out=['#pragma once','#include <cstdint>','#include "events.h"','namespace binding_memory {','using u128 = unsigned __int128;','constexpr u128 mask(unsigned n) { return n >= 128 ? ~u128(0) : (u128(1) << n) - 1; }',f'inline constexpr char header_sha256[] = "{result["header_sha256"]}";',f'inline constexpr char fir_sha256[] = "{result["fir_sha256"]}";',f'inline constexpr bool required_bindings_complete = {str(not bad).lower()};','struct Raw {']
    out += ['    uint64_t '+f['target'][2:]+' = 0;' for f in result['fields'] if f['target'].startswith('r.')]
    out+=['};','inline constexpr bool physical_owner_observed = false;','inline constexpr bool proof_events_observed = false;','template<class Model> inline void sample(const Model& m, b1::Snapshot& s, Raw& r) {','    s.physicalRequest.ownerValid = false;']
    for f in good:
        line=f'    {f["target"]} = uint64_t({f["cpp"]});'
        if f['guard']:line='    if ('+f['guard']+') '+line.strip()
        out.append(line)
    observed={x['target'] for x in good}
    for i in range(2):
        out.append(f'    s.retire[{i}].dataValid = '+(f's.retire[{i}].valid' if f's.retire[{i}].data' in observed else 'false')+';')
    # Exact selected recovery kind follows the accepted head special cases and
    # the source's localInclusive marker (only replay sets it on this config).
    names={x['target'] for x in good}
    if {'r.head_trap_accepted','r.head_system_accepted','r.local_inclusive'}<=names:
        out+=['    if (s.recovery.accepted) s.recovery.kind = r.head_trap_accepted ? b1::RecoveryKind::trap : r.head_system_accepted ? b1::RecoveryKind::system : r.local_inclusive ? b1::RecoveryKind::replay : b1::RecoveryKind::branch;']
    out+=['}','template<class Model> inline void sample(const Model& m, b1::Snapshot& s) { Raw r{}; sample(m,s,r); }','} // namespace binding_memory','']
    return '\n'.join(out)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',type=Path,required=True);p.add_argument('--out',type=Path,default=HERE/'binding_memory_retained_a.json');p.add_argument('--header',type=Path,default=HERE/'binding_memory_retained_a.h');args=p.parse_args()
    result=generate(args.model);args.out.write_text(json.dumps(result,indent=2)+'\n');args.header.write_text(emit(result))
    from collections import Counter
    print(json.dumps({'counts':dict(Counter(x['status'] for x in result['fields'])),'required_unbound':[{k:x[k] for k in ('target','expr','reason')} for x in result['fields'] if x['status']=='UNBOUND' and x['required']],'optional_unbound':[{k:x[k] for k in ('target','expr','reason')} for x in result['fields'] if x['status']=='UNBOUND' and not x['required']]},indent=2))

    if any(f['status'] != 'PROVEN' and f['required'] for f in result['fields']):
        raise SystemExit('required field binding incomplete')
