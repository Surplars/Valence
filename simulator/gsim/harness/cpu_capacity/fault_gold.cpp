// Software-only freeze of the fixed program/architectural gold, before any DUT run.
#include "fault_instruction_service.h"
#include "fault_guest.h"
int main() {
    SmokeProgram p("mprv-tor-revoke-load");
    require(p.expected.size()==87,"fixed fault retirement count");
    std::cout << "fault_pc=" << p.faultPc << " before_fault=" << p.beforeFault
              << " cause=" << p.cause << " tval=" << p.badVa << '\n';
    for (auto word:p.image.code) std::cout << "word," << word << '\n';
    for (const auto &e:p.expected)
        std::cout << "retire," << e.pc << ',' << e.instruction << ',' << e.writes
                  << ',' << e.rd << ',' << e.value << '\n';
}
