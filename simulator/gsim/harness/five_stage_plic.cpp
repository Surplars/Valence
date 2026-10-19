#include "FiveStagePlicHarness.h"
#include <array>
#include <random>
#include <stdexcept>
#include <iostream>
#include <string_view>

static void require(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
struct Oracle {
    std::array<unsigned, 9> priority{};
    std::array<bool, 9> pending{}, blocked{};
    std::array<unsigned, 2> enabled{}, threshold{};
    bool valid = false, error = false;
    uint64_t data = 0;
    unsigned winner(unsigned context) const {
        unsigned result = 0;
        for (unsigned n = 1; n <= 8; ++n)
            if (pending[n] && (enabled[context] >> n & 1) && priority[n] > priority[result]) result = n;
        return result;
    }
};
int main(int argc, char **argv) { try {
    SFiveStagePlicHarness d; Oracle o; std::mt19937_64 rng{0x504c4943};
    d.set_reset(1); d.set_io$$mmio$$request$$valid(0); d.step(); d.step(); d.set_reset(0);
    unsigned transactions = 0, claims = 0, errors = 0;
    const bool wrongIrq = argc > 1 && std::string_view(argv[1]) == "--wrong-irq";
    bool negative = argc > 1 && !wrongIrq;
    auto tick = [&](unsigned levels, bool valid, uint64_t address, bool write, uint64_t value,
                    unsigned size, unsigned mask, bool responseReady) {
        d.set_io$$mmio$$request$$valid(valid); d.set_io$$mmio$$request$$bits$$address(address);
        d.set_io$$mmio$$request$$bits$$write(write); d.set_io$$mmio$$request$$bits$$data(value);
        d.set_io$$mmio$$request$$bits$$size(size); d.set_io$$mmio$$request$$bits$$byteEnable(mask);
        d.set_io$$mmio$$response$$ready(responseReady);
        d.set_io$$levels(levels);
        d.step();
        const unsigned observedIrq = d.get_io$$irq() ^ unsigned(wrongIrq);
        require((observedIrq & 1) == (o.priority[o.winner(0)] > o.threshold[0]) &&
                (observedIrq >> 1) == (o.priority[o.winner(1)] > o.threshold[1]), "PLIC priority/threshold IRQ oracle");
        require(d.get_io$$mmio$$request$$ready() == !o.valid, "PLIC MMIO owner/ready oracle");
        require(d.get_io$$mmio$$response$$valid() == o.valid, "PLIC reply owner oracle");
        if (o.valid) {
            require(d.get_io$$mmio$$response$$bits$$data() == o.data &&
                bool(d.get_io$$mmio$$response$$bits$$error()) == o.error, "PLIC reply payload/side-effect oracle");
        }
        bool accept = valid && !o.valid;
        Oracle next = o;
        for (unsigned s = 1; s <= 8; ++s)
            if (!o.blocked[s] && !o.pending[s] && (levels >> s & 1)) next.pending[s] = next.blocked[s] = true;
        if (o.valid && responseReady) next.valid = false;
        if (accept) {
            ++transactions;
            next.valid = true; next.data = 0; next.error = true;
            bool geometry = address >= 0xc000000 && address < 0x10000000 &&
                !(address & 3) && size == 2 && mask == 15;
            uint64_t offset = address - 0xc000000;
            if (geometry) {
                if (offset <= 32) {
                    unsigned s = offset / 4;
                    next.error = false; next.data = o.priority[s];
                    if (write && s) next.priority[s] = value & 7;
                } else if (offset == 0x1000 && !write) {
                    next.error = false;
                    for (unsigned s = 1; s <= 8; ++s) next.data |= uint64_t(o.pending[s]) << s;
                }
                for (unsigned c = 0; c < 2; ++c) {
                    if (offset == 0x2000 + c * 0x80) {
                        next.error = false; next.data = o.enabled[c];
                        if (write) next.enabled[c] = value & 0x1fe;
                    }
                    if (offset == 0x200000 + c * 0x1000) {
                        next.error = false; next.data = o.threshold[c];
                        if (write) next.threshold[c] = value & 7;
                    }
                    if (offset == 0x200004 + c * 0x1000) {
                        next.error = false; unsigned winner = o.winner(c); next.data = winner;
                        if (!write && winner) { next.pending[winner] = false; ++claims; }
                        if (!write && negative) next.data ^= 1; // independent-oracle sensitivity control
                        if (write && uint32_t(value) >= 1 && uint32_t(value) <= 8 &&
                            (o.enabled[c] >> uint32_t(value) & 1)) next.blocked[uint32_t(value)] = false;
                    }
                }
            }
            errors += next.error;
        }
        o = next;
    };
    auto access = [&](uint64_t offset, bool write, unsigned value, unsigned levels = 0,
                      unsigned size = 2, unsigned mask = 15) {
        // Hold every offered request until acceptance; scramble live A AFTER acceptance to test saved response.
        while (o.valid) tick(levels, false, 0, false, 0, 2, 15, true);
        tick(levels, true, 0xc000000 + offset, write, value, size, mask, false);
        for (unsigned n = 0; n < 1 + rng() % 5; ++n) tick(levels, true, 0xfeedface, true, rng(), 0, 0, false);
        tick(levels, false, 0, false, 0, 0, 0, true);
    };
    access(4, true, 1); access(8, true, 1); access(12, true, 3);
    access(0x2000, true, 0x1fe); access(0x2080, true, 0x1fe);
    // Threshold masks notification but NOT claim. Deassertion cannot retract a pending gateway.
    access(0x200000, true, 7, 0x0e); access(0x1000, false, 0);
    require(o.pending[1] && o.pending[2] && o.pending[3], "PLIC level pulse was retracted");
    access(0x200004, false, 0); access(0x201004, false, 0); access(0x200004, false, 0);
    require(!o.pending[1] && !o.pending[2] && !o.pending[3], "PLIC claim/lowest-ID tie failed");
    access(0x200004, true, 3, 8); // enabled completion, source remains high
    access(0x200004, false, 0, 8);
    access(0x2000, true, 0); access(0x200004, true, 3, 8); // disabled completion ignored
    require(o.blocked[3], "PLIC accepted disabled completion");
    access(0x2000, true, 0x1fe); access(0x200004, true, 3, 8);
    // Real DUT/MMIO sweep, not an algebra-only software check. With all
    // pending gateways set, every enabled subset is an eligible subset.
    // Priorities cover 0..7, and both contexts see all 256 masks/8 thresholds.
    for (unsigned s = 1; s <= 8; ++s) access(4 * s, true, s - 1, 0x1fe);
    access(0x2000, true, 0x1fe, 0x1fe); access(0x2080, true, 0x1fe, 0x1fe);
    for (unsigned s = 1; s <= 8; ++s) access(0x200004, true, s, 0x1fe);
    for (unsigned s = 1; s <= 8; ++s) require(o.pending[s], "PLIC IRQ sweep missed a pending source");
    for (unsigned threshold = 0; threshold < 8; ++threshold) {
        access(0x200000, true, threshold, 0x1fe);
        access(0x201000, true, 7 - threshold, 0x1fe);
        for (unsigned mask = 0; mask < 256; ++mask) {
            access(0x2000, true, mask << 1, 0x1fe);
            access(0x2080, true, ((mask * 149) & 255) << 1, 0x1fe);
        }
    }
    for (unsigned n = 0; n < 2500; ++n) {
        unsigned levels = rng() & 0x1ff;
        unsigned kind = rng() % 7, c = rng() % 2;
        uint64_t offset = kind == 0 ? (rng() % 9) * 4 : kind == 1 ? 0x1000 :
            kind == 2 ? 0x2000 + c * 0x80 : kind == 3 ? 0x200000 + c * 0x1000 :
            kind == 4 ? 0x200004 + c * 0x1000 : kind == 5 ? 0x200008 : 3;
        access(offset, bool(rng() & 1), rng() % 1024, levels,
               n % 17 ? 2 : 3, n % 23 ? 15 : 3);
    }
    require(claims > 10 && errors > 100, "PLIC stimuli did not exercise claims/errors");
    std::cout << "FIVE_STAGE_PLIC_PASS transactions=" << transactions << " claims=" << claims
              << " errors=" << errors << " contexts=2 sources=8 held_response_level_gateway=PASS"
              << " irq_sweep_masks=256 thresholds=8\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
