"""Cycle-exact public-port parity, excluding only payloads without valid offers."""
import gzip,json,pathlib,sys,hashlib

def output_gate(key):
    if '.bits.' in key:
        return key.split('.bits.',1)[0]+'.valid'
    if key.startswith('lineGrantBits.'):return 'lineGrantValid'
    if key=='logicalReadAddress':return 'logicalRead'
    for c in 'ABCDE':
        if key.startswith('mon'+c) and key not in ('mon'+c+'Valid','mon'+c+'Ready'):return 'mon'+c+'Valid'
    if key.startswith('refillEvent.') or key=='refillError' or key.startswith('refillWord'):return 'refillValid'
    if key.startswith('installedEvent.'):return 'installedValid'
    if key.startswith('installWord') or key in ('lineWritePosted','lineWriteAddress'):return 'lineWrite'
    return None

def input_gate(key):
    if '.bits.' in key:return key.split('.bits.',1)[0]+'.valid'
    return None

def project(row):
    ins=row['inputs'];outs=row['outputs'];p={'cycle':row['cycle'],'inputs':{},'outputs':{}}
    for label,values,fn in [('inputs',ins,input_gate),('outputs',outs,output_gate)]:
        for key,value in values.items():
            gate=fn(key)
            if gate is not None:
                assert gate in values,(label,key,'missing valid selector',gate)
                if not values[gate]:continue
            p[label][key]=value
    return p

def compare(a,b):
    count=0;payload_count=0;dig=hashlib.sha256()
    import itertools
    with gzip.open(a,'rt') as x,gzip.open(b,'rt') as y:
        for left,right in itertools.zip_longest(x,y):
            assert left is not None and right is not None,'trace length mismatch'
            p=project(json.loads(left));q=project(json.loads(right));assert p==q,dict(cycle=p['cycle'],differences=[(side,k,p[side].get(k),q[side].get(k)) for side in ['inputs','outputs'] for k in sorted(set(p[side])|set(q[side])) if p[side].get(k)!=q[side].get(k)])
            count+=1;payload_count+=len(p['outputs']);dig.update((json.dumps(p,sort_keys=True,separators=(',',':'))+'\n').encode())
    assert count>0
    return dict(equal=True,cycles=count,compared_output_values=payload_count,canonical_sha256=dig.hexdigest(),scope='all cycle-stamped public values; payload excluded only while its valid selector is false')
if __name__=='__main__':print(json.dumps(compare(pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[2])),indent=2))
