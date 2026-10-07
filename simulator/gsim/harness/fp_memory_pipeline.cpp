#include "FpMemoryPipelineGsim.h"
#include <cstdint>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string_view>
#include <tuple>

static void check(bool v, const char *m) { if (!v) throw std::runtime_error(m); }
int main(int argc, char **argv) { try {
    const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    SFpMemoryPipelineGsim d;
    auto defaults = [&] {
        d.set_io$$valid(0); d.set_io$$trap(0); d.set_io$$instruction(0x0000b107);
        d.set_io$$base(0x1000); d.set_io$$data(0); d.set_io$$pc(0x80000000); d.set_io$$tag(1);
        d.set_io$$cfg(0); d.set_io$$pmpAddress(0x47f); d.set_io$$privilege(3); d.set_io$$virtualized(0);
        d.set_io$$completeReady(0); d.set_io$$memory$$request$$ready(0);
        d.set_io$$memory$$response$$valid(0); d.set_io$$memory$$response$$bits$$data(0);
        d.set_io$$memory$$response$$bits$$error(0); d.set_io$$memory$$response$$bits$$pageFault(0);
    };
    defaults(); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    std::mt19937_64 rng(0x20261005f00ULL);
    unsigned requests = 0, faults = 0, stalled = 0, immediate = 0, completed = 0;
    for (unsigned i = 0; i < 320; ++i) {
        const bool store = i & 1;
        const unsigned size = i % 3 == 0 ? 3 : 2, length = 1U << size;
        uint64_t address = (0x1000 + ((i * 12) % 1024)) & ~uint64_t(length - 1);
        if (i % 7 == 1) ++address;
        if (i % 17 == 2) address = 0x1000; // NA4/8-byte partial match, including M-mode.
        if (i % 19 == 4) address = (uint64_t{1} << 56) - 8;
        const unsigned mode = i % 4, privilege = i % 3 == 0 ? 3 : 1;
        const bool virt = i % 13 == 5;
        unsigned cfg = mode == 0 ? 0x1b : mode == 1 ? 0x19 : mode == 2 ? 0x13 : 0;
        if (i % 11 == 0) cfg |= 128;
        const uint64_t low = 0x1000, end = mode == 2 ? 0x1004 : 0x1400;
        // Independent half-open byte interval and permissions, not the RTL mask/end formula.
        const bool any = mode != 3 && address < end && address + length > low;
        const bool whole = address >= low && address + length <= end;
        const bool permission = store ? bool(cfg & 2) : bool(cfg & 1);
        const bool denied = !virt && (any ? !whole || (!permission && (privilege != 3 || (cfg & 128)))
                                                      : privilege != 3);
        const bool misaligned = address % length;
        const bool error = i % 23 == 9, page = i % 29 == 8;
        const bool fault = misaligned || denied || error || page;
        const unsigned cause = misaligned ? (store ? 6 : 4) : denied ? (store ? 7 : 5) :
                               page ? (store ? 15 : 13) : (store ? 7 : 5);
        const uint64_t data = rng(), beat = 0xfedcba9876543210ULL ^ (uint64_t(i) << 32);
        const int offset = i % 5 == 0 ? -16 : 8;
        const unsigned imm = unsigned(offset) & 4095;
        const uint32_t inst = store ? ((imm >> 5) << 25) | (2U << 20) | (1U << 15) |
                                      (size << 12) | ((imm & 31) << 7) | 0x27 :
                                      (imm << 20) | (1U << 15) | (size << 12) | (2U << 7) | 7;
        d.set_io$$valid(1); d.set_io$$instruction(inst); d.set_io$$base(address - uint64_t(offset));
        d.set_io$$data(data); d.set_io$$pc(0x80000000 + i * 4); d.set_io$$tag(i + 1);
        bool accepted = false, requested = false, replied = false, done = false;
        unsigned acceptedAt = 0, replyAt = 0, due = 1000, perRequests = 0;
        using Held = std::tuple<uint64_t, bool, unsigned, uint64_t, uint64_t, unsigned>;
        std::optional<Held> held;
        for (unsigned cycle = 0; cycle < 160; ++cycle) {
            // Change context after AGU capture but before execute/LSU acceptance.
            d.set_io$$cfg(cycle == 0 ? 0 : cfg);
            d.set_io$$pmpAddress(mode == 2 ? 0x400 : 0x47f);
            d.set_io$$privilege(privilege); d.set_io$$virtualized(cycle == 0 ? 0 : virt);
            const bool busReady = cycle >= 7 && rng() % 4 != 0;
            const bool sameCycle = i % 5 == 0 && accepted && !requested && !misaligned && !denied && busReady;
            const bool reply = !replied && (sameCycle || (requested && cycle >= due));
            const bool ready = cycle >= 18 && rng() % 3 != 0;
            d.set_io$$memory$$request$$ready(busReady); d.set_io$$memory$$response$$valid(reply);
            d.set_io$$memory$$response$$bits$$data(beat);
            d.set_io$$memory$$response$$bits$$error(error); d.set_io$$memory$$response$$bits$$pageFault(page);
            d.set_io$$completeReady(ready); d.step();
            if (!accepted && d.get_io$$ready()) {
                check(cycle >= 1, "FP memory AGU boundary bypassed");
                accepted = true; acceptedAt = cycle; d.set_io$$valid(0);
            }
            if (d.get_io$$memory$$request$$valid()) {
                check(accepted && cycle > acceptedAt, "FP memory registered request boundary bypassed");
                check(!misaligned && !denied, "FP fault produced a physical side effect");
                const unsigned lane = address % 8;
                check(d.get_io$$memory$$request$$bits$$address() == address &&
                      d.get_io$$memory$$request$$bits$$size() == size &&
                      bool(d.get_io$$memory$$request$$bits$$write()) == store &&
                      bool(d.get_io$$memory$$request$$bits$$virtualized()) == virt &&
                      d.get_io$$memory$$request$$bits$$mask() == (((1U << length) - 1) << lane) &&
                      d.get_io$$memory$$request$$bits$$data() == (data << (lane * 8)),
                      "FP memory request envelope mismatch");
                if (busReady) {
                    check(!requested, "duplicate FP memory request"); requested = true; ++perRequests; ++requests;
                    due = cycle + 1 + i % 5;
                } else ++stalled;
            }
            if (reply && d.get_io$$memory$$response$$ready()) {
                check(requested, "unsolicited FP reply accepted"); replied = true; replyAt = cycle;
                immediate += sameCycle;
            }
            const Held actual{d.get_io$$value(), bool(d.get_io$$exception()), unsigned(d.get_io$$cause()),
                              d.get_io$$tval(), d.get_io$$nextPc(), unsigned(d.get_io$$resultTag())};
            if (held) check(d.get_io$$completeValid() && actual == *held, "stalled FP completion changed");
            held = d.get_io$$completeValid() && !ready ? std::optional<Held>(actual) : std::nullopt;
            if (d.get_io$$completeValid()) {
                uint64_t expected = store ? 0 : beat >> ((address % 8) * 8);
                if (size == 2) expected &= UINT32_MAX;
                if (inject && i == 0) expected ^= 1;
                check(bool(d.get_io$$exception()) == fault &&
                      (!fault || d.get_io$$cause() == cause) &&
                      (fault || d.get_io$$value() == expected) &&
                      d.get_io$$tval() == address && d.get_io$$nextPc() == 0x80000004 + i * 4 &&
                      d.get_io$$resultTag() == i + 1, "FP memory boundary oracle mismatch");
                if (!misaligned && !denied)
                    check(replied && cycle >= replyAt + 3, "FP registered response/completion latency bypassed");
                if (ready) { done = true; ++completed; faults += fault; break; }
            }
        }
        check(done && perRequests == unsigned(!misaligned && !denied), "FP memory ownership/drain timeout");
        d.set_io$$memory$$response$$valid(0); d.step(); check(!d.get_io$$busy(), "FP memory failed to drain");
    }
    defaults(); d.set_io$$valid(1); d.step(); // Cancel an unaccepted AGU envelope.
    d.set_io$$valid(0); d.set_io$$trap(1); d.step(); d.set_io$$trap(0); d.step();
    check(!d.get_io$$busy() && !d.get_io$$memory$$request$$valid() && !d.get_io$$completeValid(),
          "cancelled preparation escaped FP boundary");
    defaults(); d.set_io$$valid(1); d.step(); d.step(); d.set_io$$valid(0); d.step();
    check(d.get_io$$busy(), "pending request reset case not reached");
    d.set_reset(1); d.step(); d.step(); d.set_reset(0); d.step();
    check(!d.get_io$$busy() && !d.get_io$$memory$$request$$valid() && !d.get_io$$completeValid(),
          "FP memory reset retained ownership");
    check(stalled > 10 && immediate > 5 && faults > 20, "FP boundary coverage insufficient");
    std::cout << "FP_MEMORY_PIPELINE_PASS completed=" << completed << " requests=" << requests
              << " faults=" << faults << " stalled=" << stalled << " immediate=" << immediate << '\n';
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
