#include "JtagBootGsim.h"
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static constexpr uint64_t romBase = 0x80000000ULL, ramBase = 0x80020000ULL;
static std::vector<uint8_t> readFile(const char *path) {
    std::ifstream f(path, std::ios::binary);
    check(f.good(), "cannot read payload");
    return {std::istreambuf_iterator<char>(f), {}};
}
static uint32_t word(const std::vector<uint8_t> &bytes, unsigned off) {
    check(off + 4 <= bytes.size(), "instruction outside payload");
    return uint32_t(bytes[off]) | uint32_t(bytes[off + 1]) << 8 |
        uint32_t(bytes[off + 2]) << 16 | uint32_t(bytes[off + 3]) << 24;
}

// Static storage initializes GSIM memory-array backing bytes before its constructor.
// Automatic storage can contain out-of-width garbage before a Queue entry is valid.
static SJtagBootGsim model;

struct Rig {
    SJtagBootGsim &d;
    std::vector<uint8_t> rom, app;
    bool running = false, sealed = false, primed = false, success = false;
    unsigned cycles = 0, commits = 0, ramCommits = 0, dirtyBeats = 0, cleanAcks = 0;
    unsigned fenceCommits = 0, invalidationsAfterSeal = 0, fillsBeforeSeal = 0, fillsAfterSeal = 0;
    Rig(std::vector<uint8_t> r, std::vector<uint8_t> a) : d(model), rom(std::move(r)), app(std::move(a)) {
        d.set_io$$hold(1); d.set_io$$romWrite(0); d.set_io$$ramWrite(0);
        d.set_io$$romIndex(0); d.set_io$$romData(0); d.set_io$$ramIndex(0); d.set_io$$ramData(0);
        d.set_io$$dmi$$request$$valid(0); d.set_io$$dmi$$request$$bits$$op(0);
        d.set_io$$dmi$$request$$bits$$address(0); d.set_io$$dmi$$request$$bits$$data(0);
        d.set_io$$dmi$$response$$ready(1); d.set_io$$inspectRegister(27);
        d.set_reset(1); tick(); tick(); d.set_reset(0); tick();
        for (unsigned n = 0; n < rom.size(); n += 4) {
            d.set_io$$romWrite(1); d.set_io$$romIndex(n / 4); d.set_io$$romData(word(rom, n)); tick();
        }
        d.set_io$$romWrite(0);
        // Initial RAM code: addi s10,zero,0x111; jalr zero,ra,0. Independently encoded RV64I.
        for (unsigned n = 0; n < 192; n += 8) {
            uint64_t initial = n == 0 ? 0x0000806711100d13ULL : n == 64 ? 0x11223344ULL : 0;
            d.set_io$$ramWrite(1); d.set_io$$ramIndex(n / 8); d.set_io$$ramData(initial); tick();
        }
        d.set_io$$ramWrite(0); tick(); d.set_io$$hold(0); running = true;
    }
    void retirement(bool valid, uint64_t pc, uint32_t inst, unsigned rd, bool writes, uint64_t data) {
        if (!valid) return;
        ++commits;
        if (pc >= romBase && pc < romBase + rom.size())
            check(inst == word(rom, pc - romBase), "ROM instruction oracle mismatch");
        else if (pc >= ramBase && pc < ramBase + 64) {
            uint32_t expected = sealed ? word(app, pc - ramBase) : pc == ramBase ? 0x11100d13 : 0x00008067;
            if (inst != expected) {
                std::cerr << "RAM instruction mismatch pc=0x" << std::hex << pc << " got=0x" << inst
                          << " expected=0x" << expected << std::dec << '\n';
                throw std::runtime_error("downloaded RAM instruction oracle mismatch");
            }
            if (sealed) ++ramCommits;
            else if (pc == ramBase && rd == 26 && writes && data == 0x111) primed = true;
        } else throw std::runtime_error("retirement outside test program");
        if (inst == 0x0000100f) ++fenceCommits;
        if (writes && rd == 27 && data == 0xbad) throw std::runtime_error("CPU boot/app policy check failed");
        if (sealed && writes && rd == 27 && data == 0x600) success = true;
    }
    void tick() {
        d.step(); ++cycles;
        if (!running) return;
        if (d.get_io$$trap$$valid()) {
            std::cerr << "trap cause=" << d.get_io$$trap$$bits$$cause() << " pc=0x" << std::hex
                      << d.get_io$$trap$$bits$$pc() << " tval=0x" << d.get_io$$trap$$bits$$tval() << std::dec << '\n';
            throw std::runtime_error("unexpected architectural trap");
        }
        retirement(d.get_io$$commit0$$valid(), d.get_io$$commit0$$bits$$pc(),
            d.get_io$$commit0$$bits$$instruction(), d.get_io$$commit0$$bits$$rd(),
            d.get_io$$commit0$$bits$$writesRd(), d.get_io$$commit0$$bits$$data());
        retirement(d.get_io$$commit1$$valid(), d.get_io$$commit1$$bits$$pc(),
            d.get_io$$commit1$$bits$$instruction(), d.get_io$$commit1$$bits$$rd(),
            d.get_io$$commit1$$bits$$writesRd(), d.get_io$$commit1$$bits$$data());
        if (d.get_io$$probeFire()) {
            auto opcode = d.get_io$$probeOpcode(), param = d.get_io$$probeParam();
            auto address = d.get_io$$probeAddress();
            if (address == ramBase + 64 && opcode == 4 && param == 1) ++cleanAcks;
            if (address == ramBase + 128 && opcode == 5 && param == 1) {
                if (dirtyBeats == 0) check(d.get_io$$probeData() == 0x55667788,
                    "dirty ProbeAckData did not carry CPU-owned value");
                ++dirtyBeats;
            }
        }
        if (sealed && d.get_io$$invalidateFetch()) ++invalidationsAfterSeal;
        if (d.get_io$$lineFill() && d.get_io$$lineFillAddress() == ramBase)
            sealed ? ++fillsAfterSeal : ++fillsBeforeSeal;
        check(cycles < 100000, "bounded boot execution timed out");
    }
    std::pair<unsigned, uint32_t> dmi(unsigned op, unsigned address, uint32_t value = 0) {
        d.set_io$$dmi$$request$$bits$$op(op); d.set_io$$dmi$$request$$bits$$address(address);
        d.set_io$$dmi$$request$$bits$$data(value); d.set_io$$dmi$$request$$valid(1);
        bool sent = false;
        for (unsigned n = 0; n < 2000; ++n) { tick(); if (d.get_io$$dmi$$request$$ready()) { sent = true; break; } }
        check(sent, "DMI request timeout"); d.set_io$$dmi$$request$$valid(0);
        for (unsigned n = 0; n < 2000; ++n) {
            tick(); if (d.get_io$$dmi$$response$$valid())
                return {unsigned(d.get_io$$dmi$$response$$bits$$status()), uint32_t(d.get_io$$dmi$$response$$bits$$data())};
        }
        throw std::runtime_error("DMI response timeout");
    }
    uint32_t rd(unsigned a) { auto [s, v] = dmi(1, a); check(s == 0, "DMI read failed"); return v; }
    void wr(unsigned a, uint32_t v) { check(dmi(2, a, v).first == 0, "DMI write failed"); }
    void idle() {
        for (unsigned n = 0; n < 2000; ++n) {
            auto s = rd(0x38); check(!(s & ((7U << 12) | (1U << 22))), "SBA error");
            if (!(s & (1U << 21))) return;
        }
        throw std::runtime_error("SBA completion timeout");
    }
};

int main(int argc, char **argv) try {
    check(argc == 3 || argc == 4, "expected ROM, app, optional negative mode");
    auto rom = readFile(argv[1]), app = readFile(argv[2]);
    check(rom.size() <= 512 && rom.size() % 4 == 0 && app.size() == 192, "payload geometry");
    std::string mode = argc == 4 ? argv[3] : "";
    if (mode == "--omit-fence") {
        unsigned patched = 0;
        for (unsigned n = 0; n < rom.size(); n += 4) if (word(rom, n) == 0x0000100f) {
            rom[n] = 0x13; rom[n + 1] = rom[n + 2] = rom[n + 3] = 0; ++patched;
        }
        check(patched == 1, "fence mutation missing");
    }
    Rig r(rom, app);
    for (unsigned n = 0; ; ++n) {
        check(n < 5000, "CPU did not OPEN session"); if (r.rd(0x41) & 1) break;
    }
    check(r.primed && r.fillsBeforeSeal > 0, "old RAM code not architecturally primed");
    check(r.rd(0x46) == 1 && r.rd(0x47) == ramBase && r.rd(0x48) == ramBase + 0x7c000,
        "CPU OPEN epoch/range mismatch");
    r.wr(0x38, (2U << 17) | (1U << 16)); r.wr(0x39, ramBase);
    for (unsigned n = 0; n < app.size(); n += 4) {
        auto value = word(app, n);
        if (mode == "--corrupt-download" && n == 0) value ^= 1U << 20;
        r.wr(0x3c, value); r.idle();
    }
    check(r.cleanAcks >= 1 && r.dirtyBeats == 8, "clean/dirty owned coherence paths not observed");
    r.wr(0x38, (2U << 17) | (1U << 20));
    for (unsigned n = 0; n < app.size(); n += 4) {
        r.wr(0x39, ramBase + n); r.idle();
        auto expected = word(app, n);
        if (mode == "--corrupt-download" && n == 0) expected ^= 1U << 20;
        check(r.rd(0x3c) == expected, "independent full RAM readback mismatch");
    }
    r.wr(0x43, ramBase); r.wr(0x44, app.size()); r.wr(0x45, 0x12345678); r.wr(0x49, 1);
    r.sealed = true; r.wr(0x42, 2);
    check(r.dmi(2, 0x43, ramBase + 4).first == 2, "sealed entry modification accepted");
    while (!r.success) r.tick();
    check(r.ramCommits >= 10 && r.fenceCommits == 1 && r.invalidationsAfterSeal > 0 && r.fillsAfterSeal > 0,
        "architectural handoff/fence visibility proof incomplete");
    check((r.rd(0x41) & 0x43) == 0x40 && r.rd(0x46) == 1 && r.rd(0x43) == ramBase,
        "CPU did not CLAIM frozen epoch/entry");
    check(r.dmi(2, 0x42, 1).first == 2, "host reopened claimed launch");
    r.d.set_io$$inspectRegister(26); r.tick(); r.tick();
    check(r.d.get_io$$committedValue() == 0x5a5, "architectural downloaded signature mismatch");
    std::cout << "JTAG_BOOT_PASS cycles=" << r.cycles << " commits=" << r.commits
              << " downloaded_commits=" << r.ramCommits << " clean_owned_acks=" << r.cleanAcks
              << " dirty_owned_beats=" << r.dirtyBeats << " fence_commits=" << r.fenceCommits
              << " ram_refills_before=" << r.fillsBeforeSeal << " ram_refills_after=" << r.fillsAfterSeal << '\n';
    return 0;
} catch (const std::exception &e) {
    std::cerr << "JTAG_BOOT_FAIL " << e.what() << '\n'; return 1;
}
