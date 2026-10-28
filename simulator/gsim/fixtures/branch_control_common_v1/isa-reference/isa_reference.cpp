#include "branch_isa.h"
int main(int argc, char** argv) {
    try {
        matched::require(argc == 3, "usage: isa-reference ELF SYMBOLS");
        matched::Image image(argv[1], argv[2]);
        branch_isa::Oracle oracle(image);
        oracle.run(image);
        std::cout << "{\"events\":[";
        bool comma = false;
        for (const auto& event : oracle.events) {
            if (comma) std::cout << ',';
            comma = true;
            std::cout << "{\"pc\":" << event.pc << ",\"instruction\":" << event.instruction
                << ",\"nextPc\":" << event.nextPc << ",\"rd\":" << event.rd
                << ",\"writes\":" << (event.writes ? "true" : "false") << ",\"data\":" << event.data << '}';
        }
        std::cout << "],\"regs\":[";
        for (unsigned i = 0; i < 32; ++i) { if (i) std::cout << ','; std::cout << oracle.regs[i]; }
        std::cout << "],\"retired\":" << oracle.retired << ",\"roi_begin_index\":" << oracle.beginCount
            << ",\"roi_end_index\":" << oracle.endCount << ",\"terminal\":{\"pc\":" << oracle.pc
            << ",\"cause\":3,\"tval\":" << oracle.pc << "},\"event_hash\":" << oracle.hash << "}\n";
    } catch (const std::exception& e) { std::cerr << "BRANCH_ISA_REFERENCE_FAIL " << e.what() << '\n'; return 1; }
}
