#!/usr/bin/env python3
"""Insertion-only cycle transcript of the unchanged qualified backend host."""
import hashlib
from pathlib import Path

BASE_SHA = 'd08b915d0bc7d8655744be78d368f9e838977c0ce1e3b79fa645850534f66244'
TRACE = r'''
        // Passive cycle transcript; never used to drive DUT inputs or oracle state.
        std::cout<<"LANE1_BACKEND_TRACE cycle="<<cycle
            <<" occupancy="<<dut.get_io$$occupancy()
            <<" architectural="<<dut.get_io$$committedValue()
            <<" memory_start="<<dut.get_io$$lsuStart()
            <<" response_ready="<<dut.get_io$$physical$$response$$ready();
#define OWNER_TRACE(N) \
        std::cout<<" renamed"<<N<<"="<<dut.get_io$$renamed##N##$$valid(); \
        if(dut.get_io$$renamed##N##$$valid())std::cout<<":"<<dut.get_io$$renamed##N##$$bits$$token$$index()<<":"<<dut.get_io$$renamed##N##$$bits$$token$$tag(); \
        std::cout<<" issued"<<N<<"="<<dut.get_io$$issued##N##$$valid(); \
        if(dut.get_io$$issued##N##$$valid())std::cout<<":"<<dut.get_io$$issued##N##$$bits$$token$$index()<<":"<<dut.get_io$$issued##N##$$bits$$token$$tag()<<":"<<dut.get_io$$issued##N##$$bits$$data()<<":"<<dut.get_io$$issued##N##$$bits$$exception()<<":"<<dut.get_io$$issued##N##$$bits$$cause()<<":"<<dut.get_io$$issued##N##$$bits$$tval(); \
        std::cout<<" commit"<<N<<"="<<dut.get_io$$commit##N##$$valid(); \
        if(dut.get_io$$commit##N##$$valid())std::cout<<":"<<dut.get_io$$commit##N##$$bits$$token$$index()<<":"<<dut.get_io$$commit##N##$$bits$$token$$tag()<<":"<<dut.get_io$$commit##N##$$bits$$data();
        OWNER_TRACE(0);OWNER_TRACE(1);
#undef OWNER_TRACE
        std::cout<<" redirect="<<dut.get_io$$redirect$$valid();
        if(dut.get_io$$redirect$$valid())std::cout<<":"<<dut.get_io$$redirect$$bits$$token$$index()<<":"<<dut.get_io$$redirect$$bits$$token$$tag()<<":"<<dut.get_io$$redirect$$bits$$target();
        std::cout<<" request="<<dut.get_io$$physical$$request$$valid();
        if(dut.get_io$$physical$$request$$valid())std::cout<<":"<<dut.get_io$$physical$$request$$bits$$address()<<":"<<dut.get_io$$physical$$request$$bits$$write()<<":"<<dut.get_io$$physical$$request$$bits$$data();
        std::cout<<'\n';
'''

def render(base):
    assert hashlib.sha256(base.encode()).hexdigest() == BASE_SHA, 'qualified backend host drift'
    anchor = '        if(reset){dut.resetAll();++cycle;return{};}'
    assert base.count(anchor) == 1
    return '// Insertion-only passive transcript of the SHA-bound original host.\n'+base.replace(anchor, anchor+TRACE)

def validate(root):
    root = Path(root)
    base = (root/'simulator/gsim/harness/dual_proof_credit_backend.cpp').read_text()
    actual = (root/'simulator/gsim/harness/lane1_owner_match_backend.cpp').read_text()
    assert actual == render(base), 'passive backend host transform drift'

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[2]
    destination = root/'simulator/gsim/harness/lane1_owner_match_backend.cpp'
    assert not destination.exists(), 'preserve existing host copy'
    destination.write_text(render((root/'simulator/gsim/harness/dual_proof_credit_backend.cpp').read_text()))
    validate(root)
