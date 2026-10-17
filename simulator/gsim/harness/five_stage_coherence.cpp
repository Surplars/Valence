#include "I1CoherentPairGsim.h"
#include <array>
#include <algorithm>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#ifndef I1_PAIR_CACHE_BYTES
#define I1_PAIR_CACHE_BYTES 256
#endif

static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

struct Events {
    std::array<unsigned, 2> probes{}, dirtyBeats{}, releaseBeats{};
    unsigned burstWriteBeats = 0, readDuringWrite = 0, acquireDuringRelease = 0, acquireDuringRead = 0;
    void sample(SI1CoherentPairGsim &dut) {
        probes[0] += dut.get_io$$probe0();
        probes[1] += dut.get_io$$probe1();
        dirtyBeats[0] += dut.get_io$$dirtyProbe0();
        dirtyBeats[1] += dut.get_io$$dirtyProbe1();
        releaseBeats[0] += dut.get_io$$releaseData0();
        releaseBeats[1] += dut.get_io$$releaseData1();
        burstWriteBeats += dut.get_io$$burstWriteBeat();
        readDuringWrite += dut.get_io$$readDuringWrite();
        acquireDuringRelease += dut.get_io$$acquireDuringRelease();
        acquireDuringRead += dut.get_io$$acquireDuringRead();
    }
};

static void drive(SI1CoherentPairGsim &dut, unsigned agent, bool valid, uint64_t address = 0,
                  bool write = false, uint64_t data = 0, bool responseReady = true) {
#define DRIVE_AGENT(name) \
    dut.set_io$$##name##$$request$$valid(valid); \
    dut.set_io$$##name##$$request$$bits$$atomic(0); \
    dut.set_io$$##name##$$request$$bits$$atomicOp(0); \
    dut.set_io$$##name##$$request$$bits$$address(address); \
    dut.set_io$$##name##$$request$$bits$$write(write); \
    dut.set_io$$##name##$$request$$bits$$size(3); \
    dut.set_io$$##name##$$request$$bits$$data(data); \
    dut.set_io$$##name##$$request$$bits$$mask(255); \
    dut.set_io$$##name##$$request$$bits$$virtualized(0); \
    dut.set_io$$##name##$$request$$bits$$uncached(0); \
    dut.set_io$$##name##$$response$$ready(responseReady)
    switch (agent) {
        case 0: DRIVE_AGENT(hart0); break;
        case 1: DRIVE_AGENT(hart1); break;
        case 2: DRIVE_AGENT(uncached); break;
        default: throw std::runtime_error("invalid agent");
    }
#undef DRIVE_AGENT
}

static bool requestReady(SI1CoherentPairGsim &dut, unsigned agent) {
    switch (agent) {
        case 0: return dut.get_io$$hart0$$request$$ready();
        case 1: return dut.get_io$$hart1$$request$$ready();
        default: return dut.get_io$$uncached$$request$$ready();
    }
}

static bool responseValid(SI1CoherentPairGsim &dut, unsigned agent) {
    switch (agent) {
        case 0: return dut.get_io$$hart0$$response$$valid();
        case 1: return dut.get_io$$hart1$$response$$valid();
        default: return dut.get_io$$uncached$$response$$valid();
    }
}

static uint64_t responseData(SI1CoherentPairGsim &dut, unsigned agent) {
    switch (agent) {
        case 0: return dut.get_io$$hart0$$response$$bits$$data();
        case 1: return dut.get_io$$hart1$$response$$bits$$data();
        default: return dut.get_io$$uncached$$response$$bits$$data();
    }
}

static bool responseError(SI1CoherentPairGsim &dut, unsigned agent) {
    switch (agent) {
        case 0: return dut.get_io$$hart0$$response$$bits$$error();
        case 1: return dut.get_io$$hart1$$response$$bits$$error();
        default: return dut.get_io$$uncached$$response$$bits$$error();
    }
}

static uint64_t transact(SI1CoherentPairGsim &dut, Events &events, unsigned agent,
                         uint64_t address, bool write = false, uint64_t data = 0) {
    bool accepted = false;
    for (unsigned cycle = 0; cycle < 4000; ++cycle) {
        drive(dut, agent, !accepted, address, write, data);
        dut.step();
        events.sample(dut);
        if (!accepted && requestReady(dut, agent)) accepted = true;
        if (responseValid(dut, agent)) {
            check(accepted && !responseError(dut, agent), "transaction failed or responded before acceptance");
            drive(dut, agent, false);
            return responseData(dut, agent);
        }
    }
    throw std::runtime_error("transaction timed out");
}

static void consecutiveReadHits(SI1CoherentPairGsim &dut, Events &events,
                                uint64_t address, uint64_t expected) {
    constexpr unsigned count = 32;
    unsigned accepted = 0, completed = 0, cycles = 0;
    while (completed < count && cycles < 100) {
        drive(dut, 0, accepted < count, address);
        dut.step();
        events.sample(dut);
        if (accepted < count && requestReady(dut, 0)) ++accepted;
        if (responseValid(dut, 0)) {
            check(!responseError(dut, 0) && responseData(dut, 0) == expected,
                  "pipelined read hit returned wrong data");
            ++completed;
        }
        ++cycles;
    }
    drive(dut, 0, false);
    check(accepted == count && completed == count && cycles <= count + 2,
          "read hits did not sustain one request per cycle");

    // A held CPU response must cap accepted reads at the two available response slots.
    unsigned stalledAccepted = 0;
    for (unsigned cycle = 0; cycle < 5; ++cycle) {
        drive(dut, 0, stalledAccepted < 3, address, false, 0, false);
        dut.step();
        events.sample(dut);
        if (stalledAccepted < 3 && requestReady(dut, 0)) ++stalledAccepted;
    }
    check(stalledAccepted ==
#ifdef I1_ORDERED_ADMISSION
          1,
#else
          2,
#endif
          "read-hit backpressure overfilled the configured response ownership");
    unsigned drained = 0;
    for (unsigned cycle = 0; cycle < 20 && drained < 3; ++cycle) {
        drive(dut, 0, stalledAccepted < 3, address);
        dut.step();
        events.sample(dut);
        if (stalledAccepted < 3 && requestReady(dut, 0)) ++stalledAccepted;
        if (responseValid(dut, 0)) {
            check(!responseError(dut, 0) && responseData(dut, 0) == expected,
                  "held read-hit response was lost or corrupted");
            ++drained;
        }
    }
    drive(dut, 0, false);
    check(stalledAccepted == 3 && drained == 3, "read-hit queue did not drain after backpressure");
}

static void readHitsBehindMiss(SI1CoherentPairGsim &dut, Events &events,
                               uint64_t missAddress, uint64_t missData,
                               uint64_t hitAddress, uint64_t hitData) {
    unsigned accepted = 0, completed = 0;
    unsigned firstReplyAt = 500, secondAcceptedAt = 500;
    bool overlap = false;
    for (unsigned cycle = 0; cycle < 500 && completed < 3; ++cycle) {
        drive(dut, 0, accepted < 3, accepted == 0 ? missAddress : hitAddress);
        dut.step();
        events.sample(dut);
        if (accepted < 3 && requestReady(dut, 0)) {
            ++accepted;
            if (accepted == 2) secondAcceptedAt = cycle;
            // A real older response and replacement accepted at the SAME
            // edge share the original owner; this is not hit-under-miss.
            overlap |= accepted >= 2 && completed == 0 && !responseValid(dut, 0);
        }
        if (responseValid(dut, 0)) {
            if (completed == 0) firstReplyAt = cycle;
            check(accepted > completed && !responseError(dut, 0) &&
                  responseData(dut, 0) == (completed == 0 ? missData : hitData),
                  "read hit passed an older miss or returned wrong data");
            ++completed;
        }
    }
    drive(dut, 0, false);
    check(accepted == 3 && completed == 3 &&
#ifdef I1_ORDERED_ADMISSION
          !overlap,
#else
          overlap,
#endif
          "independent read hits did not complete behind the older miss");
#ifdef I1_ORDERED_ADMISSION
    check(secondAcceptedAt >= firstReplyAt,
          "ordered replacement was admitted before the actual older miss reply");
#ifdef I1_MISS_TURNOVER
    check(secondAcceptedAt == firstReplyAt,
          "configured miss turnover never consumed-and-replaced the original owner");
#endif
#endif
}

static void simultaneousRead(SI1CoherentPairGsim &dut, Events &events,
                             uint64_t address, uint64_t expected) {
    std::array<bool, 2> accepted{}, completed{};
    for (unsigned cycle = 0; cycle < 8000 && (!completed[0] || !completed[1]); ++cycle) {
        for (unsigned agent = 0; agent < 2; ++agent)
            drive(dut, agent, !accepted[agent], address);
        dut.step();
        events.sample(dut);
        for (unsigned agent = 0; agent < 2; ++agent) {
            if (!accepted[agent] && requestReady(dut, agent)) accepted[agent] = true;
            if (!completed[agent] && responseValid(dut, agent)) {
                check(accepted[agent] && !responseError(dut, agent) &&
                      responseData(dut, agent) == expected, "simultaneous read returned stale data");
                completed[agent] = true;
            }
        }
    }
    check(completed[0] && completed[1], "simultaneous acquire did not complete");
    drive(dut, 0, false);
    drive(dut, 1, false);
}

static void flushAll(SI1CoherentPairGsim &dut, Events &events) {
    bool done0 = false, done1 = false;
    for (unsigned i = 0; i < 8000 && (!done0 || !done1); ++i) {
        dut.set_io$$flush0(!done0); dut.set_io$$flush1(!done1);
        dut.step(); events.sample(dut);
        done0 |= dut.get_io$$flushDone0(); done1 |= dut.get_io$$flushDone1();
    }
    dut.set_io$$flush0(0); dut.set_io$$flush1(0);
    check(done0 && done1, "clean and dirty flush bounded completion");
    for (unsigned i = 0; i < 3; ++i) { dut.step(); events.sample(dut); }
}

static void independentReads(SI1CoherentPairGsim &dut, Events &events, uint64_t base) {
    constexpr std::array<uint64_t, 2> values{0xa13579bd2468ace0ULL, 0x5eca8642db975310ULL};
    flushAll(dut, events);
    for (unsigned i=0; i<2; ++i) transact(dut, events, 2, base + 64*i, true, values[i]);
    std::array<bool, 2> accepted{}, completed{};
    for (unsigned cycle=0; cycle<8000 && (!completed[0] || !completed[1]); ++cycle) {
        for (unsigned i=0; i<2; ++i)
            drive(dut, i, !accepted[i], base+64*i, false, 0, cycle>80 && cycle%4!=i);
        dut.step(); events.sample(dut);
        for (unsigned i=0; i<2; ++i) {
            if (!accepted[i] && requestReady(dut,i)) accepted[i]=true;
            if (responseValid(dut,i) && cycle>80 && cycle%4!=i) {
                check(accepted[i] && !completed[i] && !responseError(dut,i) &&
                    responseData(dut,i)==values[i], "independent paired-read payload/order oracle");
                completed[i]=true;
            }
        }
    }
    check(completed[0] && completed[1], "paired-read bounded completion under asymmetric stalls");
    for (unsigned i=0; i<2; ++i) drive(dut,i,false);
#ifdef I1_READ_OVERLAP
    check(events.acquireDuringRead>0, "second independent Home read was still serialized through E");
#endif
    flushAll(dut, events);
}

static uint64_t atomicTransaction(SI1CoherentPairGsim &dut, Events &events,
                                 uint64_t address, unsigned op, uint64_t operand, unsigned size = 3) {
    bool accepted = false;
    for (unsigned cycle = 0; cycle < 8000; ++cycle) {
        drive(dut, 0, !accepted, address, op != 2, operand);
        dut.set_io$$hart0$$request$$bits$$atomic(1);
        dut.set_io$$hart0$$request$$bits$$atomicOp(op);
        dut.set_io$$hart0$$request$$bits$$size(size);
        dut.set_io$$hart0$$request$$bits$$mask(size == 3 ? 255 : 15 << (address & 7));
        dut.step(); events.sample(dut);
        if (!accepted && requestReady(dut, 0)) accepted = true;
        if (responseValid(dut, 0)) {
            check(accepted && !responseError(dut, 0), "atomic adapter response/permission oracle");
            const auto result = responseData(dut, 0);
            drive(dut, 0, false);
            return result;
        }
    }
    throw std::runtime_error("atomic coherent request bounded completion");
}

static void ordinaryStream(SI1CoherentPairGsim &dut, Events &events, bool mutate) {
    // Four native credits, no cache capacity/transaction expansion. Cross from
    // writes to reads with old replies still live; inject held reply periods.
    constexpr unsigned count = 128;
    constexpr uint64_t base = 0x80010c00ULL, pattern = 0x564c160000000000ULL;
    std::deque<unsigned> owners;
    unsigned sent = 0, completed = 0, peak = 0, homePeak = 0, homeWritePeak = 0, cycles = 0;
    std::optional<uint64_t> held;
    for (; cycles < 30000 && completed < 2 * count; ++cycles) {
        const bool valid = sent < 2 * count && owners.size() < 4;
        const bool writing = sent < count;
        const unsigned index = sent % count;
        const bool ready = cycles > 35 && cycles % 11 >= 3;
        drive(dut, 2, valid, base + index * 8, writing, pattern + index, ready);
        dut.step(); events.sample(dut);
        if (valid && requestReady(dut, 2)) {
            owners.push_back(sent++);
            peak = std::max(peak, unsigned(owners.size()));
        }
        const bool reply = responseValid(dut, 2);
        if (held) check(reply && responseData(dut, 2) == *held,
                        "ordinary cohort reply changed under backpressure");
        held.reset();
        if (reply) {
            check(!owners.empty() && !responseError(dut, 2), "ordinary cohort reply has no real owner");
            const auto n = owners.front();
            const uint64_t expected = n < count ? 0 : pattern + n % count;
            check(responseData(dut, 2) == (mutate && n == count ? expected ^ 1 : expected),
                  "independent ordinary cohort byte/order oracle");
            if (ready) { owners.pop_front(); ++completed; }
            else held = responseData(dut, 2);
        }
        homePeak = std::max(homePeak, unsigned(dut.get_io$$ordinaryOutstanding()));
        if (sent < count) homeWritePeak = std::max(homeWritePeak, unsigned(dut.get_io$$ordinaryOutstanding()));
    }
    drive(dut, 2, false);
    check(sent == 2 * count && completed == sent && owners.empty() && peak == 4,
          "ordinary cohort bounded completion/four-credit coverage");
#ifdef I1_HOME_WRITE_PIPELINE
    check(homeWritePeak >= 2, "pipelined Home did not exploit its existing ordinary write owners");
#endif
    std::cout << "I1_HOME_STREAM_PASS bytes_each_direction=" << count * 8
              << " cycles=" << cycles << " native_credits=" << peak << " home_peak=" << homePeak
              << " home_write_peak=" << homeWritePeak << '\n';
}

static void adjacentHitMetadata(SI1CoherentPairGsim &dut, Events &events) {
#ifdef I1_ORDERED_ADMISSION
    constexpr uint64_t base = 0x80010000ULL, value = 0x564c1800abcdef01ULL;
    constexpr uint64_t stride = I1_PAIR_CACHE_BYTES / 2;
    for (bool bypass : {true, false}) {
        flushAll(dut, events);
        for (unsigned i = 0; i < 3; ++i)
            transact(dut, events, 2, base + i * stride, true, value + i);
        transact(dut, events, 0, base);
        if (!bypass) transact(dut, events, 0, base + stride);
        const auto dirtyReleases = events.releaseBeats[0];
        unsigned sent = 0, completed = 0;
        std::array<unsigned, 2> acceptedAt{};
        for (unsigned cycle = 0; cycle < 8000 && completed < 2; ++cycle) {
            const bool writing = sent == 0;
            drive(dut, 0, sent < 2, writing || bypass ? base : base + 2 * stride,
                  writing, value ^ 0x55);
            dut.set_io$$hart0$$request$$bits$$uncached(!writing && bypass);
            dut.step(); events.sample(dut);
            if (sent < 2 && requestReady(dut, 0)) acceptedAt[sent++] = cycle;
            if (responseValid(dut, 0)) {
                const auto expected = completed == 0 ? 0 : bypass ? value ^ 0x55 : value + 2;
                check(sent > completed && !responseError(dut, 0) && responseData(dut, 0) == expected,
                      "independent adjacent hit metadata byte/order oracle");
                ++completed;
            }
        }
        drive(dut, 0, false);
        check(sent == 2 && completed == 2 && acceptedAt[1] == acceptedAt[0] + 1,
              "adjacent hit metadata stimulus did not exercise consume-and-replace");
        if (!bypass)
            check(events.releaseBeats[0] == dirtyReleases,
                  "deferred LRU lost its most recent dirty owner");
        check(transact(dut, events, 2, base) == (value ^ 0x55),
              "pending dirty hit did not reach bypass/probe backing memory");
    }
    std::cout << "I1_ADJACENT_METADATA_PASS dirty_bypass=1 MRU_forward=1 consecutive_hit_handoff=1\n";
#endif
}

int main(int argc, char **argv) {
    try {
        const bool wrong = argc > 1 && std::string(argv[1]) == "--wrong-data";
        const bool wrongStream = argc > 1 && std::string(argv[1]) == "--wrong-stream";
        constexpr uint64_t base = 0x80010000;
        constexpr uint64_t a0 = 0x1111222233334444ULL;
        constexpr uint64_t a1 = 0xaaaabbbbccccddddULL;
        constexpr uint64_t a2 = 0x0123456789abcdefULL;
        constexpr uint64_t a3 = 0xfedcba9876543210ULL;
        constexpr uint64_t b0 = 0x5555666677778888ULL;
        constexpr uint64_t b1 = 0x9999aaaabbbbccccULL;
        static SI1CoherentPairGsim dut;
        Events events;
        dut.set_io$$flush0(0); dut.set_io$$flush1(0);
        for (unsigned i = 0; i < 3; ++i) drive(dut, i, false);
        dut.set_reset(1);
        dut.step();
        dut.step();
        dut.set_reset(0);

        independentReads(dut, events, base+128);

        transact(dut, events, 2, base, true, a0);
        transact(dut, events, 2, base + 64, true, b0);
        check(transact(dut, events, 0, base) == a0, "hart 0 initial fill failed");
        consecutiveReadHits(dut, events, base, a0);
        readHitsBehindMiss(dut, events, base + 64, b0, base, a0);
        transact(dut, events, 0, base, true, a1);
        const uint64_t firstMigrationStart = dut.cycles;
        check(transact(dut, events, 1, base) == (wrong ? a1 ^ 1 : a1),
              "independent dirty-owner byte oracle");
        const uint64_t firstMigrationCycles = dut.cycles - firstMigrationStart;
        check(events.probes[0] && events.dirtyBeats[0] == 8,
              "hart 0 did not return a complete dirty ProbeAckData");
        transact(dut, events, 1, base, true, a2);
        const uint64_t secondMigrationStart = dut.cycles;
        check(transact(dut, events, 0, base) == a2, "hart 0 missed hart 1 dirty data");
        const uint64_t secondMigrationCycles = dut.cycles - secondMigrationStart;
        check(events.probes[1] && events.dirtyBeats[1] == 8,
              "hart 1 did not return a complete dirty ProbeAckData");
        transact(dut, events, 0, base, true, a2);

        check(transact(dut, events, 1, base + 64) == b0, "hart 1 second line fill failed");
        transact(dut, events, 1, base + 64, true, b1);
        check(transact(dut, events, 2, base) == a2, "uncached agent missed hart 0 data");
        check(transact(dut, events, 2, base + 64) == b1,
              "uncached agent probed the wrong owner");
        check(events.dirtyBeats[0] == 16 && events.dirtyBeats[1] == 16,
              "uncached reads did not probe both owners");

        check(transact(dut, events, 0, base) == a2, "hart 0 reacquire failed");
        transact(dut, events, 0, base, true, a3);
#ifdef I1_COHERENT_TWO_WAY
        transact(dut, events, 0, base + I1_PAIR_CACHE_BYTES / 2, true, 0xdeadbeefULL);
#endif
        transact(dut, events, 0, base + I1_PAIR_CACHE_BYTES, true, 0xdeadbeefULL);
        check(events.releaseBeats[0] == 8, "dirty eviction did not ReleaseData");
        check(transact(dut, events, 2, base) == a3, "released dirty data was not committed");
        simultaneousRead(dut, events, base, a3);
        check(events.probes[0] >= 2 && events.probes[1] >= 2,
              "simultaneous line ownership did not probe the previous hart");
        check(events.burstWriteBeats == events.dirtyBeats[0] + events.dirtyBeats[1] +
                  events.releaseBeats[0] + events.releaseBeats[1],
              "dirty line writes did not use complete 64-byte PutFullData bursts");

        // A DMA write must revoke even a CLEAN owner before it changes memory.
        transact(dut, events, 2, base, true, b0);
        check(transact(dut, events, 0, base) == b0, "DMA write did not invalidate CPU clean line");
        transact(dut, events, 0, base, true, b1);
        transact(dut, events, 2, base, true, a0);
        check(transact(dut, events, 1, base) == a0, "DMA overwrite lost dirty probe ordering");
        flushAll(dut, events);
        // Clean releases must remove directory ownership too (FENCE.I case).
        check(transact(dut, events, 0, base) == a0, "clean line reacquire after flush");
        const auto probesBeforeCleanFlush = events.probes[0] + events.probes[1];
        flushAll(dut, events);
        transact(dut, events, 2, base, true, a2);
        check(events.probes[0] + events.probes[1] == probesBeforeCleanFlush,
              "clean flush left a phantom directory owner");
        check(transact(dut, events, 0, base) == a2, "post-flush stale instruction/data line");
        // Repeated set aliases exercise the bounded directory; never a DDR-sized
        // directory or extra MSHR is needed to remember invalidated owners.
        for (unsigned i = 0; i < 24; ++i) {
            const uint64_t stride = I1_PAIR_CACHE_BYTES / 2;
            const uint64_t backing = I1_PAIR_CACHE_BYTES * 4 < 4096 ? 4096 : I1_PAIR_CACHE_BYTES * 4;
            const uint64_t addr = base + ((i * stride) % backing);
            const uint64_t value = 0x5631000000000000ULL + i;
            transact(dut, events, i & 1, addr, true, value);
            check(transact(dut, events, 2, addr) == value, "bounded directory alias byte oracle");
        }
        flushAll(dut, events);
        // A real DMA write invalidates LR/SC even after the private line has
        // been evicted for the LR bypass; Probe alone is not sufficient.
        transact(dut, events, 2, base, true, 10);
        check(transact(dut, events, 0, base) == 10, "LR dirty/clean prerequisite");
        check(atomicTransaction(dut, events, base, 2, 0) == 10, "LR.D coherent read");
        transact(dut, events, 2, base, true, 20);
        check(atomicTransaction(dut, events, base, 3, 30) == 1, "DMA write must fail SC.D");
        check(transact(dut, events, 2, base) == 20, "failed SC changed DMA data");
        check(atomicTransaction(dut, events, base, 2, 0) == 20, "LR.D re-establish");
        check(atomicTransaction(dut, events, base, 3, 30) == 0, "uncontended SC.D success");
        check(atomicTransaction(dut, events, base, 0, 12) == 30, "AMOADD.D old value");
        check(transact(dut, events, 2, base) == 42, "AMOADD.D real write acknowledgement");
        transact(dut, events, 2, base, true, 0x800000010000002aULL);
        check(atomicTransaction(dut, events, base + 4, 2, 0, 2) == 0xffffffff80000001ULL,
              "LR.W upper lane signed result");
        check(atomicTransaction(dut, events, base + 4, 3, 17, 2) == 0, "SC.W upper lane success");
        check(transact(dut, events, 2, base) == 0x000000110000002aULL,
              "SC.W upper lane byte preservation");
        flushAll(dut, events);
        // Fill BOTH private capacities concurrently: four owners per directory
        // set at two ways. Then read every dirty line via coherent DMA.
        for (unsigned agent = 0; agent < 2; ++agent)
            for (unsigned i = 0; i < I1_PAIR_CACHE_BYTES / 64; ++i)
                transact(dut, events, agent, base + agent * I1_PAIR_CACHE_BYTES + i * 64,
                         true, 0x5631000000000000ULL + agent * 0x10000 + i);
        for (unsigned agent = 0; agent < 2; ++agent)
            for (unsigned i = 0; i < I1_PAIR_CACHE_BYTES / 64; ++i)
                check(transact(dut, events, 2, base + agent * I1_PAIR_CACHE_BYTES + i * 64) ==
                      0x5631000000000000ULL + agent * 0x10000 + i,
                      "full I/D capacity directory and DMA byte oracle");

        flushAll(dut, events);
        adjacentHitMetadata(dut, events);
        flushAll(dut, events);
        ordinaryStream(dut, events, wrongStream);
#ifdef I1_MISS_TURNOVER
        // Exactly two dirty ways in ONE private cache; the other cache is
        // empty. A third same-set line has spare Home directory capacity.
        // Require Home admission before the older actual ReleaseAck.
        // This fixture's old RAM adapter serializes backing R/W bursts;
        // actual AXI overlap is separately measured in the CPU SoC model.
        flushAll(dut, events);
        constexpr uint64_t stride=I1_PAIR_CACHE_BYTES/2;
        for(unsigned i=0;i<3;++i)
            transact(dut,events,2,base+stride*i,true,0x4931574200000000ULL+i);
        transact(dut,events,0,base,true,0xa1739517c9eb2d4fULL);
        transact(dut,events,0,base+stride,true,0xf4d2b09e78563412ULL);
        check(transact(dut,events,0,base+stride*2)==0x4931574200000002ULL,
            "independent overlapping dirty-victim/refill payload oracle");
        check(transact(dut,events,2,base)==0xa1739517c9eb2d4fULL&&
              transact(dut,events,2,base+stride)==0xf4d2b09e78563412ULL,
            "independent overlapping writeback durable byte oracle");
        check(events.acquireDuringRelease>0,"no actual Acquire/Release overlap witnessed");
        flushAll(dut,events);
#endif
        std::cout << "GSIM I1 dual-cache TL-C: PASS probes=" << events.probes[0] << ','
                  << events.probes[1] << " dirtyBeats=" << events.dirtyBeats[0] << ','
                  << events.dirtyBeats[1] << " releaseBeats=" << events.releaseBeats[0]
                  << ',' << events.releaseBeats[1] << " dirtyMigrationCycles="
                  << firstMigrationCycles << ',' << secondMigrationCycles
                  << " burstWriteBeats=" << events.burstWriteBeats
                  << " readDuringWrite=" << events.readDuringWrite
                  << " acquireDuringRelease=" << events.acquireDuringRelease << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "GSIM I1 dual-cache TL-C: FAIL " << error.what() << '\n';
        return 1;
    }
}
