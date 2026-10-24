#include "DualCompletionSelectorGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

int main(int argc, char** argv) { try {
    const bool inject = argc > 1 && std::string_view(argv[1]) == "--inject-mismatch";
    SDualCompletionSelectorGsim d;
    std::mt19937_64 random(0xa1300cdb);
    uint64_t cases = 0, dual = 0, duplicate = 0, wrapped = 0, sidePairs = 0;
    d.set_reset(0);
    for (unsigned pass = 0; pass < 96; ++pass) {
        std::array<unsigned, 6> slots{};
        for (unsigned i = 0; i < slots.size(); ++i)
            slots[i] = pass < 16 ? (pass + i) % 16 : random() % 16;
        uint32_t packed = 0;
        for (unsigned i = 0; i < slots.size(); ++i) packed |= slots[i] << (i * 4);
        for (unsigned head = 0; head < 16; ++head) for (unsigned mask = 0; mask < 64; ++mask) {
            const uint64_t seed = random();
            d.set_io$$head(head); d.set_io$$present(mask); d.set_io$$indices(packed); d.set_io$$seed(seed);
            d.step();
            std::array<unsigned, 2> expected{};
            unsigned count = 0;
            // Independent software ROB walk. No ranking/PopCount equation from DUT.
            for (unsigned offset = 0; offset < 16 && count < 2; ++offset) {
                const unsigned slot = (head + offset) % 16;
                for (unsigned i = 0; i < slots.size(); ++i) {
                    if ((mask & (1U << i)) && slots[i] == slot) {
                        expected[count++] = 1U << i; break;
                    }
                }
            }
            if (inject && cases == 111) expected[0] ^= 1U;
            const std::array<unsigned, 2> got{unsigned(d.get_io$$first()), unsigned(d.get_io$$second())};
            if (got != expected || d.get_io$$selected() != (expected[0] | expected[1]))
                throw std::runtime_error("dual completion independent owner oracle mismatch");
            for (unsigned rank = 0; rank < 2; ++rank) {
                uint64_t data = 0;
                for (unsigned i = 0; i < slots.size(); ++i)
                    if (expected[rank] & (1U << i)) data = seed ^ (uint64_t(i + 1) * 0x102030405060708ULL);
                if ((rank ? d.get_io$$data1() : d.get_io$$data0()) != data)
                    throw std::runtime_error("dual completion payload owner mismatch");
            }
            dual += count == 2; sidePairs += count == 2 && !(got[0] & 48U) && !(got[1] & 48U);
            for (unsigned i = 0; i < 6; ++i) {
                wrapped += (mask & (1U << i)) && slots[i] < head;
                for (unsigned j = 0; j < i; ++j)
                    duplicate += (mask & (1U << i)) && (mask & (1U << j)) && slots[i] == slots[j];
            }
            ++cases;
        }
    }
    if (!dual || !duplicate || !wrapped || !sidePairs) throw std::runtime_error("owner coverage absent");
    std::cout << "DUAL_COMPLETION_SELECTOR_PASS cases=" << cases << " dual=" << dual
              << " duplicate=" << duplicate << " wrapped=" << wrapped << " side_pairs=" << sidePairs << '\n';
    return 0;
} catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; } }
