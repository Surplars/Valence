#include "CoherentCacheWaysGsim.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <unordered_map>
#ifndef CACHE_WAYS
#define CACHE_WAYS 2
#endif
static void check(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}
static constexpr uint64_t base = 0x80010000ULL;
struct Reply { unsigned opcode, beat, count; uint64_t address; };
struct Test {
    SCoherentCacheWaysGsim dut;
    std::unordered_map<uint64_t, uint64_t> backing, architectural;
    std::deque<Reply> replies;
    std::deque<uint64_t> expected;
    std::deque<bool> expectedMiss;
    uint64_t cycles = 0, misses = 0, hits = 0, releases = 0, probes = 0;
    unsigned cBeat = 0, cOpcode = 0;
    uint64_t cAddress = 0, probeAddress = 0;
    uint64_t underMissHits = 0;
    bool probing = false, probeAccepted = false, probeDone = false;
    bool forceReady = false, blockC = false, blockCpuResponse = false;
    bool requestValid = false, requestWrite = false;
    uint64_t requestAddress = base, requestData = 0;
    unsigned requestMask = 255;
    uint64_t word(uint64_t address) {
        auto [it, inserted] = backing.emplace(address, 0x1020304050607000ULL ^ address);
        architectural.try_emplace(address, it->second);
        return it->second;
    }
    void tick() {
        const bool aReady = forceReady || cycles % 5 != 0;
        const bool cReady = !blockC && (forceReady || cycles % 7 != 0);
        const bool responseReady = !blockCpuResponse && (forceReady || cycles % 6 != 0);
        const bool bValid = probing && !probeAccepted;
        dut.set_io$$tl$$a$$ready(aReady);
        dut.set_io$$tl$$c$$ready(cReady);
        dut.set_io$$tl$$e$$ready(cycles % 3 != 0);
        dut.set_io$$upstream$$response$$ready(responseReady);
        dut.set_io$$tl$$b$$valid(bValid);
        dut.set_io$$tl$$b$$bits$$address(probeAddress);
        const bool responding = !replies.empty() && cycles % 4 != 0;
        dut.set_io$$tl$$d$$valid(responding);
        if (!replies.empty()) {
            auto &r = replies.front();
            dut.set_io$$tl$$d$$bits$$opcode(r.opcode);
            dut.set_io$$tl$$d$$bits$$data(r.opcode == 5 ? word(r.address + 8*r.beat) : 0);
        }
        dut.step(); ++cycles;
        if (requestValid && dut.get_io$$upstream$$request$$ready()) {
            const uint64_t a = requestAddress;
            const bool write = requestWrite;
            if (!expected.empty() && expectedMiss.front() && dut.get_io$$hit()) ++underMissHits;
            word(a); expected.push_back(write ? 0 : architectural.at(a));
            expectedMiss.push_back(dut.get_io$$miss());
            if (write) {
                uint64_t value = architectural.at(a), data = requestData;
                const unsigned mask = requestMask;
                for (unsigned b = 0; b < 8; ++b)
                    if ((mask >> b) & 1)
                        value = (value & ~(0xffULL << (8*b))) | (data & (0xffULL << (8*b)));
                architectural[a] = value;
            }
        }
        if (responding && dut.get_io$$tl$$d$$ready()) {
            auto &r = replies.front();
            if (++r.beat == r.count) replies.pop_front();
        }
        if (dut.get_io$$upstream$$response$$valid() && responseReady) {
            check(!expected.empty(), "unsolicited CPU response");
            check(!dut.get_io$$upstream$$response$$bits$$error(), "CPU error");
            check(dut.get_io$$upstream$$response$$bits$$data() == expected.front(), "CPU data mismatch");
            expected.pop_front();
            expectedMiss.pop_front();
        }
        if (dut.get_io$$tl$$a$$valid() && aReady) {
            check(dut.get_io$$tl$$a$$bits$$opcode() == 6 && dut.get_io$$tl$$a$$bits$$size() == 6,
                  "expected line AcquireBlock");
            replies.push_back({5, 0, 8, dut.get_io$$tl$$a$$bits$$address()});
        }
        if (bValid && dut.get_io$$tl$$b$$ready()) probeAccepted = true;
        if (dut.get_io$$tl$$c$$valid() && cReady) {
            const unsigned op = dut.get_io$$tl$$c$$bits$$opcode();
            const uint64_t a = dut.get_io$$tl$$c$$bits$$address();
            if (!cBeat) { cAddress = a; cOpcode = op; }
            check(cAddress == a && cOpcode == op, "C burst control changed");
            check(dut.get_io$$tl$$c$$bits$$size() == 6, "C line size");
            if (op == 5 || op == 7) {
                const uint64_t beatAddress = a + 8*cBeat; word(beatAddress);
                check(dut.get_io$$tl$$c$$bits$$data() == architectural.at(beatAddress),
                      "dirty writeback mismatch");
                backing[beatAddress] = architectural.at(beatAddress);
            }
            if (op == 4 || op == 6 || cBeat == 7) {
                if (op == 6 || op == 7) {
                    replies.push_back({6, 0, 1, a}); ++releases;
                } else {
                    check(probing && probeAccepted && a == probeAddress, "unexpected ProbeAck");
                    probeDone = true; ++probes;
                }
                cBeat = 0;
            } else ++cBeat;
        }
        misses += dut.get_io$$miss(); hits += dut.get_io$$hit();
    }
    Test() {
        dut.set_reset(1);
        dut.set_io$$upstream$$request$$valid(0);
        dut.set_io$$upstream$$request$$bits$$address(base);
        dut.set_io$$upstream$$request$$bits$$size(3);
        dut.set_io$$upstream$$request$$bits$$mask(255);
        dut.set_io$$upstream$$request$$bits$$data(0);
        dut.set_io$$upstream$$request$$bits$$write(0);
        dut.set_io$$upstream$$request$$bits$$atomic(0);
        dut.set_io$$upstream$$request$$bits$$atomicOp(0);
        dut.set_io$$upstream$$request$$bits$$virtualized(0);
        dut.set_io$$upstream$$request$$bits$$uncached(0);
        dut.set_io$$downstream$$request$$ready(0);
        dut.set_io$$downstream$$response$$valid(0);
        dut.set_io$$downstream$$response$$bits$$data(0);
        dut.set_io$$downstream$$response$$bits$$error(0);
        dut.set_io$$downstream$$response$$bits$$pageFault(0);
        dut.set_io$$flushRequest(0);
        dut.set_io$$tl$$b$$bits$$opcode(6);
        dut.set_io$$tl$$b$$bits$$param(2);
        dut.set_io$$tl$$b$$bits$$size(6);
        dut.set_io$$tl$$b$$bits$$source(0);
        dut.set_io$$tl$$b$$bits$$mask(255);
        dut.set_io$$tl$$b$$bits$$data(0);
        dut.set_io$$tl$$d$$bits$$param(0);
        dut.set_io$$tl$$d$$bits$$size(6);
        dut.set_io$$tl$$d$$bits$$source(0);
        dut.set_io$$tl$$d$$bits$$sink(0);
        dut.set_io$$tl$$d$$bits$$denied(0);
        dut.set_io$$tl$$d$$bits$$corrupt(0);
        tick(); tick(); dut.set_reset(0);
    }
    void access(uint64_t a, bool write = false, uint64_t value = 0, unsigned mask = 255,
                bool waitForReply = true) {
        requestAddress = a; requestWrite = write; requestData = value; requestMask = mask; requestValid = true;
        dut.set_io$$upstream$$request$$bits$$address(a);
        dut.set_io$$upstream$$request$$bits$$write(write);
        dut.set_io$$upstream$$request$$bits$$data(value);
        dut.set_io$$upstream$$request$$bits$$mask(mask);
        dut.set_io$$upstream$$request$$valid(1);
        unsigned limit = 0;
        do { tick(); check(++limit < 1000, "request timeout"); }
        while (!dut.get_io$$upstream$$request$$ready());
        dut.set_io$$upstream$$request$$valid(0);
        requestValid = false;
        if (!waitForReply) return;
        while (!expected.empty()) { tick(); check(++limit < 1000, "response timeout"); }
    }
    void probe(uint64_t a) {
        probing = true; probeAccepted = false; probeDone = false; probeAddress = a;
        for (unsigned n = 0; !probeDone; ++n) { check(n < 1000, "probe timeout"); tick(); }
        probing = false; tick();
    }
    void flush() {
        dut.set_io$$flushRequest(1);
        for (unsigned n = 0; ; ++n) {
            check(n < 2000, "flush timeout"); tick();
            if (dut.get_io$$flushDone()) break;
        }
        dut.set_io$$flushRequest(0); tick();
        for (auto [a, value] : architectural) check(backing.at(a) == value, "flush lost dirty data");
    }
    void probeWithBypass(bool atomic, unsigned replyPhase) {
        // A dirty line needs eight C beats. The bypass uses a different empty
        // set, and the external manager may hold its reply behind a DMA probe.
        access(base); access(base, true, 0x1122334455667788ULL);
        forceReady = true;
        dut.set_io$$downstream$$request$$ready(1);
        dut.set_io$$upstream$$request$$bits$$atomic(atomic);
        dut.set_io$$upstream$$request$$bits$$uncached(!atomic);
        access(base + 64, false, 0, 255, false);
        check(expected.size() == 1, "bypass did not allocate one CPU reply");
        const uint64_t result = expected.front();
        probing = true; probeAddress = base;
        auto offerReply = [&] {
            dut.set_io$$downstream$$response$$bits$$data(result);
            dut.set_io$$downstream$$response$$valid(1);
        };
        if (replyPhase == 0) offerReply(); // same cycle as B
        blockC = replyPhase == 1;
        blockCpuResponse = replyPhase == 1;
        tick();
        check(probeAccepted, "probe blocked by pending bypass CPU reply");
        if (replyPhase == 0) check(expected.empty(), "B/CPU reply simultaneous handshake lost");
        if (replyPhase == 1) {
            offerReply();
            for (unsigned n = 0; n < 12; ++n) {
                tick();
                check(dut.get_io$$upstream$$response$$valid() &&
                      dut.get_io$$upstream$$response$$bits$$data() == result &&
                      !dut.get_io$$downstream$$response$$ready(),
                      "probe withdrew or corrupted stalled bypass response");
            }
            blockCpuResponse = false; tick();
            check(expected.empty(), "CPU reply could not retire under C backpressure");
            blockC = false;
        }
        for (unsigned n = 0; !probeDone; ++n) {
            check(n < 128, "probe waits on held bypass CPU response");
            if (replyPhase == 2 && cBeat == 7) offerReply(); // final C beat
            tick();
        }
        if (replyPhase == 2) check(expected.empty(), "final C/CPU reply simultaneous handshake lost");
        if (replyPhase == 3) {
            check(expected.size() == 1, "unsolicited CPU reply during held-response probe");
            offerReply(); tick();
            check(expected.empty(), "bypass did not resume after probe");
        }
        dut.set_io$$downstream$$response$$valid(0);
        dut.set_io$$downstream$$request$$ready(0);
        dut.set_io$$upstream$$request$$bits$$atomic(0);
        dut.set_io$$upstream$$request$$bits$$uncached(0);
        probing = false; tick();
        access(base); // must be able to start a fresh request, with dirty data preserved
    }
};
int main() {
    try {
        Test t;
        for (unsigned i = 0; i < 10; ++i) t.access(base + (i & 1)*256);
        check(t.misses == (CACHE_WAYS == 2 ? 2 : 10), "alias residency/miss contract");
        t.access(base + 64, false, 0, 255, false);
        t.access(base + 256);
        check(t.underMissHits > 0, "independent hit did not pass outstanding miss");
        for (unsigned i = 0; i < 96; ++i) {
            const uint64_t a = base + ((i*13) % 64)*8;
            t.access(a, true, 0xfedcba9876543210ULL ^ i, i % 2 ? 0x55 : 0xff); t.access(a);
            if (i % 11 == 0) { t.probe(a & ~63ULL); t.access(a); }
        }
        t.flush();
        unsigned bypassCases = 0;
        for (bool atomic : {true, false}) for (unsigned phase = 0; phase < 4; ++phase) {
            Test overlap; overlap.probeWithBypass(atomic, phase); ++bypassCases;
        }
        std::cout << "GSIM coherent cache ways: PASS ways=" << CACHE_WAYS
                  << " hits=" << t.hits << " misses=" << t.misses
                  << " releases=" << t.releases << " probes=" << t.probes
                  << " underMissHits=" << t.underMissHits << " bypassProbeCases=" << bypassCases
                  << " cycles=" << t.cycles << "\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "GSIM coherent cache ways: FAIL " << error.what() << "\n"; return 1;
    }
}
