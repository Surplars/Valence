#include "DmaPacketStopGsim.h"
#include <algorithm>
#include <cstdint>
#include <deque>
#include <functional>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
static void check(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
#define DMA_RAM_BYTES (2ULL * 1024 * 1024 * 1024)
#include "dma_coherent_ddr.h"
#define S(n, v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
#ifndef DMA_LINE_YIELD_CYCLES
#define DMA_LINE_YIELD_CYCLES 0
#endif
static constexpr uint64_t base = 0x80200000ULL;
static std::string mutation;
struct Beat { uint32_t data; unsigned keep; bool last; };
struct Owner { uint64_t offset; unsigned length, generation; };
struct PacketRequest { bool write; uint64_t address; };
struct Test {
    SDmaPacketStopGsim d;
    DmaDdr ddr;
    std::vector<uint8_t> oracle;
    std::deque<Beat> dataIn, statusIn;
    std::deque<PacketRequest> packetPending;
    std::vector<std::vector<uint8_t>> frames;
    std::vector<uint8_t> frame, txExpected;
    std::optional<Owner> txOwner, rxOwner;
    std::optional<std::tuple<uint32_t, unsigned, bool>> heldTx, heldControl;
    std::optional<std::tuple<uint64_t, uint64_t, unsigned, bool>> heldPacket;
    uint64_t cycles = 0, packetRequests = 0, packetResponses = 0, packetPeak = 0;
    uint64_t lineRequests = 0, lineResponses = 0, simultaneous = 0, lineWithPacket = 0;
    uint64_t dirtyBeats = 0, probes = 0, copyStart = 0, copyDone = 0, networkB = 0;
    uint64_t stopped = 0, bHoldStart = 0, heldBObserved = 0, heldPacketCycles = 0, heldPacketAfterStop = 0;
    unsigned controls = 0, txReads = 0, rxWrites = 0, rxBytes = 0, generations = 0;
    bool txHold = false, holdRxB = false, corruptionApplied = false;
    bool copyArmed = false, copyCompleted = false;
    static uint8_t initial(uint64_t i) { return uint8_t(((i * 0x9e3779b97f4a7c15ULL) ^ (i >> 7) ^ 0xa5) >> 23); }
    static uint8_t payload(unsigned generation, unsigned byte) { return uint8_t(generation * 71 + byte * 13 + (byte >> 4)); }
    uint64_t word(uint64_t offset) const {
        uint64_t value = 0; for (unsigned b = 0; b < 8; ++b) value |= uint64_t(oracle.at(offset + b)) << (8 * b); return value;
    }
    bool rxAddress(uint64_t offset) const { return rxOwner && offset >= rxOwner->offset && offset < rxOwner->offset + rxOwner->length; }
    Test(): oracle(1024 * 1024) {
        for (uint64_t i = 0; i < oracle.size(); ++i) ddr.memory[i] = oracle[i] = initial(i);
        for (uint64_t i = 0; i < ddr.high.size(); ++i) ddr.high[i] = initial(DMA_RAM_BYTES - ddr.high.size() + i);
        S(control$$request$$valid, 0); S(control$$response$$ready, 0); S(control$$request$$bits$$address, 0);
        S(control$$request$$bits$$write, 0); S(control$$request$$bits$$data, 0); S(control$$request$$bits$$size, 3); S(control$$request$$bits$$byteEnable, 255);
        S(packetControl$$request$$valid, 0); S(packetControl$$response$$ready, 0); S(packetControl$$request$$bits$$address, 0);
        S(packetControl$$request$$bits$$write, 0); S(packetControl$$request$$bits$$data, 0); S(packetControl$$request$$bits$$size, 3); S(packetControl$$request$$bits$$byteEnable, 255);

        S(cpu$$request$$valid, 0); S(cpu$$response$$ready, 0); S(cpu$$request$$bits$$address, base);
        S(cpu$$request$$bits$$data, 0); S(cpu$$request$$bits$$write, 0); S(cpu$$request$$bits$$mask, 255);
        S(cpu$$request$$bits$$size, 3); S(cpu$$request$$bits$$atomic, 0); S(cpu$$request$$bits$$atomicOp, 0);
        S(cpu$$request$$bits$$virtualized, 0); S(cpu$$request$$bits$$uncached, 0); S(cpu$$request$$bits$$prefetchNextAllowed, 0);
        S(rxData$$valid, 0); S(rxStatus$$valid, 0); S(flushRequest, 0); S(holdLineHome, 0);
        d.set_reset(1); tick(); tick(); d.set_reset(0); tick();
    }
    void tick() {
        check(cycles < 2000000, "packet/copy integration global cycle bound");
        // Hold only old-generation RX B responses. The real bridge/home must keep
        // ownership; the AXI host never forges a completion or bypasses coherence.
        if (holdRxB) for (auto& reply : ddr.replies) if (reply.count == 1 && rxAddress(reply.address)) {
            check(!ddr.heldB || *ddr.heldB != reply.serial, "RX B hold started after VALID");
            reply.due = cycles + 3; ++heldBObserved;
        }
        bool txReady = !txHold && cycles % 13 < 9, controlReady = cycles % 11 < 8;
        S(txData$$ready, txReady); S(txControl$$ready, controlReady);
        const Beat in = dataIn.empty() ? Beat{} : dataIn.front(), status = statusIn.empty() ? Beat{} : statusIn.front();
        S(rxData$$valid, !dataIn.empty()); S(rxData$$bits$$data, in.data); S(rxData$$bits$$keep, in.keep); S(rxData$$bits$$last, in.last);
        S(rxStatus$$valid, !statusIn.empty()); S(rxStatus$$bits$$data, status.data); S(rxStatus$$bits$$keep, status.keep); S(rxStatus$$bits$$last, status.last);
        ddr.drive(d, cycles); d.step();
        std::optional<uint32_t> corrupt;
        if (mutation == "rx-byte" && !corruptionApplied && G(ddrAxi$$w$$valid) && ddr.wReady && !ddr.writes.empty()) {
            const auto& w = ddr.writes.front(); auto a = w.address + (w.beat << w.size);
            if (w.count == 1 && rxAddress(a)) corrupt = a;
        }
        if (ddr.bValid && G(ddrAxi$$b$$ready)) {
            auto b = DmaDdr::selected(ddr.replies, ddr.heldB);
            if (b != ddr.replies.end() && b->count == 1 && rxAddress(b->address)) ++networkB;
        }
        ddr.sample(d); ++cycles;
        if (corrupt) { ddr.byte(*corrupt) ^= 1; corruptionApplied = true; }
        if (!dataIn.empty() && G(rxData$$ready)) dataIn.pop_front();
        if (!statusIn.empty() && G(rxStatus$$ready)) statusIn.pop_front();
        auto tx = std::tuple{uint32_t(G(txData$$bits$$data)), unsigned(G(txData$$bits$$keep)), bool(G(txData$$bits$$last))};
        auto control = std::tuple{uint32_t(G(txControl$$bits$$data)), unsigned(G(txControl$$bits$$keep)), bool(G(txControl$$bits$$last))};
        if (heldTx) check(G(txData$$valid) && tx == *heldTx, "STOP changed held TX data");
        if (heldControl) check(G(txControl$$valid) && control == *heldControl, "held TX control changed");
        heldTx = G(txData$$valid) && !txReady ? std::optional{tx} : std::nullopt;
        heldControl = G(txControl$$valid) && !controlReady ? std::optional{control} : std::nullopt;
        if (G(txControl$$valid) && controlReady) {
            const auto [v, k, last] = control;
            check(controls < 6 && v == (controls == 0 ? 0xa0000000U : 0U) && k == 15 && last == (controls == 5), "TX control oracle mismatch"); ++controls;
        }
        if (G(txData$$valid) && txReady) {
            const auto [v, k, last] = tx;
            check(controls == 6 && (k == 1 || k == 3 || k == 7 || k == 15) && (last || k == 15), "TX stream shape mismatch");
            for (unsigned b = 0; b < 4; ++b) if (k & (1U << b)) frame.push_back(uint8_t(v >> (8 * b)));
            if (last) {
                auto expected = txExpected; if (mutation == "tx-byte" && frames.empty()) expected.at(0) ^= 1;
                check(frame == expected, "packet TX independent generation byte oracle mismatch");
                frames.push_back(frame); frame.clear(); controls = 0;
            }
        }
        auto packetOffer = std::tuple{uint64_t(G(packetRequestAddress)), uint64_t(G(packetRequestData)),
                                      unsigned(G(packetRequestMask)), bool(G(packetRequestWrite))};
        if (heldPacket) check(G(packetRequestOffer) && packetOffer == *heldPacket, "STOP changed held packet scalar request");
        heldPacket = G(packetRequestOffer) && !G(packetRequestReady) ? std::optional{packetOffer} : std::nullopt;
        heldPacketCycles += bool(heldPacket); heldPacketAfterStop += stopped && bool(heldPacket);
        if (G(packetRequestFire)) {
            const bool write = G(packetRequestWrite); uint64_t address = G(packetRequestAddress);
            check(G(packetRequestSize) == 3, "packet DMA changed scalar 8-byte ABI");
            if (!write) {
                if (!(txOwner && address == base + txOwner->offset + 8ULL * txReads && txReads < (txOwner->length + 7) / 8)) {
                    std::cerr << "TX_REQUEST cycle=" << cycles << " address=" << std::hex << address << " owner=" << (txOwner ? txOwner->offset : 0) << std::dec << " reads=" << txReads << " length=" << (txOwner ? txOwner->length : 0) << " stopped=" << stopped << '\n';
                    throw std::runtime_error("TX request escaped active generation");
                }
                check(G(packetRequestMask) == 255, "TX scalar mask mismatch"); ++txReads;
            } else {
                check(rxOwner && address == base + rxOwner->offset + 8ULL * rxWrites && rxWrites < (rxOwner->length + 7) / 8, "RX request escaped active generation");
                unsigned remaining = rxOwner->length - 8 * rxWrites, mask = remaining >= 8 ? 255 : (1U << remaining) - 1;
                check(G(packetRequestMask) == mask, "RX independent tail mask mismatch");
                for (unsigned b = 0; b < 8; ++b) if (mask & (1U << b)) {
                    uint8_t expected = payload(rxOwner->generation, 8 * rxWrites + b);
                    check(uint8_t(G(packetRequestData) >> (8 * b)) == expected, "RX independent offered payload mismatch");
                    oracle.at(rxOwner->offset + 8 * rxWrites + b) = expected; ++rxBytes;
                }
                ++rxWrites;
            }
            packetPending.push_back({write, address}); ++packetRequests;
        }
        if (G(packetResponseFire)) {
            check(!packetPending.empty() && !G(packetResponseError), "packet scalar reply lost owner or errored");
            packetPending.pop_front(); ++packetResponses;
        }
        packetPeak = std::max(packetPeak, uint64_t(packetPending.size())); check(packetPeak <= 4, "packet scalar credit overflow");
        if (G(lineRequestFire)) {
            check(!(G(lineRequestAddress) & 63), "copy line request alignment changed");
            ++lineRequests; lineWithPacket += G(packetActive);
        }
        lineResponses += G(lineResponseFire); check(lineResponses <= lineRequests && lineRequests - lineResponses <= 1, "copy line owner count");
        if (G(lineResponseFire)) check(!G(lineResponseError), "copy line response error");
        simultaneous += G(active) && G(packetActive);
        probes += G(probeFire); dirtyBeats += G(probeReplyFire) && G(probeReplyData);
        if (copyArmed && !copyCompleted && G(irq)) {
            check(!ddr.destinationPending() && lineRequests == lineResponses, "copy completion before DDR B/line drain");
            for (uint64_t i = 0; i < ddr.length; ++i) check(ddr.byte(ddr.destination + i) == oracle.at(ddr.destination + i), "copy independent destination byte oracle mismatch");
            copyCompleted = true; copyDone = cycles;
        }
    }
    void until(const std::function<bool()>& done, const char* reason) {
        uint64_t limit = cycles + 300000; while (!done()) { tick(); check(cycles < limit, reason); }
    }
    uint64_t copyControl(unsigned offset, bool write = false, uint64_t value = 0, bool error = false) {
        S(control$$request$$bits$$address, 0x10001000ULL + offset); S(control$$request$$bits$$write, write);
        S(control$$request$$bits$$data, value); S(control$$request$$valid, 1);
        do { tick(); } while (!G(control$$request$$ready)); S(control$$request$$valid, 0);
        until([&] { return G(control$$response$$valid); }, "control response timeout");
        uint64_t result = G(control$$response$$bits$$data); check(bool(G(control$$response$$bits$$error)) == error, "control independent error mismatch");
        for (unsigned hold = 0; hold < 2; ++hold) { tick(); check(G(control$$response$$valid) && G(control$$response$$bits$$data) == result && bool(G(control$$response$$bits$$error)) == error, "held control response changed"); }
        S(control$$response$$ready, 1); tick(); S(control$$response$$ready, 0); return result;
    }
    uint64_t net(unsigned offset, bool write = false, uint64_t value = 0, bool error = false) {
        S(packetControl$$request$$bits$$address, 0x10002000ULL + offset); S(packetControl$$request$$bits$$write, write);
        S(packetControl$$request$$bits$$data, value); S(packetControl$$request$$valid, 1);
        do { tick(); } while (!G(packetControl$$request$$ready)); S(packetControl$$request$$valid, 0);
        until([&] { return G(packetControl$$response$$valid); }, "control response timeout");
        uint64_t result = G(packetControl$$response$$bits$$data); check(bool(G(packetControl$$response$$bits$$error)) == error, "control independent error mismatch");
        for (unsigned hold = 0; hold < 2; ++hold) { tick(); check(G(packetControl$$response$$valid) && G(packetControl$$response$$bits$$data) == result && bool(G(packetControl$$response$$bits$$error)) == error, "held control response changed"); }
        S(packetControl$$response$$ready, 1); tick(); S(packetControl$$response$$ready, 0); return result;
    }

    void cpu(uint64_t offset, bool write = false, uint64_t value = 0) {
        auto expected = write ? 0 : word(offset);
        S(cpu$$request$$bits$$address, base + offset); S(cpu$$request$$bits$$write, write); S(cpu$$request$$bits$$data, value); S(cpu$$request$$valid, 1);
        do { tick(); } while (!G(cpu$$request$$ready)); S(cpu$$request$$valid, 0);
        until([&] { return G(cpu$$response$$valid); }, "CPU cache access timeout");
        check(!G(cpu$$response$$bits$$error) && G(cpu$$response$$bits$$data) == expected, "CPU independent cache byte oracle mismatch");
        S(cpu$$response$$ready, 1); tick(); S(cpu$$response$$ready, 0);
        if (write) for (unsigned b = 0; b < 8; ++b) oracle.at(offset + b) = uint8_t(value >> (8 * b));
    }
    void beginCopy() {
        constexpr unsigned source = 0x10000, destination = 0x40000, length = 0x8000;
        cpu(source, true, 0x123456789abcdef0ULL); cpu(destination, true, 0x0fedcba987654321ULL);
        check(ddr.word(source) != word(source) && ddr.word(destination) != word(destination), "missing copy dirty cache witness");
        for (unsigned i = 0; i < length; ++i) oracle[destination + i] = oracle[source + i];
        ddr.destination = destination; ddr.length = length; copyArmed = true; copyStart = cycles;
        copyControl(0, true, base + source); copyControl(8, true, base + destination); copyControl(16, true, length); copyControl(24, true, 7);
    }
    void txDescriptor(uint64_t offset, unsigned length) {
        net(224, true, base + offset); net(232, true, length); net(240, true, 4);
    }
    void rxDescriptor(uint64_t offset, unsigned length) {
        net(160, true, base + offset); net(168, true, length); net(176, true, 1);
    }
    void setTx(Owner owner) {
        check(packetPending.empty(), "new TX generation before old response drain"); txOwner = owner; txReads = 0;
        txExpected.assign(oracle.begin() + owner.offset, oracle.begin() + owner.offset + owner.length); ++generations;
    }
    void setRx(Owner owner) {
        check(packetPending.empty(), "new RX generation before old response drain"); rxOwner = owner; rxWrites = rxBytes = 0; ++generations;
    }
    void supply() {
        check(rxOwner && dataIn.empty() && statusIn.empty(), "RX supply owner absent");
        for (unsigned i = 0; i < rxOwner->length; i += 4) {
            unsigned count = std::min(4U, rxOwner->length - i); uint32_t value = 0;
            for (unsigned b = 0; b < count; ++b) value |= uint32_t(payload(rxOwner->generation, i + b)) << (8 * b);
            dataIn.push_back({value, (1U << count) - 1, i + count == rxOwner->length});
        }
        for (unsigned i = 0; i < 6; ++i) statusIn.push_back({i == 0 ? 0x50000000U : i == 3 ? 0x40U : i == 5 ? rxOwner->length : 0U, 15, i == 5});
    }
    unsigned completions(bool tx) { return unsigned((net(tx ? 248 : 192) >> 8) & 255); }
    void pop(bool tx, uint64_t offset, unsigned result) {
        uint64_t address = net(tx ? 224 : 200), metadata = net(tx ? 232 : 208);
        if (mutation == "stale-owner") address ^= 512;
        check(address == base + offset && metadata == result, "packet completion generation/owner oracle mismatch");
        net(tx ? 240 : 216, true, tx ? 8 : 1);
    }
    void finish() {
        until([&] { return copyCompleted; }, "concurrent copy completion timeout");
        check(copyControl(32) == 2, "copy completion status mismatch"); copyControl(24, true, 6);
        check(packetRequests == packetResponses && packetPending.empty(), "packet completion retained scalar response owner");
        check(simultaneous > 100 && lineWithPacket > 0, "no real packet/copy line overlap witness");
        check(lineRequests >= 1024 && lineRequests == lineResponses, "64-byte copy burst coverage absent");
        check(dirtyBeats >= 16 && probes > 0, "real coherent dirty-probe coverage absent");
        S(flushRequest, 1); until([&] { return G(flushDone); }, "final cache/home flush timeout"); S(flushRequest, 0); tick();
        check(ddr.memory == oracle, "packet RX/full-memory independent generation byte oracle mismatch");
        check(ddr.reads.empty() && ddr.writes.empty() && ddr.replies.empty(), "final flush left AXI owners");
        for (unsigned n = 0; n < 100; ++n) tick();
        check(!G(packetActive) && !G(packetIrq) && !G(irq), "late response resurrected completed generation");
    }
};

static void txStop(unsigned stopWindow) {
    const bool heldStream = stopWindow == 2;
    Test t; t.net(8, true, 1); t.net(240, true, 1);
    t.cpu(0x1000, true, 0xa17b9c6d5e4f3021ULL); t.cpu(0x2000, true, 0x01fedcba98765432ULL);
    check(t.ddr.word(0x1000) != t.word(0x1000), "missing dirty TX cache witness");
    t.beginCopy(); t.ddr.readDelay = heldStream ? 32 : 400; t.txHold = heldStream;
    t.setTx({0x1000, 97, 1}); t.txDescriptor(0x1000, 97); t.txDescriptor(0x1800, 71);
    if (heldStream) t.until([&] { return t.d.get_io$$txData$$valid(); }, "held TX stream witness missing");
    else if (stopWindow == 0) t.until([&] { return t.heldPacket && t.lineRequests > t.lineResponses; }, "held TX offer with line owner witness missing");
    else t.until([&] { return !t.packetPending.empty(); }, "outstanding late TX read witness missing");
    check(t.d.get_io$$active(), "copy already finished before TX STOP");
    t.stopped = t.cycles; t.net(240, true, 16); t.net(240, true, 4, true);
    if (stopWindow == 0) check(t.heldPacketAfterStop > 0, "held scalar offer did not cross STOP with line ownership");
    t.net(240, true, 2, true); t.net(240, true, 8, true);
    if (heldStream) {
        for (unsigned i = 0; i < 24; ++i) t.tick();
        check(t.completions(true) == 0 && t.frames.empty(), "TX completion preceded held stream drain"); t.txHold = false;
    }
    t.until([&] { return t.completions(true) == 2; }, "TX STOP drain timeout");
    check(t.frames.size() == 1 && t.packetPending.empty() && t.txReads == 13, "TX STOP cancelled active/issued pending frame");
    t.pop(true, 0x1000, 97); t.pop(true, 0x1800, 65536); t.net(240, true, 2);
    t.net(240, true, 1); t.ddr.readDelay = 32; t.setTx({0x2000, 63, 2}); t.txDescriptor(0x2000, 63);
    t.until([&] { return t.completions(true) == 1; }, "TX restarted generation timeout");
    check(t.frames.size() == 2 && t.txReads == 8, "TX restart frame/beat count mismatch");
    t.pop(true, 0x2000, 63); t.net(240, true, 2); t.finish();
    std::cout << "PACKET_LINE_CASE kind=tx stop_window=" << stopWindow << " generations=" << t.generations
              << " scalar_requests=" << t.packetRequests << " line_requests=" << t.lineRequests << " overlap_cycles=" << t.simultaneous
              << " line_with_packet=" << t.lineWithPacket << " held_scalar_cycles=" << t.heldPacketCycles << " held_scalar_after_stop=" << t.heldPacketAfterStop
              << " dirty_probe_beats=" << t.dirtyBeats << " cycles=" << t.cycles << '\n';
}

static void rxStop() {
    Test t; t.net(8, true, 2); t.net(184, true, 1);
    t.cpu(0x6000, true, 0xdeadbeef00112233ULL); t.cpu(0x6008, true, 0x9988776655443322ULL);
    t.beginCopy(); t.setRx({0x6000, 128, 7}); t.holdRxB = true;
    t.rxDescriptor(0x6000, 128); t.rxDescriptor(0x6800, 128); t.supply();
    t.until([&] { return t.heldBObserved != 0; }, "RX delayed DDR B witness missing");
    check(t.d.get_io$$active() && !t.packetPending.empty(), "missing concurrent copy and RX scalar owner");
    t.bHoldStart = t.cycles; t.stopped = t.cycles; t.net(144, true, 1);
    t.net(176, true, 1, true); t.net(184, true, 0, true); t.net(216, true, 1, true);
    for (unsigned i = 0; i < 40; ++i) t.tick();
    check(t.completions(false) == 0 && t.networkB == 0, "RX STOP published completion before old-generation DDR B");
    check(t.heldBObserved > 40 && t.cycles - t.bHoldStart > 40, "late B hold coverage missing");
    t.holdRxB = false;
    t.until([&] { return t.completions(false) == 2; }, "RX STOP late-B drain timeout");
    check(t.packetPending.empty() && t.networkB == t.rxWrites && t.rxWrites > 0 && t.rxWrites < 16, "RX STOP accepted prefix/drain mismatch");
    check(t.dataIn.empty() && t.statusIn.empty(), "RX STOP left stream tail");
    t.pop(false, 0x6000, 65536 | 128); t.pop(false, 0x6800, 65536); t.net(184, true, 0);
    for (unsigned i = 0; i < 32; i += 8) t.cpu(0x6000 + i);
    t.net(184, true, 1); t.setRx({0x7000, 13, 11}); t.rxDescriptor(0x7000, 13); t.supply();
    t.until([&] { return t.completions(false) == 1; }, "RX restarted generation timeout");
    check(t.rxWrites == 2 && t.rxBytes == 13, "RX restart independent tail count mismatch");
    t.pop(false, 0x7000, 13); t.net(184, true, 0);
    t.cpu(0x7000); t.cpu(0x7008); t.finish();
    std::cout << "PACKET_LINE_CASE kind=rx generations=" << t.generations << " scalar_requests=" << t.packetRequests
              << " line_requests=" << t.lineRequests << " overlap_cycles=" << t.simultaneous << " line_with_packet=" << t.lineWithPacket
              << " late_b_hold_cycles=" << t.heldBObserved << " held_scalar_cycles=" << t.heldPacketCycles << " held_scalar_after_stop=" << t.heldPacketAfterStop
              << " dirty_probe_beats=" << t.dirtyBeats << " cycles=" << t.cycles << '\n';
}
int main(int argc, char** argv) {
    try {
        for (int i = 1; i < argc; ++i) { std::string arg = argv[i]; if (arg.starts_with("--mutate=")) mutation = arg.substr(9); }
        if (mutation == "rx-byte") rxStop(); else { txStop(0); txStop(1); txStop(2); rxStop(); }
        std::cout << "DMA_PACKET_STOP_LINE_PASS cases=4 software_generations=8 line_yield=" << DMA_LINE_YIELD_CYCLES
                  << " real_packet_engine=1 real_cache_home=1 host_axi_ddr=1 scalar_packet_abi=1\n"; return 0;
    } catch (const std::exception& error) {
        std::cerr << "DMA_PACKET_STOP_LINE_FAIL " << error.what() << '\n'; return 1;
    }
}
