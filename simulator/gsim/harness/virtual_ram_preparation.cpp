#include "VirtualRamPreparationGsim.h"
#include "virtual_load_test_memory.h"
#include <iostream>
#include <string>
#include <vector>
using namespace virtual_load_test;
struct Sample {
    bool candidate = false, response = false, stable = true, flush = false;
    uint64_t tag = 0x123456789abcdef0ULL, address = va + 24, physical = ram + 24;
    unsigned index = 3, size = 3, epoch = 7, responseEpoch = 7, pbmt = 0, cfg = 0x1f, privilege = 1;
};
struct Result { bool valid = false, allowed = false; uint64_t tag = 0, address = 0, physical = 0; unsigned index = 0, size = 0, epoch = 0; };
class Bench {
    SVirtualRamPreparationGsim d;
public:
    unsigned cycle = 0;
    bool inject = false;
    Bench() { drive({}); d.set_reset(1); d.step(); d.step(); d.set_reset(0); tick({}); }
    void drive(const Sample &s) {
        d.set_io$$candidate$$valid(s.candidate); d.set_io$$candidate$$bits$$token$$index(s.index);
        d.set_io$$candidate$$bits$$token$$tag(s.tag); d.set_io$$candidate$$bits$$address(s.address);
        d.set_io$$candidate$$bits$$size(s.size);
        d.set_io$$precheck$$response$$valid(s.response);
        d.set_io$$precheck$$response$$bits$$physicalAddress(s.physical);
        d.set_io$$precheck$$response$$bits$$pbmt(s.pbmt);
        d.set_io$$precheck$$response$$bits$$epoch(s.responseEpoch);
        d.set_io$$precheck$$epoch(s.epoch); d.set_io$$precheck$$stable(s.stable);
        d.set_io$$pmpCfg(s.cfg); d.set_io$$pmpAddress(allPmp);
        d.set_io$$privilege(s.privilege); d.set_io$$flush(s.flush);
    }
    Result tick(const Sample &s) {
        drive(s); d.step(); ++cycle;
        if (d.get_io$$precheck$$request$$valid())
            require(s.candidate && !s.flush && d.get_io$$precheck$$request$$bits$$address() == s.address &&
                d.get_io$$precheck$$request$$bits$$size() == s.size, "candidate peek ownership mismatch");
        return {bool(d.get_io$$prepared$$valid()), bool(d.get_io$$prepared$$bits$$allowed()),
            uint64_t(d.get_io$$prepared$$bits$$token$$tag()), uint64_t(d.get_io$$prepared$$bits$$address()),
            uint64_t(d.get_io$$prepared$$bits$$physicalAddress()), unsigned(d.get_io$$prepared$$bits$$token$$index()),
            unsigned(d.get_io$$prepared$$bits$$size()), unsigned(d.get_io$$prepared$$bits$$epoch())};
    }
    void pulse(Sample s, bool expectedAllowed, bool expectedCertificate = true) {
        Sample quiet = s; quiet.candidate = quiet.response = false;
        quiet.flush = true; tick(quiet); quiet.flush = false; tick(quiet); tick(quiet);
        s.candidate = true;
        auto r0 = tick(s); auto r1 = tick(quiet); auto r2 = tick(quiet);
        require(!r0.valid && !r1.valid, "certificate bypassed a register boundary");
        require(r2.valid == expectedCertificate, "two-stage certificate latency/valid mismatch");
        if (expectedCertificate) require(r2.allowed == (expectedAllowed ^ inject) && r2.tag == s.tag &&
            r2.index == s.index && r2.address == s.address && (!s.response || r2.physical == s.physical) &&
            r2.size == s.size && r2.epoch == s.epoch, "independent certificate payload/permission mismatch");
    }
};
int main(int argc, char **argv) { try {
    Bench b; b.inject = argc > 1 && std::string(argv[1]) == "--inject-allowed";
    Sample s; s.response = true;
    b.pulse(s, true);
    for (unsigned size = 0; size < 4; ++size) {
        s.size = size; s.address = va + 32; s.physical = ram + 32; b.pulse(s, true);
        if (size) { s.address += 1; s.physical += 1; b.pulse(s, false); }
    }
    s.size = 3; s.address = va + 24; s.physical = ram + 24;
    s.pbmt = 1; b.pulse(s, false); s.pbmt = 2; b.pulse(s, false); s.pbmt = 0;
    s.physical = 0x10000000ULL; b.pulse(s, false);
    s.physical = ram + ramBytes; b.pulse(s, false);
    s.physical = ram + ramBytes - 8; s.address = va + 4088; b.pulse(s, true);
    s.physical = ram + ramBytes - 4; s.address = va + 4092; b.pulse(s, false);
    s.physical = ram + 24; s.address = va + 25; b.pulse(s, false);
    s.address = va + 24; s.physical = ram + 25; b.pulse(s, false);
    s.physical = ram + 24; s.cfg = 0x18; b.pulse(s, false);
    s.cfg = 0x98; s.privilege = 3; b.pulse(s, false);
    s.cfg = 0x1f; s.privilege = 1;
    s.response = false; b.pulse(s, false); s.response = true;
    s.stable = false; b.pulse(s, false, false); s.stable = true;
    s.responseEpoch = 6; b.pulse(s, false, false); s.responseEpoch = 7;
    // The generation portion of a reused ROB slot must cross both stages intact.
    for (uint64_t tag : {0ULL, 1ULL, 0x100000001ULL, 0xffffffffffffffffULL}) {
        s.tag = tag; b.pulse(s, true);
    }
    // Revocation between raw-hit capture and authorization must not produce an allowed certificate.
    for (unsigned cut : {1U, 2U}) {
        Sample q = s; q.candidate = q.response = false; q.flush = true; b.tick(q); q.flush = false; b.tick(q); b.tick(q);
        s.candidate = true; b.tick(s);
        for (unsigned n = 1; n <= 4; ++n) {
            q.flush = n == cut;
            auto r = b.tick(q);
            require(!r.valid || !r.allowed, "flush preserved usable in-flight certificate");
        }
    }
    std::cout << "VIRTUAL_RAM_PREPARATION_PASS register_cuts=2 permission_and_range=1 token_width=64 flush_cuts=2\n";
    return 0;
} catch (const std::exception &e) { std::cerr << "VIRTUAL_RAM_PREPARATION_FAIL " << e.what() << "\n"; return 1; } }
