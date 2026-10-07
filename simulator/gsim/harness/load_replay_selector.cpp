#include "LoadReplaySelectorGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

int main(int argc, char **argv) {
    try {
        SLoadReplaySelectorGsim dut;
        dut.set_reset(0);
        const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
        uint64_t checks = 0;
        auto check = [&](unsigned head, unsigned owner, bool valid, unsigned eligible,
                         uint64_t beat, unsigned lanes, uint64_t b0, uint64_t b1,
                         unsigned l0, unsigned l1, unsigned bank) {
            dut.set_io$$head(head);
            dut.set_io$$checkedIndex(owner);
            dut.set_io$$checkedValid(valid);
            dut.set_io$$eligible(eligible);
            dut.set_io$$checkedBeat(beat);
            dut.set_io$$checkedLanes(lanes);
            dut.set_io$$beat0(b0);
            dut.set_io$$beat1(b1);
            dut.set_io$$lanes0(l0);
            dut.set_io$$lanes1(l1);
            dut.set_io$$bank(bank);
            dut.step();
            unsigned expected = 0, index = 0;
            // Independent ordered ROB walk: examine slots AFTER the checked load,
            // ending just before head. No DUT age comparator/priority algorithm.
            if (valid) {
                for (unsigned slot = (owner + 1) % 16; slot != head; slot = (slot + 1) % 16) {
                    const bool second = (bank >> slot) & 1;
                    if (((eligible >> slot) & 1) && (second ? b1 : b0) == beat &&
                        ((second ? l1 : l0) & lanes)) {
                        expected = 1U << slot;
                        index = slot;
                        break;
                    }
                }
            }
            unsigned actual = dut.get_io$$oneHot();
            if (inject && checks == 0) actual ^= 1;
            if (actual != expected || bool(dut.get_io$$valid()) != bool(expected) ||
                (expected && dut.get_io$$index() != index))
                throw std::runtime_error("replay selector independent oracle mismatch");
            ++checks;
        };
        for (unsigned head = 0; head < 16; ++head)
            for (unsigned owner = 0; owner < 16; ++owner)
                for (unsigned mask = 0; mask < 65536; ++mask)
                    check(head, owner, true, mask, 0x10000001ULL, 0x81,
                          0x10000001ULL, 0x10000001ULL, 0x81, 0x81, 0);
        for (unsigned bit = 0; bit < 61; ++bit)
            for (unsigned lane = 0; lane < 8; ++lane)
                for (unsigned head = 0; head < 16; ++head) {
                    check(head, head, true, 65535, 0, 1U << lane,
                          0, uint64_t(1) << bit, 1U << lane, 1U << lane, 0xaaaa);
                    check(head, head, true, 65535, 0, 1U << lane,
                          0, 0, 1U << lane, (1U << lane) ^ 255, 0xaaaa);
                }
        std::mt19937_64 rng(0x2b0050ULL);
        constexpr uint64_t beatMask = (uint64_t(1) << 61) - 1;
        for (unsigned n = 0; n < 100000; ++n) {
            uint64_t beat = rng() & beatMask;
            check(rng() % 16, rng() % 16, rng() % 4 != 0, rng() & 65535,
                  beat, rng() & 255, beat, (rng() & 1) ? beat : rng() & beatMask,
                  rng() & 255, rng() & 255, rng() & 65535);
        }
        std::cout << "GSIM load replay selector: PASS " << checks
                  << " vectors; exhaustive masks/head/owner, full PA, byte lanes, invalid/wrap\n";
    } catch (const std::exception &e) {
        std::cerr << e.what() << "\n";
        return 1;
    }
}
