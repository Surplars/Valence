#!/usr/bin/env python3
"""Insertion-only full registered-stage observation on the bound decoded backend oracle."""
import hashlib
from pathlib import Path
BASE_SHA='e3e59ad7bd92b2867e4ff790643dcb7d007480dde42703a405b89cf8aed7bbbb'

def render(base):
    assert hashlib.sha256(base.encode()).hexdigest()==BASE_SHA, 'qualified host drift'
    text=base.replace('PendingStoreProofBackendGsim', 'RegisteredExecutionOperandsBackendGsim')
    lines=['', '        // Compare all held bits even when invalid; input operands only on valid offers.']
    for lane in range(2):
        prefix=f'dut.get_observation{lane}$$'
        lines += [f'        std::cout<<"EXECUTION_STAGE_TRACE cycle="<<cycle<<" lane={lane}"']
        for field in ['enqValid','enqReady','deqValid','deqReady','occupied','cancel','incomingMemory','incomingStore','prepared']:
            lines += [f'            <<" {field}="<<{prefix}{field}()']
        for word in range(10):lines += [f'            <<" held{word}="<<{prefix}heldWord{word}()']
        lines[-1]+=';'
        lines += [f'        if({prefix}enqValid()) {{']
        for word in range(10):lines += [f'            std::cout<<" input{word}="<<{prefix}inputWord{word}();']
        lines += ['        }', "        std::cout<<'\\n';"]
    anchor='        if(reset){dut.resetAll();++cycle;return{};}'
    assert text.count(anchor)==1
    return text.replace(anchor,anchor+'\n'.join(lines)+'\n')

def validate(root):
    root=Path(root)
    base=(root/'simulator/gsim/harness/lane1_owner_match_backend.cpp').read_text()
    actual=(root/'simulator/gsim/harness/registered_execution_operands_backend.cpp').read_text()
    assert actual==render(base), 'observer host drift'

if __name__=='__main__':
    root=Path(__file__).resolve().parents[2]
    target=root/'simulator/gsim/harness/registered_execution_operands_backend.cpp'
    assert not target.exists()
    target.write_text(render((root/'simulator/gsim/harness/lane1_owner_match_backend.cpp').read_text()))
    validate(root)
