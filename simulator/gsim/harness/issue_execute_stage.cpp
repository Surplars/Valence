#include "IssueExecuteStageGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string_view>

static void check(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
struct Stimulus { bool valid, ready, cancel; uint64_t payload; };
struct Observed { bool ready, valid, occupied; uint64_t payload; };
static void drive(SIssueExecuteStageGsim& d, unsigned lane, const Stimulus& s) {
#define LANE(i) case i: \
    d.set_io$$in##i##$$valid(s.valid); d.set_io$$in##i##$$bits(s.payload); \
    d.set_io$$out##i##$$ready(s.ready); d.set_io$$cancel##i(s.cancel); break
    switch (lane) { LANE(0); LANE(1); }
#undef LANE
}
static Observed read(SIssueExecuteStageGsim& d, unsigned lane) {
#define LANE(i) case i: return {bool(d.get_io$$in##i##$$ready()), \
    bool(d.get_io$$out##i##$$valid()), bool(d.get_io$$occupied##i()), d.get_io$$out##i##$$bits()}
    switch (lane) { LANE(0); LANE(1); }
#undef LANE
    throw std::runtime_error("invalid lane");
}
int main(int argc, char** argv) { try {
    const bool inject = argc > 1 && std::string_view(argv[1]) == "--inject-mismatch";
    SIssueExecuteStageGsim d;
    std::array<std::optional<uint64_t>, 2> queue{};
    std::mt19937_64 rng(0xa721e650);
    unsigned accepted = 0, completed = 0, cancelled = 0, replacements = 0, held = 0, dual = 0;
    unsigned cancelBlockedCredits = 0, cancelReadyReplacements = 0, directedRefills = 0;
    auto reset = [&] {
        for (unsigned lane = 0; lane < 2; ++lane) drive(d, lane, {false, false, false, 0});
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        queue = {};
    };
    reset();
    for (unsigned cycle = 0; cycle < 20000; ++cycle) {
        if (cycle == 10000) reset();
        std::array<Stimulus, 2> inputs{};
        for (unsigned lane = 0; lane < 2; ++lane) {
            auto& s = inputs[lane];
            s = {rng() % 5 != 0, rng() % 3 != 0, rng() % 17 == 0, rng()};
            // Continuous two-lane traffic must not become a half-rate queue.
            if (cycle < 256) { s.valid = true; s.ready = true; s.cancel = false; }
            // A stalled slot 0 cannot impede independent slot 1.
            if (cycle >= 256 && cycle < 320) {
                s.valid = true; s.ready = lane == 1; s.cancel = false;
            }
            // Both full owners are killed, but cancellation cannot lend input
            // credit while downstream is blocked. Refill the empty slots only
            // on the following cycle, then independently exercise ready+cancel.
            if (cycle == 320) { s.valid = true; s.ready = false; s.cancel = true; }
            if (cycle == 321) { s.valid = true; s.ready = false; s.cancel = false; }
            if (cycle == 322) { s.valid = true; s.ready = true; s.cancel = true; }
            if (cycle == 323) { s.valid = true; s.ready = true; s.cancel = false; }
            drive(d, lane, s);
        }
        d.step();
        unsigned fired = 0;
        for (unsigned lane = 0; lane < 2; ++lane) {
            const auto& s = inputs[lane];
            const auto actual = read(d, lane);
            // Credit comes only from independent capacity or consumer readiness;
            // cancellation affects the resident owner, never same-cycle capacity.
            const bool expectedReady = !queue[lane].has_value() || s.ready;
            const bool expectedValid = queue[lane].has_value() && !s.cancel;
            check(actual.ready == expectedReady, "execution input credit mismatch");
            check(actual.valid == expectedValid, "execution latency/cancel mismatch");
            check(actual.occupied == queue[lane].has_value(), "execution occupancy mismatch");
            if (expectedValid) check((actual.payload ^ uint64_t(inject && cycle == 200 && lane == 0)) ==
                *queue[lane], "execution held payload/order mismatch");
            if (cycle > 0 && cycle < 256) check(actual.valid && actual.ready,
                "execution stream must sustain two results per cycle");
            if (cycle >= 256 && cycle < 320 && lane == 1) check(actual.valid && actual.ready,
                "one execution slot stalled the other lane");
            if (cycle == 320) check(actual.occupied && !actual.valid && !actual.ready,
                "cancelled full stalled slot borrowed same-cycle input credit");
            if (cycle == 321) {
                check(!actual.occupied && !actual.valid && actual.ready,
                    "cancel-only slot was not empty and refillable on the next cycle");
                directedRefills++;
            }
            if (cycle == 322) check(actual.occupied && !actual.valid && actual.ready,
                "ready cancellation prevented an authorized replacement");
            if (cycle == 323) check(actual.occupied && actual.valid && actual.ready,
                "ready cancellation lost the independently authorized replacement");
            const bool old = queue[lane].has_value();
            cancelBlockedCredits += old && s.cancel && !s.ready && s.valid;
            cancelReadyReplacements += old && s.cancel && s.ready && s.valid;
            if (s.cancel || (expectedValid && s.ready)) {
                cancelled += s.cancel && old;
                completed += expectedValid && s.ready;
                fired += expectedValid && s.ready;
                queue[lane].reset();
            }
            held += expectedValid && !s.ready;
            if (s.valid && expectedReady) {
                accepted++;
                replacements += old;
                queue[lane] = s.payload;
            }
        }
        dual += fired == 2;
    }
    check(accepted > 20000 && held > 2000 && cancelled > 1000 && dual > 3000,
        "execution oracle coverage too low");
    check(cancelBlockedCredits > 100 && cancelReadyReplacements > 500 && directedRefills == 2,
        "cancel-independent execution credit coverage incomplete");
    std::cout << "ISSUE_EXECUTE_STAGE_PASS cycles=20000 accepted=" << accepted
        << " completed=" << completed << " cancelled=" << cancelled << " replacements=" << replacements
        << " held=" << held << " dual_cycles=" << dual
        << " cancel_blocked_credits=" << cancelBlockedCredits
        << " cancel_ready_replacements=" << cancelReadyReplacements
        << " directed_refills=" << directedRefills << " resets=2\n";
    return 0;
} catch (const std::exception& e) {
    std::cerr << "execution stage oracle mismatch: " << e.what() << '\n';
    return 1;
} }
