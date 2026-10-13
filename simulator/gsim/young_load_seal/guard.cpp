#include "PostedYoungerLoadSealGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

// Expected outcomes are authored from the ordering contract, not read from a
// DUT expression. Raw RV64 words go through the actual IntegerDecode modules.
int main() {
    try {
        SPostedYoungerLoadSealGsim d;
        unsigned cases = 0;
        auto baseline = [&] {
            d.set_reset(0);
#define YES(x) d.set_io$$##x(1)
            YES(enabled); YES(postedBusy); YES(headValid); YES(choiceValid); YES(younger);
            YES(live); YES(pending); YES(indexMatches); YES(physical); YES(ordinaryRam);
            YES(pmpAllowed); YES(aligned);
#undef YES
            d.set_io$$selectedInstruction(0x0000b503U); // LD x10,0(x1)
            d.set_io$$headInstruction(0x0020b023U);     // SD x2,0(x1)
            d.set_io$$selectedFetchFault(0); d.set_io$$selectedFetchPageFault(0);
            d.set_io$$headFetchFault(0); d.set_io$$headFetchPageFault(0);
            d.set_io$$hardCauses(0); d.set_io$$postedEligible(0); d.set_io$$preparedPhysicalStore(0);
        };
        auto expect = [&](const char *name, bool deferred, bool seal) {
            d.step(); ++cases;
            if (bool(d.get_io$$deferred()) != deferred || bool(d.get_io$$seal()) != seal)
                throw std::runtime_error(std::string(name) + " ordering outcome mismatch");
        };
        baseline(); expect("young physical load behind head store", true, false);
        baseline(); d.set_io$$headInstruction(0x00000013U); expect("young load behind ordinary ALU", true, false);
        baseline(); d.set_io$$headInstruction(0x00001463U); expect("young load behind branch", true, false);
        baseline(); d.set_io$$enabled(0); expect("default OFF keeps original intent", false, true);
        baseline(); d.set_io$$younger(0); expect("selected actual head load", false, true);
        baseline(); d.set_io$$headInstruction(0x0000b583U);
        expect("unselected head load with selected younger load", false, true);
        for (uint32_t instruction : {0x0000a52fU, 0x1000b52fU, 0x1820b52fU}) {
            baseline(); d.set_io$$headInstruction(instruction); expect("head AMO LR SC", false, true);
        }
        baseline(); d.set_io$$headFetchFault(1); expect("faulting head store", false, true);
        baseline(); d.set_io$$headFetchPageFault(1); expect("fetch-page-fault head store", false, true);
#define REJECT(x) baseline(); d.set_io$$##x(0); expect(#x, false, true)
        REJECT(postedBusy); REJECT(headValid); REJECT(live); REJECT(pending); REJECT(indexMatches);
        REJECT(physical); REJECT(ordinaryRam); REJECT(pmpAllowed); REJECT(aligned);
#undef REJECT
        baseline(); d.set_io$$choiceValid(0); expect("stale full-token choice rejected upstream", false, false);
        baseline(); d.set_io$$selectedFetchFault(1); expect("selected fetch fault", false, true);
        baseline(); d.set_io$$selectedFetchPageFault(1); expect("selected fetch page fault", false, true);
        for (uint32_t instruction : {0x0020b023U, 0x00000013U, 0x02208533U,
                                    0x00001463U, 0x0ff0000fU, 0x0000100fU, 0x1000b52fU, 0xffffffffU}) {
            baseline(); d.set_io$$selectedInstruction(instruction); expect("selected nonordinary load class", false, true);
        }
        for (unsigned bit = 0; bit < 8; ++bit) {
            baseline(); d.set_io$$hardCauses(1U << bit); expect("hard cause dominates eligible exception", true, true);
        }
        baseline(); d.set_io$$headInstruction(0x0ff0000fU); expect("head FENCE retains system seal", true, true);
        baseline(); d.set_io$$headInstruction(0x0000100fU); expect("head FENCE.I retains system seal", true, true);
        baseline(); d.set_io$$selectedInstruction(0x0020b023U); d.set_io$$preparedPhysicalStore(1);
        expect("existing safe prepared-store exception", false, false);
        baseline(); d.set_io$$selectedInstruction(0x0020b023U); d.set_io$$postedEligible(1);
        expect("actual head posted proof path unchanged", false, false);
        std::cout << "YOUNG_LOAD_GUARD_PASS cases=" << cases
                  << " selected_head_load=1 unselected_head_load=1 hard_dominance=1 cpu_executed=0\n";
    } catch (const std::exception &error) {
        std::cerr << "YOUNG_LOAD_GUARD_FAIL " << error.what() << '\n';
        return 1;
    }
}
