#pragma once
#include "benchmark_oracle.h"
// A workload-specific envelope around the existing, unchanged software ISA.
// It intentionally does not call the CoreMark-specific Oracle::run or weaken it.
namespace branch_isa {
class Oracle : public benchmark_oracle::Oracle {
public:
    using benchmark_oracle::Oracle::Oracle;
    std::vector<benchmark_oracle::Event> events;
    benchmark_oracle::Event step() {
        const uint32_t inst = uint32_t(memory.read(pc, 4));
        const auto* e = benchmark_oracle::decode(inst);
        matched::require(e != nullptr, "branch unsupported/illegal instruction");
        const std::string name(e->name);
        matched::require(name == "addi" || name == "xor" || name == "ori" || name == "auipc" ||
            name == "beq" || name == "bne" || name == "blt" || name == "bge" ||
            name == "bltu" || name == "bgeu" || name == "jal" || name == "jalr",
            "branch instruction outside fixed source ISA");
        auto event = benchmark_oracle::Oracle::step();
        if (!event.writes) { event.rd = 0; event.data = 0; }
        events.push_back(event);
        return event;
    }
    void run(const matched::Image& image, uint64_t bound = 10000) {
        const auto start = image.symbols.at("roi_begin");
        const auto end = image.symbols.at("roi_end");
        const auto complete = image.symbols.at("benchmark_complete");
        const auto terminal = image.symbols.at("benchmark_terminal");
        matched::require(start == matched::RamBase && end > start && complete == end + 4 &&
            terminal == complete + 4, "branch marker layout mismatch");
        matched::require(memory.read(end, 4) == 0x13 && memory.read(complete, 4) == 0x13 &&
            memory.read(terminal, 4) == 0x00100073, "branch completion bytes mismatch");
        while (pc != terminal && retired < bound) {
            matched::require(pc == matched::RomBase || pc == matched::RomBase + 4 ||
                (pc >= start && pc < terminal && !(pc & 3)), "branch execution outside boot/body/tail");
            if (pc == start) { matched::require(!beginCount, "duplicate branch ROI begin"); beginCount = retired; }
            if (pc == end) { matched::require(beginCount && !endCount, "unmatched branch ROI end"); endCount = retired; }
            step();
        }
        matched::require(pc == terminal, "branch oracle terminal not reached within bound");
        matched::require(beginCount == 2 && endCount > beginCount && retired == endCount + 2,
            "branch boot/ROI/tail retirement mismatch");
        matched::require(stores.empty(), "branch oracle unexpectedly wrote memory");
    }
};
}
