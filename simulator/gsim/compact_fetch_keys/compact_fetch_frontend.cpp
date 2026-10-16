#ifdef SHARED_TWO_WORD_FRONTEND_PAIR
#include "SharedTwoWordFetchFrontendGsim.h"
#define SCompactFetchFrontendGsim SSharedTwoWordFetchFrontendGsim
#include <cstring>
#include <type_traits>
#else
#include "CompactFetchFrontendGsim.h"
#endif
#include "compact_fetch_frontend_oracle.h"
#include <algorithm>
#include <iomanip>
#include <iostream>
#include <random>
#include <sstream>
#include <vector>
using namespace independent;
#ifdef SHARED_TWO_WORD_FRONTEND_PAIR
static bool injectOracle = false, injectPair = false;
#endif
static void check(bool ok, const std::string &message) { if (!ok) throw std::runtime_error(message); }
static uint64_t mix(uint64_t x) { x ^= x >> 30; x *= UINT64_C(0xbf58476d1ce4e5b9); x ^= x >> 27;
    x *= UINT64_C(0x94d049bb133111eb); return x ^ (x >> 31); }
static uint64_t packet(uint64_t address, uint64_t serial) {
    uint64_t data = 0;
    for (unsigned h = 0; h < 4; ++h) {
        uint16_t half = uint16_t(mix(address + 2*h + serial * 173));
        // Every packet ends with a 32-bit start; other halfwords mix compressed and long instructions.
        half = uint16_t((half & ~3U) | ((h == 3 || ((serial + h) % 3 == 0)) ? 3U : 1U));
        data |= uint64_t(half) << (16*h);
    }
    return data;
}
struct Driver {
    SCompactFetchFrontendGsim dut;
    Model model;
    Input in;
    struct Memory { bool busy = false; uint64_t address = 0, serial = 0; unsigned mask = 0, delay = 0; } memory;
    uint64_t serial = 0;
    unsigned latency = 1;
    Output last;
#ifdef SHARED_TWO_WORD_FRONTEND_PAIR
    unsigned prepareCancels = 0, irrevocableCancels = 0;
#endif
    Driver() {
#ifdef SHARED_TWO_WORD_FRONTEND_PAIR
        static_assert(std::is_trivially_copyable_v<SCompactFetchFrontendGsim>);
        std::memset(&dut, 0, sizeof(dut)); dut.LOG_START = 1; dut.activateAll();
        dut.set_io$$pairMismatch(injectPair);
#endif
        in.enable = false; in.pause = true; apply(); dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        in.enable = true; in.pause = false;
    }
    void apply() {
        dut.set_io$$pc(in.pc); dut.set_io$$requestFrontier(in.frontier); dut.set_io$$suppressRequest(in.suppress);
        dut.set_io$$enable(in.enable); dut.set_io$$invalidate(in.invalidate); dut.set_io$$pause(in.pause);
        dut.set_io$$privilege(in.privilege); dut.set_io$$virtualized(in.virtualized);
        dut.set_io$$pmpCfg0(in.pmpCfg); dut.set_io$$pmpAddr0(in.pmpAddr);
        dut.set_io$$requestReady(in.ready); dut.set_io$$responseValid(in.response);
        dut.set_io$$responseData(in.data); dut.set_io$$responseErrors(in.errors); dut.set_io$$responsePages(in.pages);
    }
    std::string where(const std::string &kind) {
        std::ostringstream out; out << "COMPACT_FRONTEND_ORACLE " << kind << " cycle=" << model.coverage.cycles
            << " pc=0x" << std::hex << in.pc << " pending=" << model.pending << " locked=" << model.locked;
        return out.str();
    }
    Output tick() {
        in.pmpAddr &= (UINT64_C(1) << 54) - 1; // Input port is a 54-bit architectural PMP address.
        in.response = memory.busy && memory.delay == 0;
        in.data = packet(memory.address, memory.serial);
        in.errors = ((~memory.mask) & 3) | unsigned((memory.serial % 7) == 0);
        in.pages = (memory.serial % 11) == 0 ? 2 : 0;
        const Output expected = model.evaluate(in);
        apply(); dut.step();
        check(bool(dut.get_io$$requestValid()) == expected.request, where("request valid"));
        check(bool(dut.get_io$$responseReady()) == expected.responseReady, where("response ready"));
        check(bool(dut.get_io$$quiescent()) == expected.quiescent, where("quiescent"));
        if (expected.request) {
            check(dut.get_io$$requestAddress() == expected.address, where("request address"));
#ifdef SHARED_TWO_WORD_FRONTEND_PAIR
            check((dut.get_io$$requestMask() ^ unsigned(injectOracle)) == expected.mask, where("request PMP mask"));
#else
            check(dut.get_io$$requestMask() == expected.mask, where("request PMP mask"));
#endif
        }
        const bool valid[] = {bool(dut.get_io$$lane0$$valid()), bool(dut.get_io$$lane1$$valid())};
        const uint32_t bits[] = {dut.get_io$$lane0$$bits(), dut.get_io$$lane1$$bits()};
        const uint64_t faults[] = {dut.get_io$$fault0(), dut.get_io$$fault1()};
        const unsigned offsets[] = {unsigned(dut.get_io$$faultOffset0()), unsigned(dut.get_io$$faultOffset1())};
        for (unsigned lane = 0; lane < 2; ++lane) {
            const auto &want = expected.lanes[lane];
            check(valid[lane] == want.valid, where("lane validity " + std::to_string(lane)));
            if (!want.valid) continue; // No comparison of semantically dead payloads.
            check(bits[lane] == want.data, where("valid instruction data"));
            check(bool((dut.get_io$$errors() >> lane) & 1) == want.error, where("valid access fault"));
            check(bool((dut.get_io$$pages() >> lane) & 1) == want.page, where("valid page fault"));
            check(faults[lane] == want.fault && offsets[lane] == want.offset, where("valid fault address/offset"));
        }
#ifdef SHARED_TWO_WORD_FRONTEND_PAIR
        prepareCancels += model.locked && !model.maskCaptured && expected.cancelPrepared;
        irrevocableCancels += model.locked && model.maskCaptured && expected.cancelPrepared;
#endif
        model.advance(in, expected);
        if (in.response) memory.busy = false;
        if (expected.request && in.ready) {
            check(!memory.busy, where("memory single outstanding"));
            memory = {true, expected.address, ++serial, expected.mask, latency};
        } else if (memory.busy && memory.delay) --memory.delay;
        last = expected; return expected;
    }
    void move(uint64_t pc, unsigned cycles = 1) {
        in.pc = pc; in.frontier = pc;
        for (unsigned cycle = 0; cycle < cycles; ++cycle) tick();
    }
    void drain() {
        in.pause = true; in.enable = true; in.invalidate = false; in.ready = true; in.suppress = false;
        for (unsigned n = 0; n < 30 && (model.pending || model.locked || memory.busy); ++n) tick();
        check(!model.pending && !model.locked && !memory.busy, where("drain timeout"));
    }
    void fill(uint64_t base) {
        in.enable = true; in.pause = false; in.ready = true; in.invalidate = false; in.suppress = false;
        in.pc = base; in.frontier = base;
        bool found = false;
        for (unsigned n = 0; n < 30; ++n) {
            tick();
            for (const auto &r : model.rows[Model::index(base)])
                if (r.valid && r.base == base && r.context == in.context()) found = true;
            if (found) break;
        }
        check(found, where("directed fill timeout")); drain();
    }
    void checkResidentOffsets() {
        drain(); in.pause = true;
        for (const auto &set : model.rows) for (const auto r : set) if (r.valid && r.context == in.context())
            for (unsigned offset = 0; offset < 3; ++offset) {
                // Capture the selected resident through each query offset, then consume it as row zero.
                // In particular offset two has an architectural validity witness on the next cursor move.
                move(r.base - uint64_t(8 * offset)); move(r.base); move(r.base + 2); move(r.base + 4);
            }
    }
    void staleBorrowProbe(unsigned set, uint64_t newTag) {
        drain(); in.pc = newTag + 8 * set; in.frontier = in.pc;
        in.enable = true; in.pause = false; in.ready = false;
        for (unsigned n = 0; n < 8 && !(model.locked && (!FETCH_STAGED || model.maskCaptured)); ++n) tick();
        check(model.locked, where("stale borrow locked offer not reached"));
        if (FETCH_STAGED) {
            // Cancel only after the offer becomes irrevocable. No invalidate: old residents stay live.
            in.enable = false; tick();
            check(model.lockedStale, where("stale borrow cancellation not captured"));
        } else {
            in.invalidate = true; tick(); in.invalidate = false;
        }
        in.ready = true; tick();
        check(model.pendingStale, where("stale borrow accepted owner not stale"));
        unsigned liveRows = 0; for (const auto &row : model.rows[set]) liveRows += row.valid;
        if (FETCH_STAGED) check(liveRows == 2, where("stale probe requires both resident ways live"));
        std::cout << "STALE_OWNER_LIVE_ROWS set=" << set << " live=" << liveRows
                  << " pending_stale=1 invalidate=" << in.invalidate << " staged=" << FETCH_STAGED << std::endl;
        in.pause = true;
        while (memory.busy) tick();
        in.enable = true; checkResidentOffsets();
    }
};
int main(int argc, char **argv) {
    try {
#ifdef SHARED_TWO_WORD_FRONTEND_PAIR
        check(argc == 1 || (argc == 2 && (std::string(argv[1]) == "--inject-oracle-mismatch" ||
            std::string(argv[1]) == "--inject-pair-mismatch")), "unknown argument");
        injectOracle = argc == 2 && std::string(argv[1]) == "--inject-oracle-mismatch";
        injectPair = argc == 2 && std::string(argv[1]) == "--inject-pair-mismatch";
#endif
        Driver d;
#ifdef SHARED_TWO_WORD_FRONTEND_PAIR
        // Explicitly cancel a revocable preparation before its mask is captured.
        d.move(UINT64_C(0x80040000));
        check(d.model.locked && !d.model.maskCaptured, "preparation witness absent");
        d.in.suppress = true; d.tick();
        check(!d.model.locked && !d.memory.busy && d.prepareCancels, "preparation cancel failed");
        d.in.suppress = false; d.move(UINT64_C(0x80041000), 2);
        check(d.memory.busy && d.model.pending, "reset outstanding owner witness absent");
        // Whole-interface reset discards this epoch's owner and external response obligation.
        // No tagged late-response/cancel contract is invented.
        d.dut.set_reset(1); d.dut.step(); d.dut.step();
        d.model = Model{}; d.memory = {}; d.serial = 0; d.in = Input{};
        d.in.enable = false; d.in.pause = true; d.dut.set_reset(0); d.tick();
        check(d.last.quiescent && !d.last.request, "reset retained abandoned fetch owner");
#endif
        // Fill every way at every native set. Adjacent-prefetch fills are allowed, independently modelled.
        const uint64_t stride = uint64_t(Sets) * 8;
        for (uint64_t root : {UINT64_C(0x80000000), UINT64_C(0x80000000) + stride,
                              UINT64_C(0x80000000) + 2 * stride})
            for (unsigned set = 0; set < Sets; ++set) d.fill(root + 8 * set);
        d.checkResidentOffsets();
        for (unsigned set = 0; set < Sets; ++set) for (unsigned way = 0; way < 2; ++way) {
            check(d.model.coverage.fills[set][way] != 0, "directed fill omitted set/way");
            for (unsigned offset = 0; offset < 3; ++offset)
                check(d.model.coverage.hits[set][way][offset] != 0, "directed read omitted set/way/offset");
        }
        // Fault CE negative witness: stale reply has another high tag and must not change live borrow keys.
        for (unsigned set = 0; set < 2; ++set) for (unsigned round = 0; round < 2; ++round) {
            d.fill(UINT64_C(0x80008000) + round * stride + 8 * set);
            d.staleBorrowProbe(set, UINT64_C(0xc0000000) + round * stride);
        }
        // Zero and maximum address regions exercise subtraction borrow and modulo-XLEN query wrap.
        for (uint64_t base : {UINT64_C(0), UINT64_C(8), UINT64_MAX - 15, UINT64_MAX - 7}) d.fill(base);
        d.checkResidentOffsets();
        // A live fill and a cached instruction hit are legal simultaneously.
        d.in.pause = false; d.move(UINT64_C(0x80012006), 25); d.drain();
        // PMP NA4 denies exactly one 32-bit word, plus S no-match denial and virtual bypass.
        for (unsigned privilege : {3U, 1U, 0U}) for (bool virtualized : {false, true}) {
            d.in.privilege = privilege; d.in.virtualized = virtualized;
            d.in.pmpCfg = 0x90; d.in.pmpAddr = UINT64_C(0x80020004) >> 2;
            d.in.invalidate = true; d.tick(); d.in.invalidate = false;
            d.fill(UINT64_C(0x80020000)); d.fill(UINT64_C(0x80020008));
            d.in.pause = true; d.move(UINT64_C(0x80020006), 3);
        }
        d.drain();
        std::mt19937_64 rng(UINT64_C(0x434f4d504143544b));
        d.in = {}; d.in.pc = UINT64_C(0x80000000); d.in.frontier = d.in.pc;
        for (unsigned cycle = 0; cycle < 16000; ++cycle) {
            d.in.enable = cycle % 29 != 0;
            d.in.pause = cycle % 31 == 7;
            d.in.invalidate = cycle % 113 == 19;
            d.in.suppress = FETCH_STAGED && cycle % 43 == 9;
            d.in.ready = cycle % 7 != 2 && cycle % 7 != 3;
            d.in.privilege = (cycle / 251) % 3 == 0 ? 3 : (cycle / 251) % 2;
            d.in.virtualized = (cycle / 197) & 1;
            d.in.pmpCfg = cycle % 401 < 200 ? 0 : 0x94;
            d.in.pmpAddr = (d.in.pc & ~UINT64_C(7)) >> 2;
            d.latency = cycle % 5;
            if (cycle % 73 == 0) d.in.pc = UINT64_C(0x80000000) + (rng() & 1022);
            if (cycle % 509 == 0) d.in.pc = UINT64_MAX - 29;
            d.in.frontier = d.in.pc;
            if (FETCH_STAGED && cycle % 97 == 3) d.in.frontier += 24;
            const auto out = d.tick();
            unsigned take = cycle % 4 == 0 ? 0 : 1 + unsigned(rng() & 1);
            for (unsigned lane = 0; lane < take && out.lanes[lane].valid; ++lane)
                d.in.pc += (out.lanes[lane].data & 3) == 3 ? 4 : 2;
        }
        d.drain();
        const auto &c = d.model.coverage;
        check(c.instructions > 1000 && c.requests > 100 && c.stalls > 100, "insufficient owner/throughput coverage");
        check(c.staleResponses > 0 && c.fillWithHit > 0 && c.invalidations > 0 && c.contextChanges > 0,
              "insufficient stale/fill-hit/context coverage");
        check(c.longInstructions > 100 && c.shortInstructions > 100 && c.straddles > 10 && c.faults > 10 &&
              c.pageFaults > 10 && c.pmpDenied > 10 && c.wrappedQueries > 0, "insufficient instruction/PMP/wrap coverage");
        if (!FETCH_STAGED) check(c.turnover > 0, "no response/new-request turnover");
        else check(c.prepareTurnover > 0, "no response/new-preparation turnover");
        std::cout << "COMPACT_FETCH_FRONTEND_PAIR_ORACLE_PASS sets=" << Sets
                  << " window=" << FETCH_WINDOW << " staged=" << FETCH_STAGED << " cycles=" << c.cycles
                  << " instructions=" << c.instructions << " requests=" << c.requests << " stalls=" << c.stalls
                  << " stale=" << c.staleResponses << " fill_hit=" << c.fillWithHit << " turnover=" << c.turnover
                  << " prepare_turnover=" << c.prepareTurnover << " faults=" << c.faults << " pages=" << c.pageFaults << " straddles=" << c.straddles
                  << " pmp_denied=" << c.pmpDenied << " wrapped_queries=" << c.wrappedQueries
#ifdef SHARED_TWO_WORD_FRONTEND_PAIR
                  << " all_set_way_offsets=1 real_off_on_full_io_peer=1 full64_independent_oracle=1\n";
        check(d.prepareCancels && d.irrevocableCancels, "missing prepare/irrevocable cancellation coverage");
        std::cout << "SHARED_TWO_WORD_FRONTEND_PAIR_PASS prepare_cancels=" << d.prepareCancels
                  << " irrevocable_cancels=" << d.irrevocableCancels << " context_changes=" << c.contextChanges
                  << " invalidations=" << c.invalidations << " reset_epochs=2\n";
#else
                  << " all_set_way_offsets=1 frozen_cycle_peer=1 full64_independent_oracle=1\n";
#endif
    } catch (const std::exception &e) { std::cerr << "COMPACT_FETCH_FRONTEND_FAIL " << e.what() << '\n'; return 1; }
}
