#include "FpgaFetchGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <dlfcn.h>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>
constexpr uint64_t base = 0x80000000, dataBase = base + 0x10000;
using Memory = std::array<uint8_t, 4096>;
static void check(bool ok, const std::string &message) { if (!ok) throw std::runtime_error(message); }
#include "reference.h"
static uint32_t word(uint64_t pc) { return 0x12345678U ^ uint32_t(pc >> 2); }
static uint64_t beat(uint64_t pc) { return word(pc) | (uint64_t(word(pc + 4)) << 32); }
static uint64_t extend(uint64_t x, unsigned bits) { return (x ^ (UINT64_C(1) << (bits - 1))) - (UINT64_C(1) << (bits - 1)); }
static void idle(SFpgaFetchGsim &d) {
    d.set_io$$write(0); d.set_io$$writeIndex(0); d.set_io$$writeData(0);
    d.set_io$$rom$$request$$valid(0); d.set_io$$rom$$request$$bits(base); d.set_io$$rom$$response$$ready(1);
    d.set_io$$rom$$requestMask(3);
    d.set_io$$pc(base); d.set_io$$enable(0); d.set_io$$invalidate(0);
    d.set_io$$pmpCfg0(0); d.set_io$$pmpAddr0(0); d.set_io$$privilege(3); d.set_io$$pause(0);
    d.set_io$$fetch$$request$$ready(0); d.set_io$$fetch$$response$$valid(0); d.set_io$$fetch$$response$$bits(0);
    d.set_io$$fetch$$responseError(0);
    d.set_io$$bootHold(1); d.set_io$$commitEnable(1);
}
static void reset(SFpgaFetchGsim &d) { idle(d); d.set_reset(1); d.step(); d.step(); d.set_reset(0); }
static void load(SFpgaFetchGsim &d, const std::vector<uint32_t> &words) {
    for (unsigned i = 0; i < 256; ++i) {
        d.set_io$$write(1); d.set_io$$writeIndex(i); d.set_io$$writeData(i < words.size() ? words[i] : 0); d.step();
    }
    d.set_io$$write(0); d.step();
}
static void romTest(SFpgaFetchGsim &d) {
    reset(d);
    std::vector<uint32_t> contents;
    for (unsigned i = 0; i < 256; ++i) contents.push_back(word(base + i * 4));
    load(d, contents);
    std::mt19937_64 rng(8193);
    struct Reply { uint64_t data; unsigned error; unsigned earliest; };
    std::deque<Reply> replies;
    std::optional<std::pair<uint64_t, unsigned>> held;
    unsigned accepted = 0, completed = 0, stalled = 0, odd = 0;
    for (unsigned cycle = 0; cycle < 12000; ++cycle) {
        const bool valid = cycle < 11000 || bool(held);
        const uint64_t pc = held ? held->first :
            (cycle < 258 ? base + cycle * 4 : base - 4 + (rng() % 260) * 4);
        const unsigned mask = held ? held->second : cycle % 4;
        const bool ready = rng() % 4 == 0;
        d.set_io$$rom$$request$$valid(valid); d.set_io$$rom$$request$$bits(pc);
        d.set_io$$rom$$requestMask(mask); d.set_io$$rom$$response$$ready(ready); d.step();
        if (d.get_io$$rom$$response$$valid()) {
            check(!replies.empty() && cycle >= replies.front().earliest, "ROM must respond after a clock edge");
            check(d.get_io$$rom$$response$$bits() == replies.front().data, "ROM bank rotation/range/held data");
            check(d.get_io$$rom$$responseError() == replies.front().error, "ROM per-word range errors");
            if (ready) { replies.pop_front(); ++completed; } else ++stalled;
        }
        if (valid && d.get_io$$rom$$request$$ready()) {
            uint64_t value = 0;
            unsigned error = 0;
            for (unsigned lane = 0; lane < 2; ++lane) {
                uint64_t address = pc + 4 * lane;
                if ((mask & (1U << lane)) && address >= base && address < base + 1024)
                    value |= uint64_t(word(address)) << (32 * lane);
                else error |= 1U << lane;
            }
            replies.push_back({value, error, cycle + 1}); ++accepted; odd += bool(pc & 4); held.reset();
        } else if (valid) held = std::make_pair(pc, mask);
    }
    check(replies.empty() && accepted == completed && odd > 500 && stalled > 1000, "ROM test coverage/drain");
    std::cout << "GSIM InstructionRom: PASS transactions=" << completed << " oddPc=" << odd << " stalledResponses=" << stalled << '\n';
}
static void fetchTest(SFpgaFetchGsim &d) {
    reset(d);
    std::mt19937_64 rng(613);
    struct Reply { uint64_t pc; unsigned due; };
    std::optional<Reply> pending;
    std::optional<uint64_t> held;
    uint64_t pc = base;
    unsigned checked = 0, stale = 0, stalls = 0;
    for (unsigned cycle = 0; cycle < 15000; ++cycle) {
        if (rng() % 5 == 0) pc = base + 4 * (rng() % 256);
        else if (rng() % 3 == 0) pc += 4;
        bool enabled = rng() % 9 != 0, ready = rng() % 4 == 0;
        bool response = pending && cycle >= pending->due;
        d.set_io$$pc(pc); d.set_io$$enable(enabled); d.set_io$$fetch$$request$$ready(ready);
        d.set_io$$fetch$$response$$valid(response); d.set_io$$fetch$$response$$bits(response ? beat(pending->pc) : 0); d.step();
        check(!d.get_io$$instructionFault0() && !d.get_io$$instructionFault1(),
              "unexpected fault in error-free fetch packets");
        check(!held || d.get_io$$fetch$$request$$valid(), "withdrawn fetch request during redirect/disable");
        // Retire the old ownership before accepting a simultaneous next request.
        if (response) {
            check(d.get_io$$fetch$$response$$ready(), "fetch response not drained");
            stale += pending->pc != pc; pending.reset();
        }
        if (d.get_io$$fetch$$request$$valid()) {
            uint64_t target = d.get_io$$fetch$$request$$bits();
            check(!held || *held == target, "fetch request changed under backpressure");
            if (ready) { check(!pending, "multiple outstanding fetches"); pending = Reply{target, cycle + 1 + unsigned(rng() % 9)}; held.reset(); }
            else { held = target; ++stalls; }
        }
        if (d.get_io$$instruction0$$valid()) {
            check(enabled && d.get_io$$instruction0$$bits() == word(pc), "stale instruction lane zero"); ++checked;
        }
        if (d.get_io$$instruction1$$valid())
            check(d.get_io$$instruction0$$valid() && d.get_io$$instruction1$$bits() == word(pc + 4), "partial packet lane alignment");
    }
    check(checked > 100 && stale > 100 && stalls > 100, "fetch redirect/backpressure coverage");
    std::cout << "GSIM SynchronousFetch: PASS checked=" << checked << " staleResponses=" << stale << " stalls=" << stalls << '\n';
}
static void fetchThroughputTest(SFpgaFetchGsim &d) {
    reset(d);
    std::optional<uint64_t> pending;
    uint64_t pc = base;
    unsigned requests = 0, steady = 0, atHold = 0;
    for (unsigned cycle = 0; cycle < 260; ++cycle) {
        d.set_io$$pc(pc); d.set_io$$enable(1);
        d.set_io$$fetch$$request$$ready(1);
        d.set_io$$fetch$$response$$valid(bool(pending));
        d.set_io$$fetch$$response$$bits(pending ? beat(*pending) : 0);
        d.step();
        if (pending) { check(d.get_io$$fetch$$response$$ready(), "throughput response drain"); pending.reset(); }
        if (d.get_io$$fetch$$request$$valid()) { pending = d.get_io$$fetch$$request$$bits(); ++requests; }
        const bool first = d.get_io$$instruction0$$valid(), second = d.get_io$$instruction1$$valid();
        if (first) check(d.get_io$$instruction0$$bits() == word(pc), "throughput lane zero data");
        if (second) check(first && d.get_io$$instruction1$$bits() == word(pc + 4), "throughput lane one data");
        if (cycle == 31) check(requests == 2, "prefetch ran ahead while consumer stopped");
        if (cycle >= 32 && cycle < 160) {
            check(first && second, "sequential one-cycle memory supply bubble");
            pc += 8; ++steady;
        }
        if (cycle == 180) atHold = requests;
        if (cycle == 200) check(requests == atHold, "prefetch did not stop after filling lookahead");
        if (cycle > 200 && first) pc += (cycle % 3 == 0 || !second) ? 4 : 8;
    }
    check(steady == 128, "steady fetch throughput coverage");
    std::cout << "GSIM Fetch throughput: PASS dualSupplyCycles=" << steady << " boundedLookahead=2 partialConsumption=checked\n";
}
static void fetchStitchTest(SFpgaFetchGsim &d) {
    for (unsigned delay : {0U, 3U}) {
        reset(d);
        struct Reply { uint64_t pc; unsigned due; };
        std::optional<Reply> pending;
        unsigned requests = 0, bypass = 0, cached = 0, single = 0;
        for (unsigned cycle = 0; cycle < 16; ++cycle) {
            const uint64_t pc = cycle < 2 ? base : base + 4;
            const bool enabled = cycle != 12;
            const bool response = pending && cycle >= pending->due;
            const bool successor = response && pending->pc == base + 8;
            d.set_io$$pc(pc); d.set_io$$enable(enabled);
            d.set_io$$fetch$$request$$ready(1);
            d.set_io$$fetch$$response$$valid(response);
            d.set_io$$fetch$$response$$bits(response ? beat(pending->pc) : 0);
            d.step();
            if (response) { check(d.get_io$$fetch$$response$$ready(), "stitch response drain"); pending.reset(); }
            if (d.get_io$$fetch$$request$$valid()) {
                check(!pending, "stitch outstanding ownership");
                const uint64_t address = d.get_io$$fetch$$request$$bits();
                pending = Reply{address, cycle + 1 + (address == base + 8 ? delay : 0)};
                ++requests;
            }
            if (!enabled) {
                check(!d.get_io$$instruction0$$valid() && !d.get_io$$instruction1$$valid(), "disabled stitched supply");
            } else if (cycle >= 2) {
                check(d.get_io$$instruction0$$valid() && d.get_io$$instruction0$$bits() == word(pc), "stitch first lane");
                const bool available = cycle >= 2 + delay;
                check(bool(d.get_io$$instruction1$$valid()) == available, "cross-packet lane availability");
                if (available) {
                    check(d.get_io$$instruction1$$bits() == word(pc + 4), "cross-packet lane data");
                    if (successor) ++bypass; else ++cached;
                } else ++single;
            }
        }
        check(requests == 2 && bypass == 1 && cached > 5 && single == delay, "stitch bounded prefetch/coverage");
    }
    std::cout << "GSIM Fetch stitching: PASS cached=checked responseBypass=checked missingSuccessor=checked disabled=checked\n";
}
static void fetchInvalidateTest(SFpgaFetchGsim &d) {
    reset(d);
    d.set_io$$pc(base);d.set_io$$enable(1);d.set_io$$fetch$$request$$ready(1);d.step();
    check(d.get_io$$fetch$$request$$valid() && d.get_io$$fetch$$request$$bits()==base,
          "initial instruction request missing");
    d.set_io$$fetch$$request$$ready(0);d.set_io$$fetch$$response$$valid(1);
    d.set_io$$fetch$$response$$bits(beat(base));d.step();
    check(d.get_io$$instruction0$$valid() && d.get_io$$instruction0$$bits()==word(base) &&
          d.get_io$$fetch$$request$$valid() && d.get_io$$fetch$$request$$bits()==base+8,
          "old packet or locked lookahead missing");
    d.set_io$$pc(base+8);d.set_io$$invalidate(1);d.set_io$$fetch$$response$$valid(0);d.step();
    check(!d.get_io$$instruction0$$valid() && d.get_io$$fetch$$request$$valid() &&
          d.get_io$$fetch$$request$$bits()==base+8,"invalidation did not hide cached instructions");
    d.set_io$$invalidate(0);d.set_io$$fetch$$request$$ready(1);d.step();
    check(d.get_io$$fetch$$request$$valid() && d.get_io$$fetch$$request$$bits()==base+8,
          "locked request was not drained");
    d.set_io$$fetch$$response$$valid(1);d.set_io$$fetch$$response$$bits(beat(base+8));d.step();
    check(!d.get_io$$instruction0$$valid() && d.get_io$$fetch$$request$$valid() &&
          d.get_io$$fetch$$request$$bits()==base+8,"stale response escaped or fresh request missing");
    const uint64_t changed = beat(base+8) ^ 1ULL;
    d.set_io$$fetch$$request$$ready(0);d.set_io$$fetch$$response$$bits(changed);d.step();
    check(d.get_io$$instruction0$$valid() && d.get_io$$instruction0$$bits()==(word(base+8)^1U),
          "refetched instruction did not replace stale packet");
    reset(d);
    d.set_io$$pc(base);d.set_io$$enable(1);d.set_io$$fetch$$request$$ready(1);d.step();
    check(d.get_io$$fetch$$request$$valid() && d.get_io$$fetch$$request$$bits()==base,
          "pending invalidation request missing");
    d.set_io$$invalidate(1);d.set_io$$fetch$$response$$valid(0);d.step();
    check(!d.get_io$$instruction0$$valid(),"pending invalidation exposed cached data");
    d.set_io$$invalidate(0);d.set_io$$fetch$$response$$valid(1);
    d.set_io$$fetch$$response$$bits(beat(base));d.step();
    check(!d.get_io$$instruction0$$valid() && d.get_io$$fetch$$request$$valid() &&
          d.get_io$$fetch$$request$$bits()==base,"pending stale response escaped or refetch missing");
    d.set_io$$fetch$$response$$bits(beat(base)^1ULL);d.step();
    check(d.get_io$$instruction0$$valid() && d.get_io$$instruction0$$bits()==(word(base)^1U),
          "pending invalidation did not use fresh response");
    std::cout << "GSIM Fetch invalidation: PASS lockedRequest=drained pendingResponse=dropped freshPacket=used\n";
}
static uint32_t branch(int off) {
    unsigned i = unsigned(off) & 8191;
    return ((i >> 12) << 31) | (((i >> 5) & 63) << 25) | (2U << 20) | (1U << 15) | (4U << 12) |
        (((i >> 1) & 15) << 8) | (((i >> 11) & 1) << 7) | 0x63;
}
static void coreTest(SFpgaFetchGsim &d, Reference &ref, bool straight = false) {
    reset(d);
    std::vector<uint32_t> code{0x00000093, 0x06400113, 0x00108093, branch(-4), 0x008001ef, 0,
        0x00000217, 0x00c202e7, 0, 0x00728313, 0x0080006f, 0, 0x02a00393, 0};
    if (straight) { code.assign(240, 0x00100013U); code.push_back(0); }
    load(d, code); ref.load(code);
    std::array<uint64_t, 32> regs{};
    uint64_t pc = base;
    unsigned retired = 0, lastRetirementCycle = 0;
    std::mt19937_64 rng(9921);
    d.set_io$$bootHold(0);
    for (unsigned cycle = 0; cycle < 10000; ++cycle) {
        bool enable = straight || rng() % 4 != 0;
        d.set_io$$commitEnable(enable); d.step();
        struct Commit { bool valid, writes; unsigned rd; uint64_t pc, next, data; uint32_t inst; };
        std::array<Commit,2> commits{};
#define COMMIT(N) commits[N] = {bool(d.get_io$$commit##N##$$valid()), bool(d.get_io$$commit##N##$$bits$$writesRd()), d.get_io$$commit##N##$$bits$$rd(), d.get_io$$commit##N##$$bits$$pc(), d.get_io$$commit##N##$$bits$$nextPc(), d.get_io$$commit##N##$$bits$$data(), d.get_io$$commit##N##$$bits$$instruction()};
        COMMIT(0) COMMIT(1)
#undef COMMIT
        for (auto c : commits) if (c.valid) {
            check(enable && pc >= base && (pc - base) / 4 < code.size(), "invalid core retirement");
            uint32_t inst = code[(pc - base) / 4];
            unsigned op = inst & 127, rd = (inst >> 7) & 31, rs = (inst >> 15) & 31;
            uint64_t next = pc + 4, value = 0;
            if (op == 0x13) value = regs[rs] + extend(inst >> 20, 12);
            else if (op == 0x17) value = pc + extend(inst & 0xfffff000U, 32);
            else if (op == 0x63) { rd = 0; if (regs[1] < regs[2]) next = pc - 4; }
            else if (op == 0x6f) { value = pc + 4; next = pc + 8; }
            else if (op == 0x67) { value = pc + 4; next = (regs[rs] + extend(inst >> 20,12)) & ~UINT64_C(1); }
            else throw std::runtime_error("wrong-path illegal instruction retired");
            check(c.pc == pc && c.inst == inst && c.next == next && c.writes == bool(rd) && (!rd || (c.rd == rd && c.data == value)), "synchronous core ISA mismatch");
            if (rd) regs[rd] = value;
            pc = next; ref.compare(regs, pc); ++retired; lastRetirementCycle = cycle + 1;
        }
        if (d.get_io$$exception$$valid()) {
            check(pc == base + (straight ? 960 : 52) && d.get_io$$exception$$bits$$pc() == pc && d.get_io$$exception$$bits$$cause() == 2 && (straight || regs[7] == 42),
                  "synchronous ROM precise end exception");
            check(retired == (straight ? 240 : 208), "synchronous core retirement coverage");
            if (straight) check(lastRetirementCycle <= 125, "synchronous sequential frontend throughput regression");
            std::cout << "GSIM FPGA core + NEMU: PASS commits=" << retired << " cycles=" << cycle + 1 << " retirementCycles=" << lastRetirementCycle << " straight=" << straight << '\n';
            return;
        }
    }
    throw std::runtime_error("synchronous core timeout");
}
static void romAccessFaultTest(SFpgaFetchGsim &d, Reference &ref, bool lowerBoundary) {
    reset(d);
    std::vector<uint32_t> code(256, 0);
    code[0] = lowerBoundary ? 0xffdff06fU : 0x3fc0006fU;
    // The upper boundary packet has one valid then one invalid word; the lower boundary reverses them.
    if (!lowerBoundary) code[255] = 0x00108093U;
    load(d, code); ref.load(code);
    std::array<uint64_t, 32> regs{};
    unsigned retired = 0;
    d.set_io$$bootHold(0);
    for (unsigned cycle = 0; cycle < 2000; ++cycle) {
        d.step();
        for (unsigned lane = 0; lane < 2; ++lane) {
            const bool valid = lane ? d.get_io$$commit1$$valid() : d.get_io$$commit0$$valid();
            if (!valid) continue;
            const uint64_t commitPc = lane ? d.get_io$$commit1$$bits$$pc() : d.get_io$$commit0$$bits$$pc();
            const uint64_t nextPc = lane ? d.get_io$$commit1$$bits$$nextPc() : d.get_io$$commit0$$bits$$nextPc();
            const uint32_t instruction = lane ? d.get_io$$commit1$$bits$$instruction() : d.get_io$$commit0$$bits$$instruction();
            const uint64_t result = lane ? d.get_io$$commit1$$bits$$data() : d.get_io$$commit0$$bits$$data();
            const uint64_t expectedPc = retired == 0 ? base : base + 1020;
            const uint64_t expectedNext = retired == 0 ? (lowerBoundary ? base - 4 : base + 1020) : base + 1024;
            check(retired < (lowerBoundary ? 1U : 2U) && commitPc == expectedPc && nextPc == expectedNext &&
                  instruction == code[(expectedPc - base) / 4] && (retired == 0 || result == 1),
                  "instruction access fault retired an unexpected instruction");
            if (retired == 1) regs[1] = result;
            ref.compare(regs, expectedNext);
            ++retired;
        }
        if (d.get_io$$exception$$valid()) {
            const uint64_t faultPc = lowerBoundary ? base - 4 : base + 1024;
            check(retired == (lowerBoundary ? 1U : 2U) && d.get_io$$exception$$bits$$pc() == faultPc &&
                  d.get_io$$exception$$bits$$cause() == 1 &&
                  d.get_io$$exception$$bits$$tval() == faultPc,
                  "ROM boundary must raise a precise instruction access fault");
            std::cout << "GSIM FPGA ROM access fault + NEMU prefix: PASS commits=" << retired
                      << " boundary=" << (lowerBoundary ? "low" : "high") << '\n';
            return;
        }
    }
    throw std::runtime_error("ROM access fault timeout");
}
static void pmpRequestMaskTest(SFpgaFetchGsim &d) {
    constexpr uint64_t boundary = base + 0xfc;
    for (unsigned expected : {0U, 1U}) {
        reset(d);
        d.set_io$$pmpCfg0(0x14); // NA4, execute only.
        d.set_io$$pmpAddr0(boundary >> 2);
        d.set_io$$privilege(1);
        d.set_io$$pc(expected ? boundary : boundary + 4);
        d.set_io$$enable(1);
        d.set_io$$fetch$$request$$ready(1);
        d.step();
        check(d.get_io$$fetch$$request$$valid() &&
              d.get_io$$fetch$$requestMask() == expected,
              "fetch PMP mask included a denied instruction word");
    }
    reset(d);
    d.set_io$$enable(1);
    d.set_io$$pause(1);
    d.step();
    check(!d.get_io$$fetch$$request$$valid() && d.get_io$$quiescent(),
          "PMP CSR barrier did not quiesce instruction fetch");
    std::cout << "GSIM PMP fetch request mask: PASS crossing=1 denied=0 quiescent=1\n";
}
int main(int argc, char **argv) {
    try { check(argc == 2, "NEMU library required"); SFpgaFetchGsim dut; romTest(dut); fetchTest(dut); fetchThroughputTest(dut); fetchStitchTest(dut); fetchInvalidateTest(dut); pmpRequestMaskTest(dut); Reference ref(argv[1]); coreTest(dut, ref); coreTest(dut, ref, true); romAccessFaultTest(dut, ref, false); romAccessFaultTest(dut, ref, true); }
    catch (const std::exception &e) { std::cerr << "GSIM FPGA fetch: FAIL " << e.what() << '\n'; return 1; }
}
