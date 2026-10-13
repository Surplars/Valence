#pragma once
#include <deque>
#include <optional>
#include <tuple>

#ifndef DDR_READ_CREDITS
#define DDR_READ_CREDITS 8
#endif
#ifndef DDR_READ_LATENCY
#define DDR_READ_LATENCY 32
#endif
#ifndef DDR_READ_BEAT_GAP
#define DDR_READ_BEAT_GAP 1
#endif
#ifndef BOARD_DDR_BYTES
#define BOARD_DDR_BYTES 0x20000000ULL
#endif

// ID-neutral benchmark derivative; stress model is retained separately.
// Optional independent host-side AXI model, not a MIG/PHY/CDC performance model.
// All settings must match across compared RTL candidates. Independent AR/AW
// credit queues permit mixed traffic; W follows AW order and B may reorder by ID.
// Every read ID has independent latency and a bounded in-order beat cursor. R
// chooses the newest eligible transaction, then holds ID/data/last/resp until fire.
// Byte-lane writes and sparse data are independent of the RTL implementation.
struct DdrModel {
    struct Read {
        uint32_t address;
        unsigned count, size, id, beat;
        uint64_t due, sequence;
        bool error;
    };
    std::unordered_map<uint32_t, uint64_t> memory;
    std::deque<Read> pendingReads;
    struct Write { uint32_t address; unsigned count, size, id, beat; bool error; uint64_t due, sequence; };
    std::deque<Write> pendingWrites, pendingB;
    std::optional<uint64_t> heldRead, heldB;
    uint64_t heldReadData = 0;
    uint64_t peakWriteIds = 0, mixedCycles = 0, twoReadTwoWriteCycles = 0, reorderedB = 0;
    uint64_t rBeats = 0, wBeats = 0, bResponses = 0;
    bool writing = false, responding = false, writeWaiting = false;
    unsigned wBeat = 0, wCount = 0, wSize = 0, wId = 0;
    uint32_t wAddr = 0;
    uint64_t now = 0, sequence = 0, bDue = 0;
    bool arReady = false, awReady = false, wReady = false, rValid = false, bValid = false;
    uint64_t reads = 0, writes = 0, readBursts = 0, writeBursts = 0, stalls = 0;
    uint64_t peakReadIds = 0, reorderedBeats = 0;
    // Test-only injection addresses. Unset for normal board benchmarks.
    std::optional<uint32_t> denyReadAddress, denyWriteAddress;
    bool writeError = false;
    static_assert(DDR_READ_CREDITS >= 1 && DDR_READ_CREDITS <= 16);
    static_assert(DDR_READ_LATENCY >= 1 && DDR_READ_BEAT_GAP >= 1);
    static void address(uint32_t addr, unsigned count, unsigned size, unsigned burst) {
        check(size <= 3 && count >= 1 && count <= 16 && burst == 1, "DDR AXI burst format");
        check(uint64_t(addr) + (uint64_t(count) << size) <= BOARD_DDR_BYTES,
              "DDR address was not rebased into the configured aperture");
        check((addr & ((1U << size) - 1)) == 0 &&
              (addr & 4095U) + (count << size) <= 4096, "DDR alignment / 4 KiB boundary");
    }
    auto selected() {
        return std::find_if(pendingReads.begin(), pendingReads.end(),
                           [&](const Read& r) { return heldRead && r.sequence == *heldRead; });
    }
    template<class Dut> void drive(Dut &d, uint64_t cycle) {
        now = cycle;
        arReady = pendingReads.size() < DDR_READ_CREDITS && cycle % 7 != 2;
        awReady = pendingWrites.size() + pendingB.size() < 8 && cycle % 11 != 3;
        wReady = !pendingWrites.empty() && cycle % 5 != 1;
        if (!heldRead) {
            for (auto i = pendingReads.rbegin(); i != pendingReads.rend(); ++i)
                if (cycle >= i->due) { heldRead = i->sequence; heldReadData = memory[(i->address + (i->beat << i->size)) & ~7U]; break; }
        }
        auto r = selected();
        rValid = r != pendingReads.end();
        if (!heldB) for (auto i = pendingB.rbegin(); i != pendingB.rend(); ++i)
            if (cycle >= i->due) { heldB = i->sequence; break; }
        auto b = std::find_if(pendingB.begin(), pendingB.end(), [&](const Write& w) { return heldB && w.sequence == *heldB; });
        bValid = b != pendingB.end();
        d.set_io$$ddrAxi$$ar$$ready(arReady);
        d.set_io$$ddrAxi$$aw$$ready(awReady);
        d.set_io$$ddrAxi$$w$$ready(wReady);
        d.set_io$$ddrAxi$$r$$valid(rValid);
        d.set_io$$ddrAxi$$r$$bits$$data(rValid ? heldReadData : 0);
        d.set_io$$ddrAxi$$r$$bits$$id(rValid ? r->id : 0);
        d.set_io$$ddrAxi$$r$$bits$$resp(rValid && r->error && r->beat + 1 == r->count ? 2 : 0);
        d.set_io$$ddrAxi$$r$$bits$$last(rValid && r->beat + 1 == r->count);
        d.set_io$$ddrAxi$$b$$valid(bValid);
        d.set_io$$ddrAxi$$b$$bits$$id(bValid ? b->id : 0);
        d.set_io$$ddrAxi$$b$$bits$$resp(bValid && b->error ? 2 : 0);
    }
    template<class Dut> void sample(Dut &d) {
        // Observe AW only after DUT evaluation. Reading an unevaluated output
        // in drive() could inspect uninitialized generated-model state.
        writeWaiting = d.get_io$$ddrAxi$$aw$$valid() && !awReady;
        if (d.get_io$$ddrAxi$$ar$$valid()) {
            if (arReady) {
                const uint32_t addr = d.get_io$$ddrAxi$$ar$$bits$$addr();
                const unsigned count = d.get_io$$ddrAxi$$ar$$bits$$len() + 1;
                const unsigned size = d.get_io$$ddrAxi$$ar$$bits$$size();
                const unsigned id = d.get_io$$ddrAxi$$ar$$bits$$id();
                address(addr, count, size, d.get_io$$ddrAxi$$ar$$bits$$burst());
                for (const auto& r : pendingReads) check(r.id != id, "DDR live read ID reused");
                pendingReads.push_back({addr, count, size, id, 0, now + DDR_READ_LATENCY,
                                        sequence++, denyReadAddress && *denyReadAddress == addr});
                peakReadIds = std::max(peakReadIds, uint64_t(pendingReads.size()));
                ++reads; readBursts += count > 1;
            } else ++stalls;
        }
        if (d.get_io$$ddrAxi$$aw$$valid()) {
            if (awReady) {

                wAddr = d.get_io$$ddrAxi$$aw$$bits$$addr();
                wCount = d.get_io$$ddrAxi$$aw$$bits$$len() + 1;
                wSize = d.get_io$$ddrAxi$$aw$$bits$$size();
                wId = d.get_io$$ddrAxi$$aw$$bits$$id();
                address(wAddr, wCount, wSize, d.get_io$$ddrAxi$$aw$$bits$$burst());
                for (auto& w : pendingWrites) check(w.id != wId, "DDR live write ID reused");
                for (auto& w : pendingB) check(w.id != wId, "DDR live B ID reused");
                pendingWrites.push_back({wAddr,wCount,wSize,wId,0,denyWriteAddress && *denyWriteAddress == wAddr,0,sequence++});
                ++writes; writeBursts += wCount > 1;
            } else ++stalls;
        }
        if (d.get_io$$ddrAxi$$w$$valid()) {
            if (wReady) {
                check(!pendingWrites.empty(), "DDR W lacks address owner");
                auto& owner = pendingWrites.front();
                wAddr=owner.address; wCount=owner.count; wSize=owner.size; wId=owner.id; wBeat=owner.beat;
                check(wBeat < wCount, "DDR W overrun");
                check(bool(d.get_io$$ddrAxi$$w$$bits$$last()) == (wBeat + 1 == wCount), "DDR WLAST");
                auto &value = memory[(wAddr + (wBeat << wSize)) & ~7U];
                const uint64_t data = d.get_io$$ddrAxi$$w$$bits$$data();
                const unsigned mask = d.get_io$$ddrAxi$$w$$bits$$strb();
                for (unsigned lane = 0; lane < 8; ++lane)
                    if (mask & (1U << lane))
                        value = (value & ~(0xffULL << (8 * lane))) | (data & (0xffULL << (8 * lane)));
                ++wBeats; ++owner.beat;
                if (owner.beat == owner.count) {
                    owner.due = now + 32; // Benchmark mode: fixed WLAST-to-B eligibility, independent of ID.
                    pendingB.push_back(owner); pendingWrites.pop_front();
                }
            } else ++stalls;
        }
        if (rValid && d.get_io$$ddrAxi$$r$$ready()) {
            auto r = selected();
            check(r != pendingReads.end(), "DDR R lacks ID owner");
            if (r != pendingReads.begin()) ++reorderedBeats;
            ++rBeats; ++r->beat;
            if (r->beat == r->count) pendingReads.erase(r);
            else r->due = now + DDR_READ_BEAT_GAP;
            heldRead.reset();
        }
        if (bValid && d.get_io$$ddrAxi$$b$$ready()) {
            auto b = std::find_if(pendingB.begin(), pendingB.end(), [&](const Write& w) { return heldB && w.sequence == *heldB; });
            check(b != pendingB.end(), "DDR B lost owner");
            reorderedB += b != pendingB.begin(); pendingB.erase(b); heldB.reset(); ++bResponses;
        }
        writing = !pendingWrites.empty(); responding = !pendingB.empty();
        if (writing) { wBeat=pendingWrites.front().beat; wCount=pendingWrites.front().count; }
        const uint64_t writeLive = pendingWrites.size() + pendingB.size();
        peakWriteIds = std::max(peakWriteIds, writeLive);
        mixedCycles += !pendingReads.empty() && writeLive;
        twoReadTwoWriteCycles += pendingReads.size() >= 2 && writeLive >= 2;
    }
};
