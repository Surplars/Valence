#!/usr/bin/env python3
"""Count complete CHIRRTL register types and memory ports by instance. Not mapped PPA."""
import argparse,hashlib,json,re
from pathlib import Path

def fields(s):
    out=[];depth=0;begin=0
    for i,c in enumerate(s):
        depth+=c in '{[';depth-=c in '}]'
        if c==',' and depth==0:out.append(s[begin:i].strip());begin=i+1
    out.append(s[begin:].strip());return out

def bits(t):
    t=t.strip();factor=1
    while (m:=re.search(r'\[(\d+)\]$',t)):
        factor*=int(m[1]);t=t[:m.start()].strip()
    if t.startswith('{'):
        assert t.endswith('}'),t
        return factor*sum(bits(x.split(':',1)[1]) for x in fields(t[1:-1]))
    m=re.fullmatch(r'(?:UInt|SInt|Analog)<(\d+)>',t)
    if m:return factor*int(m[1])
    if t in ['Clock','Reset','AsyncReset']:return factor
    raise ValueError('Uncounted register/memory type '+t)

def inspect(p):
    text=p.read_text();definitions={}
    for m in re.finditer(r'^  (?:public )?module (\w+) :.*?(?=^  (?:public )?(?:module|extmodule) |\Z)',text,re.M|re.S):
        name=m[1];s=m[0]
        regs={r[1]:r[2] for r in re.finditer(r'^\s+(?:reg|regreset) (\w+) : (.+?), clock(?:\s|,|$)',s,re.M)}
        mems={r[1]:r[2] for r in re.finditer(r'^\s+[cs]mem (\w+) : (.+?)(?: @\[|$)',s,re.M)}
        ports=[line.strip().split(' @[')[0] for line in s.splitlines() if re.match(r'\s+(?:read|write|rdwr) mport ',line)]
        definitions[name]={'register_types':regs,'register_bits':sum(map(bits,regs.values())),'memory_types':mems,'memory_bits':sum(map(bits,mems.values())),'ports':ports,'instances':re.findall(r'^\s+inst (\w+) of (\w+)',s,re.M)}
    instances={}
    def visit(path,name):
        d=definitions[name];instances[path]={'module':name,**{k:v for k,v in d.items() if k!='instances'}}
        for child,typ in d['instances']:visit(path+'.'+child,typ)
    visit('top','DmaPipelineGsim')
    return {'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'instances':instances,'total_register_bits':sum(x['register_bits'] for x in instances.values()),'total_memory_bits':sum(x['memory_bits'] for x in instances.values()),'total_memory_ports':sum(len(x['ports']) for x in instances.values())}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    old,new=inspect(a.baseline),inspect(a.candidate);assert old['instances'].keys()==new['instances'].keys(),'Instance structure changed: review explicitly'
    changes={}
    for k,x in old['instances'].items():
        y=new['instances'][k]
        if any(x[field]!=y[field] for field in ['register_types','memory_types','ports']):
            changes[k]={'old_register_bits':x['register_bits'],'new_register_bits':y['register_bits'],'register_bits_delta':y['register_bits']-x['register_bits'],'memory_types_equal':x['memory_types']==y['memory_types'],'memory_ports':[len(x['ports']),len(y['ports'])],'changed_registers':{n:[x['register_types'].get(n),y['register_types'].get(n)] for n in sorted(x['register_types'].keys()|y['register_types'].keys()) if x['register_types'].get(n)!=y['register_types'].get(n)}}
    report={'status':'PASS_COMPLETE_CHIRRTL_DECLARATION_COUNT','not_measured':['mapped LUT/FF/BRAM','routed timing','Fmax','CDC'],'baseline':old,'candidate':new,'register_bits_delta':new['total_register_bits']-old['total_register_bits'],'memory_bits_delta':new['total_memory_bits']-old['total_memory_bits'],'memory_ports_delta':new['total_memory_ports']-old['total_memory_ports'],'changed_instances':changes}
    a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k] for k in ['status','register_bits_delta','memory_bits_delta','memory_ports_delta']}))
if __name__=='__main__':main()
