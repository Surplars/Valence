#include "PreparedStorePoolGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

int main(int argc, char** argv) { try {
    SPreparedStorePoolGsim dut;
    dut.set_reset(0);
    const std::string_view mode = argc == 2 ? argv[1] : "";
    const bool inject = mode == "--inject-mismatch";
    uint64_t checks = 0, liveChecks = 0, staleChecks = 0, issuedChecks = 0;
    uint64_t firstResident = 0, otherResident = 0, emptyFresh = 0;
    auto check = [&](unsigned original, unsigned prepared, bool bare, bool postedWindow, unsigned head, unsigned resident, bool present, bool pending,
                     unsigned savedIndex, uint64_t savedTag, uint64_t rowTag, bool issued) {
        const bool live = present && pending && savedIndex == resident && savedTag == rowTag;
        dut.set_io$$in$$original(original); dut.set_io$$in$$prepared(prepared);
        dut.set_io$$in$$bare(bare); dut.set_io$$in$$postedWindow(postedWindow); dut.set_io$$in$$head(head); dut.set_io$$in$$resident(resident);
        dut.set_io$$in$$present(present); dut.set_io$$in$$pending(pending);
        dut.set_io$$in$$savedIndex(savedIndex); dut.set_io$$in$$savedTag(savedTag); dut.set_io$$in$$rowTag(rowTag);
        dut.set_io$$in$$issued(issued);
        dut.step();
        const unsigned mask = original ? original : (bare ? prepared : 0);
        auto oracle = [&](bool posted) {
            const unsigned pool = posted && postedWindow && bare && original ? original | prepared : mask;
            int fresh = -1, selected = -1;
            // Independent circular walk, not the DUT ranks, masks or helper.
            for (unsigned age = 0; age < 16; ++age) {
                const unsigned slot = (head + age) % 16;
                if (!((pool >> slot) & 1)) continue;
                if (fresh < 0 && !(live && slot == resident)) fresh = slot;
                if (selected < 0 && !(live && issued && slot == resident)) selected = slot;
            }
            const bool reuse = selected >= 0 && live && !issued && unsigned(selected) == resident;
            return (selected < 0 ? 0U : uint32_t(selected) << 23) |
                (uint32_t(selected >= 0) << 22) | (uint32_t(reuse) << 21) |
                (fresh < 0 ? 0U : (uint32_t(fresh) << 17) | (1U << 16) | (1U << fresh));
        };
        const auto expected = oracle(false), posted = oracle(true);
        uint32_t actual = dut.get_io$$candidate();
        if (inject && checks == 0) actual ^= 1;
        if (actual != expected || dut.get_io$$original() != expected ||
            dut.get_io$$binaryCandidate() != expected || dut.get_io$$postedOriginal() != posted ||
            dut.get_io$$postedCandidate() != posted || !dut.get_io$$equivalent())
            throw std::runtime_error("prepared pool independent oracle mismatch");
        int first = -1;
        for (unsigned age=0; age<16; ++age) {
            const unsigned slot=(head+age)%16;
            if ((mask>>slot)&1) { first=slot; break; }
        }
        ++checks; liveChecks += live; staleChecks += present && !live; issuedChecks += issued;
        firstResident += live && first >= 0 && unsigned(first) == resident;
        otherResident += live && first >= 0 && unsigned(first) != resident;
        emptyFresh += (expected & (1U << 16)) == 0;
    };
    if (mode == "--invalid-issued") {
        check(1, 2, true, false, 0, 0, false, false, 0, 0, 0, true);
        throw std::runtime_error("invalid issued owner was not rejected by DUT");
    }
    // Every 16-bit pool at every head; cycle live, invalid and consumed cases.
    // Resident position varies independently of the head in the directed pass.
    for (unsigned head = 0; head < 16; ++head)
        for (unsigned mask = 0; mask < 65536; ++mask) {
            const unsigned resident = ((mask >> 5) + head) % 16;
            const bool live = (mask & 3) != 0;
            check((mask & 4) ? mask : 0, mask ^ 0xa55a, (mask & 8) != 0, (mask & 16) != 0, head, resident, live, true, resident, 0x8000000000000001ULL,
                0x8000000000000001ULL, live && (mask & 3) == 3);
        }
    for (unsigned head = 0; head < 16; ++head)
        for (unsigned resident = 0; resident < 16; ++resident)
            for (unsigned other = 0; other < 16; ++other)
                for (unsigned mask : {0U, 1U << resident, 1U << other,
                        (1U << resident) | (1U << other), 65535U, 0xaaaaU, 0x5555U})
                    for (unsigned state = 0; state < 3; ++state)
                        check(mask, 65535 ^ mask, state != 0, true, head, resident, state != 0, true, resident,
                            0xffffffffffffffffULL, 0xffffffffffffffffULL, state == 2);
    // Full tag bits and stale index independently suppress resident ownership.
    for (unsigned bit = 0; bit < 64; ++bit)
        for (unsigned resident = 0; resident < 16; ++resident) {
            check(65535, 0, true, false, 15, resident, true, true, resident, 0, uint64_t(1) << bit, false);
            check(0, 65535, false, true, 1, resident, true, true, (resident + 1) % 16, 7, 7, false);
            check(0, 65535, true, false, 7, resident, true, false, resident, 7, 7, false);
        }
    std::mt19937_64 random(0x7265736964656e74ULL);
    for (unsigned n = 0; n < 20000; ++n) {
        const unsigned resident = random() % 16;
        const uint64_t tag = random();
        const bool live = n % 3 != 0;
        check(n % 4 == 0 ? 0 : random() & 65535, random() & 65535, n % 2, (n / 2) % 2, random() % 16, resident, true, true, resident,
            tag, live ? tag : tag ^ (uint64_t(1) << (n % 64)), live && n % 2 == 0);
    }
    if (!liveChecks || !staleChecks || !issuedChecks || !firstResident || !otherResident || !emptyFresh)
        throw std::runtime_error("prepared pool coverage missing");
    std::cout << "PASS_PREPARED_STORE_POOL checks=" << checks << " live=" << liveChecks
              << " stale=" << staleChecks << " issued=" << issuedChecks << " firstResident=" << firstResident
              << " otherResident=" << otherResident << " emptyFresh=" << emptyFresh << '\n';
    return 0;
} catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; } }
