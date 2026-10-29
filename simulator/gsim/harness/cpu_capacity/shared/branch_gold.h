#pragma once
#include "source-gold.h"
namespace branch_gold {
template <typename Event> void check_event(const Event& actual, uint64_t index) {
    matched::require(index < branch_source_gold::events.size(), "branch sealed event overflow");
    const auto& expected = branch_source_gold::events[index];
    matched::require(actual.pc == expected.pc && actual.instruction == expected.instruction &&
        actual.nextPc == expected.nextPc && actual.rd == expected.rd && actual.writes == expected.writes &&
        actual.data == expected.data, "branch sealed source event mismatch at " + std::to_string(index));
}
template <typename Oracle> void check_reference(const Oracle& actual) {
    matched::require(actual.events.size() == branch_source_gold::events.size(), "branch sealed event count mismatch");
    for (uint64_t i = 0; i < actual.events.size(); ++i) check_event(actual.events[i], i);
    matched::require(actual.regs == branch_source_gold::regs, "branch sealed source GPR mismatch");
    matched::require(actual.retired == branch_source_gold::retired &&
        actual.beginCount == branch_source_gold::roi_begin_index &&
        actual.endCount == branch_source_gold::roi_end_index &&
        actual.pc == branch_source_gold::terminal_pc && actual.stores.empty(),
        "branch sealed retirement/ROI/terminal mismatch");
}
}
