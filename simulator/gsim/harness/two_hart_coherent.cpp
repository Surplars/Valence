#include "TwoHartCoherentGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>

static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

struct Events {
    std::array<unsigned, 2> probes{}, dirtyBeats{}, releaseBeats{};
    unsigned burstWriteBeats = 0;
    void sample(STwoHartCoherentGsim &dut) {
        probes[0] += dut.get_io$$probe0();
        probes[1] += dut.get_io$$probe1();
        dirtyBeats[0] += dut.get_io$$dirtyProbe0();
        dirtyBeats[1] += dut.get_io$$dirtyProbe1();
        releaseBeats[0] += dut.get_io$$releaseData0();
        releaseBeats[1] += dut.get_io$$releaseData1();
        burstWriteBeats += dut.get_io$$burstWriteBeat();
    }
};

static void drive(STwoHartCoherentGsim &dut, unsigned agent, bool valid, uint64_t address = 0,
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

static bool requestReady(STwoHartCoherentGsim &dut, unsigned agent) {
    switch (agent) {
        case 0: return dut.get_io$$hart0$$request$$ready();
        case 1: return dut.get_io$$hart1$$request$$ready();
        default: return dut.get_io$$uncached$$request$$ready();
    }
}

static bool responseValid(STwoHartCoherentGsim &dut, unsigned agent) {
    switch (agent) {
        case 0: return dut.get_io$$hart0$$response$$valid();
        case 1: return dut.get_io$$hart1$$response$$valid();
        default: return dut.get_io$$uncached$$response$$valid();
    }
}

static uint64_t responseData(STwoHartCoherentGsim &dut, unsigned agent) {
    switch (agent) {
        case 0: return dut.get_io$$hart0$$response$$bits$$data();
        case 1: return dut.get_io$$hart1$$response$$bits$$data();
        default: return dut.get_io$$uncached$$response$$bits$$data();
    }
}

static bool responseError(STwoHartCoherentGsim &dut, unsigned agent) {
    switch (agent) {
        case 0: return dut.get_io$$hart0$$response$$bits$$error();
        case 1: return dut.get_io$$hart1$$response$$bits$$error();
        default: return dut.get_io$$uncached$$response$$bits$$error();
    }
}

static uint64_t transact(STwoHartCoherentGsim &dut, Events &events, unsigned agent,
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

static void consecutiveReadHits(STwoHartCoherentGsim &dut, Events &events,
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
    check(stalledAccepted == 2, "read-hit backpressure overfilled the response queue");
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

static void readHitsBehindMiss(STwoHartCoherentGsim &dut, Events &events,
                               uint64_t missAddress, uint64_t missData,
                               uint64_t hitAddress, uint64_t hitData) {
    unsigned accepted = 0, completed = 0;
    bool overlap = false;
    for (unsigned cycle = 0; cycle < 500 && completed < 3; ++cycle) {
        drive(dut, 0, accepted < 3, accepted == 0 ? missAddress : hitAddress);
        dut.step();
        events.sample(dut);
        if (accepted < 3 && requestReady(dut, 0)) {
            ++accepted;
            overlap |= accepted >= 2 && completed == 0;
        }
        if (responseValid(dut, 0)) {
            check(accepted > completed && !responseError(dut, 0) &&
                  responseData(dut, 0) == (completed == 0 ? missData : hitData),
                  "read hit passed an older miss or returned wrong data");
            ++completed;
        }
    }
    drive(dut, 0, false);
    check(accepted == 3 && completed == 3 && overlap,
          "independent read hits did not complete behind the older miss");
}

static void simultaneousRead(STwoHartCoherentGsim &dut, Events &events,
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

int main() {
    try {
        constexpr uint64_t base = 0x80010000;
        constexpr uint64_t a0 = 0x1111222233334444ULL;
        constexpr uint64_t a1 = 0xaaaabbbbccccddddULL;
        constexpr uint64_t a2 = 0x0123456789abcdefULL;
        constexpr uint64_t a3 = 0xfedcba9876543210ULL;
        constexpr uint64_t b0 = 0x5555666677778888ULL;
        constexpr uint64_t b1 = 0x9999aaaabbbbccccULL;
        static STwoHartCoherentGsim dut;
        Events events;
        for (unsigned i = 0; i < 3; ++i) drive(dut, i, false);
        dut.set_reset(1);
        dut.step();
        dut.step();
        dut.set_reset(0);

        transact(dut, events, 2, base, true, a0);
        transact(dut, events, 2, base + 64, true, b0);
        check(transact(dut, events, 0, base) == a0, "hart 0 initial fill failed");
        consecutiveReadHits(dut, events, base, a0);
        readHitsBehindMiss(dut, events, base + 64, b0, base, a0);
        transact(dut, events, 0, base, true, a1);
        const uint64_t firstMigrationStart = dut.cycles;
        check(transact(dut, events, 1, base) == a1, "hart 1 missed hart 0 dirty data");
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
        transact(dut, events, 0, base + 128, true, 0xdeadbeefULL);
        check(events.releaseBeats[0] == 8, "dirty eviction did not ReleaseData");
        check(transact(dut, events, 2, base) == a3, "released dirty data was not committed");
        simultaneousRead(dut, events, base, a3);
        check(events.probes[0] >= 2 && events.probes[1] >= 2,
              "simultaneous line ownership did not probe the previous hart");
        check(events.burstWriteBeats == events.dirtyBeats[0] + events.dirtyBeats[1] +
                  events.releaseBeats[0] + events.releaseBeats[1],
              "dirty line writes did not use complete 64-byte PutFullData bursts");

        std::cout << "GSIM two-hart TL-C: PASS probes=" << events.probes[0] << ','
                  << events.probes[1] << " dirtyBeats=" << events.dirtyBeats[0] << ','
                  << events.dirtyBeats[1] << " releaseBeats=" << events.releaseBeats[0]
                  << ',' << events.releaseBeats[1] << " dirtyMigrationCycles="
                  << firstMigrationCycles << ',' << secondMigrationCycles
                  << " burstWriteBeats=" << events.burstWriteBeats << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "GSIM two-hart TL-C: FAIL " << error.what() << '\n';
        return 1;
    }
}
