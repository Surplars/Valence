#pragma once
// Test-only writes to both simulated synchronous ROM banks while the CPU is held reset.
// Physical RTL has readmemh initialization and no host initialization port.
inline void i1InitializeRom(SFiveStageSoc &d, AxiMemory &memory, const char *path) {
#if I1_HAS_ROM
    std::ifstream rom(path); need(bool(rom), "missing exact BootROM initialization");
    d.set_io$$romInitialize$$valid(1);
    uint64_t word;
    for (unsigned n = 0; n < 512; ++n) {
        need(bool(rom >> std::hex >> word), "short BootROM initialization");
        d.set_io$$romInitialize$$bits$$index(n); d.set_io$$romInitialize$$bits$$data(word);
        memory.inputs(0); d.step();
    }
    need(!(rom >> std::hex >> word), "overlong BootROM initialization");
    d.set_io$$romInitialize$$valid(0);
#else
    (void)d; (void)memory; (void)path;
#endif
}
