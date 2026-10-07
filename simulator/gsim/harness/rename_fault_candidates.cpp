#include "RenameFaultCandidatesGsim.h"

#include <array>
#include <cstdint>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>

#ifndef PHYSICAL_REGS
#define PHYSICAL_REGS 40
#endif
static_assert(PHYSICAL_REGS == 40 || PHYSICAL_REGS == 48);
constexpr unsigned ROB = 16, PATTERNS = 12, PRESSURES = 3, WAKE_MODES = 2;

struct Request {
    bool valid = false, writes = false;
    unsigned rs1 = 0, rs2 = 0, rd = 0;
    uint64_t pc = 0;
    uint32_t instruction = 0;
};
struct Event { bool valid = false; unsigned index = 0; };
struct Input {
    std::array<Request, 2> raw{};
    std::array<Event, 3> wakes{};
    unsigned faultMask = 0, inspect = 0;
    bool dispatch = true;
};
struct Allocation {
    bool valid = false, writes = false, alias = false;
    unsigned index = 0, source1 = 0, source2 = 0, destination = 0, oldDestination = 0;
    uint64_t tag = 0;
};
struct Counts {
    unsigned cases = 0, cycles = 0, accepted = 0, aliases = 0, blocked = 0;
    unsigned noFreeFaultAccepted = 0, noFreeFullBlocked = 0, wakeReserveCollision = 0;
    unsigned readyChecks = 0, rawForward = 0, faultSuppressedRaw = 0, aliasWithoutFree = 0;
    std::array<unsigned, 4> masks{};
    std::array<unsigned, PRESSURES> pressure{};
    std::array<unsigned, PATTERNS> patterns{};
    std::array<unsigned, WAKE_MODES> wakeModes{};
};

// Only the port adapters depend on GSIM accessor spelling.
static void drive(SRenameFaultCandidatesGsim& d, const Input& in, uint64_t physical) {
#define RAW(n) \
    d.set_io$$raw##n##$$valid(in.raw[n].valid); \
    d.set_io$$raw##n##$$bits$$writesRd(in.raw[n].writes); \
    d.set_io$$raw##n##$$bits$$rs1(in.raw[n].rs1); \
    d.set_io$$raw##n##$$bits$$rs2(in.raw[n].rs2); \
    d.set_io$$raw##n##$$bits$$rd(in.raw[n].rd); \
    d.set_io$$raw##n##$$bits$$pc(in.raw[n].pc); \
    d.set_io$$raw##n##$$bits$$instruction(in.raw[n].instruction);
    RAW(0) RAW(1)
#undef RAW
#define WAKE(n) \
    d.set_io$$wake##n##$$valid(in.wakes[n].valid); \
    d.set_io$$wake##n##$$bits(in.wakes[n].index);
    WAKE(0) WAKE(1) WAKE(2)
#undef WAKE
    d.set_io$$faultMask(in.faultMask);
    d.set_io$$dispatchReady(in.dispatch);
    d.set_io$$physical(physical);
    d.set_io$$inspectRegister(in.inspect);
}
static std::array<Allocation, 2> sample(SRenameFaultCandidatesGsim& d) {
    std::array<Allocation, 2> out{};
#define SAMPLE(n) \
    out[n].valid = d.get_io$$renamed##n##$$valid(); \
    out[n].writes = d.get_io$$renamed##n##$$bits$$writesRd(); \
    out[n].alias = d.get_io$$renamed##n##$$bits$$moveAlias(); \
    out[n].index = d.get_io$$renamed##n##$$bits$$token$$index(); \
    out[n].tag = d.get_io$$renamed##n##$$bits$$token$$tag(); \
    out[n].source1 = d.get_io$$renamed##n##$$bits$$source1(); \
    out[n].source2 = d.get_io$$renamed##n##$$bits$$source2(); \
    out[n].destination = d.get_io$$renamed##n##$$bits$$destination(); \
    out[n].oldDestination = d.get_io$$renamed##n##$$bits$$oldDestination();
    SAMPLE(0) SAMPLE(1)
#undef SAMPLE
    return out;
}

static void check(bool ok, std::string_view reason) {
    if (!ok) throw std::runtime_error(std::string(reason));
}
static Request addi(unsigned rd, unsigned rs, unsigned immediate = 1) {
    return {true, true, rs, 0, rd, 0, uint32_t((immediate << 20) | (rs << 15) | (rd << 7) | 0x13)};
}
static Request compressedMove(unsigned rd, unsigned rs) {
    return {true, true, 0, rs, rd, 0, uint32_t(0x8002 | (rd << 7) | (rs << 2))};
}
static Request addMove(unsigned rd, unsigned rs1, unsigned rs2) {
    return {true, true, rs1, rs2, rd, 0, uint32_t((rs2 << 20) | (rs1 << 15) | (rd << 7) | 0x33)};
}
// Architectural instruction classes are decoded procedurally, without importing
// the DUT helper, its mask candidates, equality tree, or selected-source outputs.
static int moveSource(const Request& r) {
    if (!r.writes || !r.rd) return -1;
    const uint32_t insn = r.instruction;
    if ((insn >> 16) == 0 && (insn & 0xf003) == 0x8002 &&
        ((insn >> 7) & 31) == r.rd && ((insn >> 2) & 31) == r.rs2 &&
        r.rs1 == 0 && r.rs2 != 0) return int(r.rs2);
    if ((insn & 0x707f) == 0x13 && (insn >> 20) == 0 &&
        ((insn >> 15) & 31) == r.rs1 && ((insn >> 7) & 31) == r.rd && r.rs1)
        return int(r.rs1);
    if ((insn & 0xfe00707f) == 0x33 && ((insn >> 7) & 31) == r.rd &&
        ((insn >> 15) & 31) == r.rs1 && ((insn >> 20) & 31) == r.rs2) {
        if (r.rs1 == 0 && r.rs2 != 0) return int(r.rs2);
        if (r.rs2 == 0 && r.rs1 != 0) return int(r.rs1);
    }
    return -1;
}
static Request effective(Request request, unsigned mask, unsigned lane) {
    if (mask & (1U << lane)) {
        request.writes = false;
        request.rs1 = request.rs2 = request.rd = 0;
    }
    return request;
}

class Model {
    SRenameFaultCandidatesGsim dut;
    std::array<unsigned, 32> rat{};
    std::set<unsigned> free;
    std::array<unsigned, ROB> source1{}, source2{};
    unsigned occupancy = 0, active = 0, ready1 = 0, ready2 = 0;
    uint64_t tag = 0, physical = 0;
    Counts& counts;
public:
    explicit Model(Counts& counters): counts(counters) {}
    void reset() {
        for (unsigned r = 0; r < 32; ++r) rat[r] = r;
        free.clear();
        for (unsigned r = 32; r < PHYSICAL_REGS; ++r) free.insert(r);
        occupancy = active = ready1 = ready2 = 0; tag = 0;
        source1.fill(0); source2.fill(0);
        // Deliberately late architectural operands exercise ready initialization;
        // this fixture supplies a ready file, not a CPU reset/boot contract.
        physical = 0xffffffffULL & ~(uint64_t(1) << 5) & ~(uint64_t(1) << 6);
        drive(dut, Input{}, physical);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    }
    unsigned freeCount() const { return unsigned(free.size()); }
    unsigned size() const { return occupancy; }
    unsigned mapping(unsigned reg) const { return rat.at(reg); }

    // Sequential software RAT updates and a set of unused physical identities.
    // Every expectation is computed before reading any output of the DUT.
    std::array<Allocation, 2> expected(const Input& in) const {
        std::array<Allocation, 2> result{};
        auto map = rat;
        auto available = free;
        bool prefix = in.dispatch;
        uint64_t nextTag = tag;
        for (unsigned lane = 0; lane < 2; ++lane) {
            const Request r = effective(in.raw[lane], in.faultMask, lane);
            const bool writes = r.writes && r.rd != 0;
            const int alias = moveSource(r);
            Allocation& a = result[lane];
            a.valid = prefix && r.valid && occupancy + lane < ROB &&
                (!writes || alias >= 0 || !available.empty());
            prefix = a.valid;
            if (!a.valid) continue;
            a.index = occupancy + lane; a.tag = nextTag++;
            a.source1 = map.at(r.rs1); a.source2 = map.at(r.rs2);
            a.writes = writes; a.alias = alias >= 0;
            if (writes) {
                a.destination = alias >= 0 ? map.at(unsigned(alias)) : *available.begin();
                if (alias < 0) available.erase(a.destination);
                a.oldDestination = map.at(r.rd);
                map.at(r.rd) = a.destination;
            }
        }
        return result;
    }
    void tick(const Input& in, bool inject = false, bool countedCase = false) {
        auto want = expected(in);
        const auto correct = want;
        if (inject) {
            check(want[0].valid && want[1].valid && want[1].source1 == want[0].destination,
                "negative fixture did not reach a real same-packet RAW");
            want[1].source1 ^= 1; // Corrupt a real software expectation, never DUT state.
        }
        drive(dut, in, physical); dut.step();
        const auto actual = sample(dut);
        check(dut.get_io$$occupancy() == occupancy, "pre-edge occupancy");
        check(dut.get_io$$freeCount() == free.size(), "pre-edge free register conservation");
        check(dut.get_io$$speculativeMapping() == rat.at(in.inspect), "pre-edge RAT mapping");
        check(dut.get_io$$ownerReady1() == ready1 && dut.get_io$$ownerReady2() == ready2,
            "owner-ready state differs from independent physical event scoreboard");
        counts.readyChecks += 2 * ROB;
        for (unsigned lane = 0; lane < 2; ++lane) {
            const auto& a = actual[lane]; const auto& e = want[lane];
            check(a.valid == e.valid, "contiguous prefix or exact fault-aware capacity");
            if (!e.valid) continue;
            check(a.index == e.index && a.tag == e.tag, "full allocation owner");
            check(a.source1 == e.source1 && a.source2 == e.source2, "fault-aware RAW source mapping");
            check(a.destination == e.destination && a.oldDestination == e.oldDestination,
                "fresh rank, alias destination or same-packet WAW mapping");
            check(a.writes == e.writes && a.alias == e.alias, "fault/x0/alias write metadata");
        }
        if (countedCase) {
            for (unsigned lane = 0; lane < 2; ++lane) {
                const auto& e = correct[lane];
                counts.accepted += e.valid; counts.aliases += e.valid && e.alias;
                counts.blocked += in.raw[lane].valid && !e.valid;
                counts.noFreeFaultAccepted += free.empty() && e.valid && (in.faultMask & (1U << lane));
                counts.noFreeFullBlocked += free.empty() && occupancy == ROB &&
                    in.raw[lane].valid && !e.valid && (in.faultMask & (1U << lane));
                counts.aliasWithoutFree += free.empty() && e.valid && e.alias;
            }
            counts.rawForward += correct[0].valid && correct[0].writes && correct[1].valid &&
                (correct[1].source1 == correct[0].destination || correct[1].source2 == correct[0].destination);
            counts.faultSuppressedRaw += (in.faultMask & 1) && correct[0].valid && correct[1].valid &&
                in.raw[0].writes && in.raw[0].rd != 0 &&
                (in.raw[1].rs1 == in.raw[0].rd || in.raw[1].rs2 == in.raw[0].rd) &&
                !(in.faultMask & 2);
        }
        // Accepted reserves alone are authoritative. Wake is applied first;
        // a simultaneous reserve for the same identity wins, including a new
        // same-packet consumer. Aliased moves never reserve a fresh destination.
        for (auto wake : in.wakes) if (wake.valid) physical |= uint64_t(1) << wake.index;
        for (unsigned lane = 0; lane < 2; ++lane) {
            const auto& e = correct[lane];
            if (!e.valid) continue;
            const auto r = effective(in.raw[lane], in.faultMask, lane);
            if (e.writes) {
                rat.at(r.rd) = e.destination;
                if (!e.alias) {
                    check(free.erase(e.destination) == 1, "software double fresh allocation");
                    physical &= ~(uint64_t(1) << e.destination);
                    if (countedCase) for (auto wake : in.wakes)
                        counts.wakeReserveCollision += wake.valid && wake.index == e.destination;
                }
            }
            source1[e.index] = e.source1; source2[e.index] = e.source2;
            active |= 1U << e.index; ++occupancy; ++tag;
        }
        for (unsigned slot = 0; slot < ROB; ++slot) if (active & (1U << slot)) {
            if ((physical >> source1[slot]) & 1) ready1 |= 1U << slot;
            else ready1 &= ~(1U << slot);
            if ((physical >> source2[slot]) & 1) ready2 |= 1U << slot;
            else ready2 &= ~(1U << slot);
        }
        check(rat[0] == 0, "x0 RAT ownership"); ++counts.cycles;
    }
};

static Input pattern(unsigned which) {
    Input in;
    in.raw = {addi(5, 1), addi(6, 5)};
    switch (which) {
        case 0: break; // fresh RAW
        case 1: in.raw[1] = addi(5, 5); break; // RAW + WAW
        case 2: in.raw = {compressedMove(5, 6), compressedMove(6, 5)}; break;
        case 3: in.raw = {addi(5, 6, 0), addi(6, 5, 0)}; break;
        case 4: in.raw = {addMove(5, 0, 6), addMove(6, 5, 0)}; break;
        case 5: in.raw = {addMove(5, 6, 0), addMove(6, 0, 5)}; break;
        case 6: in.raw[0] = {true, false, 5, 6, 0, 0, 0x63}; break;
        case 7: in.raw = {addi(0, 6), addi(6, 0)}; break;
        case 8: in.raw[0].valid = false; break;
        case 9: in.raw[1].valid = false; break;
        case 10: in.dispatch = false; break;
        case 11: in.raw = {Request{true, false, 5, 6, 0, 0, 0x63},
                              Request{true, false, 6, 5, 0, 0, 0x63}}; break;
        default: throw std::runtime_error("pattern index");
    }
    return in;
}

int main(int argc, char** argv) { try {
    const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    check(argc == 1 || inject, "unsupported raw-fault fixture argument");
    Counts counts;
    Model model(counts);
    for (unsigned mask = 0; mask < 4; ++mask)
        for (unsigned pressure = 0; pressure < PRESSURES; ++pressure)
            for (unsigned which = 0; which < PATTERNS; ++which)
                for (unsigned wakes = 0; wakes < WAKE_MODES; ++wakes) {
                    model.reset();
                    const unsigned preload = PHYSICAL_REGS - 34 + pressure;
                    for (unsigned n = 0; n < preload; ++n) {
                        Input in; in.raw[0] = addi(10 + n % 16, 1);
                        in.raw[0].pc = 0x10000000 + n * 4;
                        in.inspect = n ? 10 + (n - 1) % 16 : 0;
                        model.tick(in);
                    }
                    check(model.freeCount() == 2 - pressure && model.size() == preload,
                        "pressure fixture did not reach its independent free/ROB boundary");
                    Input in = pattern(which); in.faultMask = mask;
                    in.inspect = 10 + (preload - 1) % 16;
                    for (unsigned lane = 0; lane < 2; ++lane)
                        in.raw[lane].pc = 0x80000000ULL + counts.cases * 0x100 + lane * 4;
                    if (wakes) {
                        const auto allocation = model.expected(in);
                        in.wakes[0] = {true, model.mapping(5)};
                        in.wakes[1] = {true, allocation[0].valid && allocation[0].writes && !allocation[0].alias ?
                            allocation[0].destination : model.mapping(6)};
                        in.wakes[2] = {true, allocation[1].valid && allocation[1].writes && !allocation[1].alias ?
                            allocation[1].destination : model.mapping(5)};
                    }
                    model.tick(in, inject && mask == 0 && pressure == 0 && which == 0 && wakes == 1, true);
                    // Observe the resulting owner readiness on the next edge,
                    // without letting a reset hide a bad allocation initializer.
                    Input idle; idle.inspect = which == 7 ? 0 : 5; model.tick(idle);
                    idle.inspect = 6; model.tick(idle);
                    ++counts.cases; ++counts.masks[mask]; ++counts.pressure[pressure];
                    ++counts.patterns[which]; ++counts.wakeModes[wakes];
                }
    check(counts.cases == 288 && counts.cycles == (PHYSICAL_REGS == 40 ? 2880 : 5184),
        "raw-fault matrix count");
    for (auto n : counts.masks) check(n == 72, "fault-mask matrix coverage");
    for (auto n : counts.pressure) check(n == 96, "pressure matrix coverage");
    for (auto n : counts.patterns) check(n == 24, "instruction pattern matrix coverage");
    for (auto n : counts.wakeModes) check(n == 144, "wake-mode matrix coverage");
    check(counts.wakeReserveCollision > 0 && counts.rawForward > 0 &&
        counts.faultSuppressedRaw > 0 && counts.aliases > 0 && counts.blocked > 0,
        "raw-fault allocation/readiness witnesses incomplete");
    if (PHYSICAL_REGS == 40) check(counts.noFreeFaultAccepted > 0 && counts.aliasWithoutFree > 0,
        "no-free fault or alias must remain admissible with ROB capacity");
    else check(counts.noFreeFaultAccepted == 0 && counts.noFreeFullBlocked > 0,
        "no-free full ROB must still reject fault entries");
    std::cout << "GSIM raw-fault rename: PASS physical=" << PHYSICAL_REGS
        << " cases=" << counts.cases << " cycles=" << counts.cycles
        << " mask0=" << counts.masks[0] << " mask1=" << counts.masks[1]
        << " mask2=" << counts.masks[2] << " mask3=" << counts.masks[3]
        << " pressure0=" << counts.pressure[0] << " pressure1=" << counts.pressure[1]
        << " pressure2=" << counts.pressure[2] << " patterns=" << PATTERNS << " wakeModes=" << WAKE_MODES
        << " accepted=" << counts.accepted << " aliases=" << counts.aliases << " blocked=" << counts.blocked
        << " noFreeFaultAccepted=" << counts.noFreeFaultAccepted << " noFreeFullBlocked=" << counts.noFreeFullBlocked
        << " wakeReserveCollision=" << counts.wakeReserveCollision << " readyChecks=" << counts.readyChecks
        << " rawForward=" << counts.rawForward << " faultSuppressedRaw=" << counts.faultSuppressedRaw
        << " aliasWithoutFree=" << counts.aliasWithoutFree << '\n';
    return 0;
} catch (const std::exception& e) {
    std::cerr << "independent raw-fault rename oracle mismatch: " << e.what() << '\n';
    return 1;
} }
