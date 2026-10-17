#ifndef FIVE_STAGE_ORACLE_ONLY
#include "FiveStageCore.h"
#endif
#include <array>
#include <cstdint>
#include <cstring>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef DUT_XLEN
#define DUT_XLEN 64
#endif
#ifndef DUT_HAS_M
#define DUT_HAS_M 1
#endif
#ifndef DUT_MEM_BYPASS
#define DUT_MEM_BYPASS 1
#endif
#ifndef DUT_PIPELINE_STAGES
#define DUT_PIPELINE_STAGES 5
#endif
static constexpr unsigned N = DUT_XLEN, BYTES = N / 8;
#ifndef FIVE_STAGE_BASE
#define FIVE_STAGE_BASE 0x80000000ULL
#endif
static constexpr uint64_t BASE = FIVE_STAGE_BASE, DATA = BASE + 0x2000, VECTOR = BASE + 0x100;
static constexpr uint64_t MASK = N == 64 ? UINT64_MAX : UINT32_MAX;
static uint64_t fit(uint64_t x) { return x & MASK; }
static int64_t signedValue(uint64_t x) { return N == 64 ? int64_t(x) : int32_t(x); }
static uint64_t signExtend(uint64_t x, unsigned bits) {
    if (bits == 64) return fit(x);
    uint64_t sign = uint64_t(1) << (bits - 1);
    return fit((x & ((uint64_t(1) << bits) - 1)) ^ sign) - sign & MASK;
}
static uint32_t ri(unsigned op, unsigned rd, unsigned f, unsigned a, int imm) {
    return (uint32_t(imm) & 4095) << 20 | a << 15 | f << 12 | rd << 7 | op;
}
static uint32_t rr(unsigned op, unsigned rd, unsigned f, unsigned a, unsigned b, unsigned hi = 0) {
    return hi << 25 | b << 20 | a << 15 | f << 12 | rd << 7 | op;
}
static uint32_t st(unsigned f, unsigned a, unsigned b, int imm) {
    return (uint32_t(imm) & 0xfe0) << 20 | b << 20 | a << 15 | f << 12 |
        (uint32_t(imm) & 31) << 7 | 0x23;
}
static uint32_t br(unsigned f, unsigned a, unsigned b, unsigned imm) {
    return (imm >> 12 & 1) << 31 | (imm >> 5 & 63) << 25 | b << 20 | a << 15 |
        f << 12 | (imm >> 1 & 15) << 8 | (imm >> 11 & 1) << 7 | 0x63;
}
static uint32_t jal(unsigned rd, unsigned imm) {
    return (imm >> 20 & 1) << 31 | (imm >> 1 & 1023) << 21 | (imm >> 11 & 1) << 20 |
        (imm >> 12 & 255) << 12 | rd << 7 | 0x6f;
}
static void need(bool x, const std::string &s) { if (!x) throw std::runtime_error(s); }

// Independent sequential ISA oracle. No Scala controls, encodings or legacy decoder are imported.
struct Oracle {
    std::array<uint64_t, 32> r{};
    std::vector<uint8_t> memory;
    uint64_t pc = BASE, scratch = 0, epc = 0, cause = 0, tval = 0, count = 0;
    uint64_t status = 0x1800, mie = 0;
    uint64_t mtvec = VECTOR;
    uint64_t timerValue = 0;
    explicit Oracle(std::vector<uint8_t> m) : memory(std::move(m)) {}
    uint64_t load(uint64_t a, unsigned size) {
        if (a == 0x0200bff8 && size == 8) return timerValue;
        need(a >= BASE && a + size <= BASE + memory.size(), "oracle address out of bounds");
        uint64_t v = 0;
        for (unsigned j = 0; j < size; ++j) v |= uint64_t(memory[a - BASE + j]) << (8 * j);
        return v;
    }
    struct Result { uint64_t next, value = 0, cause = 0, tval = 0; unsigned rd = 0; bool write = false, trap = false; };
    Result evaluate(uint32_t ins, bool fetchError, bool dataError) {
        unsigned op = ins & 127, rd = ins >> 7 & 31, f = ins >> 12 & 7;
        unsigned a = ins >> 15 & 31, b = ins >> 20 & 31, hi = ins >> 25;
        uint64_t x = r[a], y = r[b], imm = signExtend(ins >> 20, 12);
        Result out{fit(pc + 4)};
        auto trap = [&](unsigned c, uint64_t v) { out.trap = true; out.cause = c; out.tval = v; out.write = false; out.next = mtvec & ~3ULL; };
        auto write = [&](uint64_t v) { out.write = rd != 0; out.rd = rd; out.value = fit(v); };
        if (fetchError) { trap(1, pc); return out; }
        if (op == 0x37 || op == 0x17) {
            write(signExtend(ins & 0xfffff000U, 32) + (op == 0x17 ? pc : 0));
        } else if (op == 0x13 || op == 0x33 || (N == 64 && (op == 0x1b || op == 0x3b))) {
            bool w = op == 0x1b || op == 0x3b, im = op == 0x13 || op == 0x1b;
            unsigned width = w ? 32 : N;
            unsigned shift = (im ? ins >> 20 : y) & (width - 1);
            uint64_t v = 0;
            if (!im && hi == 1 && DUT_HAS_M && (!w || f == 0 || f >= 4)) {
                uint64_t ux = w ? uint32_t(x) : fit(x), uy = w ? uint32_t(y) : fit(y);
                int64_t sx = w ? int32_t(x) : signedValue(x), sy = w ? int32_t(y) : signedValue(y);
                if (f == 0) v = uint64_t(__uint128_t(ux) * uy);
                if (f == 1) v = uint64_t((__int128(sx) * sy) >> N);
                if (f == 2) v = uint64_t((__int128(sx) * __int128(uy)) >> N);
                if (f == 3) v = uint64_t((__uint128_t(ux) * uy) >> N);
                int64_t minimum = width == 64 ? INT64_MIN : INT32_MIN;
                if (f == 4) v = uy == 0 ? UINT64_MAX : sx == minimum && sy == -1 ? uint64_t(sx) : uint64_t(sx / sy);
                if (f == 5) v = uy == 0 ? UINT64_MAX : ux / uy;
                if (f == 6) v = uy == 0 ? uint64_t(sx) : sx == minimum && sy == -1 ? 0 : uint64_t(sx % sy);
                if (f == 7) v = uy == 0 ? ux : ux % uy;
            } else {
                bool legal = (!w || f == 0 || f == 1 || f == 5);
                if (im) {
                    if (f == 1) legal &= (ins >> (w || N == 32 ? 25 : 26)) == 0;
                    if (f == 5) {
                        unsigned top = ins >> (w || N == 32 ? 25 : 26);
                        legal &= top == 0 || top == (w || N == 32 ? 32U : 16U);
                    }
                } else legal &= hi == 0 || (hi == 32 && (f == 0 || f == 5));
                if (!legal) { trap(2, ins); return out; }
                y = im ? imm : y;
                switch (f) {
                    case 0: v = !im && hi == 32 ? x - y : x + y; break;
                    case 1: v = x << shift; break;
                    case 2: v = signedValue(x) < signedValue(y); break;
                    case 3: v = fit(x) < fit(y); break;
                    case 4: v = x ^ y; break;
                    case 5: v = ins & (1U << 30) ? uint64_t((w ? int64_t(int32_t(x)) : signedValue(x)) >> shift)
                        : (w ? uint32_t(x) : fit(x)) >> shift; break;
                    case 6: v = x | y; break;
                    case 7: v = x & y; break;
                }
            }
            write(w ? signExtend(v, 32) : v);
        } else if (op == 0x03 || op == 0x23) {
            bool store = op == 0x23;
            unsigned size = 1U << (f & 3);
            if (size > BYTES || (store && f >= 4) || (!store && (f == 7 || (N == 32 && f == 6)))) {
                trap(2, ins); return out;
            }
            uint64_t aImm = store ? signExtend((ins >> 25 << 5) | (ins >> 7 & 31), 12) : imm;
            uint64_t address = fit(x + aImm);
            if (address & (size - 1)) { trap(store ? 6 : 4, address); return out; }
            if (dataError) { trap(store ? 7 : 5, address); return out; }
            if (store) {
                need(address >= BASE && address + size <= BASE + memory.size(), "oracle store range");
                for (unsigned j = 0; j < size; ++j) memory[address - BASE + j] = y >> (8 * j);
            } else {
                uint64_t v = load(address, size);
                write(f < 4 ? signExtend(v, 8 * size) : v);
            }
        } else if (op == 0x63 || op == 0x6f || op == 0x67) {
            uint64_t target = 0; bool taken = true;
            if (op == 0x63) {
                unsigned bi = (ins >> 31 << 12) | (ins >> 7 & 1) << 11 | (ins >> 25 & 63) << 5 | (ins >> 8 & 15) << 1;
                target = fit(pc + signExtend(bi, 13));
                switch (f) {
                    case 0: taken = x == y; break; case 1: taken = x != y; break;
                    case 4: taken = signedValue(x) < signedValue(y); break;
                    case 5: taken = signedValue(x) >= signedValue(y); break;
                    case 6: taken = x < y; break; case 7: taken = x >= y; break;
                    default: trap(2, ins); return out;
                }
            } else if (op == 0x6f) {
                unsigned ji = (ins >> 31 << 20) | (ins >> 12 & 255) << 12 | (ins >> 20 & 1) << 11 | (ins >> 21 & 1023) << 1;
                target = fit(pc + signExtend(ji, 21));
            } else {
                if (f != 0) { trap(2, ins); return out; }
                target = fit(x + imm) & ~uint64_t(1);
            }
            if (taken && (target & 3)) { trap(0, target); return out; }
            if (taken) out.next = target;
            if (op != 0x63) write(pc + 4);
        } else if (op == 0x73 && f != 0 && f != 4) {
            unsigned address = ins >> 20;
            uint64_t source = f & 4 ? a : x;
            bool change = (f & 3) == 1 || a != 0;
            uint64_t old = 0;
            switch (address) {
                case 0x300: old = status; break; case 0x304: old = mie; break;
                case 0x305: old = mtvec; break;
                case 0x340: old = scratch; break; case 0x341: old = epc; break;
                case 0x342: old = cause; break; case 0x343: old = tval; break;
                case 0xc02: old = fit(count); break;
                default: trap(2, ins); return out;
            }
            if (change && address >= 0xc00) { trap(2, ins); return out; }
            uint64_t value = (f & 3) == 1 ? source : (f & 3) == 2 ? old | source : old & ~source;
            if (change && address == 0x300) status = 0x1800 | (value & 0x88);
            if (change && address == 0x304) mie = value & 0x888;
            if (change && address == 0x305) mtvec = (fit(value) & ~3ULL) | ((value & 3) == 1);
            if (change && address == 0x340) scratch = fit(value);
            if (change && address == 0x341) epc = fit(value) & ~uint64_t(3);
            if (change && address == 0x342) cause = fit(value);
            if (change && address == 0x343) tval = fit(value);
            write(old);
        } else if (ins == 0x30200073) { out.next = epc; status = 0x1880 | ((status >> 4) & 8); }
        else if (ins == 0x00000073) { trap(11, 0); }
        else if (ins == 0x00100073) { trap(3, pc); }
        else if (ins == 0x10500073 || ins == 0x0000000f || ins == 0x0000100f) { }
        else { trap(2, ins); }
        return out;
    }
    void commit(const Result &out) {
        if (out.trap) {
            epc = pc; cause = out.cause; tval = out.tval;
            status = 0x1800 | ((status & 8) << 4);
        }
        else { if (out.write) r[out.rd] = out.value; ++count; }
        r[0] = 0; pc = out.next;
    }
};

#ifndef FIVE_STAGE_ORACLE_ONLY
struct MemoryReply { uint64_t due, address, data; bool error; bool write = false; };
struct StoreIntent { uint64_t address, data; unsigned size, mask; bool error, acknowledged = false; };
struct Stats {
    uint64_t cycles = 0, retires = 0, stalls = 0, loadStalls = 0, branches = 0;
    uint64_t aluRetires = 0, aluFirst = 0, aluLast = 0, aluMaxGap = 0;
    uint64_t wrongPathMduBlocked = 0;
};

static Stats execute(const std::string &name, const std::vector<uint32_t> &code, unsigned latency,
                     std::optional<uint64_t> fetchError = {}, std::optional<uint64_t> dataError = {},
                     bool returnFromTrap = false, bool inject = false, bool interrupt = false, bool injectStore = false,
                     unsigned extraDataDelay = 0) {
    std::vector<uint8_t> actual(65536);
    for (unsigned j = 0; j < actual.size(); ++j) actual[j] = uint8_t(j * 73 + 19);
    for (unsigned j = 0; j < code.size(); ++j) std::memcpy(actual.data() + 4 * j, &code[j], 4);
    const std::array<uint32_t, 6> handler = {ri(0x73, 22, 2, 0, 0x341), ri(0x73, 23, 2, 0, 0x342),
        br(4, 23, 0, 8), ri(0x13, 22, 0, 22, 4),
        ri(0x73, 0, 1, 22, 0x341), 0x30200073};
    if (returnFromTrap) for (unsigned j = 0; j < handler.size(); ++j)
        std::memcpy(actual.data() + 0x100 + 4 * j, &handler[j], 4);
    // Independent signed/unsigned MUL/DIV corner operands.
    std::array<uint64_t, 6> corners{uint64_t(1) << (N - 1), MASK, 0, 7, fit(-7), uint64_t(1) << 31};
    for (unsigned j = 0; j < corners.size(); ++j)
        for (unsigned k = 0; k < BYTES; ++k) actual[0x2000 + 512 + j * BYTES + k] = corners[j] >> (8 * k);
    Oracle oracle(actual);
    SFiveStageCore d;
    d.set_reset(1); d.set_io$$instructionRequest$$ready(0); d.set_io$$instructionResponse$$valid(0);
    d.set_io$$dataRequest$$ready(0); d.set_io$$dataResponse$$valid(0);
    d.set_io$$externalIrq(0); d.set_io$$timerIrq(0); d.set_io$$softwareIrq(0); d.set_io$$time(0);
    d.step(); d.step(); d.set_reset(0);
    std::optional<MemoryReply> fetch, data;
    std::deque<StoreIntent> unretiredStores;
    std::optional<uint64_t> heldFetch;
    std::optional<std::array<uint64_t, 5>> heldData;
    std::mt19937_64 rng(0x1a102026 + latency);
    Stats stats;
    unsigned traps = 0;
    bool interruptInjected = false, interruptSeen = false;
    for (uint64_t cycle = 0; cycle < 150000; ++cycle) {
        bool ir = latency == 1 || rng() % 4 != 0;
        bool dr = latency == 1 || rng() % 3 != 0;
        bool fv = fetch && fetch->due <= cycle, dv = data && data->due <= cycle;
        d.set_io$$instructionRequest$$ready(ir); d.set_io$$dataRequest$$ready(dr);
        d.set_io$$instructionResponse$$valid(fv);
        d.set_io$$instructionResponse$$bits$$instruction(fetch ? fetch->data : 0xf0f0f0f0U);
        d.set_io$$instructionResponse$$bits$$error(fetch && fetch->error);
        d.set_io$$dataResponse$$valid(dv); d.set_io$$dataResponse$$bits$$data(data ? data->data : 0xabcdU);
        d.set_io$$dataResponse$$bits$$error(data && data->error); d.set_io$$time(cycle);
        if (interrupt && !interruptInjected && oracle.count >= (DUT_HAS_M ? 6U : 5U) &&
            (DUT_HAS_M ? d.get_io$$stallMulDiv() : d.get_io$$stallMemory())) interruptInjected = true;
        d.set_io$$externalIrq(interruptInjected && !interruptSeen);
        d.step();
        if (d.get_io$$trapTaken() && !d.get_io$$retire$$valid()) {
            need(unretiredStores.empty(), name + ": interrupt overtook an external store");
            uint64_t irqCause = uint64_t(1) << (N - 1) | 11;
            need(interrupt && interruptInjected && !interruptSeen && (oracle.status & 8) && (oracle.mie & 0x800),
                "unexpected or masked interrupt");
            need(d.get_io$$trapPc() == oracle.pc && d.get_io$$trapCause() == irqCause,
                "independent interrupt resume-PC oracle mismatch");
            oracle.epc = oracle.pc; oracle.cause = irqCause; oracle.tval = 0;
            oracle.status = 0x1800 | ((oracle.status & 8) << 4); oracle.pc = VECTOR;
            interruptSeen = true;
        }
        if (heldFetch) need(d.get_io$$instructionRequest$$valid() && d.get_io$$instructionRequest$$bits() == *heldFetch,
            name + ": instruction offer changed under backpressure");
        if (heldData) {
            std::array<uint64_t, 5> now{d.get_io$$dataRequest$$bits$$address(), d.get_io$$dataRequest$$bits$$write(),
                d.get_io$$dataRequest$$bits$$size(), d.get_io$$dataRequest$$bits$$data(), d.get_io$$dataRequest$$bits$$mask()};
            need(d.get_io$$dataRequest$$valid() && now == *heldData, name + ": data offer changed under backpressure");
        }
        heldFetch.reset(); heldData.reset();
        if (d.get_io$$instructionRequest$$valid() && !ir) heldFetch = d.get_io$$instructionRequest$$bits();
        if (d.get_io$$dataRequest$$valid() && !dr) heldData = std::array<uint64_t, 5>{
            d.get_io$$dataRequest$$bits$$address(), d.get_io$$dataRequest$$bits$$write(), d.get_io$$dataRequest$$bits$$size(),
            d.get_io$$dataRequest$$bits$$data(), d.get_io$$dataRequest$$bits$$mask()};
        ++stats.cycles; stats.stalls += d.get_io$$stallMemory(); stats.loadStalls += d.get_io$$stallLoadUse();
        if (name.starts_with("mixed-late-redirect") && oracle.pc == BASE + 12 &&
            d.get_io$$stallMemory() && d.get_io$$stallMulDiv()) ++stats.wrongPathMduBlocked;
        if (d.get_io$$retire$$valid()) {
            uint64_t pc = d.get_io$$retire$$bits$$pc();
            need(pc == oracle.pc, name + ": retired wrong PC expected=" + std::to_string(oracle.pc) + " got=" + std::to_string(pc));
            uint32_t ins = uint32_t(oracle.load(pc, 4));
            need(ins == d.get_io$$retire$$bits$$instruction(), name + ": retired wrong instruction");
            const bool isStore = (ins & 127) == 0x23;
            const unsigned storeSize = 1U << (ins >> 12 & 7);
            const uint64_t storeImmediate = signExtend((ins >> 25 << 5) | (ins >> 7 & 31), 12);
            const uint64_t storeAddress = fit(oracle.r[ins >> 15 & 31] + storeImmediate);
            const uint64_t storeValue = oracle.r[ins >> 20 & 31];
            auto expected = oracle.evaluate(ins, fetchError && *fetchError == pc,
                dataError && (ins & 127) == 0x03 ? true : dataError && (ins & 127) == 0x23);
            if (name.starts_with("alu-stream") && !expected.trap) {
                if (!stats.aluRetires) stats.aluFirst = stats.cycles;
                else stats.aluMaxGap = std::max(stats.aluMaxGap, stats.cycles - stats.aluLast);
                stats.aluLast = stats.cycles; ++stats.aluRetires;
            }
            if (inject && stats.retires == 2) expected.value ^= 1;
            need(bool(d.get_io$$retire$$bits$$trap()) == expected.trap, name + ": independent trap oracle mismatch");
            if (expected.trap) {
                need(d.get_io$$retire$$bits$$cause() == expected.cause && d.get_io$$retire$$bits$$tval() == expected.tval,
                    name + ": independent exception oracle mismatch");
                ++traps;
            } else {
                need(bool(d.get_io$$retire$$bits$$writesRd()) == expected.write, name + ": independent write-enable oracle mismatch");
                if (expected.write) need(d.get_io$$retire$$bits$$rd() == expected.rd && d.get_io$$retire$$bits$$data() == expected.value,
                    name + ": independent register oracle mismatch pc=" + std::to_string(pc) + " expected=" +
                    std::to_string(expected.value) + " got=" + std::to_string(d.get_io$$retire$$bits$$data()));
                need(d.get_io$$retire$$bits$$nextPc() == expected.next, name + ": independent next-PC oracle mismatch");
            }
            if (isStore && (!expected.trap || expected.cause == 7)) {
                need(!unretiredStores.empty(), name + ": committed store has no external intent");
                const auto &intent = unretiredStores.front();
                const unsigned offset = storeAddress & (BYTES - 1);
                need(intent.address == storeAddress && intent.size == storeSize &&
                    intent.mask == (((1U << storeSize) - 1) << offset) &&
                    intent.error == expected.trap && intent.acknowledged,
                    name + ": independent store ownership/address/mask/ack mismatch");
                for (unsigned j = 0; j < storeSize; ++j)
                    need(uint8_t(intent.data >> (8 * (offset + j))) == uint8_t(storeValue >> (8 * j)),
                        name + ": independent store intent data mismatch");
                unretiredStores.pop_front();
            }
            if (expected.trap) need(unretiredStores.empty(), name + ": fault overtook a younger external store");
            oracle.commit(expected); ++stats.retires;
            // The real bus may write before WB. Compare EVERY byte each retirement after overlaying
            // its at-most-one unretired external intent; independently validate that intent against
            // the sequential ISA store on its eventual retirement. Never skip memory comparisons.
            auto busExpected = oracle.memory;
            need(unretiredStores.size() <= 1, name + ": more than one unretired store owner");
            for (const auto &intent : unretiredStores) if (!intent.error) {
                uint64_t aligned = intent.address & ~uint64_t(BYTES - 1);
                for (unsigned j = 0; j < BYTES; ++j) if (intent.mask >> j & 1)
                    busExpected[aligned - BASE + j] = intent.data >> (8 * j);
            }
            need(std::memcmp(actual.data() + 0x2000, busExpected.data() + 0x2000, 4096) == 0,
                name + ": independent store-byte oracle mismatch");
            if (expected.trap && (!returnFromTrap || traps == (interrupt ? 1U : 2U))) {
                if (name.starts_with("mixed") || name.starts_with("alu-stream"))
                    need(ins == 0x00100073 && expected.cause == 3, "workload stopped on an unexpected early trap");
                if (returnFromTrap) need(oracle.r[31] == 77, "MRET did not resume the caller");
                if (interrupt) need(interruptSeen, "busy-operation interrupt was never exercised");
                std::cout << "FIVE_STAGE_CASE_PASS name=" << name << " cycles=" << stats.cycles
                    << " retired=" << stats.retires << " memory_stalls=" << stats.stalls
                    << " load_use_stalls=" << stats.loadStalls << '\n';
                return stats;
            }
        }
        if (fv && d.get_io$$instructionResponse$$ready()) fetch.reset();
        if (dv && d.get_io$$dataResponse$$ready()) {
            if (data->write) {
                need(!unretiredStores.empty() && unretiredStores.front().address == data->address,
                    name + ": external store ack has no matching intent");
                unretiredStores.front().acknowledged = true;
            }
            data.reset();
        }
        if (d.get_io$$instructionRequest$$valid() && ir) {
            need(!fetch, name + ": duplicate fetch owner");
            uint64_t a = d.get_io$$instructionRequest$$bits();
            need(a >= BASE && a + 4 <= BASE + actual.size() && !(a & 3), name + ": fetch range/alignment");
            uint32_t value; std::memcpy(&value, actual.data() + a - BASE, 4);
            fetch = MemoryReply{cycle + latency, a, value, fetchError && *fetchError == a};
        }
        if (d.get_io$$dataRequest$$valid() && dr) {
            need(!data, name + ": duplicate MEM owner");
            uint64_t a = d.get_io$$dataRequest$$bits$$address();
            unsigned size = 1U << d.get_io$$dataRequest$$bits$$size();
            need(a >= DATA && a + size <= DATA + 4096 && !(a & (size - 1)), name + ": unexpected/faulting data request");
            uint64_t aligned = a & ~uint64_t(BYTES - 1), value = 0;
            bool error = dataError && a == *dataError;
            unsigned mask = d.get_io$$dataRequest$$bits$$mask();
            need(mask == (((1U << size) - 1) << (a & (BYTES - 1))), name + ": byte enable mismatch");
            if (d.get_io$$dataRequest$$bits$$write()) {
                uint64_t v = d.get_io$$dataRequest$$bits$$data();
                if (injectStore && !error) { v ^= uint64_t(1) << (8 * (a & (BYTES - 1))); injectStore = false; }
                unretiredStores.push_back(StoreIntent{a, v, size, mask, error});
                need(unretiredStores.size() <= 1, name + ": duplicated unretired store");
                if (!error) for (unsigned j = 0; j < BYTES; ++j)
                    if (mask >> j & 1) actual[aligned - BASE + j] = v >> (8 * j);
            }
            for (unsigned j = 0; j < BYTES; ++j) value |= uint64_t(actual[aligned - BASE + j]) << (8 * j);
            data = MemoryReply{cycle + latency + extraDataDelay + (latency == 1 ? 0 : rng() % 4), a, value, error,
                bool(d.get_io$$dataRequest$$bits$$write())};
        }
    }
    throw std::runtime_error(name + ": progress watchdog expired");
}

int main(int argc, char **argv) { try {
    bool inject = argc == 2 && std::string(argv[1]) == "--inject-register-mismatch";
    bool injectStore = argc == 2 && std::string(argv[1]) == "--inject-store-mismatch";
    std::vector<uint32_t> program{0x00002a17}; // AUIPC x20,0x2000 -> DATA
    for (unsigned r = 1; r <= 15; ++r) program.push_back(ri(0x13, r, 0, 0, int(r * 37) - 400));
    // MEM/WB forwarding, x0, store data forwarding, load-use and lane sign extension.
    program.push_back(ri(0x13, 1, 0, 1, 7)); program.push_back(ri(0x13, 1, 0, 1, 9));
    program.push_back(rr(0x33, 2, 0, 1, 1)); program.push_back(st(N == 64 ? 3 : 2, 20, 2, 0));
    program.push_back(ri(0x03, 3, N == 64 ? 3 : 2, 20, 0)); program.push_back(rr(0x33, 4, 0, 3, 2));
    program.push_back(ri(0x13, 0, 0, 4, 99)); program.push_back(rr(0x33, 5, 0, 0, 4));
    program.push_back(br(0, 0, 0, 8)); program.push_back(st(0, 20, 1, 16));
    program.push_back(jal(5, 8)); program.push_back(st(0, 20, 1, 17)); program.push_back(ri(0x13, 6, 0, 5, 3));
    program.push_back(23 << 7 | 0x17); program.push_back(ri(0x13, 23, 0, 23, 16));
    program.push_back(ri(0x67, 8, 0, 23, 0)); program.push_back(st(0, 20, 1, 18));
    std::mt19937_64 rng(0x2026101311);
    for (unsigned j = 0; j < 600; ++j) {
        unsigned rd = 1 + rng() % 15, a = rng() % 16, b = rng() % 16;
        unsigned f = rng() % 8, kind = rng() % (DUT_HAS_M ? 6 : 5);
        if (kind == 0) {
            int imm = int(rng() % 4096) - 2048;
            if (f == 1 || f == 5) imm = rng() % N | (f == 5 && (rng() & 1) ? 0x400 : 0);
            program.push_back(ri(0x13, rd, f, a, imm));
        } else if (kind == 1) program.push_back(rr(0x33, rd, f, a, b, (f == 0 || f == 5) && (rng() & 1) ? 32 : 0));
        else if (kind == 2) {
            unsigned sf = rng() % (N == 64 ? 4 : 3);
            unsigned offset = (rng() % 64) << sf;
            program.push_back(st(sf, 20, b, offset));
            program.push_back(ri(0x03, rd, sf < (N == 64 ? 3U : 2U) && (rng() & 1) ? sf + 4 : sf, 20, offset));
        } else if (kind == 3 && N == 64) {
            unsigned wf = std::array<unsigned, 3>{0, 1, 5}[rng() % 3];
            program.push_back(rr(0x3b, rd, wf, a, b, (wf == 0 || wf == 5) && (rng() & 1) ? 32 : 0));
        } else if (kind == 5) program.push_back(rr(0x33, rd, f, a, b, 1));
        else program.push_back(br(std::array<unsigned, 6>{0, 1, 4, 5, 6, 7}[rng() % 6], a, b, 8));
    }
    if (DUT_HAS_M) {
        for (unsigned a = 0; a < 6; ++a) for (unsigned b = 0; b < 6; ++b) {
            program.push_back(ri(0x03, 1, N == 64 ? 3 : 2, 20, 512 + a * BYTES));
            program.push_back(ri(0x03, 2, N == 64 ? 3 : 2, 20, 512 + b * BYTES));
            for (unsigned f = 0; f < 8; ++f) program.push_back(rr(0x33, 3 + f, f, 1, 2, 1));
            if (N == 64) for (unsigned f : {0, 4, 5, 6, 7}) program.push_back(rr(0x3b, 3 + f, f, 1, 2, 1));
        }
    }
    for (auto ins : {ri(0x73, 9, 1, 1, 0x340), ri(0x73, 10, 2, 0, 0x340), ri(0x73, 11, 5, 5, 0x340),
                    ri(0x73, 12, 7, 1, 0x340), ri(0x73, 13, 6, 2, 0x340), ri(0x73, 14, 2, 0, 0xc02),
                    uint32_t(0x0000000f), uint32_t(0x0000100f), uint32_t(0x00100073)}) program.push_back(ins);
    auto low = execute("mixed-low-latency", program, 1, {}, {}, false, inject, false, injectStore);
    auto blocked = execute("mixed-backpressure", program, 7);
    need(low.retires == blocked.retires, "latency changed retired workload");
    std::vector<uint32_t> stream;
    for (unsigned j = 0; j < 800; ++j) stream.push_back(ri(0x13, 1 + j % 15, 0, 0, int(j)));
    stream.push_back(0x00100073);
    auto peak = execute("alu-stream-independent", stream, 1);
    // Count steady-state retirement separately from filling and the serial EBREAK drain.
    // A deeper profile pays finite entry/exit cost, never 800 hidden body bubbles.
    const unsigned finiteBudget = 812 + 2 * (DUT_PIPELINE_STAGES - 5);
    need(peak.retires == 801 && peak.cycles <= finiteBudget && peak.aluRetires == 800 &&
        peak.aluLast - peak.aluFirst == 799 && peak.aluMaxGap == 1,
        "pipeline inserted bubbles into independent ALU stream");
    for (unsigned j = 0; j < 800; ++j) stream[j] = ri(0x13, 1, 0, 1, 1);
    auto chain = execute("alu-stream-dependent", stream, 1);
    if (DUT_MEM_BYPASS) need(chain.cycles <= finiteBudget && chain.aluRetires == 800 &&
        chain.aluLast - chain.aluFirst == 799 && chain.aluMaxGap == 1,
        "forwarding inserted bubbles into dependent ALU chain");
    std::cout << "PIPELINE_STEADY_ALU_PASS stages=" << DUT_PIPELINE_STAGES
        << " independent_800_span=799 dependent_with_bypass_span=" << chain.aluLast - chain.aluFirst << '\n';
    if (DUT_HAS_M) {
        // A branch waits in ADDR behind a real older load, while the wrong-path
        // divider enters EX. Check complete retire/store ledgers after redirect,
        // then execute a NEW real divider owner to catch leaked stale results.
        std::vector<uint32_t> late{0x00002a17, ri(0x13,1,0,0,93), ri(0x13,2,0,0,7),
            ri(0x03,4,N==64?3:2,20,512), br(0,0,0,16), rr(0x33,7,4,1,2,1),
            st(0,20,7,16), ri(0x13,31,0,0,88), ri(0x13,31,0,0,77),
            ri(0x03,7,N==64?3:2,20,520), rr(0x33,8,4,1,2,1), st(0,20,8,24), 0x00100073};
        unsigned covered=0;
        for(unsigned delay:{16U,96U}) {
            auto result=execute("mixed-late-redirect-"+std::to_string(delay),late,1,{},{},
                                false,false,false,false,delay);
#if defined(I1_TIMING_CUTS) && I1_TIMING_CUTS
            need(result.wrongPathMduBlocked>0,"late redirect did not overlap the wrong-path MDU and older memory");
            covered+=result.wrongPathMduBlocked;
#endif
        }
        execute("late-redirect-older-load-error",late,1,{},DATA+512,false,false,false,false,32);
        std::cout<<"I1_LATE_RECOVERY_PASS overlap_cycles="<<covered
                 <<" mid_or_held_MDU_kill_precise_old_fault_no_wrong_store_new_owner=PASS\n";
    }
    std::vector<uint32_t> irqProgram{0x00002a17, ri(0x13, 1, 0, 0, 8), ri(0x73, 0, 1, 1, 0x300),
        ri(0x13, 1, 0, 0, -2048), ri(0x73, 0, 1, 1, 0x304),
        ri(0x03, 2, N == 64 ? 3 : 2, 20, 512)};
    if (DUT_HAS_M) irqProgram.push_back(rr(0x33, 3, 4, 2, 1, 1));
    irqProgram.push_back(ri(0x13, 31, 0, 0, 77)); irqProgram.push_back(0x00100073);
    execute("interrupt-during-busy", irqProgram, 7, {}, {}, true, false, true);
    std::vector<std::pair<std::string, uint32_t>> faults{
        {"illegal", 0xffffffff}, {"unaligned-jump", jal(1, 2)},
        {"unaligned-load", ri(0x03, 3, 2, 20, 1)}, {"unaligned-store", st(2, 20, 1, 1)},
        {"readonly-csr", ri(0x73, 1, 1, 1, 0xc02)}, {"reserved-shift", ri(0x13, 1, 1, 2, 0x200)},
        {"ecall-return", 0x00000073}
    };
    if (!DUT_HAS_M) faults.push_back({"disabled-m", rr(0x33, 3, 0, 1, 2, 1)});
    for (const auto &[name, ins] : faults) {
        std::vector<uint32_t> p{0x00002a17, ri(0x13, 1, 0, 0, 3), ins,
            ri(0x13, 31, 0, 0, 77), 0x00100073};
        execute(name, p, 5, {}, {}, name == "ecall-return");
    }
    execute("fetch-error", {0x00002a17, ri(0x13, 1, 0, 0, 3), 0x00000013}, 8, BASE + 8);
    execute("load-error", {0x00002a17, ri(0x03, 1, 2, 20, 128)}, 5, {}, DATA + 128);
    execute("store-error", {0x00002a17, st(2, 20, 1, 128)}, 5, {}, DATA + 128);
    std::cout << "FIVE_STAGE_PASS xlen=" << N << " M=" << DUT_HAS_M << " matched_retires=" << low.retires
        << " low_cycles=" << low.cycles << " blocked_cycles=" << blocked.cycles << '\n';
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
#endif
