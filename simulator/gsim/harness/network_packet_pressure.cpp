// Reuse the production cache/atomic/FIFO/home model, not its private state.
// Independent byte memory and architectural CPU words are the correctness oracle.
#define main existing_network_probe_main
#include "network_probe.cpp"
#undef main
#include <optional>
#include <random>
#include <vector>

struct CpuOp {
    unsigned index;
    bool write, atomic, uncached;
    uint64_t data, expected;
};

static void pressure(unsigned length, bool dmaWrite, bool atomics, unsigned seed, bool inject) {
    Test t;
    auto &d = t.d;
    std::mt19937 random(seed);
    std::array<uint64_t, 512> cpuWords{};
    for (unsigned i = 0; i < cpuWords.size(); ++i) cpuWords[i] = t.word(4096 + 8 * i);
    // Dirty data must be supplied by a real probe rather than the memory oracle.
    t.cpuAccess(base + 256, true, 0x0123456789abcdefULL);
    t.cpuAccess(base + 320, true, 0xfedcba9876543210ULL);
    auto expectedMemory = t.memory;
    for (unsigned i = 0; i < 8; ++i) {
        expectedMemory[256 + i] = uint64_t(0x0123456789abcdefULL) >> (8 * i);
        expectedMemory[320 + i] = uint64_t(0xfedcba9876543210ULL) >> (8 * i);
    }
    std::vector<uint64_t> dmaExpected;
    for (unsigned off = 0; off < length; off += 8) {
        uint64_t value = 0;
        for (unsigned b = 0; b < 8; ++b) value |= uint64_t(expectedMemory[256 + off + b]) << (8 * b);
        dmaExpected.push_back(value);
    }
    if (dmaWrite) for (unsigned i = 0; i < length; ++i) expectedMemory[256 + i] = uint8_t(i * 29 + seed);
    if (inject) dmaExpected[0] ^= 1;

    const unsigned cpuGoal = 192, dmaGoal = (length + 7) / 8;
    unsigned cpuSent = 0, cpuReceived = 0, dmaSent = 0, dmaReceived = 0;
    unsigned start = t.cycle, lastProgress = t.cycle;
    std::optional<CpuOp> offered, outstanding;
    while (cpuReceived < cpuGoal || dmaReceived < dmaGoal) {
        if (!offered && !outstanding && cpuSent < cpuGoal) {
            unsigned index = random() % cpuWords.size();
            bool atomic = atomics && cpuSent % 5 == 0;
            bool uncached = !atomic && cpuSent % 7 == 0;
            bool write = !atomic && random() % 3 == 0;
            uint64_t data = (uint64_t(random()) << 32) | random();
            if (atomic) data &= 255;
            offered = CpuOp{index, write, atomic, uncached, data, write ? 0 : cpuWords[index]};
        }
        S(cpu$$request$$valid, bool(offered));
        if (offered) {
            S(cpu$$request$$bits$$address, base + 4096 + 8 * offered->index);
            S(cpu$$request$$bits$$write, offered->write);
            S(cpu$$request$$bits$$atomic, offered->atomic);
            S(cpu$$request$$bits$$atomicOp, 0);
            S(cpu$$request$$bits$$uncached, offered->uncached);
            S(cpu$$request$$bits$$data, offered->data);
        }
        const bool dmaOffer = dmaSent < dmaGoal && dmaSent - dmaReceived < 4;
        S(dma$$request$$valid, dmaOffer);
        S(dma$$request$$bits$$address, base + 256 + 8 * dmaSent);
        S(dma$$request$$bits$$write, dmaWrite);
        unsigned remaining = length - std::min(length, 8 * dmaSent);
        S(dma$$request$$bits$$mask, !dmaWrite || remaining >= 8 ? 255 : ((1U << remaining) - 1));
        uint64_t data = 0;
        for (unsigned b = 0; b < 8; ++b) data |= uint64_t(uint8_t((dmaSent * 8 + b) * 29 + seed)) << (8 * b);
        S(dma$$request$$bits$$data, data);
        t.cpuReady = t.cycle % 13 < 10;
        t.dmaReady = t.cycle % 17 < 12;
        unsigned cpuBefore = t.cpuCount, dmaBefore = t.dmaCount;
        t.tick();
        bool progress = false;
        if (offered && G(cpu$$request$$ready)) {
            check(!outstanding, "CPU credit overwritten");
            outstanding = offered;
            offered.reset(); ++cpuSent; progress = true;
        }
        if (dmaOffer && G(dma$$request$$ready)) { ++dmaSent; progress = true; }
        if (t.cpuCount != cpuBefore) {
            check(bool(outstanding), "unsolicited CPU reply");
            check(t.cpuData == outstanding->expected, "CPU independent architectural word mismatch");
            if (outstanding->write) cpuWords[outstanding->index] = outstanding->data;
            if (outstanding->atomic) cpuWords[outstanding->index] += outstanding->data;
            outstanding.reset(); ++cpuReceived; progress = true;
        }
        if (t.dmaCount != dmaBefore) {
            check(dmaReceived < dmaSent, "unsolicited DMA reply");
            if (!dmaWrite) check(t.dmaData == dmaExpected.at(dmaReceived), "DMA pressure dirty byte oracle mismatch");
            ++dmaReceived; progress = true;
        }
        if (progress) lastProgress = t.cycle;
        if (t.cycle - lastProgress >= 2000 || t.cycle - start >= 100000) {
            std::cerr << "CASE length=" << length << " write=" << dmaWrite << " atomics=" << atomics
                      << " seed=" << seed << " cpu=" << cpuReceived << '/' << cpuSent
                      << " dma=" << dmaReceived << '/' << dmaSent << " cycle=" << t.cycle
                      << " cpu_req=" << bool(offered) << '/' << unsigned(G(cpu$$request$$ready))
                      << " dma_req=" << dmaOffer << '/' << unsigned(G(dma$$request$$ready))
                      << " backing_replies=" << t.replies.size() << '\n';
            // Diagnostic snapshots only: never consulted by stimuli or oracle.
            std::cerr << "STATE cache=" << unsigned(d.cache$state)
                      << " home=" << unsigned(d.home$state) << " home_resume=" << unsigned(d.home$resume)
                      << " ordinary_reads=" << unsigned(d.home$reads)
                      << " atomic=" << unsigned(d.shared$unit$state)
                      << " probe_phase=" << unsigned(d.home$probeEngine$phase[0]) << ','
                      << unsigned(d.home$probeEngine$phase[1]) << ',' << unsigned(d.home$probeEngine$phase[2])
                      << ',' << unsigned(d.home$probeEngine$phase[3])
                      << " pending=" << std::hex << d.cache$pending$$address
                      << " victim=" << d.cache$victimAddress << " probe=" << d.home$probeAddress
                      << " fifo_head=" << d.buffer$TwoEntryRegisterQueue$head$$request$$address
                      << std::dec << '\n';
            std::cerr << "LINE reader=";
            for (unsigned i = 0; i < 4; ++i) std::cerr << unsigned(d.home$lineTransfer$reader$phase[i]) << ':'
                << unsigned(d.home$lineTransfer$reader$beats[i]) << ' ';
            std::cerr << " writer=";
            for (unsigned i = 0; i < 4; ++i) std::cerr << unsigned(d.home$lineTransfer$writer$phase[i]) << ' ';
            std::cerr << " inner_lock=" << unsigned(d.home$lineTransfer$arbiter$locked) << ':'
                << unsigned(d.home$lineTransfer$arbiter$lockedOwner) << " outer_lock=" << unsigned(d.arbiter$locked)
                << ':' << unsigned(d.arbiter$lockedOwner) << " manager=" << unsigned(d.manager$state)
                << " sent=" << unsigned(d.manager$sent) << " returned=" << unsigned(d.manager$returned)
                << " bridge=";
            for (unsigned i = 0; i < 8; ++i) std::cerr << unsigned(d.bridge$occupied[i]) << ':' << unsigned(d.bridge$done[i]) << ' ';
            std::cerr << '\n';
            throw std::runtime_error("packet/cache/atomic/home pressure bounded liveness failure");
        }
    }
    S(cpu$$request$$valid, 0); S(dma$$request$$valid, 0);
    S(cpu$$request$$bits$$atomic, 0); S(cpu$$request$$bits$$uncached, 0);
    t.cpuReady = true; t.dmaReady = true;
    for (unsigned i = 0; i < cpuWords.size(); ++i) {
        t.cpuAccess(base + 4096 + 8 * i);
        check(t.cpuData == cpuWords[i], "CPU pressure final word oracle mismatch");
    }
    for (unsigned off = 0; off < length; off += 8) {
        uint64_t expected = 0;
        for (unsigned b = 0; b < 8; ++b) expected |= uint64_t(expectedMemory[256 + off + b]) << (8 * b);
        t.cpuAccess(base + 256 + off);
        check(t.cpuData == expected, "RX pressure final byte/tail oracle mismatch");
    }
    check(t.replies.empty(), "pressure left accepted backing replies pending");
}

int main(int argc, char **) {
    try {
        unsigned cases = 0;
        for (unsigned length : {64U, 512U, 1024U, 1442U, 1514U, 2048U})
            for (bool write : {false, true}) for (bool atomics : {false, true}) for (unsigned seed : {7U, 31U}) {
                pressure(length, write, atomics, seed, argc > 1); ++cases;
            }
        std::cout << "NETWORK_PACKET_PRESSURE_PASS cases=" << cases
                  << " max_dma_credits=4 dirty_probe=1 cpu_cache_thrash=1 atomic_bypass=1 independent_memory=1\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "NETWORK_PACKET_PRESSURE_FAIL " << e.what() << '\n';
        return 1;
    }
}
