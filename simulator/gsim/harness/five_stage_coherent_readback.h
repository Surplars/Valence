#pragma once

#ifdef I1_COHERENT_READBACK
// Real coherent agent. Dirty data must be returned via ProbeAckData, written
// back and acknowledged before the uncached read can complete.
static void i1CoherentHostIdle(SFiveStageSoc &d) {
    d.set_io$$networkMemory$$request$$valid(0);
    d.set_io$$networkMemory$$response$$ready(1);
}
static uint64_t coherentRead(SFiveStageSoc &d, AxiMemory &memory, uint64_t &cycle, uint64_t offset) {
    bool accepted = false;
    d.set_io$$networkMemory$$response$$ready(1);
    d.set_io$$networkMemory$$request$$bits$$address(0x80200000ULL + offset);
    d.set_io$$networkMemory$$request$$bits$$write(0);
    d.set_io$$networkMemory$$request$$bits$$data(0);
    d.set_io$$networkMemory$$request$$bits$$byteEnable(255);
    d.set_io$$networkMemory$$request$$bits$$size(3);
    for (unsigned i = 0; i < 10000; ++i) {
        d.set_io$$networkMemory$$request$$valid(!accepted);
        memory.inputs(cycle); d.step(); memory.outputs(cycle++);
        if (!accepted && d.get_io$$networkMemory$$request$$ready()) accepted = true;
        if (d.get_io$$networkMemory$$response$$valid()) {
            need(accepted && !d.get_io$$networkMemory$$response$$bits$$error(),
                 "independent coherent readback transaction");
            auto data = d.get_io$$networkMemory$$response$$bits$$data();
            i1CoherentHostIdle(d);
            return data;
        }
    }
    throw std::runtime_error("coherent readback bounded completion");
}
#else
static void i1CoherentHostIdle(SFiveStageSoc &) {}
#endif
