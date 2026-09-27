#include "SvWalkerGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <unordered_map>
#include <vector>

static void check(bool value, const char *message) {
    if (!value) throw std::runtime_error(message);
}
static uint64_t pte(uint64_t ppn, unsigned flags, unsigned pbmt = 0, bool napot = false) {
    return (uint64_t(napot) << 63) | (uint64_t(pbmt) << 61) | (ppn << 10) | flags;
}
static unsigned vpn(uint64_t va, unsigned level) { return (va >> (12 + 9 * level)) & 511; }

struct Case {
    unsigned mode = 8, privilege = 1, access = 0;
    uint64_t va = 0x3456789abcULL, root = 0x100;
    bool sum = false, mxr = false, denyPmp = false, readError = false;
    uint64_t expectedPa = 0;
    bool pageFault = false, accessFault = false, global = false;
    unsigned expectedLevel = 0, expectedPbmt = 0, reads = 0;
    std::unordered_map<uint64_t, uint64_t> memory;
};
static Case mapping(unsigned levels, unsigned leafLevel, unsigned flags = 0xcf, unsigned pbmt = 0,
                    uint64_t va = 0x3456789abcULL) {
    Case c;
    c.va = va;
    c.mode = levels + 5;
    c.expectedLevel = leafLevel;
    c.expectedPbmt = pbmt;
    c.reads = levels - leafLevel;
    uint64_t table = c.root;
    for (int level = int(levels) - 1; level > int(leafLevel); --level) {
        const uint64_t next = 0x100 + uint64_t(levels - level) * 0x10;
        c.memory[(table << 12) + vpn(c.va, level) * 8] = pte(next, level == int(levels) - 1 ? 0x21 : 0x01);
        table = next;
    }
    // A naturally aligned leaf PPN; VPN chunks below leafLevel supply the superpage offset.
    const uint64_t ppn = leafLevel <= 2 ? 0x40000 : uint64_t(1) << (9 * leafLevel);
    c.memory[(table << 12) + vpn(c.va, leafLevel) * 8] = pte(ppn, flags, pbmt);
    const unsigned offsetBits = 12 + 9 * leafLevel;
    c.expectedPa = (ppn << 12) | (c.va & ((uint64_t(1) << offsetBits) - 1));
    c.global = leafLevel != levels - 1;
    return c;
}

static void inputs(SSvWalkerGsim &dut, const Case &c, bool start, bool readReady,
                   bool reply, uint64_t data = 0, bool error = false, bool completeReady = true) {
    dut.set_io$$startValid(start);
    dut.set_io$$virtualAddress(c.va);
    dut.set_io$$rootPpn(c.root);
    dut.set_io$$mode(c.mode);
    dut.set_io$$privilege(c.privilege);
    dut.set_io$$access(c.access);
    dut.set_io$$sum(c.sum);
    dut.set_io$$mxr(c.mxr);
    dut.set_io$$completeReady(completeReady);
    dut.set_io$$pteReady(readReady);
    dut.set_io$$pteReplyValid(reply);
    dut.set_io$$pteData(data);
    dut.set_io$$pteError(error);
    dut.set_io$$pmpCfg(c.denyPmp ? 0 : 0x1f); // NAPOT grants R/W/X over the 56-bit PA range.
    dut.set_io$$pmpAddr((uint64_t(1) << 54) - 1);
}

static void run(SSvWalkerGsim &dut, const Case &c) {
    inputs(dut, c, true, true, false);
    dut.step();
    check(dut.get_io$$startReady(), "walker did not accept an idle request");
    bool reply = false;
    uint64_t replyData = 0;
    bool replyError = false;
    unsigned reads = 0;
    for (unsigned cycle = 0; cycle < 100; ++cycle) {
        // Exercise stable request payload under one cycle of memory backpressure.
        const bool ready = cycle % 3 != 0;
        inputs(dut, c, false, ready, reply, replyData, replyError, false);
        dut.step();
        const bool readFire = dut.get_io$$pteValid() && ready;
        if (reply) check(dut.get_io$$pteReplyReady(), "walker dropped an outstanding PTE reply");
        reply = false;
        if (readFire) {
            ++reads;
            const auto found = c.memory.find(dut.get_io$$pteAddress());
            check(found != c.memory.end(), "walker requested an unexpected PTE address");
            replyData = found->second;
            replyError = c.readError;
            reply = true;
        }
        if (dut.get_io$$completeValid()) {
            check(reads == c.reads, "walker made the wrong number of PTE reads");
            check(bool(dut.get_io$$pageFault()) == c.pageFault, "page-fault classification mismatch");
            check(bool(dut.get_io$$accessFault()) == c.accessFault, "access-fault classification mismatch");
            if (!c.pageFault && !c.accessFault) {
                check(dut.get_io$$physicalAddress() == c.expectedPa, "translated address mismatch");
                check(dut.get_io$$level() == c.expectedLevel, "leaf level mismatch");
                check(bool(dut.get_io$$global()) == c.global, "global mapping mismatch");
                check(dut.get_io$$pbmt() == c.expectedPbmt, "PBMT mismatch");
            }
            inputs(dut, c, false, true, false, 0, false, true);
            dut.step();
            check(dut.get_io$$completeValid(), "completion was not held under backpressure");
            return;
        }
    }
    throw std::runtime_error("walker timed out");
}

int main() {
    try {
        SSvWalkerGsim dut;
        Case reset;
        inputs(dut, reset, false, true, false);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        unsigned cases = 0;
        for (unsigned levels : {3u, 4u, 5u}) {
            for (unsigned leaf = 0; leaf < levels; ++leaf) {
                auto c = mapping(levels, leaf);
                run(dut, c); ++cases;
            }
            auto c = mapping(levels, 0, 0xcf, 2);
            run(dut, c); ++cases;
            const unsigned signBit = 12 + 9 * levels - 1;
            c = mapping(levels, 0, 0xcf, 0,
                        (uint64_t(1) << signBit) | (~uint64_t(0) << (signBit + 1)) | 0x1234);
            run(dut, c); ++cases;
            c = mapping(levels, 0); c.va |= uint64_t(1) << (12 + 9 * levels);
            c.pageFault = true; c.reads = 0;
            run(dut, c); ++cases;
        }
        auto c = mapping(3, 0); c.memory[(c.root << 12) + vpn(c.va, 2) * 8] |= uint64_t(1) << 54;
        c.pageFault = true; c.reads = 1; run(dut, c); ++cases;
        c = mapping(3, 0); c.denyPmp = true; c.accessFault = true; c.reads = 0;
        run(dut, c); ++cases;
        c = mapping(3, 0); c.readError = true; c.accessFault = true; c.reads = 1;
        run(dut, c); ++cases;
        c = mapping(3, 0); c.access = 1;
        run(dut, c); ++cases;
        c = mapping(3, 0); c.access = 3;
        run(dut, c); ++cases;
        c = mapping(3, 0); c.access = 1;
        c.memory[(0x120ULL << 12) + vpn(c.va, 0) * 8] &= ~(uint64_t(1) << 7);
        c.pageFault = true; run(dut, c); ++cases;
        c = mapping(3, 0);
        c.memory[(0x120ULL << 12) + vpn(c.va, 0) * 8] &= ~(uint64_t(1) << 6);
        c.pageFault = true; run(dut, c); ++cases;
        c = mapping(3, 0, 0xc5); c.pageFault = true; // W without R.
        run(dut, c); ++cases;
        c = mapping(4, 2);
        c.memory[(0x110ULL << 12) + vpn(c.va, 2) * 8] |= uint64_t(1) << 10;
        c.pageFault = true; run(dut, c); ++cases;
        c = mapping(3, 0, 0xcf, 3); c.pageFault = true;
        run(dut, c); ++cases;
        c = mapping(3, 0);
        c.memory[(c.root << 12) + vpn(c.va, 2) * 8] |= uint64_t(1) << 4;
        c.pageFault = true; c.reads = 1; run(dut, c); ++cases;
        c = mapping(3, 0); c.privilege = 0; c.pageFault = true;
        run(dut, c); ++cases;
        c = mapping(3, 0, 0xdf); c.privilege = 0; c.pageFault = false;
        run(dut, c); ++cases;
        c = mapping(3, 0, 0xdf); c.pageFault = true; // SUM absent.
        run(dut, c); ++cases;
        c = mapping(3, 0, 0xdf); c.sum = true; c.pageFault = false;
        run(dut, c); ++cases;
        c = mapping(3, 0, 0xdf); c.sum = true; c.access = 2; c.pageFault = true;
        run(dut, c); ++cases;
        c = mapping(3, 0, 0xc9); c.pageFault = true;
        run(dut, c); ++cases;
        c = mapping(3, 0, 0xc9); c.mxr = true;
        run(dut, c); ++cases;
        c = mapping(3, 0);
        c.memory[(0x120ULL << 12) + vpn(c.va, 0) * 8] = pte(0x40008, 0xcf, 0, true);
        c.expectedPa = (0x40000ULL << 12) | (c.va & 0xffff);
        run(dut, c); ++cases;
        c = mapping(3, 0);
        c.memory[(0x120ULL << 12) + vpn(c.va, 0) * 8] = pte(0x40004, 0xcf, 0, true);
        c.pageFault = true; run(dut, c); ++cases;
        c = mapping(3, 0); c.mode = 0; c.reads = 0; c.expectedPa = c.va; c.global = false;
        run(dut, c); ++cases;
        std::cout << "GSIM Sv39/Sv48/Sv57 walker: PASS cases=" << cases << '\n';
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "GSIM Sv walker: FAIL " << e.what() << '\n';
        return 1;
    }
}
