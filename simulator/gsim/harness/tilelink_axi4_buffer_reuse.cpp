// Focused shared-slot payload proof. External bus oracles intentionally do not
// inspect the implementation's payload array, state encodings, or slot pointers.
#include "TileLinkAxi4Bridge.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
#ifndef MAX_BURST_BEATS
#define MAX_BURST_BEATS 8
#endif
#ifndef AXI_SLOTS
#define AXI_SLOTS 1
#endif
#ifndef WRITE_CREDITS
#define WRITE_CREDITS 0
#endif

// Record fully specified inputs and only meaningful outputs. Never compare
// undefined payload bits on invalid channels or memory contents during reset.
class TracedBridge : public STileLinkAxi4Bridge {
    std::array<uint64_t, 24> inputs{};
    std::ofstream trace;
    uint64_t cycle = 0;
    bool resetting = true;
    std::array<int, AXI_SLOTS> lastDirection{};
    std::array<unsigned, AXI_SLOTS> readToWrite{}, writeToRead{};
    void recordOwner(unsigned id, bool write) {
        if (id >= AXI_SLOTS) throw std::runtime_error("AXI owner outside slot range");
        if (lastDirection[id] == 0 && write) ++readToWrite[id];
        if (lastDirection[id] == 1 && !write) ++writeToRead[id];
        lastDirection[id] = write;
    }
public:
    explicit TracedBridge(const std::string& path = "") {
        lastDirection.fill(-1);
        if (!path.empty()) {
            trace.open(path);
            if (!trace) throw std::runtime_error("cannot open trace file");
        }
    }
#define INPUT(port, index) \
    void set_##port(uint64_t value) { inputs[index] = value; STileLinkAxi4Bridge::set_##port(value); }
    INPUT(io$$tl$$a$$valid, 0)
    INPUT(io$$tl$$a$$bits$$opcode, 1)
    INPUT(io$$tl$$a$$bits$$param, 2)
    INPUT(io$$tl$$a$$bits$$size, 3)
    INPUT(io$$tl$$a$$bits$$source, 4)
    INPUT(io$$tl$$a$$bits$$address, 5)
    INPUT(io$$tl$$a$$bits$$mask, 6)
    INPUT(io$$tl$$a$$bits$$data, 7)
    INPUT(io$$tl$$a$$bits$$corrupt, 8)
    INPUT(io$$tl$$c$$valid, 9)
    INPUT(io$$tl$$e$$valid, 10)
    INPUT(io$$tl$$d$$ready, 11)
    INPUT(io$$axi$$ar$$ready, 12)
    INPUT(io$$axi$$aw$$ready, 13)
    INPUT(io$$axi$$w$$ready, 14)
    INPUT(io$$axi$$r$$valid, 15)
    INPUT(io$$axi$$r$$bits$$id, 16)
    INPUT(io$$axi$$r$$bits$$data, 17)
    INPUT(io$$axi$$r$$bits$$resp, 18)
    INPUT(io$$axi$$r$$bits$$last, 19)
    INPUT(io$$axi$$b$$valid, 20)
    INPUT(io$$axi$$b$$bits$$id, 21)
    INPUT(io$$axi$$b$$bits$$resp, 22)
#undef INPUT
    void set_reset(uint64_t value) {
        resetting = value;
        inputs[23] = value;
        STileLinkAxi4Bridge::set_reset(value);
    }
    void verifyReuseCoverage() const {
        for (unsigned id = 0; id < AXI_SLOTS; ++id)
            if (readToWrite[id] < 2 || writeToRead[id] < 2)
                throw std::runtime_error("physical slot read/write reuse coverage missing");
        std::cout << "REUSE_EVERY_SLOT_PASS slots=" << AXI_SLOTS << '\n';
    }
    void step() {
        STileLinkAxi4Bridge::step();
        if (!resetting) {
            if (get_io$$axi$$ar$$valid() && inputs[12]) recordOwner(get_io$$axi$$ar$$bits$$id(), false);
            if (get_io$$axi$$aw$$valid() && inputs[13]) recordOwner(get_io$$axi$$aw$$bits$$id(), true);
        }
        if (trace) {
            trace << "I " << cycle;
            for (auto value : inputs) trace << ' ' << value;
            trace << '\n' << "O " << cycle;
            if (resetting) trace << " reset";
            else {
                trace << ' ' << uint64_t(get_io$$tl$$a$$ready()) << ' '
                      << uint64_t(get_io$$axi$$r$$ready()) << ' ' << uint64_t(get_io$$axi$$b$$ready());
#define ADDRESS(channel) \
                trace << ' ' << uint64_t(get_io$$axi$$##channel##$$valid()); \
                if (get_io$$axi$$##channel##$$valid()) \
                    trace << ' ' << uint64_t(get_io$$axi$$##channel##$$bits$$addr()) \
                          << ' ' << uint64_t(get_io$$axi$$##channel##$$bits$$id()) \
                          << ' ' << uint64_t(get_io$$axi$$##channel##$$bits$$len()) \
                          << ' ' << uint64_t(get_io$$axi$$##channel##$$bits$$size());
                ADDRESS(ar)
                ADDRESS(aw)
#undef ADDRESS
                trace << ' ' << uint64_t(get_io$$axi$$w$$valid());
                if (get_io$$axi$$w$$valid())
                    trace << ' ' << uint64_t(get_io$$axi$$w$$bits$$data()) << ' '
                          << uint64_t(get_io$$axi$$w$$bits$$strb()) << ' ' << uint64_t(get_io$$axi$$w$$bits$$last());
                trace << ' ' << uint64_t(get_io$$tl$$d$$valid());
                if (get_io$$tl$$d$$valid())
                    trace << ' ' << uint64_t(get_io$$tl$$d$$bits$$source()) << ' '
                          << uint64_t(get_io$$tl$$d$$bits$$size()) << ' ' << uint64_t(get_io$$tl$$d$$bits$$opcode())
                          << ' ' << uint64_t(get_io$$tl$$d$$bits$$denied()) << ' ' << uint64_t(get_io$$tl$$d$$bits$$corrupt())
                          << ' ' << uint64_t(get_io$$tl$$d$$bits$$data());
            }
            trace << '\n';
        }
        ++cycle;
    }
};

// Reuse the established independent AW/W payload/strobe/order checks unchanged.
// Its entry point is not executed: the focused entry below chooses bounded cases.
#define STileLinkAxi4Bridge TracedBridge
#define main existing_write_channel_entry
#include "tilelink_axi4_mixed_channels.cpp"
#undef main
#undef STileLinkAxi4Bridge

static bool injectReadMismatch = false;
static std::vector<uint64_t> readWords(unsigned seed, unsigned beats) {
    std::vector<uint64_t> words;
    for (unsigned beat = 0; beat < beats; ++beat)
        words.push_back(0xc35a9f1072e846bdULL ^ (uint64_t(seed) << 36) ^ (uint64_t(beat) * 0x1837465a19ULL));
    return words;
}

// Exercise a complete R burst, the late-error aggregation barrier, and a stalled
// first D beat. A reset cut is made only after confirming live payload exists.
static void readTransaction(TracedBridge& d, unsigned n, const std::vector<uint64_t>& words,
                            bool error = false, bool reject = false, unsigned resetCut = 0) {
    const unsigned beats = words.size();
    unsigned a = 0, ar = 0, r = 0, replies = 0, id = 0;
    unsigned arCycle = 0, finalRCycle = 0, heldCycles = 0;
    std::optional<std::tuple<uint64_t, unsigned, unsigned, unsigned>> heldAr;
    std::optional<std::tuple<uint64_t, unsigned, unsigned, unsigned, bool, bool>> heldD;
    for (unsigned cycle = 0; cycle < 2000; ++cycle) {
        const bool arReady = cycle % 7 >= 3;
        const bool rValid = ar && r < beats && cycle > arCycle + 3 && cycle % 4 != 1;
        const bool dReady = (reject ? cycle >= 20 : r == beats && cycle > finalRCycle + 9) && cycle % 5 < 2;
        d.set_io$$tl$$a$$valid(!a);
        d.set_io$$tl$$a$$bits$$opcode(4); d.set_io$$tl$$a$$bits$$param(0);
        d.set_io$$tl$$a$$bits$$size(size(beats)); d.set_io$$tl$$a$$bits$$source(n % 8);
        d.set_io$$tl$$a$$bits$$address(base + 0x80 + n * 4096ULL);
        d.set_io$$tl$$a$$bits$$mask(255); d.set_io$$tl$$a$$bits$$data(0);
        d.set_io$$tl$$a$$bits$$corrupt(0); d.set_io$$tl$$d$$ready(dReady);
        d.set_io$$axi$$ar$$ready(arReady); d.set_io$$axi$$aw$$ready(1); d.set_io$$axi$$w$$ready(1);
        d.set_io$$axi$$r$$valid(rValid); d.set_io$$axi$$r$$bits$$id(id);
        d.set_io$$axi$$r$$bits$$data(r < beats ? words[r] : 0);
        d.set_io$$axi$$r$$bits$$resp(error && r + 1 == beats ? 2 : 0);
        d.set_io$$axi$$r$$bits$$last(r + 1 == beats); d.set_io$$axi$$b$$valid(0);
        d.step();
        const bool av = d.get_io$$axi$$ar$$valid(), dv = d.get_io$$tl$$d$$valid();
        auto address = std::make_tuple(uint64_t(d.get_io$$axi$$ar$$bits$$addr()),
            unsigned(d.get_io$$axi$$ar$$bits$$id()), unsigned(d.get_io$$axi$$ar$$bits$$len()),
            unsigned(d.get_io$$axi$$ar$$bits$$size()));
        auto reply = std::make_tuple(uint64_t(d.get_io$$tl$$d$$bits$$data()),
            unsigned(d.get_io$$tl$$d$$bits$$source()), unsigned(d.get_io$$tl$$d$$bits$$size()),
            unsigned(d.get_io$$tl$$d$$bits$$opcode()), bool(d.get_io$$tl$$d$$bits$$denied()),
            bool(d.get_io$$tl$$d$$bits$$corrupt()));
        if (heldAr) check(av && address == *heldAr, "reuse held AR changed");
        if (heldD) check(dv && reply == *heldD, "reuse held D changed");
        heldAr = av && !arReady ? std::optional{address} : std::nullopt;
        heldD = dv && !dReady ? std::optional{reply} : std::nullopt;
        if (!a && d.get_io$$tl$$a$$ready()) ++a;
        check(!d.get_io$$axi$$aw$$valid() && !d.get_io$$axi$$w$$valid(), "read leaked write payload");
        if (reject) check(!av && !d.get_io$$axi$$r$$ready(), "oversize Get reached AXI");
        if (av && arReady) {
            check(a && !ar && std::get<0>(address) == 0x80 + n * 4096ULL &&
                std::get<1>(address) < AXI_SLOTS && std::get<2>(address) + 1 == beats &&
                std::get<3>(address) == 3, "reuse AR owner/attributes mismatch");
            id = std::get<1>(address); arCycle = cycle; ++ar;
        }
        if (rValid && d.get_io$$axi$$r$$ready()) { ++r; if (r == beats) finalRCycle = cycle; }
        if (dv) {
            check(reject || r == beats, "partial read escaped before late R error known");
            check(std::get<1>(reply) == n % 8 && std::get<2>(reply) == size(beats) &&
                std::get<3>(reply) == 1 && std::get<4>(reply) == (error || reject) &&
                std::get<5>(reply) == (error || reject), "reuse D owner/error metadata mismatch");
            const uint64_t expected = (error || reject ? 0 : words.at(replies)) ^ (injectReadMismatch ? 1ULL : 0ULL);
            check(std::get<0>(reply) == expected, "independent reuse read-data oracle mismatch");
            if (!dReady) ++heldCycles;
            else ++replies;
        }
        if ((resetCut == 1 && r == beats / 2) || (resetCut == 2 && heldCycles >= 4)) {
            check(a && ar && r && !replies, "reset did not interrupt live read payload");
            reset(d);
            std::cout << "REUSE_READ_RESET_PASS cut=" << resetCut << '\n';
            return;
        }
        if (replies == beats) {
            check(a == 1 && ar == unsigned(!reject) && r == (reject ? 0 : beats) && heldCycles,
                "reuse read missing beats or D backpressure coverage");
            return;
        }
    }
    throw std::runtime_error("reuse read progress deadline");
}

// Keep a completed read live under D backpressure while another slot drains an
// oversized Put. This catches accidental bank/address aliasing and wrong D owner
// selection. Both denied Put and denied Get must emit no AW/W/AR traffic.
static void liveReadWithDeniedTraffic(TracedBridge& d) {
    reset(d);
    constexpr unsigned readBeats = MAX_BURST_BEATS, deniedBeats = MAX_BURST_BEATS * 2;
    auto words = readWords(91, readBeats);
    unsigned request = 0, aBeat = 0, ar = 0, r = 0, id = 0, completed = 0;
    std::array<unsigned, 3> dBeats{};
    std::optional<unsigned> dOwner;
    std::optional<std::tuple<uint64_t, unsigned, unsigned, unsigned, bool, bool>> heldD;
    bool concurrent = false;
    for (unsigned cycle = 0; cycle < 3000 && completed < 3; ++cycle) {
        const bool aValid = request < 3;
        const unsigned owner = std::min(request, 2U);
        const bool put = owner == 1;
        const unsigned beats = owner == 0 ? readBeats : deniedBeats;
        const bool rv = ar && r < readBeats && cycle % 3 != 1;
        const bool dr = cycle >= 120 && cycle % 4 == 0;
        d.set_io$$tl$$a$$valid(aValid); d.set_io$$tl$$a$$bits$$opcode(put ? 1 : 4);
        d.set_io$$tl$$a$$bits$$param(0); d.set_io$$tl$$a$$bits$$size(size(beats));
        d.set_io$$tl$$a$$bits$$source(owner); d.set_io$$tl$$a$$bits$$address(base + owner * 4096ULL);
        d.set_io$$tl$$a$$bits$$mask(put ? strobe(aBeat) : 255);
        d.set_io$$tl$$a$$bits$$data(data(72, aBeat)); d.set_io$$tl$$a$$bits$$corrupt(0);
        d.set_io$$tl$$d$$ready(dr); d.set_io$$axi$$ar$$ready(1);
        d.set_io$$axi$$aw$$ready(1); d.set_io$$axi$$w$$ready(1); d.set_io$$axi$$b$$valid(0);
        d.set_io$$axi$$r$$valid(rv); d.set_io$$axi$$r$$bits$$id(id);
        d.set_io$$axi$$r$$bits$$data(r < readBeats ? words[r] : 0);
        d.set_io$$axi$$r$$bits$$resp(0); d.set_io$$axi$$r$$bits$$last(r + 1 == readBeats);
        d.step();
        if (aValid && d.get_io$$tl$$a$$ready()) {
            if (put && ar && !completed) concurrent = true;
            ++aBeat;
            if (!put || aBeat == beats) { ++request; aBeat = 0; }
        }
        check(!d.get_io$$axi$$aw$$valid() && !d.get_io$$axi$$w$$valid(), "denied traffic emitted AXI write");
        if (d.get_io$$axi$$ar$$valid()) {
            check(!ar && d.get_io$$axi$$ar$$bits$$addr() == 0 &&
                d.get_io$$axi$$ar$$bits$$len() == readBeats - 1, "denied traffic emitted extra AXI read");
            id = d.get_io$$axi$$ar$$bits$$id(); ++ar;
        }
        if (rv && d.get_io$$axi$$r$$ready()) ++r;
        const bool dv = d.get_io$$tl$$d$$valid();
        auto reply = std::make_tuple(uint64_t(d.get_io$$tl$$d$$bits$$data()),
            unsigned(d.get_io$$tl$$d$$bits$$source()), unsigned(d.get_io$$tl$$d$$bits$$size()),
            unsigned(d.get_io$$tl$$d$$bits$$opcode()), bool(d.get_io$$tl$$d$$bits$$denied()),
            bool(d.get_io$$tl$$d$$bits$$corrupt()));
        if (heldD) check(dv && reply == *heldD, "denied overlap changed stalled D");
        heldD = dv && !dr ? std::optional{reply} : std::nullopt;
        if (dv && dr) {
            const unsigned source = std::get<1>(reply);
            check(source < 3, "denied overlap D unknown source");
            if (dOwner) check(*dOwner == source, "denied overlap interleaved D burst");
            else dOwner = source;
#ifndef UNORDERED_TL
            check(source == completed, "denied overlap FIFO D order changed");
#endif
            const bool write = source == 1, denied = source != 0;
            const unsigned count = write ? 1 : source == 0 ? readBeats : deniedBeats;
            check(dBeats[source] < count && std::get<2>(reply) == size(source == 0 ? readBeats : deniedBeats) &&
                std::get<3>(reply) == unsigned(!write) && std::get<4>(reply) == denied &&
                std::get<5>(reply) == (denied && !write), "denied overlap metadata/duplicate mismatch");
            check(std::get<0>(reply) == (denied ? 0 : words[dBeats[source]]), "denied drain corrupted live read payload");
            if (!denied) check(r == readBeats, "denied overlap partial read escaped");
            if (write) check(request > 1, "denied Put replied before complete A drain");
            if (++dBeats[source] == count) { ++completed; dOwner.reset(); }
        }
    }
    check((WRITE_CREDITS == 0 || AXI_SLOTS == 1 || concurrent) &&
        completed == 3 && request == 3 && ar == 1 && r == readBeats,
        "denied/live-payload coverage or progress missing");
    std::cout << "REUSE_DENIED_LIVE_PAYLOAD_PASS\n";
}

int main(int argc, char** argv) {
    try {
        std::string tracePath;
        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--inject-read") injectReadMismatch = true;
            else if (arg == "--inject-write") injectMismatch = true;
            else if (arg == "--trace" && i + 1 < argc) tracePath = argv[++i];
            else throw std::runtime_error("unknown or incomplete buffer-reuse option");
        }
        check(MAX_BURST_BEATS <= 8, "focused denial test requires encodable oversized bursts");
        TracedBridge d(tracePath); reset(d);
        unsigned n = 0;
        // Blocks of AXI_SLOTS requests force each physical ID to alternate read
        // and write ownership, including when FIFO allocation wraps repeatedly.
        for (unsigned round = 0; round < 3; ++round) {
            for (unsigned slot = 0; slot < AXI_SLOTS; ++slot) {
                const unsigned owner = n++;
                readTransaction(d, owner, readWords(owner, MAX_BURST_BEATS), round == 1);
            }
            for (unsigned slot = 0; slot < AXI_SLOTS; ++slot)
                transaction(d, n++, MAX_BURST_BEATS, round, round == 2);
        }
        d.verifyReuseCoverage();
        // Partial-byte readback has a separately computed software byte oracle.
        for (unsigned beats : {1U, 2U, 4U, 8U}) {
            const unsigned owner = n++;
            transaction(d, owner, beats, 4);
            auto expected = readWords(owner, beats);
            for (unsigned beat = 0; beat < beats; ++beat)
                for (unsigned byte = 0; byte < 8; ++byte)
                    if (strobe(beat) & (1U << byte)) {
                        const uint64_t byteMask = 0xffULL << (8 * byte);
                        expected[beat] = (expected[beat] & ~byteMask) | (data(owner, beat) & byteMask);
                    }
            readTransaction(d, owner, expected);
        }
        readTransaction(d, n++, readWords(101, MAX_BURST_BEATS * 2), false, true);
        liveReadWithDeniedTraffic(d);
        if (AXI_SLOTS > 1 && WRITE_CREDITS >= 2) {
            queuedWrites(d); // Whole W bursts before AW, then inverse-ID B order.
            deniedHead(d);
        }
        reset(d);
        for (unsigned cut : {1U, 2U}) {
            readTransaction(d, n++, readWords(102 + cut, MAX_BURST_BEATS), false, false, cut);
            transaction(d, n++, MAX_BURST_BEATS, cut == 1 ? 0 : 1);
            readTransaction(d, n++, readWords(110 + cut, MAX_BURST_BEATS));
        }
        transaction(d, n++, MAX_BURST_BEATS, 0, false, 1);
        readTransaction(d, n++, readWords(121, MAX_BURST_BEATS));
        transaction(d, n++, MAX_BURST_BEATS, 1, false, 2);
        readTransaction(d, n++, readWords(122, MAX_BURST_BEATS));
        std::cout << "BUFFER_REUSE_ALL_PASS slots=" << AXI_SLOTS << " burst=" << MAX_BURST_BEATS
                  << " writes=" << WRITE_CREDITS << "\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "BUFFER_REUSE_FAIL " << error.what() << '\n';
        return 1;
    }
}
