#include "IndependentClockProbeGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string_view>
#include <utility>
#include <vector>

// Independent oracle: enabled counters advance on 0->1 transitions only.
// Repeated evaluations at a constant level and falling edges do not advance.
int main(int argc, char **argv) { try {
    const bool observe = argc == 2 && std::string_view(argv[1]) == "--observe";
    if (argc > 2 || (argc == 2 && !observe))
        throw std::runtime_error("usage: clock-probe [--observe]");
    struct Result { const char *name; uint16_t expectedA, expectedB, actualA, actualB; };
    std::vector<Result> results;
    auto initialize = [&](SIndependentClockProbeGsim &d) {
        d.set_enableA(0); d.set_enableB(0);
        d.set_clockA(0); d.set_clockB(0);
        d.set_resetA(1); d.set_resetB(1);
        for (unsigned i = 0; i < 3; ++i) d.step();
        d.set_resetA(0); d.set_resetB(0);
        for (unsigned i = 0; i < 3; ++i) d.step();
        if (d.get_countA() || d.get_countB())
            throw std::runtime_error("clock probe initial zero/disabled sanity failed");
    };
    auto evaluate = [&](const char *name, const std::vector<std::pair<bool, bool>> &levels) {
        // Fresh instance per case: reset scheduling must not hide clock evidence.
        // Post-activity async assertion is tested independently below.
        SIndependentClockProbeGsim d;
        initialize(d);
        bool previousA = false, previousB = false;
        uint16_t expectedA = 0, expectedB = 0;
        d.set_enableA(1); d.set_enableB(1);
        for (auto [a, b] : levels) {
            expectedA += a && !previousA;
            expectedB += b && !previousB;
            previousA = a; previousB = b;
            d.set_clockA(a); d.set_clockB(b); d.step();
        }
        // Freeze both counters, then permit combinational outputs to settle.
        // This does not introduce a further enabled rising edge in the oracle.
        d.set_enableA(0); d.set_enableB(0);
        for (unsigned i = 0; i < 3; ++i) d.step();
        uint16_t actualA = d.get_countA(), actualB = d.get_countB();
        for (unsigned i = 0; i < 8; ++i) {
            d.set_clockA(i & 1); d.set_clockB(!(i & 1)); d.step();
        }
        if (d.get_countA() != actualA || d.get_countB() != actualB)
            throw std::runtime_error("clock probe disabled hold sanity failed");
        results.push_back({name, expectedA, expectedB, actualA, actualB});
    };
    evaluate("held-low", std::vector<std::pair<bool, bool>>(16, {false, false}));
    evaluate("held-high", std::vector<std::pair<bool, bool>>(16, {true, true}));
    std::vector<std::pair<bool, bool>> levels;
    for (unsigned i = 0; i < 64; ++i) levels.emplace_back(i & 1, false);
    evaluate("a-only", levels);
    levels.clear();
    for (unsigned i = 0; i < 64; ++i) levels.emplace_back(false, i & 1);
    evaluate("b-only", levels);
    levels.clear();
    for (unsigned i = 0; i < 64; ++i) levels.emplace_back(i & 1, i & 1);
    evaluate("simultaneous", levels);
    levels.clear();
    for (unsigned i = 0; i < 300; ++i)
        levels.emplace_back((i % 6) >= 3, ((i + 1) % 10) >= 5);
    evaluate("ratio-5-to-3-phase-offset", levels);
    levels.clear();
    for (unsigned i = 0; i < 315; ++i)
        levels.emplace_back(((i + 2) % 14) >= 7, ((i + 3) % 10) >= 5);
    evaluate("ratio-5-to-7-phase-offset", levels);

    SIndependentClockProbeGsim resetProbe;
    initialize(resetProbe);
    resetProbe.set_enableA(1); resetProbe.set_enableB(1);
    for (unsigned i = 0; i < 32; ++i) {
        resetProbe.set_clockA(i & 1); resetProbe.set_clockB(i & 1); resetProbe.step();
    }
    resetProbe.set_enableA(0); resetProbe.set_enableB(0);
    for (unsigned i = 0; i < 3; ++i) resetProbe.step();
    const uint16_t beforeResetA = resetProbe.get_countA(), beforeResetB = resetProbe.get_countB();
    if (!beforeResetA || !beforeResetB)
        throw std::runtime_error("clock probe enabled progress sanity failed");
    // Async assertion must reset state even without any further clock edge.
    resetProbe.set_resetA(1); resetProbe.set_resetB(1);
    for (unsigned i = 0; i < 3; ++i) resetProbe.step();
    const uint16_t afterResetA = resetProbe.get_countA(), afterResetB = resetProbe.get_countB();
    const bool asyncResetVerified = afterResetA == 0 && afterResetB == 0;

    unsigned mismatches = 0;
    std::cout << "{\"status\":\"tool-capability-observation\",\"cases\":[";
    for (unsigned i = 0; i < results.size(); ++i) {
        const auto &r = results[i];
        bool match = r.expectedA == r.actualA && r.expectedB == r.actualB;
        mismatches += !match;
        if (i) std::cout << ',';
        std::cout << "{\"name\":\"" << r.name << "\",\"expected_a\":" << r.expectedA
                  << ",\"expected_b\":" << r.expectedB << ",\"actual_a\":" << r.actualA
                  << ",\"actual_b\":" << r.actualB << ",\"match\":" << (match ? "true" : "false") << '}';
    }
    std::cout << "],\"mismatching_cases\":" << mismatches
              << ",\"independent_edges_verified\":" << (mismatches ? "false" : "true")
              << ",\"initial_zero_and_disabled_sanity_passed\":true,\"enabled_progress_sanity_passed\":true"
              << ",\"async_reset\":{\"before_a\":" << beforeResetA << ",\"before_b\":" << beforeResetB
              << ",\"after_a\":" << afterResetA << ",\"after_b\":" << afterResetB
              << ",\"expected_after_a\":0,\"expected_after_b\":0,\"verified\":"
              << (asyncResetVerified ? "true" : "false") << "}}\n";
    // Observation mode reports capability, not a hardware/CDC acceptance pass.
    if ((mismatches || !asyncResetVerified) && !observe) {
        std::cerr << "independent clock edge/reset contract mismatch\n";
        return 1;
    }
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 2; } }
