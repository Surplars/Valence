#!/usr/bin/env python3
"""Compare literal reachable register/RAM declarations, never mapped FPGA PPA."""
import argparse,collections,hashlib,json,re,subprocess,sys,tempfile
from pathlib import Path

def require(ok,why):
    if not ok:raise RuntimeError(why)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def strip(text):
    return re.sub(r'//[^\n]*','',re.sub(r'/\*.*?\*/','',text,flags=re.S))
def declarations(text):
    text=strip(text)
    without_automatic=re.sub(r'\bautomatic\s+logic\b','',text)
    require(not re.search(r'\b(?:logic|integer|int|bit|byte|struct|enum|time|real|shortint|longint)\b',without_automatic),
            'unsupported persistent state declaration')
    scalar=0;arrays=0;records=[]
    rows=re.findall(r'\breg\b\s*(?:\[(\d+):(\d+)\]\s*)?([^;]+);',text)
    require(len(rows)==len(re.findall(r'\breg\b',text)),'unconsumed register declaration')
    for high,low,body in rows:
        require('=' not in body,'initialized register declarations are unsupported')
        width=abs(int(high)-int(low))+1 if high else 1
        for item in body.split('=')[0].strip().split(','):
            item=item.strip();m=re.fullmatch(r'([\w$]+)\s*\[(\d+):(\d+)\]',item)
            if m:
                depth=abs(int(m[2])-int(m[3]))+1;arrays+=width*depth
                records.append({'name':m[1],'width':width,'depth':depth})
            else:
                require(re.fullmatch(r'[\w$]+',item) is not None,'unsupported reg declaration '+item)
                scalar+=width
    return {'scalar_reg_bits':scalar,'array_reg_bits':arrays,'arrays':records}
def structural_instances(text, known):
    """Accept the bounded firtool flat structural grammar; fail closed otherwise."""
    # The only supported parameterized external primitive in these exports.
    # Retain its declaration as an explicit, excluded instance.
    text=re.sub(r'\bBUFGCE\s*#\s*\(\s*\.CE_TYPE\s*\(\s*"SYNC"\s*\)\s*\)\s*(\w+)\s*\(',
                r'BUFGCE \1 (',text)
    text=re.sub(r'\(\*[\s\S]*?\*\)','',text)
    text=re.sub(r'"(?:\\.|[^"\\])*"','""',text)
    require(not re.search(r'\b(?:generate|endgenerate|genvar|parameter|localparam|function|task)\b|#\s*\(',text),
            'unsupported generate/parameterized/function structure')
    header=re.match(r'\s*module\s+\w+\s*\([^;]*\);',text)
    require(header is not None and len(re.findall(r'\bendmodule\b',text))==1,'unsupported module structure')
    body=text[header.end():text.rindex('endmodule')]
    # Every emitted procedural block has an explicit begin/end. Erasing these
    # before parsing structural statements avoids mistaking procedural locals
    # for instances while rejecting implicit/conditional generate constructs.
    while True:
        start=re.search(r'\b(?:always|initial)\b',body)
        if start is None:break
        opening=re.match(r'(?:always\s*@\s*\([^;]*?\)|initial)\s+begin\b',body[start.start():])
        require(opening is not None,'unsupported procedural block form')
        begin=start.start()+opening.end()-len('begin');depth=0;end=None
        for token in re.finditer(r'\b(?:begin|end)\b',body[begin:]):
            depth+=1 if token[0]=='begin' else -1
            if depth==0:end=begin+token.end();break
        require(end is not None,'unterminated procedural block')
        body=body[:start.start()]+re.sub(r'[^\n]',' ',body[start.start():end])+body[end:]
    require(not re.search(r'\b(?:if|else|for|case|endcase|begin|end|always_comb|always_ff|always_latch)\b',body),
            'unsupported conditional/generate structure')
    # Firtool's optional initialization macros do not add structural owners.
    directives=re.findall(r'(?m)^[ \t]*`([^\n]*)',body)
    allowed={'ifdef ENABLE_INITIAL_REG_','ifdef FIRRTL_BEFORE_INITIAL','ifdef FIRRTL_AFTER_INITIAL',
             'FIRRTL_BEFORE_INITIAL','FIRRTL_AFTER_INITIAL','endif'}
    require(all(x.strip() in allowed for x in directives),'unsupported structural preprocessor directive')
    body=re.sub(r'(?m)^[ \t]*`[^\n]*','',body)
    result=[]
    for statement in body.split(';'):
        statement=statement.strip()
        if not statement:continue
        if re.match(r'^(?:wire|reg|assign)\b',statement):continue
        instance=re.fullmatch(r'(\w+)\s+(\w+)\s*(\([\s\S]*\))',statement)
        require(instance is not None,'unsupported structural statement '+statement[:100])
        typ,name,ports=instance.groups();depth=0
        for i,char in enumerate(ports):
            depth+=(char=='(')-(char==')')
            require(depth>0 or (depth==0 and i==len(ports)-1),'unbalanced instance ports')
        require(depth==0,'unbalanced instance ports')
        require(typ in known or typ in ('blk_mem_gen_0','BUFGCE'),'unknown external instance '+typ)
        result.append({'module':typ,'instance':name})
    require(len({x['instance'] for x in result})==len(result),'duplicate structural instance')
    return result

def census(directory):
    directory=Path(directory);receipt=json.loads((directory/'receipt.json').read_text())
    require(receipt['status']=='PASS_RTL_EXPORT_ONLY','completed native export required')
    actual={p.relative_to(directory).as_posix() for p in (directory/'rtl').rglob('*') if p.is_file()}
    require(actual==set(receipt['rtl_sha256']),'native RTL inventory differs from receipt')
    require(all(name=='rtl/filelist.f' or re.fullmatch(r'rtl/[\w.$-]+\.sv',name) for name in actual),'unsupported native RTL path')
    for name,digest in receipt['rtl_sha256'].items():require(sha(directory/name)==digest,'native artifact changed '+name)
    files=sorted((directory/'rtl').glob('*.sv'));modules={}
    for path in files:
        text=strip(path.read_text());names=re.findall(r'^module\s+(\w+)\s*\(',text,re.M)
        require(len(names)==1 and names[0] not in modules,'ambiguous native module '+str(path))
        modules[names[0]]={'file':path.name,'sha256':sha(path),'text':text,**declarations(text)}
    for name,row in modules.items():
        row['children']=structural_instances(row['text'],modules)
    def reachable(top):
        counts=collections.Counter();external=collections.Counter()
        def visit(name,stack):
            require(name not in stack,'recursive hardware hierarchy')
            if name not in modules:external[name]+=1;return
            counts[name]+=1
            for child in modules[name]['children']:visit(child['module'],stack+(name,))
        visit(top,())
        return {'instances':dict(sorted(counts.items())),'excluded_external_instances':dict(sorted(external.items())),
                'scalar_reg_bits':sum(n*modules[k]['scalar_reg_bits'] for k,n in counts.items()),
                'array_reg_bits':sum(n*modules[k]['array_reg_bits'] for k,n in counts.items())}
    result={'receipt_sha256':sha(directory/'receipt.json'),'source_sha256':receipt['source_sha256'],
            'profile':receipt['profile'],'scopes':{x:reachable(x) for x in ('BoardSocTop','IntegerBackend','ParallelLoadStoreUnit','StoreBuffer')},
            'modules':{k:{x:y for x,y in v.items() if x!='text'} for k,v in modules.items()}}
    expected=receipt['profile']['lsu_entries'];lsu=modules['ParallelLoadStoreUnit']
    slots=[p for p in lsu['children'] if p['instance'].startswith('slots_')]
    require(sorted(p['instance'] for p in slots)==['slots_'+str(i) for i in range(expected)],'emitted LSU owner geometry mismatch')
    require(all(p['module']=='LoadStoreUnit' for p in slots),'unexpected owner implementation')
    result['lsu_primitive_scalar_bits']=modules['LoadStoreUnit']['scalar_reg_bits']
    return result

def validate_storage_report(reported,recomputed):
    require(reported==recomputed,'fixed-storage report differs from fresh independent census')

def fresh_storage(directory):
    tool=Path(__file__).with_name('native_storage_census.py');before=sha(tool)
    with tempfile.TemporaryDirectory(prefix='valence-storage-census-') as temporary:
        output=Path(temporary)/'storage.json'
        command=[sys.executable,'-B',str(tool),'--rtl',str(Path(directory)/'rtl'),'--output',str(output)]
        result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=30)
        require(result.returncode==0,'fresh fixed-storage census failed: '+result.stdout)
        require(sha(tool)==before,'fixed-storage tool changed while running')
        return json.loads(output.read_text())


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--two',required=True,type=Path);ap.add_argument('--four',required=True,type=Path);ap.add_argument('--out',required=True,type=Path);ap.add_argument('--two-storage',required=True,type=Path);ap.add_argument('--four-storage',required=True,type=Path);args=ap.parse_args()
    a,b=census(args.two),census(args.four)
    require(a['profile']['lsu_entries']==2 and b['profile']['lsu_entries']==4,'explicit LSU2/4 pair required')
    require(a['source_sha256']==b['source_sha256'],'different native source inventories')
    require({k:v for k,v in a['profile'].items() if k not in ('name','lsu_entries')}==
            {k:v for k,v in b['profile'].items() if k not in ('name','lsu_entries')},'unrelated profile dimension changed')
    for scope in a['scopes']:
        require(a['scopes'][scope]['excluded_external_instances']==b['scopes'][scope]['excluded_external_instances'],'external IP multiplicity changed')
    for wrapper in ('InstructionRom','ManagedClockBuffer'):
        require(a['modules'][wrapper]['sha256']==b['modules'][wrapper]['sha256'],'external IP wrapper changed '+wrapper)
    storage={}
    for label,path,directory,export in (('lsu2',args.two_storage,args.two,a),('lsu4',args.four_storage,args.four,b)):
        row=json.loads(path.read_text())
        validate_storage_report(row,fresh_storage(directory))
        require(row['status']=='PASS_SELECTED_NATIVE_STORAGE_CENSUS' and row['export_receipt_sha256']==export['receipt_sha256'],
                'fixed-storage receipt/export mismatch')
        require(len(row['groups'])==10,'fixed-storage contract inventory mismatch')
        for group in row['groups'].values():
            require(group['parent_sha256']==export['modules'][group['parent']]['sha256'],'fixed-storage parent drift')
            for bank in group['banks']:
                require(bank['helper_sha256']==export['modules'][bank['module']]['sha256'],'fixed-storage helper drift')
        storage[label]={'receipt_sha256':sha(path),'groups':row['groups']}
    require(storage['lsu2']['groups']==storage['lsu4']['groups'],'fixed-storage groups changed')
    result={'status':'PASS_LITERAL_REACHABLE_LSU_CAPACITY_CENSUS','tool_sha256':sha(__file__),
        'fixed_storage_tool_sha256':sha(Path(__file__).with_name('native_storage_census.py')),'fresh_fixed_storage_runs':2,'fixed_storage':storage,'exports':{'lsu2':a,'lsu4':b},
        'delta':{scope:{kind:b['scopes'][scope][kind]-a['scopes'][scope][kind] for kind in ('scalar_reg_bits','array_reg_bits')} for scope in a['scopes']},
        'limits':['External blk_mem_gen_0 ROM and BUFGCE clock primitive state is excluded; identical wrappers and instance multiplicities are checked.','Source-level reachable declaration counts; arrays may map to registers, LUTRAM, BRAM or be optimized.','Hierarchy weighted once per explicit emitted instance; no mapped cell/resource/100MHz timing claim.','Fixed memory port/storage contracts are separately checked by native_storage_census.py.']}
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n');print(result['status'],json.dumps(result['delta']))
if __name__=='__main__':main()
