#include "CircularFetchStorageGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>

using Dut = SCircularFetchStorageGsim;

// The correctness oracle is an ordered event deque, not a model of the DUT's
// bank, row, head, tail, write address, or read-selection implementation.
struct Payload {
    uint32_t instruction = 0;
    bool accessFault = false, pageFault = false;
    uint64_t faultAddress = 0, pc = 0, nextPc = 0;
};
struct Entry {
    Payload data;
    uint64_t tag = 0, capturedCycle = 0;
};
struct Observed { bool valid = false; Payload data; };

static void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error("CIRCULAR_FETCH_STORAGE_ORACLE " + message);
}
static uint64_t mix(uint64_t value) {
    value += UINT64_C(0x9e3779b97f4a7c15);
    value = (value ^ (value >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    value = (value ^ (value >> 27)) * UINT64_C(0x94d049bb133111eb);
    return value ^ (value >> 31);
}
static Payload payload(uint64_t tag) {
    // Independent, nonsequential full-width PCs and successors ensure storage
    // cannot reconstruct nextPc, truncate upper bits, or substitute a fault PC.
    if (tag == 1) return {0, false, false, 0, 0, UINT64_MAX};
    if (tag == 2) return {UINT32_MAX, true, true, UINT64_MAX, UINT64_MAX, 0};
    return {uint32_t(mix(tag ^ 0x1357)), bool(tag & 1), bool(tag & 2),
        mix(tag ^ UINT64_C(0x91357ace2468bdf0)), mix(tag),
        mix(tag ^ UINT64_C(0x7258deca13579bdf))};
}
static void drive(Dut &d, unsigned lane, bool valid, const Payload &p) {
#define LANE(N) case N: \
    d.set_io$$capture##N##$$valid(valid); \
    d.set_io$$capture##N##$$bits$$instruction(p.instruction); \
    d.set_io$$capture##N##$$bits$$accessFault(p.accessFault); \
    d.set_io$$capture##N##$$bits$$pageFault(p.pageFault); \
    d.set_io$$capture##N##$$bits$$faultAddress(p.faultAddress); \
    d.set_io$$capture##N##$$bits$$pc(p.pc); \
    d.set_io$$capture##N##$$bits$$nextPc(p.nextPc); break
    switch (lane) { LANE(0); LANE(1); default: require(false, "bad capture lane"); }
#undef LANE
}
static Observed read(Dut &d, unsigned lane) {
#define LANE(N) case N: return {bool(d.get_io$$lane##N##$$valid()), \
    {uint32_t(d.get_io$$lane##N##$$bits$$instruction()), \
    bool(d.get_io$$lane##N##$$bits$$accessFault()), \
    bool(d.get_io$$lane##N##$$bits$$pageFault()), \
    d.get_io$$lane##N##$$bits$$faultAddress(), d.get_io$$lane##N##$$bits$$pc(), \
    d.get_io$$lane##N##$$bits$$nextPc()}}
    switch (lane) { LANE(0); LANE(1); }
#undef LANE
    throw std::runtime_error("CIRCULAR_FETCH_STORAGE_ORACLE bad read lane");
}

struct Coverage {
    std::array<unsigned, 5> occupancy{};
    std::array<unsigned, 3> captured{}, consumed{}, lookahead{};
    std::array<unsigned, 4> faultClasses{};
    // All bits in all six fields must be observed as both zero and one.
    std::array<uint64_t, 6> ones{}, zeroes{};
    unsigned reads = 0, simultaneous = 0, partialConsume = 0, held = 0;
    unsigned full = 0, fullConsumeNoBorrow = 0, clippedNoBorrow = 0;
    unsigned cancels = 0, cancelWithBoth = 0, cancelOutputVisible = 0;
    unsigned cancelDeadWrites = 0, cancelImmediateRefill = 0;
    unsigned capturedEntries = 0, consumedEntries = 0, discardedEntries = 0;
    unsigned noBypass = 0, latencyOne = 0, resetDiscarded = 0;
    unsigned continuousTwo = 0, continuousRun = 0, longestContinuousRun = 0;
    unsigned singleTurnover = 0, wrapReadWitnesses = 0, wrapWriteWitnesses = 0;
    // Coverage only: event totals since reset/cancel mark modulo-four crossings.
    // They are never used to select an expected entry or drive an input credit.
    uint64_t removedEvents = 0, appendedEvents = 0;
    std::array<unsigned, 4> readStartResidue{}, writeStartResidue{};
    std::array<unsigned, 4> cancelledWriteStartResidue{};

    void observe(const Payload &p) {
        const std::array<uint64_t, 6> fields = {p.instruction, uint64_t(p.accessFault),
            uint64_t(p.pageFault), p.faultAddress, p.pc, p.nextPc};
        for (unsigned field = 0; field < fields.size(); ++field) {
            ones[field] |= fields[field]; zeroes[field] |= ~fields[field];
        }
        ++faultClasses[unsigned(p.accessFault) | (unsigned(p.pageFault) << 1)];
        ++reads;
    }
};

struct Driver {
    Dut dut;
    std::deque<Entry> queue;
    Coverage coverage;
    std::string injection;
    bool injected = false, cancelledLastCycle = false;
    uint64_t cycle = 0, nextTag = 1;

    explicit Driver(std::string mode) : injection(std::move(mode)) { reset(); }

    std::string where(const std::string &message) const {
        return message + " cycle=" + std::to_string(cycle);
    }
    void equal(uint64_t actual, uint64_t expected, const std::string &message,
        unsigned lane, uint64_t tag) const {
        if (actual == expected) return;
        std::ostringstream detail;
        detail << where(message) << " lane=" << lane << " tag=" << tag
               << " expected=0x" << std::hex << expected << " observed=0x" << actual;
        require(false, detail.str());
    }
    void reset() {
        for (unsigned lane = 0; lane < 2; ++lane) drive(dut, lane, false, {});
        dut.set_io$$consume0(0); dut.set_io$$consume1(0); dut.set_io$$cancel(0);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        coverage.resetDiscarded += queue.size(); queue.clear();
        coverage.removedEvents = coverage.appendedEvents = 0;
        cancelledLastCycle = false;
    }

    // offer is the desired supply prefix, not an already accepted count. The
    // external caller contract admits only old free capacity, even with consume.
    // This fixture checks storage under that contract; admission gating itself
    // belongs to the enclosing RegisteredFetchPacket integration check.
    void tick(unsigned offer, unsigned consume, bool cancel = false, bool continuous = false) {
        const unsigned oldCount = queue.size();
        require(offer <= 2 && consume <= std::min(2U, oldCount), where("illegal test prefix"));
        const unsigned capture = std::min(offer, 4U - oldCount);
        std::array<Entry, 2> incoming{};
        for (unsigned lane = 0; lane < 2; ++lane) {
            incoming[lane] = {payload(nextTag), nextTag, cycle}; ++nextTag;
            // Invalid input bits deliberately change too. They must neither
            // overwrite live entries nor become visible after a cancellation.
            drive(dut, lane, lane < capture, incoming[lane].data);
        }
        dut.set_io$$consume0(consume > 0); dut.set_io$$consume1(consume > 1);
        dut.set_io$$cancel(cancel);
        dut.step();

        // GSIM step() exposes the pre-edge combinational observation, matching
        // the repository's existing event-ledger hosts. Apply events only after
        // checking all old entries, including on the cancel cycle itself.
        equal(dut.get_io$$occupancy(), oldCount, "occupancy mismatch", 0, 0);
        std::array<Observed, 2> observed = {read(dut, 0), read(dut, 1)};
        if (!injected && injection == "--inject-read-slot" && oldCount >= 2) {
            std::cerr << "INJECT read-slot\n";
            observed[0] = observed[1]; injected = true;
        }
        if (!injected && injection == "--inject-next-pc" && oldCount != 0) {
            std::cerr << "INJECT next-pc\n";
            observed[0].data.nextPc ^= UINT64_C(1) << 63; injected = true;
        }
        for (unsigned lane = 0; lane < 2; ++lane) {
            require(observed[lane].valid == (lane < oldCount), where("output prefix validity mismatch"));
            if (lane >= oldCount) continue;
            const auto &wanted = queue[lane];
            const auto &actual = observed[lane].data;
            require(wanted.capturedCycle < cycle, where("less than one-cycle latency"));
            equal(actual.pc, wanted.data.pc, "read-slot pc mismatch", lane, wanted.tag);
            equal(actual.instruction, wanted.data.instruction, "instruction mismatch", lane, wanted.tag);
            equal(actual.accessFault, wanted.data.accessFault, "access-fault mismatch", lane, wanted.tag);
            equal(actual.pageFault, wanted.data.pageFault, "page-fault mismatch", lane, wanted.tag);
            equal(actual.faultAddress, wanted.data.faultAddress, "fault-address mismatch", lane, wanted.tag);
            equal(actual.nextPc, wanted.data.nextPc, "next-pc mismatch", lane, wanted.tag);
            coverage.observe(actual);
            coverage.latencyOne += wanted.capturedCycle + 1 == cycle;
        }
        const std::array<uint64_t, 3> lookahead = {dut.get_io$$lookaheadPc0(),
            dut.get_io$$lookaheadPc1(), dut.get_io$$lookaheadPc2()};
        for (unsigned offset = 0; offset < std::min(3U, oldCount); ++offset) {
            equal(lookahead[offset], queue[offset].data.pc, "lookahead-pc mismatch", offset, queue[offset].tag);
            ++coverage.lookahead[offset];
        }

        ++coverage.occupancy[oldCount]; ++coverage.captured[capture]; ++coverage.consumed[consume];
        coverage.simultaneous += capture != 0 && consume != 0 && !cancel;
        coverage.partialConsume += consume == 1 && oldCount >= 2 && !cancel;
        coverage.held += oldCount != 0 && consume == 0 && !cancel;
        coverage.full += oldCount == 4;
        coverage.fullConsumeNoBorrow += oldCount == 4 && offer != 0 && consume != 0 && capture == 0;
        coverage.clippedNoBorrow += oldCount == 3 && offer == 2 && consume != 0 && capture == 1;
        coverage.noBypass += oldCount == 0 && capture != 0;
        coverage.cancels += cancel;
        coverage.cancelWithBoth += cancel && capture != 0 && consume != 0;
        coverage.cancelOutputVisible += cancel && oldCount != 0;
        coverage.cancelImmediateRefill += cancelledLastCycle && oldCount == 0 && capture != 0 && !cancel;
        if (continuous) {
            require(oldCount == 2 && capture == 2 && consume == 2 && !cancel,
                where("continuous two-wide witness inserted a bubble"));
            ++coverage.continuousTwo; ++coverage.continuousRun;
            coverage.longestContinuousRun = std::max(coverage.longestContinuousRun, coverage.continuousRun);
        } else coverage.continuousRun = 0;
        coverage.singleTurnover += capture == 1 && consume == 1 && !cancel;

        if (cancel) {
            coverage.cancelDeadWrites += capture;
            if (capture) ++coverage.cancelledWriteStartResidue[coverage.appendedEvents % 4];
            coverage.discardedEntries += oldCount + capture;
            coverage.capturedEntries += capture;
            queue.clear();
            coverage.removedEvents = coverage.appendedEvents = 0;
        } else {
            if (consume) {
                ++coverage.readStartResidue[coverage.removedEvents % 4];
                coverage.wrapReadWitnesses += coverage.removedEvents / 4 != (coverage.removedEvents + consume) / 4;
            }
            if (capture) {
                ++coverage.writeStartResidue[coverage.appendedEvents % 4];
                coverage.wrapWriteWitnesses += coverage.appendedEvents / 4 != (coverage.appendedEvents + capture) / 4;
            }
            coverage.removedEvents += consume; coverage.appendedEvents += capture;
            coverage.consumedEntries += consume; coverage.capturedEntries += capture;
            for (unsigned lane = 0; lane < consume; ++lane) queue.pop_front();
            for (unsigned lane = 0; lane < capture; ++lane) queue.push_back(incoming[lane]);
        }
        require(queue.size() <= 4, where("oracle capacity overflow"));
        cancelledLastCycle = cancel;
        ++cycle;
    }
    void drain() {
        while (!queue.empty()) tick(0, std::min(2U, unsigned(queue.size())));
        tick(0, 0); // Observe the terminal empty state, not merely the last pop.
    }
    void run() {
        // Fill all four slots, then release a full queue without borrowing its
        // consume credit. Next exercise a one-credit clip and partial joins.
        tick(2, 0); tick(2, 0); tick(2, 2);
        tick(2, 1); tick(2, 1); tick(0, 2); tick(0, 1);
        tick(1, 0); tick(0, 0); tick(1, 0); tick(0, 0); tick(0, 1); tick(0, 1);

        tick(2, 0);
        for (unsigned n = 0; n < 64; ++n) tick(2, 2, false, true);
        // Seventeen single-entry turns visit every start position, wrap both
        // histories repeatedly, and shift parity before the next two-wide run.
        for (unsigned n = 0; n < 17; ++n) tick(1, 1);
        for (unsigned n = 0; n < 64; ++n) tick(2, 2, false, true);
        drain();

        // Each occupancy gets an edge cancellation. At occupancies 1..3 this
        // includes valid capture AND consume, while pre-edge output stays live.
        for (unsigned count = 0; count <= 4; ++count) {
            while (queue.size() < count) tick(std::min(2U, count - unsigned(queue.size())), 0);
            tick(2, std::min(2U, count), true);
            tick(2, 0); drain(); // Immediate refill must not expose cancelled writes.
        }

        // Cancel with two live owners and two dead captures at EVERY old-tail
        // residue, including a dead write across slot 3 -> 0. The following
        // cycle already captures a fresh pair at reset ownership. Invalid old
        // payload is deliberately not required to clear or read as zero.
        for (unsigned start = 0; start < 4; ++start) {
            tick(0, 0, true);
            for (unsigned n = 0; n < start; ++n) { tick(1, 0); tick(0, 1); }
            tick(2, 0);
            tick(2, 1, true);
            tick(2, 0); drain();
        }

        uint64_t random = UINT64_C(0xa18e53047692dcfb);
        for (unsigned n = 0; n < 512; ++n) {
            random = mix(random);
            const unsigned offer = random % 3;
            const unsigned available = std::min(2U, unsigned(queue.size()));
            const unsigned consume = (random >> 12) % (available + 1);
            tick(offer, consume, (random >> 24) % 41 == 0);
        }
        drain();
        tick(2, 0); reset(); tick(0, 0);
        validate();
        report();
    }
    void validate() const {
        const auto &c = coverage;
        require(cycle <= 1000 && queue.empty(), "bounded run did not finish empty");
        require(injection.empty() && !injected, "requested injection did not reach its witness");
        require(c.capturedEntries == c.consumedEntries + c.discardedEntries + c.resetDiscarded,
            "captured/consumed/cancelled/reset event conservation mismatch");
        for (unsigned n = 0; n < 5; ++n) require(c.occupancy[n] != 0, "missing occupancy coverage");
        for (unsigned n = 0; n < 3; ++n) {
            require(c.captured[n] && c.consumed[n], "missing capture/consume prefix coverage");
            require(c.lookahead[n], "missing lookahead position coverage");
        }
        for (unsigned n = 0; n < 4; ++n) {
            require(c.faultClasses[n], "missing access/page fault combination");
            require(c.readStartResidue[n] && c.writeStartResidue[n], "missing modulo-four event start coverage");
            require(c.cancelledWriteStartResidue[n], "missing cancelled-write old-tail residue");
        }
        const std::array<uint64_t, 6> masks = {UINT32_MAX, 1, 1, UINT64_MAX, UINT64_MAX, UINT64_MAX};
        for (unsigned field = 0; field < masks.size(); ++field)
            require((c.ones[field] & masks[field]) == masks[field] &&
                (c.zeroes[field] & masks[field]) == masks[field], "payload bit polarity coverage missing");
        require(c.continuousTwo == 128 && c.longestContinuousRun == 64,
            "continuous two-instructions-per-cycle witness incomplete");
        require(c.singleTurnover >= 17 && c.wrapReadWitnesses >= 8 && c.wrapWriteWitnesses >= 8,
            "single/dual turnover or wrap coverage missing");
        require(c.simultaneous >= 128 && c.partialConsume >= 17 && c.held > 0 && c.full > 0,
            "simultaneous/partial/stall/full coverage missing");
        require(c.fullConsumeNoBorrow > 0 && c.clippedNoBorrow > 0,
            "registered-only capture credit stimulus missing");
        require(c.cancels >= 5 && c.cancelWithBoth >= 3 && c.cancelOutputVisible >= 4 &&
            c.resetDiscarded == 2 && c.noBypass > 0 && c.latencyOne >= 256,
            "cancel/reset/no-bypass/minimum-latency coverage missing");
        require(c.cancelDeadWrites >= 8 && c.cancelImmediateRefill >= 9,
            "cancelled old-tail writes/immediate fresh capture coverage missing");
    }
    void report() const {
        const auto &c = coverage;
        std::cout << "PASS CIRCULAR_FETCH_STORAGE cycles=" << cycle << " reads=" << c.reads
            << " captured=" << c.capturedEntries << " consumed=" << c.consumedEntries
            << " discarded=" << c.discardedEntries << " reset_discarded=" << c.resetDiscarded
            << " simultaneous=" << c.simultaneous << " partial_consume=" << c.partialConsume
            << " held=" << c.held << " full=" << c.full
            << " full_consume_no_borrow=" << c.fullConsumeNoBorrow << " clipped_no_borrow=" << c.clippedNoBorrow
            << " cancel=" << c.cancels << " cancel_with_both=" << c.cancelWithBoth
            << " cancel_output_visible=" << c.cancelOutputVisible << " cancel_dead_writes=" << c.cancelDeadWrites
            << " cancel_immediate_refill=" << c.cancelImmediateRefill << " no_bypass=" << c.noBypass
            << " latency_one=" << c.latencyOne << " continuous2_cycles=" << c.continuousTwo
            << " continuous2_longest=" << c.longestContinuousRun << " single_turnover=" << c.singleTurnover
            << " wrap_read=" << c.wrapReadWitnesses << " wrap_write=" << c.wrapWriteWitnesses
            << " payload_bits_both_polarities=226";
        for (unsigned n = 0; n < 5; ++n) std::cout << " occupancy" << n << '=' << c.occupancy[n];
        for (unsigned n = 0; n < 3; ++n)
            std::cout << " capture" << n << '=' << c.captured[n] << " consume" << n << '=' << c.consumed[n]
                << " lookahead" << n << '=' << c.lookahead[n];
        for (unsigned n = 0; n < 4; ++n)
            std::cout << " fault" << n << '=' << c.faultClasses[n]
                << " read_residue" << n << '=' << c.readStartResidue[n]
                << " write_residue" << n << '=' << c.writeStartResidue[n]
                << " cancelled_write_residue" << n << '=' << c.cancelledWriteStartResidue[n];
        std::cout << '\n';
    }
};

int main(int argc, char **argv) {
    try {
        const std::string mode = argc == 2 ? argv[1] : "";
        require(argc <= 2 && (mode.empty() || mode == "--inject-read-slot" || mode == "--inject-next-pc"),
            "usage: run [--inject-read-slot|--inject-next-pc]");
        Driver driver(mode); driver.run();
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
