#pragma once
#include <algorithm>
#include <array>
#include <bit>
#include <cstdint>
#include <deque>
#include <map>
#include <ostream>
#include <stdexcept>
#include <string>

// Passive edge samples only. This ledger never drives ready, valid, latency,
// ordering or guest input. The caller supplies its actual driven input values
// together with DUT outputs from the same evaluated tick, before memory.sample.
namespace posted_board {
inline void demand(bool value, const char *message) {
    if (!value) throw std::runtime_error(message);
}
enum class Window { None, Kernel, Flush };
struct AxiSample {
    bool arValid = false, arReady = false, awValid = false, awReady = false;
    bool rValid = false, rReady = false, wValid = false, wReady = false;
    bool bValid = false, bReady = false, rLast = false, wLast = false;
    unsigned arId = 0, arLen = 0, arSize = 0, awId = 0, awLen = 0, awSize = 0;
    unsigned rId = 0, bId = 0, wStrobe = 0;
};
struct ChannelCycles {
    uint64_t fire = 0, backpressured = 0, noOffer = 0;
    void sample(bool valid, bool ready) {
        if (!valid) ++noOffer;
        else if (ready) ++fire;
        else ++backpressured;
    }
    void verify(uint64_t cycles) const {
        demand(fire + backpressured + noOffer == cycles, "AXI channel buckets do not conserve cycles");
    }
};
struct WindowCounters {
    bool entered = false, exited = false;
    uint64_t cycles = 0, rBytes = 0, wBytes = 0, rWireBytes = 0, wWireBytes = 0;
    uint64_t readOutstandingCycles = 0, writeOutstandingCycles = 0;
    uint64_t bothOutstandingCycles = 0, simultaneousRwFire = 0;
    uint64_t outstandingWithoutRValid = 0, rBackpressure = 0;
    uint64_t readWindowEmpty = 0, wholeBusEmpty = 0;
    unsigned readPeak = 0, writePeak = 0;
    unsigned readCarryIn = 0, writeCarryIn = 0, readCarryOut = 0, writeCarryOut = 0;
    std::map<unsigned, uint64_t> readHistogram, writeHistogram;
    std::array<ChannelCycles, 4> channel; // AR, AW, R, W
    void sample(const AxiSample &s, unsigned reads, unsigned writes) {
        ++cycles;
        channel[0].sample(s.arValid, s.arReady);
        channel[1].sample(s.awValid, s.awReady);
        channel[2].sample(s.rValid, s.rReady);
        channel[3].sample(s.wValid, s.wReady);
        // Fixed 64-bit bus occupancy differs from requested payload and WSTRB.
        rWireBytes += s.rValid && s.rReady ? 8 : 0;
        wWireBytes += s.wValid && s.wReady ? 8 : 0;
        readOutstandingCycles += reads; writeOutstandingCycles += writes;
        readPeak = std::max(readPeak, reads); writePeak = std::max(writePeak, writes);
        ++readHistogram[reads]; ++writeHistogram[writes];
        bothOutstandingCycles += reads != 0 && writes != 0;
        simultaneousRwFire += s.rValid && s.rReady && s.wValid && s.wReady;
        outstandingWithoutRValid += reads != 0 && !s.rValid;
        rBackpressure += s.rValid && !s.rReady;
        readWindowEmpty += reads == 0 && !s.arValid && !s.rValid;
        wholeBusEmpty += reads == 0 && writes == 0 && !s.arValid && !s.awValid && !s.rValid &&
            !s.wValid && !s.bValid;
    }
    void verify() const {
        demand(entered && exited && cycles, "AXI accounting window was not completely sampled");
        for (const auto &counts : channel) counts.verify(cycles);
        uint64_t rCycles = 0, wCycles = 0, rWeighted = 0, wWeighted = 0;
        for (const auto &[depth, count] : readHistogram) { rCycles += count; rWeighted += depth * count; }
        for (const auto &[depth, count] : writeHistogram) { wCycles += count; wWeighted += depth * count; }
        demand(rCycles == cycles && wCycles == cycles && rWeighted == readOutstandingCycles &&
            wWeighted == writeOutstandingCycles, "AXI occupancy histogram does not conserve cycles/ownership");
        demand(rBackpressure == channel[2].backpressured, "AXI R backpressure classification differs");
        demand(rWireBytes == channel[2].fire * 8 && wWireBytes == channel[3].fire * 8 &&
            rBytes <= rWireBytes && wBytes <= wWireBytes, "AXI wire/payload byte accounting differs");
    }
    void json(std::ostream &out, const char *name) const {
        verify();
        out << "{\"window\":\"" << name << "\",\"cycles\":" << cycles
            << ",\"accepted_r_wire_bytes\":" << rWireBytes
            << ",\"accepted_r_requested_payload_bytes\":" << rBytes
            << ",\"accepted_w_wire_bytes\":" << wWireBytes << ",\"accepted_w_strobe_bytes\":" << wBytes
            << ",\"outstanding_sample\":\"pre_edge_accepted_owners\""
            << ",\"read_outstanding_cycle_sum\":" << readOutstandingCycles
            << ",\"write_outstanding_cycle_sum\":" << writeOutstandingCycles
            << ",\"read_outstanding_mean\":" << double(readOutstandingCycles) / cycles
            << ",\"write_outstanding_mean\":" << double(writeOutstandingCycles) / cycles
            << ",\"read_outstanding_peak\":" << readPeak << ",\"write_outstanding_peak\":" << writePeak
            << ",\"both_outstanding_cycles\":" << bothOutstandingCycles
            << ",\"simultaneous_r_w_fire\":" << simultaneousRwFire
            << ",\"read_outstanding_without_r_valid\":" << outstandingWithoutRValid
            << ",\"r_backpressure_cycles\":" << rBackpressure
            << ",\"read_window_empty\":" << readWindowEmpty << ",\"whole_bus_empty\":" << wholeBusEmpty
            << ",\"read_carry_in\":" << readCarryIn << ",\"write_carry_in\":" << writeCarryIn
            << ",\"read_carry_out\":" << readCarryOut << ",\"write_carry_out\":" << writeCarryOut;
        const std::array<const char *, 4> names{"ar", "aw", "r", "w"};
        for (unsigned i = 0; i < names.size(); ++i) out << ",\"" << names[i] << "\":{\"fire\":"
            << channel[i].fire << ",\"valid_not_ready\":" << channel[i].backpressured
            << ",\"no_offer\":" << channel[i].noOffer << '}';
        auto histogram = [&](const char *label, const auto &values) {
            out << ",\"" << label << "\":{";
            bool first = true;
            for (const auto &[depth, count] : values) {
                if (!first) out << ',';
                first = false; out << '"' << depth << "\":" << count;
            }
            out << '}';
        };
        histogram("read_outstanding_histogram", readHistogram);
        histogram("write_outstanding_histogram", writeHistogram);
        out << '}';
    }
};

class AxiAccounting {
    struct Read { unsigned beats, size; };
    struct Write { unsigned beats, size; };
    std::map<unsigned, Read> reads;
    std::map<unsigned, Write> writes;
    std::deque<unsigned> wOrder;
    AxiSample previous;
    bool havePrevious = false;
    Window active = Window::None;
    WindowCounters *counts() {
        return active == Window::Kernel ? &kernel : active == Window::Flush ? &flush : nullptr;
    }
    void readBeat(const AxiSample &s, WindowCounters *window) {
        auto it = reads.find(s.rId);
        demand(it != reads.end(), "AXI R has no accepted AR owner");
        demand(s.rLast == (it->second.beats == 1), "AXI RLAST does not complete its original AR burst");
        if (window) window->rBytes += uint64_t(1) << it->second.size;
        if (--it->second.beats == 0) reads.erase(it);
    }
    void writeResponse(const AxiSample &s) {
        auto it = writes.find(s.bId);
        demand(it != writes.end() && it->second.beats == 0, "AXI B has no completed original AW/W owner");
        writes.erase(it);
    }
public:
    WindowCounters kernel, flush;
    void sample(const AxiSample &s, Window window) {
        // Only metadata present in AxiSample is checked here. Address/data/RESP
        // stability remains the source interface's responsibility. W may be
        // offered before AW is accepted, but cannot fire without an AW owner.
        if (havePrevious) {
            if (previous.arValid && !previous.arReady) demand(s.arValid && s.arId == previous.arId &&
                s.arLen == previous.arLen && s.arSize == previous.arSize, "AXI held AR metadata changed");
            if (previous.awValid && !previous.awReady) demand(s.awValid && s.awId == previous.awId &&
                s.awLen == previous.awLen && s.awSize == previous.awSize, "AXI held AW metadata changed");
            if (previous.rValid && !previous.rReady) demand(s.rValid && s.rId == previous.rId &&
                s.rLast == previous.rLast, "AXI held R ID/LAST changed");
            if (previous.wValid && !previous.wReady) demand(s.wValid && s.wLast == previous.wLast &&
                s.wStrobe == previous.wStrobe, "AXI held W LAST/strobe changed");
            if (previous.bValid && !previous.bReady) demand(s.bValid && s.bId == previous.bId,
                "AXI held B ID changed");
        }
        // BVALID itself requires an AW and its complete W burst on earlier
        // edges. BREADY being low cannot legitimize an orphan/early offer.
        // Check before accepting this edge's AW/W, including same-ID turnover.
        if (s.bValid) {
            const auto owner = writes.find(s.bId);
            demand(owner != writes.end() && owner->second.beats == 0,
                "AXI BVALID has no prior-edge completed AW/W owner");
        }
        if (s.rValid) {
            const auto owner = reads.find(s.rId);
            const bool sameEdgeAr = s.arValid && s.arReady && s.arId == s.rId;
            demand(owner != reads.end() || sameEdgeAr, "AXI R has no accepted AR owner");
            const unsigned beats = owner != reads.end() ? owner->second.beats : s.arLen + 1;
            demand(s.rLast == (beats == 1), "AXI RLAST does not complete its original AR burst");
        }
        if (window != active) {
            if (auto *old = counts()) {
                old->readCarryOut = reads.size(); old->writeCarryOut = writes.size(); old->exited = true;
            }
            active = window;
            if (auto *next = counts()) {
                demand(!next->entered, "AXI accounting window reentered");
                next->entered = true; next->readCarryIn = reads.size(); next->writeCarryIn = writes.size();
            }
        }
        auto *current = counts();
        // Occupancy is the pre-edge accepted-transaction responsibility. Track
        // it outside ROI too, so carry-in and carry-out cannot disappear.
        if (current) current->sample(s, reads.size(), writes.size());
        const bool rf = s.rValid && s.rReady, bf = s.bValid && s.bReady;
        const bool oldRead = rf && reads.count(s.rId);
        if (oldRead) readBeat(s, current);
        if (bf) writeResponse(s);
        if (s.arValid && s.arReady) {
            demand(s.arSize <= 3 && s.arLen < 256 && !reads.count(s.arId), "AXI AR reused a live ID or invalid size");
            reads.emplace(s.arId, Read{s.arLen + 1, s.arSize});
        }
        if (rf && !oldRead) readBeat(s, current); // Legal zero-latency same-edge AR/R.
        if (s.awValid && s.awReady) {
            demand(s.awSize <= 3 && s.awLen < 256 && !writes.count(s.awId), "AXI AW reused a live ID or invalid size");
            writes.emplace(s.awId, Write{s.awLen + 1, s.awSize}); wOrder.push_back(s.awId);
        }
        if (s.wValid && s.wReady) {
            demand(!wOrder.empty() && s.wStrobe <= 255, "AXI W has no accepted AW owner or invalid strobe");
            auto &owner = writes.at(wOrder.front());
            demand(owner.beats && s.wLast == (owner.beats == 1), "AXI WLAST does not complete original AW burst");
            demand(unsigned(std::popcount(s.wStrobe)) <= (1U << owner.size),
                "AXI W strobe exceeds original AW transfer size");
            if (current) current->wBytes += std::popcount(s.wStrobe);
            if (--owner.beats == 0) wOrder.pop_front();
        }
        previous = s;
        havePrevious = true;
    }
    void finish() {
        if (auto *last = counts()) {
            last->readCarryOut = reads.size(); last->writeCarryOut = writes.size(); last->exited = true;
        }
        active = Window::None;
        kernel.verify(); flush.verify();
        demand(reads.empty() && writes.empty() && wOrder.empty(), "AXI final drain lost accepted read/write responsibility");
    }
};
} // namespace posted_board
