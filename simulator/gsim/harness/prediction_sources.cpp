#include "PredictionSourceQualification.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string_view>

int main(int argc, char **argv) { try {
    const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    SPredictionSourceQualification d;
    d.set_reset(0);
    unsigned checks = 0, blockedWinner = 0;
    // Select the first present source procedurally, THEN test its eligibility.
    // A lower aligned/different source never substitutes for an ineligible winner.
    for (unsigned present = 0; present < 16; ++present)
        for (unsigned aligned = 0; aligned < 16; ++aligned)
            for (unsigned different = 0; different < 16; ++different) {
                unsigned selected = 4;
                for (unsigned i = 0; i < 4; ++i)
                    if (selected == 4 && (present & (1U << i))) selected = i;
                const unsigned grant = selected == 4 ? 0 : 1U << selected;
                bool expected = selected != 4 && (aligned & grant) && (different & grant);
                if (inject && checks == 100) expected = !expected;
                d.set_io$$present(present); d.set_io$$aligned(aligned);
                d.set_io$$different(different); d.step();
                if (d.get_io$$grants() != grant || bool(d.get_io$$predicts()) != expected)
                    throw std::runtime_error("prediction source priority oracle mismatch");
                blockedWinner += grant && !expected && (present & aligned & different);
                ++checks;
            }
    if (!blockedWinner) throw std::runtime_error("prediction source blocked-winner coverage missing");
    std::cout << "GSIM prediction sources: PASS vectors=" << checks
              << " blocked_winner=" << blockedWinner << '\n';
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
