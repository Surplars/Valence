#include "TranslationPlatformGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <tuple>
#include <utility>

static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}
struct Request {
    uint64_t va = 0x40002000, root = 0x80010;
    unsigned mode = 8, asid = 1, privilege = 1, access = 0;
};
static void drive(STranslationPlatformGsim &dut, const Request &a, const Request &b,
                  bool valid0 = false, bool valid1 = false, bool flush = false, bool ready0 = true) {
    dut.set_io$$hold(0);
    dut.set_io$$romWrite(0);
    dut.set_io$$romIndex(0);
    dut.set_io$$romData(0);
    dut.set_io$$ramWrite(0);
    dut.set_io$$ramIndex(0);
    dut.set_io$$ramData(0);
    dut.set_io$$requestValid0(valid0);
    dut.set_io$$request0$$virtualAddress(a.va);
    dut.set_io$$request0$$rootPpn(a.root);
    dut.set_io$$request0$$asid(a.asid);
    dut.set_io$$request0$$mode(a.mode);
    dut.set_io$$request0$$privilege(a.privilege);
    dut.set_io$$request0$$access(a.access);
    dut.set_io$$request0$$sum(0);
    dut.set_io$$request0$$mxr(0);
    dut.set_io$$responseReady0(ready0);
    dut.set_io$$requestValid1(valid1);
    dut.set_io$$request1$$virtualAddress(b.va);
    dut.set_io$$request1$$rootPpn(b.root);
    dut.set_io$$request1$$asid(b.asid);
    dut.set_io$$request1$$mode(b.mode);
    dut.set_io$$request1$$privilege(b.privilege);
    dut.set_io$$request1$$access(b.access);
    dut.set_io$$request1$$sum(0);
    dut.set_io$$request1$$mxr(0);
    dut.set_io$$responseReady1(1);
    dut.set_io$$flush(flush);
}
struct Result { unsigned cycles = 0, walks = 0, reads = 0, cacheHits = 0; bool hit = false; };
static Result translate(STranslationPlatformGsim &dut, Request a, Request b, bool use0, bool use1,
                        bool fault0 = false, bool fault1 = false,
                        uint64_t expected0 = UINT64_MAX, uint64_t expected1 = UINT64_MAX) {
    if (expected0 == UINT64_MAX) expected0 = 0x80000000ULL + (a.va & 0xfff);
    if (expected1 == UINT64_MAX) expected1 = 0x80000000ULL + (b.va & 0xfff);
    bool done0 = !use0, done1 = !use1;
    drive(dut, a, b, use0, use1);
    dut.step();
    check(!use0 || dut.get_io$$requestReady0(), "instruction service did not accept request");
    check(!use1 || dut.get_io$$requestReady1(), "data service did not accept request");
    Result result;
    result.hit = (use0 && dut.get_io$$hit0()) || (use1 && dut.get_io$$hit1());
    if (use0 && dut.get_io$$responseValid0()) {
        check(!fault0 && !dut.get_io$$response0$$pageFault() && !dut.get_io$$response0$$accessFault() &&
              dut.get_io$$response0$$physicalAddress() == expected0,
              "I fast translation mismatch");
        done0 = true;
    }
    if (use1 && dut.get_io$$responseValid1()) {
        check(!fault1 && !dut.get_io$$response1$$pageFault() && !dut.get_io$$response1$$accessFault() &&
              dut.get_io$$response1$$physicalAddress() == expected1,
              "D fast translation mismatch");
        done1 = true;
    }
    for (unsigned cycle = 0; cycle < 150 && (!done0 || !done1); ++cycle) {
        drive(dut, a, b);
        dut.step();
        result.cycles++;
        result.walks += dut.get_io$$walk0() + dut.get_io$$walk1();
        result.reads += dut.get_io$$pteRead0() + dut.get_io$$pteRead1();
        result.cacheHits += dut.get_io$$pteCacheHit0() + dut.get_io$$pteCacheHit1();
        if (dut.get_io$$responseValid0() && !done0) {
            check(bool(dut.get_io$$response0$$pageFault()) == fault0, "I page fault mismatch");
            check(!dut.get_io$$response0$$accessFault(), "I page-table access fault");
            if (!fault0) check(dut.get_io$$response0$$physicalAddress() == expected0,
                               "I physical address mismatch");
            done0 = true;
        }
        if (dut.get_io$$responseValid1() && !done1) {
            check(bool(dut.get_io$$response1$$pageFault()) == fault1, "D page fault mismatch");
            check(!dut.get_io$$response1$$accessFault(), "D page-table access fault");
            if (!fault1) check(dut.get_io$$response1$$physicalAddress() == expected1,
                               "D physical address mismatch");
            done1 = true;
        }
    }
    check(done0 && done1, "parallel translation timed out");
    return result;
}

int main() {
    try {
        STranslationPlatformGsim dut;
        Request empty;
        drive(dut, empty, empty);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        const uint32_t firmware[] = {0xfff00293U, 0x3b029073U, 0x01f00293U, 0x3a029073U,
                                     0x000c02b7U, 0x3002a073U, 0x800002b7U, 0x02029293U,
                                     0x01028293U, 0x18029073U, 0xfff00313U, 0x18031073U,
                                     0x12000073U, 0x0000006fU};
        for (unsigned i = 0; i < sizeof(firmware) / sizeof(firmware[0]); ++i) {
            drive(dut, empty, empty);
            dut.set_io$$hold(1);
            dut.set_io$$romWrite(1);
            dut.set_io$$romIndex(i);
            dut.set_io$$romData(firmware[i]);
            dut.step();
        }
        for (const auto [levels, rootPage] : {std::pair{3u, 0u}, std::pair{4u, 3u}, std::pair{5u, 7u}}) {
            for (int level = int(levels) - 1; level >= 0; --level) {
                const unsigned page = rootPage + levels - 1 - unsigned(level);
                const unsigned vpn = (0x40002000ULL >> (12 + 9 * level)) & 511;
                const uint64_t ppn = level == 0 ? 0x80000ULL : 0x80010ULL + page + 1;
                const uint64_t value = (ppn << 10) | (level == 0 ? 0xcfULL : 1ULL);
                drive(dut, empty, empty);
                dut.set_io$$hold(1);
                dut.set_io$$ramWrite(1);
                dut.set_io$$ramIndex(page * 512 + vpn);
                dut.set_io$$ramData(value);
                dut.step();
            }
        }
        for (const auto [page, index, value] : {
                 std::tuple{12u, unsigned((0x40200000ULL >> 30) & 511), (0x8001dULL << 10) | 1ULL},
                 std::tuple{13u, unsigned((0x40200000ULL >> 21) & 511), (0x80000ULL << 10) | 0xcfULL},
                 std::tuple{2u, unsigned((0x40004000ULL >> 12) & 511), (0x80000ULL << 10) | 0xcfULL}}) {
            drive(dut, empty, empty);
            dut.set_io$$hold(1);
            dut.set_io$$ramWrite(1);
            dut.set_io$$ramIndex(page * 512 + index);
            dut.set_io$$ramData(value);
            dut.step();
        }
        for (unsigned alias = 16; alias < 32; ++alias) {
            drive(dut, empty, empty);
            dut.set_io$$hold(1);
            dut.set_io$$ramWrite(1);
            dut.set_io$$ramIndex(2 * 512 + alias);
            dut.set_io$$ramData((uint64_t(1) << 63) | (0x80008ULL << 10) | 0xcfULL);
            dut.step();
        }
        drive(dut, empty, empty);
        dut.set_io$$hold(1);
        dut.set_io$$ramWrite(1);
        dut.set_io$$ramIndex(2 * 512 + ((0x40003000ULL >> 12) & 511));
        dut.set_io$$ramData(0);
        dut.step();
        drive(dut, empty, empty);
        dut.set_io$$hold(1);
        dut.step();
        unsigned commits = 0, vmFlushes = 0;
        bool walkStarted = false, releaseWalk = false, observedDrain = false;
        Request setupWalk;
        for (unsigned cycle = 0; cycle < 180; ++cycle) {
            const bool startWalk = !walkStarted && dut.get_io$$satp() == 0x8000000000000010ULL;
            drive(dut, setupWalk, empty, startWalk, false, false, releaseWalk);
            dut.step();
            if (startWalk) {
                check(dut.get_io$$requestReady0(), "setup walk was not accepted");
                walkStarted = true;
            }
            commits += dut.get_io$$committed();
            vmFlushes += dut.get_io$$sfenceFlush();
            if (walkStarted && !releaseWalk && dut.get_io$$vmFlushPending() &&
                dut.get_io$$responseValid0()) {
                check(!dut.get_io$$sfenceFlush(), "SFENCE flushed a busy page-table service");
                observedDrain = true;
                releaseWalk = true;
            }
            if (dut.get_io$$trap()) {
                std::cerr << "PMP setup trap cycle=" << cycle << " pc=0x" << std::hex
                          << dut.get_io$$trapPc() << " cause=" << dut.get_io$$trapCause()
                          << " tval=" << dut.get_io$$trapTval() << std::dec << '\n';
                throw std::runtime_error("PMP setup firmware trapped");
            }
        }
        check(commits >= 13, "VM control firmware did not retire");
        check(walkStarted && observedDrain, "SFENCE did not wait for an outstanding translation response");
        check(dut.get_io$$satp() == 0x8000000000000010ULL, "satp write or unsupported-mode WARL mismatch");
        check(dut.get_io$$sum() && dut.get_io$$mxr(), "mstatus SUM/MXR write mismatch");
        check(vmFlushes == 2, "PMP update and SFENCE.VMA did not each flush both translation services");
        Request sv39, sv48;
        sv48.root = 0x80013; sv48.mode = 9;
        const auto parallel = translate(dut, sv39, sv48, true, true);
        check(parallel.walks == 2 && parallel.reads == 7, "I/D walks did not share TileLink RAM");
        drive(dut, empty, empty, false, false, true); dut.step();
        const auto serialI = translate(dut, sv39, {}, true, false);
        const auto serialD = translate(dut, {}, sv48, false, true);
        check(parallel.cycles < serialI.cycles + serialD.cycles,
              "independent I/D walkers did not reduce miss completion time");
        sv39.va += 0x100;
        sv48.va += 0x200;
        const auto hits = translate(dut, sv39, sv48, true, true);
        check(hits.hit && hits.walks == 0 && hits.reads == 0, "TLB hit performed a page walk");
        sv39.va = 0x40004000;
        const auto cachedWalk = translate(dut, sv39, {}, true, false);
        check(cachedWalk.walks == 1 && cachedWalk.cacheHits == 2 && cachedWalk.reads == 1,
              "same-region miss did not reuse two non-leaf PTEs");
        Request malformed = sv39;
        malformed.va |= uint64_t(1) << 39;
        const auto canonical = translate(dut, malformed, {}, true, false, true);
        check(canonical.walks == 1 && canonical.reads == 0,
              "noncanonical address incorrectly reused a TLB entry");
        Request sv57;
        sv57.mode = 10; sv57.root = 0x80017;
        const auto deep = translate(dut, sv57, {}, true, false);
        check(deep.walks == 1 && deep.reads == 5, "Sv57 page depth mismatch");
        sv39.va = 0x40003000;
        const auto missing = translate(dut, sv39, {}, true, false, true);
        check(missing.walks == 1 && missing.cacheHits == 2 && missing.reads == 1,
              "page-fault walk did not reuse valid non-leaf PTEs");
        drive(dut, empty, empty, false, false, true); dut.step();
        sv39.va = 0x40002000;
        const auto afterFlush = translate(dut, sv39, {}, true, false);
        check(afterFlush.walks == 1 && afterFlush.reads == 3, "TLB flush retained a stale hit");
        check(cachedWalk.cycles < afterFlush.cycles, "non-leaf cache did not shorten the same-depth walk");
        Request superpage = sv39;
        superpage.root = 0x8001c; superpage.va = 0x40201000;
        const auto superMiss = translate(dut, superpage, {}, true, false, false, false, 0x80001000);
        superpage.va = 0x40202000;
        const auto superHit = translate(dut, superpage, {}, true, false, false, false, 0x80002000);
        check(superMiss.walks == 1 && superMiss.reads == 2 && superHit.hit && superHit.walks == 0,
              "superpage TLB reach or offset mismatch");
        Request napot = sv39;
        napot.va = 0x40010000;
        const auto napotMiss = translate(dut, napot, {}, true, false);
        napot.va += 0x1000;
        const auto napotHit = translate(dut, napot, {}, true, false, false, false, 0x80001000);
        check(napotMiss.walks == 1 && napotMiss.reads == 1 && napotMiss.cacheHits == 2 &&
              napotHit.hit && napotHit.walks == 0,
              "64 KiB NAPOT TLB reach or offset mismatch");
        std::cout << "GSIM SoC translation: PASS parallelWalkCycles=" << parallel.cycles
                  << " serialWalkCycles=" << serialI.cycles + serialD.cycles
                  << " parallelPteReads=" << parallel.reads << " hitCycles=" << hits.cycles
                  << " cachedWalkCycles=" << cachedWalk.cycles << " cachedWalkRamReads=" << cachedWalk.reads
                  << " uncachedWalkCycles=" << afterFlush.cycles
                  << " sv57PteReads=" << deep.reads << " commits=" << commits << '\n';
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "GSIM SoC translation: FAIL " << e.what() << '\n';
        return 1;
    }
}
