#include "ResidentLateExclusionGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

int main(int argc, char** argv) { try {
    SResidentLateExclusionGsim dut;
    dut.set_reset(0);
    const std::string_view mode = argc == 2 ? argv[1] : "";
    const bool inject = mode == "--inject-mismatch";
    uint64_t checks = 0, liveChecks = 0, staleChecks = 0, issuedChecks = 0;
    uint64_t firstResident = 0, otherResident = 0, emptyFresh = 0;
    auto check = [&](unsigned mask, unsigned head, unsigned resident, bool present, bool pending,
                     unsigned savedIndex, uint64_t savedTag, uint64_t rowTag, bool issued) {
        const bool live = present && pending && savedIndex == resident && savedTag == rowTag;
        dut.set_io$$eligible(mask); dut.set_io$$head(head); dut.set_io$$resident(resident);
        dut.set_io$$residentPresent(present); dut.set_io$$pending(pending);
        dut.set_io$$savedIndex(savedIndex); dut.set_io$$savedTag(savedTag); dut.set_io$$rowTag(rowTag);
        dut.set_io$$issued(issued);
        dut.step();
        int fresh = -1, selected = -1, first = -1;
        // Independent ordered walk, with no prefix summaries, age arithmetic,
        // old/new first-rank selection or DUT physical-register implementation.
        for (unsigned age = 0; age < 16; ++age) {
            const unsigned slot = (head + age) % 16;
            if (!((mask >> slot) & 1)) continue;
            if (first < 0) first = slot;
            if (fresh < 0 && !(live && slot == resident)) fresh = slot;
            if (selected < 0 && !(live && issued && slot == resident)) selected = slot;
        }
        const bool reuse = selected >= 0 && live && !issued && unsigned(selected) == resident;
        const uint32_t expected = (selected < 0 ? 0U : uint32_t(selected) << 23) |
            (uint32_t(selected >= 0) << 22) | (uint32_t(reuse) << 21) |
            (fresh < 0 ? 0U : (uint32_t(fresh) << 17) | (1U << 16) | (1U << fresh));
        uint32_t actual = dut.get_io$$candidate();
        if (inject && checks == 0) actual ^= 1;
        if (actual != expected || dut.get_io$$binaryHead() != expected || dut.get_io$$previous() != expected)
            throw std::runtime_error("resident late exclusion independent oracle mismatch");
        ++checks; liveChecks += live; staleChecks += present && !live; issuedChecks += issued;
        firstResident += live && first >= 0 && unsigned(first) == resident;
        otherResident += live && first >= 0 && unsigned(first) != resident;
        emptyFresh += fresh < 0;
    };
    if (mode == "--invalid-issued") {
        check(1, 0, 0, false, false, 0, 0, 0, true);
        throw std::runtime_error("invalid issued owner was not rejected by DUT");
    }
    // Every 16-bit pool at every head; cycle live, invalid and consumed cases.
    // Resident position varies independently of the head in the directed pass.
    for (unsigned head = 0; head < 16; ++head)
        for (unsigned mask = 0; mask < 65536; ++mask) {
            const unsigned resident = ((mask >> 5) + head) % 16;
            const bool live = (mask & 3) != 0;
            check(mask, head, resident, live, true, resident, 0x8000000000000001ULL,
                0x8000000000000001ULL, live && (mask & 3) == 3);
        }
    for (unsigned head = 0; head < 16; ++head)
        for (unsigned resident = 0; resident < 16; ++resident)
            for (unsigned other = 0; other < 16; ++other)
                for (unsigned mask : {0U, 1U << resident, 1U << other,
                        (1U << resident) | (1U << other), 65535U, 0xaaaaU, 0x5555U})
                    for (unsigned state = 0; state < 3; ++state)
                        check(mask, head, resident, state != 0, true, resident,
                            0xffffffffffffffffULL, 0xffffffffffffffffULL, state == 2);
    // Full tag bits and stale index independently suppress resident ownership.
    for (unsigned bit = 0; bit < 64; ++bit)
        for (unsigned resident = 0; resident < 16; ++resident) {
            check(65535, 15, resident, true, true, resident, 0, uint64_t(1) << bit, false);
            check(65535, 1, resident, true, true, (resident + 1) % 16, 7, 7, false);
            check(65535, 7, resident, true, false, resident, 7, 7, false);
        }
    std::mt19937_64 random(0x7265736964656e74ULL);
    for (unsigned n = 0; n < 20000; ++n) {
        const unsigned resident = random() % 16;
        const uint64_t tag = random();
        const bool live = n % 3 != 0;
        check(random() & 65535, random() % 16, resident, true, true, resident,
            tag, live ? tag : tag ^ (uint64_t(1) << (n % 64)), live && n % 2 == 0);
    }
    if (!liveChecks || !staleChecks || !issuedChecks || !firstResident || !otherResident || !emptyFresh)
        throw std::runtime_error("resident late exclusion coverage missing");
    std::cout << "PASS_RESIDENT_LATE_EXCLUSION checks=" << checks << " live=" << liveChecks
              << " stale=" << staleChecks << " issued=" << issuedChecks << " firstResident=" << firstResident
              << " otherResident=" << otherResident << " emptyFresh=" << emptyFresh << '\n';
    return 0;
} catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; } }
