#!/usr/bin/env python3
"""Generate source-bound rename, held-stage, accepted completion and PRF readers."""
import argparse,json
from pathlib import Path
from binding_memory_generate import Binder,BACKEND,HERE,sha,Unbound

def specification():
    fields=[]
    def add(target,expr,guard='',required=True):fields.append(dict(target=target,expr=expr,path=BACKEND,guard=guard,required=required))
    for i in range(2):
        t=f's.rename[{i}]';ref=f'ledger.io.renamed[{i}]';add(t+'.valid',ref+'.valid');g=t+'.valid'
        for dest,src in [('token.index','token.index'),('token.tag','token.tag'),('source1','source1'),('source2','source2'),('destination','destination'),('oldDestination','oldDestination'),('writes','writesRd'),('moveAlias','moveAlias')]:add(t+'.'+dest,ref+'.bits.'+src,g)
        for f in ('pc','instruction','rd'):add(t+'.'+f,f'io.allocate[{i}].bits.rename.'+f,g)
        t=f's.stage[{i}]';stage=f'executionStages_{i}';old=f'executingOperands_{i}'
        for dest,src in [('occupied','occupied'),('cancel','cancel'),('enqValid','enq.valid'),('enqReady','enq.ready'),('deqValid','deq.valid'),('deqReady','deq.ready')]:add(t+'.'+dest,stage+'.io.'+src)
        g=t+'.occupied'
        for dest,src in [('held.index','entry.renamed.token.index'),('held.tag','entry.renamed.token.tag'),('destination','entry.renamed.destination'),('heldSource1','entry.renamed.source1'),('heldSource2','entry.renamed.source2'),('source1','entry.renamed.source1'),('source2','entry.renamed.source2'),('left','left'),('right','right'),('forwardable','forwardable'),('heldUsePc','entry.request.usePc'),('heldUseImmediate','entry.request.useImmediate')]:add(t+'.'+dest,old+'.'+src,g)
        add(t+'.result',f'executionData[{i}]',g);add(t+'.promise',f'executionWake[{i}].valid');add(t+'.promiseDestination',f'executionWake[{i}].bits',t+'.promise')
        t=f's.complete[{i}]';ref=f'ledger.io.complete[{i}]';add(t+'.valid',ref+'.valid');add(t+'.accepted',f'ledger.io.completionAccepted[{i}]');g=t+'.valid'
        for f in ('token.index','token.tag','exception','data','nextPc','cause','tval'):add(t+'.'+f,ref+'.bits.'+f,g)
        t=f's.prfWrite[{i}]';ref=f'physicalWrites[{i}]';add(t+'.valid',ref+'.valid')
        for dest,src in [('destination','address'),('data','data')]:add(t+'.'+dest,ref+'.bits.'+src,t+'.valid')
        for name in ('wake','reserve'):
            t=f's.{name}[{i}]';ref=f'readyUpdate.io.{name}[{i}]';add(t+'.valid',ref+'.valid');add(t+'.destination',ref+'.bits',t+'.valid')
    add('selected_class_mask','payload_1.selected')
    for i in range(48):
        add(f's.ready[{i}]',f'ready[{i}]')
        # Exact asynchronous PRF read law of OwnerBankedPhysicalRegisterFile:
        # x0/uninitialized=>0, otherwise current last-writer bank; no bypass.
        add(f's.physical[{i}]',f'mux(and(neq(UInt<6>(0h{i:x}), UInt<6>(0h0)), physicalFile.initialized[{i}]), mux(physicalFile.owner[{i}], physicalFile.banks_1[{i}], physicalFile.banks_0[{i}]), UInt<64>(0h0))')
    return fields

def generate(model):
    b=Binder(model);out=[]
    for f in specification():
        try:
            v=b.resolve(f['path'],f['expr']);e={json.dumps(x,sort_keys=True):x for x in v.proof}
            out.append(dict(f,status='PROVEN',width=v.width,cpp=v.code,proof=list(e.values())))
        except (Unbound,KeyError,ValueError,IndexError) as e:out.append(dict(f,status='UNBOUND',reason=str(e)))
    return dict(schema='b1-retained-a-core-binding-v1',header_sha256=sha(model/'BoardSocGsim.h'),fir_sha256=sha(model/'BoardSocGsim.fir'),generator_sha256=sha(Path(__file__)),resolver_sha256=sha(HERE/'binding_memory_generate.py'),fields=out,physical_capacity=48,capture_contract='Capture is pre-edge enq.valid && enq.ready followed by next settled occupied held payload. No incoming payload fabricated.',scope='Read-only source-bound retained-A snapshot; no simulation or build.')

def emit(result, memory_include="binding_memory_retained_a.h"):
    good=[f for f in result['fields'] if f['status']=='PROVEN'];bad=[f for f in result['fields'] if f['status']=='UNBOUND']
    out=['#pragma once','#include "'+memory_include+'"','namespace binding_core {','using binding_memory::u128; using binding_memory::mask;',f'inline constexpr bool required_bindings_complete = {str(not bad).lower()};','template<class Model> inline void sample(const Model& m, b1::Snapshot& s) {', '    uint64_t selected_class_mask = 0;']
    for f in good:
        line=f'{f["target"]} = uint64_t({f["cpp"]});'
        out.append('    '+('if ('+f['guard']+') ' if f['guard'] else '')+line)
    out+=['    if (s.complete[0].valid) s.complete[0].producer = (selected_class_mask & 1) ? b1::Producer::lsu : (selected_class_mask & 2) ? b1::Producer::divider : (selected_class_mask & 4) ? b1::Producer::multiplier : (selected_class_mask & 8) ? b1::Producer::system : (selected_class_mask & 16) ? b1::Producer::heldBranch : b1::Producer::execution0;','    if (s.complete[1].valid) s.complete[1].producer = b1::Producer::execution1;','}','} // namespace binding_core','']
    return '\n'.join(out)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--model',type=Path,required=True);p.add_argument('--out',type=Path,default=HERE/'binding_memory_core_retained_a.json');p.add_argument('--header',type=Path,default=HERE/'binding_memory_core_retained_a.h');p.add_argument('--memory-include',default='binding_memory_retained_a.h');args=p.parse_args();r=generate(args.model)
    args.out.write_text(json.dumps(r,indent=2)+'\n');args.header.write_text(emit(r,args.memory_include))
    print(json.dumps({'proven':sum(x['status']=='PROVEN' for x in r['fields']),'unbound':[{k:x[k] for k in ('target','expr','reason')} for x in r['fields'] if x['status']=='UNBOUND']},indent=2))

    if any(f['status'] != 'PROVEN' and f['required'] for f in r['fields']):
        raise SystemExit('required field binding incomplete')
