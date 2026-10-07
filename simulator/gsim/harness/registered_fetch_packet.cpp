#include "RegisteredFetchPacketGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

#ifndef FETCH_WIDTH
#define FETCH_WIDTH 2
#endif
#ifndef COMPRESSED
#define COMPRESSED 1
#endif
#ifndef HINT_ENTRIES
#define HINT_ENTRIES 8
#endif
static void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
struct Instruction {
    bool valid = false, access = false, page = false;
    uint32_t bits = 0;
    uint64_t tval = 0, pc = 0, next = 0;
};
struct Successor {
    bool valid = false;
    uint64_t pc = 0, next = 0;
    uint32_t bits = 0;
};
using Packet = std::array<Instruction, FETCH_WIDTH>;
using Training = std::array<Successor, FETCH_WIDTH>;
static unsigned length(const Instruction& instruction) {
    return COMPRESSED && (instruction.bits & 3) != 3 ? 2 : 4;
}
static unsigned hintIndex(uint64_t pc) {
    return ((pc / 2) % HINT_ENTRIES) ^ ((pc / (2 * HINT_ENTRIES)) % HINT_ENTRIES);
}
static int64_t signedImmediate(uint32_t value, unsigned width) {
    return int64_t(value) - ((value & (1U << (width - 1))) ? (int64_t(1) << width) : 0);
}
// ISA bit-position tables, independently assembled into a signed displacement.
// This oracle uses ordinary signed offsets + modulo-64 PC addition, not the
// DUT's split low/high carry implementation.
static constexpr std::array<unsigned, 21> jalSources =
    {0, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 20, 12, 13, 14, 15, 16, 17, 18, 19, 31};
static constexpr std::array<unsigned, 12> cjSources =
    {0, 3, 4, 5, 11, 2, 7, 6, 9, 10, 8, 12};
template<size_t Width> static int64_t displacement(uint32_t bits, const std::array<unsigned, Width>& sources) {
    uint32_t immediate = 0;
    for (unsigned position = 1; position < Width; ++position)
        immediate |= ((bits >> sources[position]) & 1U) << position;
    return signedImmediate(immediate, Width);
}
template<size_t Width> static uint32_t encodeJump(int32_t delta, uint32_t opcode,
    const std::array<unsigned, Width>& sources) {
    const uint32_t immediate = uint32_t(delta) & ((1U << Width) - 1);
    for (unsigned position = 1; position < Width; ++position)
        opcode |= ((immediate >> position) & 1U) << sources[position];
    return opcode;
}
static bool directOffset(const Instruction& instruction, int64_t& offset) {
    if (length(instruction) == 4 && (instruction.bits & 127) == 0x6f) {
        offset = displacement(instruction.bits, jalSources); return true;
    }
    if (COMPRESSED && length(instruction) == 2 && (instruction.bits & 0xe003) == 0xa001) {
        offset = displacement(instruction.bits, cjSources); return true;
    }
    return false;
}
static void drive(SRegisteredFetchPacketGsim& d, unsigned lane, const Instruction& instruction) {
#define LANE(i) case i: \
    d.set_io$$supply$$lane##i##$$valid(instruction.valid); \
    d.set_io$$supply$$lane##i##$$bits$$instruction(instruction.bits); \
    d.set_io$$supply$$lane##i##$$bits$$accessFault(instruction.access); \
    d.set_io$$supply$$lane##i##$$bits$$pageFault(instruction.page); \
    d.set_io$$supply$$lane##i##$$bits$$faultAddress(instruction.tval); break
    switch (lane) {
        LANE(0); LANE(1);
#if FETCH_WIDTH == 4
        LANE(2); LANE(3);
#endif
        default: throw std::runtime_error("invalid fetch supply lane");
    }
#undef LANE
}
static void train(SRegisteredFetchPacketGsim& d, unsigned lane, const Successor& successor) {
#define LANE(i) case i: \
    d.set_io$$train$$lane##i##$$valid(successor.valid); \
    d.set_io$$train$$lane##i##$$bits$$pc(successor.pc); \
    d.set_io$$train$$lane##i##$$bits$$instruction(successor.bits); \
    d.set_io$$train$$lane##i##$$bits$$nextPc(successor.next); break
    switch (lane) {
        LANE(0); LANE(1);
#if FETCH_WIDTH == 4
        LANE(2); LANE(3);
#endif
        default: throw std::runtime_error("invalid fetch training lane");
    }
#undef LANE
}
static Instruction read(SRegisteredFetchPacketGsim& d, unsigned lane) {
#define LANE(i) case i: return {bool(d.get_io$$instructions$$lane##i##$$valid()), \
    bool(d.get_io$$instructions$$lane##i##$$bits$$accessFault()), \
    bool(d.get_io$$instructions$$lane##i##$$bits$$pageFault()), \
    uint32_t(d.get_io$$instructions$$lane##i##$$bits$$instruction()), \
    d.get_io$$instructions$$lane##i##$$bits$$faultAddress(), \
    d.get_io$$instructions$$lane##i##$$bits$$pc(), \
    d.get_io$$instructions$$lane##i##$$bits$$nextPc()}
    switch (lane) {
        LANE(0); LANE(1);
#if FETCH_WIDTH == 4
        LANE(2); LANE(3);
#endif
        default: throw std::runtime_error("invalid fetch output lane");
    }
#undef LANE
}

struct Oracle {
    SRegisteredFetchPacketGsim d;
    std::deque<Instruction> queue;
    std::array<Successor, HINT_ENTRIES> hints{};
    uint64_t pc = 0x80000000ULL;
    bool inject = false;
    unsigned cycles = 0, resetCancelled = 0, matches = 0, mismatches = 0, jumps = 0, learned = 0;
    unsigned priorFaultSuppressed = 0;
    void reset() {
        d.set_io$$pause(0); d.set_io$$consumed(0); d.set_io$$invalidate(0);
        d.set_io$$flush$$valid(0); d.set_io$$flush$$bits(0);
        d.set_io$$expectedNext$$valid(0); d.set_io$$expectedNext$$bits(0);
        for (unsigned lane = 0; lane < FETCH_WIDTH; ++lane) { drive(d, lane, {}); train(d, lane, {}); }
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        resetCancelled += queue.size(); queue.clear(); hints = {}; pc = 0x80000000ULL;
    }
    unsigned step(Packet offered = {}, unsigned consumed = 0, bool pause = false,
        bool flush = false, uint64_t target = 0, bool expectedValid = false, uint64_t expected = 0,
        Training training = {}, bool invalidate = false) {
        check(consumed <= std::min<unsigned>(FETCH_WIDTH, queue.size()), "invalid oracle consume");
        for (unsigned lane = 0; lane < FETCH_WIDTH; ++lane) { drive(d, lane, offered[lane]); train(d, lane, training[lane]); }
        d.set_io$$pause(pause); d.set_io$$consumed(consumed);
        d.set_io$$flush$$valid(flush); d.set_io$$flush$$bits(target);
        d.set_io$$expectedNext$$valid(expectedValid); d.set_io$$expectedNext$$bits(expected);
        d.set_io$$invalidate(invalidate); d.step();
        check(d.get_io$$pc() == pc, "raw supply PC differs from independent event model");
        check(d.get_io$$occupancy() == queue.size(), "fetch reservoir occupancy mismatch");
        for (unsigned lane = 0; lane < FETCH_WIDTH; ++lane) {
            auto actual = read(d, lane);
            check(actual.valid == (lane < queue.size()), "fetch output prefix validity mismatch");
            if (actual.valid) {
                if (inject && cycles == 500 && lane == 0) actual.tval ^= 2;
                const auto& wanted = queue[lane];
                check(actual.bits == wanted.bits && actual.access == wanted.access && actual.page == wanted.page &&
                    actual.tval == wanted.tval && actual.pc == wanted.pc && actual.next == wanted.next,
                    "fetch packet oracle mismatch");
            }
        }
        unsigned captured = 0;
        uint64_t next = pc;
        bool priorFault = false;
        if (!pause) for (unsigned lane = 0; lane < FETCH_WIDTH; ++lane) {
            if (!offered[lane].valid || queue.size() + lane >= 2 * FETCH_WIDTH) break;
            auto& instruction = offered[lane];
            instruction.pc = next;
            const uint64_t sequential = next + length(instruction);
            int64_t delta = 0;
            const bool direct = directOffset(instruction, delta);
            const auto& hint = hints[hintIndex(next)];
            const bool hit = hint.valid && hint.pc == next && hint.bits == instruction.bits;
            const uint64_t prediction = direct ? next + uint64_t(delta) : hint.next;
            const bool candidate = direct || hit;
            const bool aligned = (prediction & (COMPRESSED ? 1 : 3)) == 0;
            const bool taken = !priorFault && !instruction.access && !instruction.page && candidate &&
                aligned && prediction != sequential;
            priorFaultSuppressed += priorFault && candidate;
            instruction.next = taken ? prediction : sequential;
            next = instruction.next; ++captured;
            jumps += taken && direct; learned += taken && !direct;
            priorFault |= instruction.access || instruction.page;
            if (taken) break;
        }
        const uint64_t first = queue.size() > consumed ? queue[consumed].pc : pc;
        const bool wrongPath = expectedValid && expected != first;
        matches += expectedValid && !wrongPath; mismatches += wrongPath;
        if (flush || wrongPath) captured = 0;
        check(d.get_io$$captured() == ((1U << captured) - 1), "capture prefix/registered credits mismatch");
        if (flush) next = target;
        else if (wrongPath) next = expected;
        check(d.get_io$$nextPc() == next, "next supply PC prediction/path validation mismatch");
        if (flush || wrongPath) queue.clear();
        else {
            for (unsigned lane = 0; lane < consumed; ++lane) queue.pop_front();
            for (unsigned lane = 0; lane < captured; ++lane) queue.push_back(offered[lane]);
        }
        for (const auto& successor : training) if (successor.valid) hints[hintIndex(successor.pc)] = successor;
        if (invalidate) hints = {};
        pc = next; ++cycles;
        return captured;
    }
};

int main(int argc, char** argv) { try {
    Oracle o;
    o.inject = argc > 1 && std::string_view(argv[1]) == "--inject-mismatch";
    std::mt19937_64 random(0x516ca315ULL);
    unsigned streaming = 0, full = 0, partialJoin = 0, flushTraffic = 0;
    unsigned faults = 0, secondFault = 0, paused = 0, wrapped = 0;
    o.reset();
    for (unsigned cycle = 0; cycle < 30000; ++cycle) {
        if (cycle == 10000 || cycle == 20000) o.reset();
        const bool stream = cycle < 1024;
        const unsigned available = std::min<unsigned>(FETCH_WIDTH, o.queue.size());
        const unsigned consumed = stream ? available : random() % (available + 1);
        const bool pause = !stream && random() % 7 == 0;
        const bool flush = !stream && (cycle == 1100 || cycle == 1110 || random() % 29 == 0);
        const uint64_t mask = COMPRESSED ? 1 : 3;
        const uint64_t target = cycle == 1100 ? UINT64_MAX - mask :
            cycle == 1110 ? (0xffe & ~mask) : (random() & ~mask);
        Packet offered{};
        uint64_t address = o.pc;
        for (unsigned lane = 0; lane < FETCH_WIDTH; ++lane) {
            auto& instruction = offered[lane];
            instruction.valid = stream || random() % 5 != 0;
            instruction.bits = stream ? 0x00108093U : uint32_t(random());
            if (!COMPRESSED || random() % 2 || stream) instruction.bits |= 3;
            else instruction.bits = (instruction.bits & ~3U) | (random() % 3);
            instruction.access = !stream && random() % 11 == 0;
            instruction.page = !stream && random() % 13 == 0;
            instruction.tval = address + ((length(instruction) == 4 && random() % 2) ? 2 : 0);
            if (cycle % 137 == 0 && lane == 1) {
                instruction.valid = true; instruction.page = true;
                instruction.bits |= 3; instruction.tval = 0x1000;
            }
            address += length(instruction);
        }
        bool expectedValid = !stream && consumed != 0 && random() % 3 == 0;
        const uint64_t expected = expectedValid ? (random() % 4 == 0 ? target : o.queue[consumed - 1].next) : 0;
        Training training{};
        if (consumed != 0 && !stream && random() % 4 == 0) {
            const auto& last = o.queue[consumed - 1];
            training[0] = {true, last.pc, expectedValid ? expected : last.next, last.bits};
        }
        for (unsigned lane = 0; lane < available; ++lane) {
            faults += o.queue[lane].access || o.queue[lane].page;
            secondFault += lane == 1 && o.queue[lane].page;
        }
        full += o.queue.size() == 2 * FETCH_WIDTH;
        paused += pause && !o.queue.empty();
        const auto oldPc = o.pc;
        const auto oldCount = o.queue.size();
        const auto captured = o.step(offered, consumed, pause, flush, target, expectedValid, expected, training, flush);
        streaming += stream && consumed == FETCH_WIDTH && captured == FETCH_WIDTH;
        partialJoin += consumed == 1 && oldCount > 1 && captured == FETCH_WIDTH;
        flushTraffic += flush && consumed != 0 && offered[0].valid;
        wrapped += !flush && o.pc < oldPc;
    }
    check(streaming == 1023, "registered frontend introduces a steady-state packet bubble");
    check(full > 200 && partialJoin > 200 && flushTraffic > 100 && paused > 100,
        "insufficient occupancy/partial-prefix/flush/backpressure coverage");
    check(faults > 1000 && secondFault > 500 && o.resetCancelled > 0,
        "insufficient precise fault or reset cancellation coverage");
    check(wrapped > 0 && o.mismatches > 100 && o.matches > 100, "insufficient PC/path correction coverage");

    // First-time direct JALs: one admission every cycle after the initial fill,
    // with no accepted-successor cache population at all.
    o.reset();
    unsigned jalAdmissions = 0;
    for (unsigned cycle = 0; cycle < 512; ++cycle) {
        Packet packet{};
        packet[0] = {true, false, false, encodeJump(8, 0x6f, jalSources), o.pc};
        packet[1] = {true, false, false, 0x13, o.pc + 4};
        const unsigned consumed = o.queue.empty() ? 0 : 1;
        jalAdmissions += consumed;
        const uint64_t expected = consumed ? o.queue[0].next : 0;
        check(o.step(packet, consumed, false, false, 0, consumed != 0, expected) == 1,
            "first-time direct JAL raw capture throughput lost");
    }
    check(jalAdmissions == 511, "first-time direct JAL stream has avoidable fetch bubbles");
    o.reset();
    Packet jumpThenTarget{};
    jumpThenTarget[0] = {true, false, false, encodeJump(64, 0x6f, jalSources)};
    o.step(jumpThenTarget);
    Packet targetPacket{};
    targetPacket[0] = {true, false, false, 0x13};
    targetPacket[1] = {true, false, false, 0x13};
    o.step(targetPacket);
    check(o.queue.size() == 3 && o.queue[0].pc == 0x80000000ULL &&
        o.queue[1].pc == 0x80000040ULL, "nonsequential packet join lost real target PC metadata");
    o.step({}, 1, false, false, 0, true, 0x80000040ULL);
    check(o.queue.size() == 2 && o.queue[0].pc == 0x80000040ULL,
        "correct prefetched target was discarded after accepting its jump");

    // Learned conditional loop: two instructions per cycle, with the branch
    // at lane one and its target already in the next raw packet.
    o.reset();
    Training hint{};
    hint[0] = {true, 0x80000004ULL, 0x80000000ULL, 0xfe009ee3U};
    o.step({}, 0, false, false, 0, false, 0, hint);
    unsigned loopAdmissions = 0;
    for (unsigned cycle = 0; cycle < 512; ++cycle) {
        Packet packet{};
        packet[0] = {true, false, false, 0x00108093, o.pc};
        packet[1] = {true, false, false, 0xfe009ee3, o.pc + 4};
        const unsigned consumed = o.queue.empty() ? 0 : 2;
        loopAdmissions += consumed;
        check(o.step(packet, consumed, false, false, 0, consumed != 0, 0x80000000ULL) == 2,
            "learned conditional loop loses two-wide supply throughput");
    }
    check(loopAdmissions == 1022, "learned taken loop has avoidable fetch bubbles");
    // A change to not-taken must remove the prefetched loop target. Instruction
    // changes and full-PC hash collisions cannot reuse an old successor hint.
    o.step({}, 2, false, false, 0, true, 0x80000008ULL);
    check(o.queue.empty() && o.pc == 0x80000008ULL, "changed decode prediction did not cancel stale raw path");
    o.step({}, 0, false, true, 0x80000000ULL);
    Packet changed{};
    changed[0] = {true, false, false, 0x00108093};
    changed[1] = {true, false, false, 0x00000013};
    o.step(changed);
    check(o.pc == 0x80000008ULL, "changed instruction reused stale successor hint");
    o.step({}, 0, false, true, 0x80000020ULL);
    Packet aliased{};
    aliased[0] = {true, false, false, 0xfe009ee3};
    o.step(aliased);
    check(o.pc == 0x80000024ULL, "full PC tag allowed a false hash-collision prediction");
    // Invalidation wins over simultaneous training of the matching entry.
    o.step({}, 0, false, true, 0x80000000ULL, false, 0, hint, true);
    Packet invalidated{};
    invalidated[0] = {true, false, false, 0x00108093};
    invalidated[1] = {true, false, false, 0xfe009ee3};
    o.step(invalidated);
    check(o.pc == 0x80000008ULL, "context invalidation left a valid successor hint");

    // Exercise both signs, high-field carries and modulo-64 wrap independently
    // of the DUT's narrow-adder implementation. An early fetch fault suppresses
    // direct steering while preserving the original tval at either lane.
    unsigned boundaryJumps = 0;
    const std::array<uint64_t, 8> addresses = {0, 2, 0x1ffffc, 0x200000,
        0x200004, 0x7ffffffffffffffcULL, UINT64_MAX - 3, UINT64_MAX - 1};
    const std::array<int32_t, 8> offsets = {0, 2, 4, 8, -2, -4, 1048574, -1048576};
    for (uint64_t base : addresses) for (int32_t delta : offsets) {
        base &= ~(COMPRESSED ? 1ULL : 3ULL);
        o.step({}, 0, false, true, base);
        Packet packet{};
        packet[0] = {true, false, false, encodeJump(delta, 0x6f, jalSources), base};
        o.step(packet);
        const uint64_t target = base + uint64_t(int64_t(delta));
        const bool aligned = (target & (COMPRESSED ? 1 : 3)) == 0;
        check(o.pc == (aligned ? target : base + 4), "JAL signed/boundary target oracle mismatch");
        ++boundaryJumps;
    }
    if (COMPRESSED) {
        for (uint64_t base : addresses) for (int32_t delta : {0, 2, 6, -2, -6, 2046, -2048}) {
            o.step({}, 0, false, true, base & ~1ULL);
            Packet packet{};
            packet[0] = {true, false, false, encodeJump(delta, 0xa001, cjSources), o.pc};
            const uint64_t target = o.pc + uint64_t(int64_t(delta));
            o.step(packet);
            check(o.pc == target, "C.J signed/boundary target oracle mismatch");
            ++boundaryJumps;
        }
        // RV64 quadrant-1 funct3=001 is ADDIW, never C.JAL.
        o.step({}, 0, false, true, 0x80000000ULL);
        Packet addiw{}; addiw[0] = {true, false, false, 0x2081};
        o.step(addiw); check(o.pc == 0x80000002ULL, "RV64 C.ADDIW was misclassified as a jump");
        o.reset();
        unsigned cjAdmissions = 0;
        for (unsigned cycle = 0; cycle < 512; ++cycle) {
            Packet packet{};
            packet[0] = {true, false, false, encodeJump(6, 0xa001, cjSources)};
            const unsigned consumed = o.queue.empty() ? 0 : 1;
            cjAdmissions += consumed;
            const uint64_t expected = consumed ? o.queue[0].next : 0;
            check(o.step(packet, consumed, false, false, 0, consumed != 0, expected) == 1,
                "first-time C.J raw capture throughput lost");
        }
        check(cjAdmissions == 511, "first-time C.J stream has avoidable fetch bubbles");
    }
    for (unsigned faultLane = 0; faultLane < 2; ++faultLane) {
        o.step({}, 0, false, true, 0xffcULL);
        Packet packet{};
        packet[0] = {true, false, false, 0x13, 0xffc};
        packet[1] = {true, false, false, encodeJump(-4, 0x6f, jalSources), 0x1002};
        packet[faultLane].page = true;
        o.step(packet);
        check(o.pc == 0x1004ULL, "faulting packet launched a speculative direct jump");
    }
    check(o.priorFaultSuppressed > 0, "prior-fault suppression coverage missing");
    o.step({}, 0, false, true, 0x80000000ULL);
    Packet pausedJump{};
    pausedJump[0] = {true, false, false, encodeJump(64, 0x6f, jalSources)};
    check(o.step(pausedJump, 0, true) == 0 && o.pc == 0x80000000ULL,
        "paused frontend launched an early direct jump");
    // Hint qualification must use the exact trained instruction length and
    // full64 modulo successor. Test sequential/misaligned hints, both signs,
    // high addresses and wrap without changing the full-target event oracle.
    unsigned hintQualificationCases = 0, hintTaken = 0, hintRejected = 0;
    const std::array<uint64_t, 9> hintAddresses = {0, 1, 2, 0x80000000ULL, 0x80000002ULL,
        0x7ffffffffffffffcULL, UINT64_MAX - 3, UINT64_MAX - 1, UINT64_MAX};
    for (auto base : hintAddresses) for (uint32_t bits : {0x13U, 0x0085U}) {
        if (!COMPRESSED && bits == 0x0085U) continue;
        const unsigned bytes = (bits & 3) == 3 ? 4 : 2;
        const uint64_t sequential = base + bytes;
        const std::array<uint64_t, 7> targets = {sequential, base + 8, base - 8,
            base + 1, base + 2, 0, UINT64_MAX};
        for (auto target : targets) {
            o.step({}, 0, false, true, base, false, 0, {}, true);
            Training qualificationHint{};
            qualificationHint[0] = {true, base, target, bits};
            o.step({}, 0, false, false, 0, false, 0, qualificationHint);
            Packet packet{};
            packet[0] = {true, false, false, bits};
            packet[1] = {true, false, false, 0x13};
            const bool taken = (target & (COMPRESSED ? 1 : 3)) == 0 && target != sequential;
            const auto captured = o.step(packet);
            check(captured == (taken ? 1U : 2U), "hint qualification changed raw packet termination");
            check(o.pc == (taken ? target : sequential + 4),
                "hint qualification differs from full64 trained successor");
            ++hintQualificationCases; hintTaken += taken; hintRejected += !taken;
        }
    }
    check(hintTaken && hintRejected, "hint alignment/sequential qualification coverage missing");
    // Flush may expose an arbitrary cursor even when an architectural fetch
    // would later fault. Low-bit qualification must not assume legal PC input.
    for (auto base : std::array<uint64_t, 3>{1, 3, UINT64_MAX}) {
        o.step({}, 0, false, true, base, false, 0, {}, true);
        Packet packet{};
        packet[0] = {true, false, false, encodeJump(8, 0x6f, jalSources)};
        packet[1] = {true, false, false, 0x13};
        check(o.step(packet) == 2 && o.pc == base + 8,
            "misaligned raw JAL cursor bypassed target alignment qualification");
        ++boundaryJumps;
        if (COMPRESSED) {
            o.step({}, 0, false, true, base);
            packet[0].bits = encodeJump(6, 0xa001, cjSources);
            check(o.step(packet) == 2 && o.pc == base + 6,
                "misaligned raw C.J cursor bypassed target alignment qualification");
            ++boundaryJumps;
        }
    }
    std::cout << "GSIM registered fetch packet: PASS width=" << FETCH_WIDTH
        << " compressed=" << COMPRESSED << " cycles=" << o.cycles << " streaming=" << streaming
        << " full=" << full << " partialJoin=" << partialJoin << " flushTraffic=" << flushTraffic
        << " faultLanes=" << faults << " secondFault=" << secondFault << " paused=" << paused
        << " wrapped=" << wrapped << " resetCancelled=" << o.resetCancelled
        << " firstJalAdmissions=" << jalAdmissions << " loopAdmissions=" << loopAdmissions
        << " pathMatches=" << o.matches << " pathMisses=" << o.mismatches
        << " earlyJumps=" << o.jumps << " learnedJumps=" << o.learned
        << " boundaryJumps=" << boundaryJumps << " hintQualificationCases=" << hintQualificationCases
        << " hintTaken=" << hintTaken << " hintRejected=" << hintRejected << '\n';
    return 0;
} catch (const std::exception& error) {
    std::cerr << "GSIM registered fetch packet: " << error.what() << '\n'; return 1;
} }
