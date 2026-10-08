#!/usr/bin/env python3
"""Scoped combinational native-SV audit for the packed I-cache SRAM address/enable."""
import re
import hashlib
import json

def port_expression(block, port):
    start=re.search(r'\.'+re.escape(port)+r'\s*\(',block)
    assert start,port
    pos=start.end();depth=1;end=pos
    while depth:
        assert end<len(block),'unbalanced native port expression'
        depth+=(block[end]=='(')-(block[end]==')');end+=1
    return block[pos:end-1]

def ports(text):
    header=text.split(');',1)[0]
    header=re.sub(r'/\*.*?\*/|//[^\n]*','',header,flags=re.S)
    header=header[header.index('(')+1:]
    direction=None;result={}
    for item in header.split(','):
        found=re.search(r'\b(input|output|inout)\b',item)
        if found:direction=found.group(1)
        clean=re.sub(r'\[[^\]]+\]','',item)
        names=[n for n in re.findall(r'[A-Za-z_$][\w$]*',clean)
            if n not in {'input','output','inout','wire','logic','reg','signed','unsigned'}]
        assert direction and len(names)==1, ('unsupported normalized port declaration',item)
        result[names[0]]=direction
    return result

def cone(expression,definitions,legal_leaves):
    expanded=[];leaves=set()
    def visit(value,path=frozenset()):
        expanded.append(value)
        clean=re.sub(r"\b\d+'[sS]?[hHdDbBoO][0-9a-fA-F_xXzZ?]+",'',value)
        for token in re.findall(r'[A-Za-z_$][\w$]*',clean):
            if token in definitions and token not in legal_leaves:
                assert token not in path, 'combinational cycle: '+token
                visit(definitions[token],path|{token})
            else:
                assert token in legal_leaves, 'unresolved internal alias: '+token
                leaves.add(token)
    visit(expression)
    return '\n'.join(expanded), sorted(leaves)

def audit(text, independent, module_sources):
    text=re.sub(r'//[^\n]*','',re.sub(r'/\*.*?\*/','',text,flags=re.S))
    definitions={}
    for name,expr in re.findall(r'\b(?:wire|logic)\s+(?:\[[^\]]+\]\s*)*([A-Za-z_$][\w$]*)\s*=\s*(.*?);',text,re.S)+re.findall(r'\bassign\s+([A-Za-z_$][\w$]*)\s*=\s*(.*?);',text,re.S):
        assert name not in definitions or definitions[name]==expr, 'ambiguous combinational assignment: '+name
        definitions[name]=expr
    registers=set(re.findall(r'^\s*reg\s+(?:\[[^\]]+\]\s*)*([A-Za-z_$][\w$]*)',text,re.M))
    inputs={name for name,direction in ports(text).items() if direction=='input'}
    child_outputs=set()
    for kind,instance,block in re.findall(r'^[ \t]*(?!(?:module|else|priority|unique)\b)([A-Za-z_$][\w$]*)[ \t]+([A-Za-z_$][\w$]*)\s*\((.*?)\);',text,re.M|re.S):
        if kind in {'module','else','priority','unique'}:continue
        assert kind in module_sources, 'unresolved child module declaration: '+kind
        declared=re.search(r'\bmodule\s+([A-Za-z_$][\w$]*)\s*\(',module_sources[kind])
        assert declared and declared.group(1)==kind, 'child module identity mismatch: '+kind
        for port,direction in ports(module_sources[kind]).items():
            if direction!='output' or not re.search(r'\.'+re.escape(port)+r'\s*\(',block):continue
            value=port_expression(block,port).strip()
            if not value:continue
            assert re.fullmatch(r'[A-Za-z_$][\w$]*',value), ('unsupported normalized child output connection',instance,port,value)
            child_outputs.add(value)
    legal_leaves=registers|inputs|child_outputs
    blocks=re.findall(r'\bdataBanks_512x64\s+dataBanks_\d+_ext\s*\((.*?)\);',text,re.S)
    assert len(blocks)==8,'expected eight reachable packed data-bank instances'
    rows=[]
    for i,block in enumerate(blocks):
        address,address_leaves=cone(port_expression(block,'R0_addr'),definitions,legal_leaves)
        enable,enable_leaves=cone(port_expression(block,'R0_en'),definitions,legal_leaves)
        slices=[(int(hi),int(lo or hi)) for hi,lo in re.findall(r'io_fetch_request_bits\[(\d+)(?::(\d+))?\]',address)]
        assert slices,'no physical request address reached packed SRAM'
        has_invalidate=bool(re.search(r'\bio_invalidate\b',address))
        assert bool(re.search(r'\bio_invalidate\b',enable)), 'SRAM read enable lost invalidation qualification'
        assert '_pmp_io_denied' in enable,'SRAM read enable lost PMP qualification'
        if independent:
            assert not has_invalidate,'independent RAM address retains invalidation cone'
            assert max(hi for hi,_ in slices)<=32,'independent RAM address retains aperture-prefix qualification'
            assert '_pmp_io_denied' not in address,'independent RAM address acquired PMP cone'
        else:
            assert has_invalidate and max(hi for hi,_ in slices)==63,'reference no longer has expected qualified address'
        rows.append({'bank':i,'address_has_invalidate':has_invalidate,'address_max_request_bit':max(hi for hi,_ in slices),
            'read_enable_has_invalidate':True,'read_enable_has_pmp':True,
            'address_leaves':address_leaves,'enable_leaves':enable_leaves})
    return {'status':'PASS_SCOPED_NATIVE_ADDRESS_CONE','independent':independent,'banks':rows,
        'scope':'Combinational expressions in InstructionLineCache only; register and memory outputs are leaves. No routed timing/physical path claim.'}

def checked_audit(text,independent,module_sources):
    result=audit(text,independent,module_sources)
    if independent:
        bad=re.sub(r'(wire\s+\[8:0\]\s+hitPacket_readIndex\s*=)(.*?);',
            r'\1 (\2) & {9{~io_invalidate}};',text,flags=re.S)
        assert bad!=text,'address-cone negative control could not find its target'
        try:audit(bad,True,module_sources)
        except AssertionError:pass
        else:raise AssertionError('address-cone negative control escaped')
        bad=re.sub(r'(\.R0_en\s*\()(.*?)(\),)',lambda m: m[1]+"1'h1"+m[3],text,flags=re.S)
        try:audit(bad,True,module_sources)
        except AssertionError:pass
        else:raise AssertionError('enable-qualification negative control escaped')
        bad=re.sub(r'(wire\s+\[8:0\]\s+)hitPacket_readIndex(\s*=)',r'\1hitPacket_readIndex_missing\2',text,count=1)
        assert bad!=text,'unresolved-alias mutation missed its target'
        try:audit(bad,True,module_sources)
        except AssertionError as error:assert 'unresolved internal alias: hitPacket_readIndex' in str(error)
        else:raise AssertionError('unresolved-alias negative control escaped')
        result['negative_controls']=['restored address invalidate rejected','removed read-enable qualification rejected',
            'unresolved internal alias rejected']
    sets={}
    for bank in result['banks']:
        for field in ('address_leaves','enable_leaves'):
            members=bank.pop(field);key=hashlib.sha256(json.dumps(members,separators=(',',':')).encode()).hexdigest()
            sets[key]=members;bank[field.replace('_leaves','_dependency_set')]=key
    result['dependency_sets']=sets
    return result
