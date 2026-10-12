#include "RegisteredExecutionOperandPairGsim.h"
#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <type_traits>

namespace {
constexpr unsigned slots = 16, registers = 48, entryBits = 462, payloadBits = 591;
using Entry = std::array<uint64_t, 8>;
using Payload = std::array<uint64_t, 10>;
struct Field { unsigned offset, width; };
// Independent host ABI, audited against Bundle declaration order, not imported
// DUT constants. Every bit of the entry is retained/checked, including controls
// irrelevant to the arithmetic operation. Banked execution omits expanded only.
namespace f {
constexpr Field unsignedLoad{0, 1}, size{1, 2}, store{3, 1}, atomicOp{4, 5}, atomic{9, 1};
constexpr Field memory{10, 1}, controlFlow{11, 4}, immediate{15, 64};
constexpr Field useImmediate{79, 1}, usePc{80, 1}, word{81, 1}, mulDivOp{82, 3};
constexpr Field mulDiv{85, 1}, system{86, 1}, operation{87, 6}, expanded{93, 32};
constexpr Field fetchTval{125, 64}, fetchPageFault{189, 1}, fetchFault{190, 1};
constexpr Field renameWritesRd{191, 1}, rd{192, 5}, rs2{197, 5}, rs1{202, 5};
constexpr Field instruction{207, 32}, pc{239, 64}, prediction{303, 64}, predictionValid{367, 1};
constexpr Field moveAlias{368, 1}, writesRd{369, 1}, oldDestination{370, 6}, destination{376, 6};
constexpr Field source2{382, 6}, source1{388, 6}, tag{394, 64}, index{458, 4};
}
template<size_t N> uint64_t get(const std::array<uint64_t, N>& bits, Field field) {
    uint64_t value = 0;
    for (unsigned bit = 0; bit < field.width; ++bit)
        value |= ((bits[(field.offset + bit) / 64] >> ((field.offset + bit) % 64)) & 1) << bit;
    return value;
}
template<size_t N> void put(std::array<uint64_t, N>& bits, Field field, uint64_t value) {
    for (unsigned bit = 0; bit < field.width; ++bit) {
        auto& word = bits[(field.offset + bit) / 64];
        const auto mask = uint64_t(1) << ((field.offset + bit) % 64);
        word = (word & ~mask) | (((value >> bit) & 1) ? mask : 0);
    }
}
Entry unpack(const Payload& payload) {
    Entry entry{};
    for (unsigned bit = 0; bit < entryBits; ++bit)
        put(entry, {bit, 1}, get(payload, {129 + bit, 1}));
    return entry;
}
Payload pack(const Entry& entry, uint64_t left, uint64_t right, bool forwardable) {
    Payload payload{};
    put(payload, {0, 1}, forwardable); put(payload, {1, 64}, right); put(payload, {65, 64}, left);
    for (unsigned bit = 0; bit < entryBits; ++bit)
        put(payload, {129 + bit, 1}, get(entry, {bit, 1}));
    return payload;
}
bool legal(const Entry& entry) {
    const unsigned operation = get(entry, f::operation);
    // Stimulus is deliberately restricted to base integer controls and 63.
    // This is an independent legality truth table, not a DUT result oracle.
    if (operation > 11) return false;
    if (!get(entry, f::word)) return true;
    return operation == 0 || operation == 1 || operation == 5 || operation == 6 || operation == 7;
}
struct Wake { bool valid = false; unsigned destination = 0; uint64_t data = 0; };
struct Write { bool valid = false; unsigned address = 63; uint64_t data = 0; };
struct Input {
    bool rowValid = false; unsigned rowIndex = 0; Entry row{};
    std::array<Write, 2> writes{};
    unsigned head = 0, pending = 0, prepared = 0, addressKnown = 0, preparationBusy = 0, killed = 0;
    uint64_t ready = (uint64_t(1) << registers) - 1;
    bool pendingException = false, headException = false, branchRedirect = false;
    std::array<bool, 3> reserve{}, complete{}; // system, memory, M unit
    std::array<bool, 2> sinkReady{true, true};
    Wake load; std::array<Wake, 2> alu{};
};
struct State { bool occupied = false; Payload payload{}; };
struct Observation {
    unsigned eligible = 0, owner = 0, index = 0;
    bool rankValid = false, opportunity = false, enqValid = false, enqReady = false, enqFire = false;
    bool deqValid = false, deqReady = false, deqFire = false, occupied = false, cancel = false;
    Payload offered{}, held{};
    bool prepare = false;
    uint64_t storeBase = 0, storeData = 0, storeAddress = 0;
    bool mutationApplied = false;
    bool operator==(const Observation&) const = default;
};

Observation read(SRegisteredExecutionOperandPairGsim& d, unsigned cfg, unsigned lane, bool candidate) {
    Observation o;
#define SIDE(C,L,P) \
    o.eligible = d.get_io$$cfg##C##$$eligible(); \
    o.owner = d.get_io$$cfg##C##$$lane##L##$$owner(); \
    o.index = d.get_io$$cfg##C##$$lane##L##$$index(); \
    o.rankValid = d.get_io$$cfg##C##$$lane##L##$$rankValid(); \
    o.opportunity = d.get_io$$cfg##C##$$lane##L##$$##P##$$opportunity(); \
    o.enqValid = d.get_io$$cfg##C##$$lane##L##$$##P##$$enqValid(); \
    o.enqReady = d.get_io$$cfg##C##$$lane##L##$$##P##$$enqReady(); \
    o.enqFire = d.get_io$$cfg##C##$$lane##L##$$##P##$$enqFire(); \
    o.deqValid = d.get_io$$cfg##C##$$lane##L##$$##P##$$deqValid(); \
    o.deqReady = d.get_io$$cfg##C##$$lane##L##$$##P##$$deqReady(); \
    o.deqFire = d.get_io$$cfg##C##$$lane##L##$$##P##$$deqFire(); \
    o.occupied = d.get_io$$cfg##C##$$lane##L##$$##P##$$occupied(); \
    o.cancel = d.get_io$$cfg##C##$$lane##L##$$##P##$$cancel(); \
    o.prepare = d.get_io$$cfg##C##$$lane##L##$$##P##$$prepare(); \
    o.storeBase = d.get_io$$cfg##C##$$lane##L##$$##P##$$storeBase(); \
    o.storeData = d.get_io$$cfg##C##$$lane##L##$$##P##$$storeData(); \
    o.storeAddress = d.get_io$$cfg##C##$$lane##L##$$##P##$$storeAddress(); \
    o.mutationApplied = d.get_io$$cfg##C##$$lane##L##$$##P##$$mutationApplied(); \
    o.offered = {d.get_io$$cfg##C##$$lane##L##$$##P##$$offered0(), \
        d.get_io$$cfg##C##$$lane##L##$$##P##$$offered1(), d.get_io$$cfg##C##$$lane##L##$$##P##$$offered2(), \
        d.get_io$$cfg##C##$$lane##L##$$##P##$$offered3(), d.get_io$$cfg##C##$$lane##L##$$##P##$$offered4(), \
        d.get_io$$cfg##C##$$lane##L##$$##P##$$offered5(), d.get_io$$cfg##C##$$lane##L##$$##P##$$offered6(), \
        d.get_io$$cfg##C##$$lane##L##$$##P##$$offered7(), d.get_io$$cfg##C##$$lane##L##$$##P##$$offered8(), \
        d.get_io$$cfg##C##$$lane##L##$$##P##$$offered9()}; \
    o.held = {d.get_io$$cfg##C##$$lane##L##$$##P##$$held0(), \
        d.get_io$$cfg##C##$$lane##L##$$##P##$$held1(), d.get_io$$cfg##C##$$lane##L##$$##P##$$held2(), \
        d.get_io$$cfg##C##$$lane##L##$$##P##$$held3(), d.get_io$$cfg##C##$$lane##L##$$##P##$$held4(), \
        d.get_io$$cfg##C##$$lane##L##$$##P##$$held5(), d.get_io$$cfg##C##$$lane##L##$$##P##$$held6(), \
        d.get_io$$cfg##C##$$lane##L##$$##P##$$held7(), d.get_io$$cfg##C##$$lane##L##$$##P##$$held8(), \
        d.get_io$$cfg##C##$$lane##L##$$##P##$$held9()}
#define CASE(C,L,P,B) case (4 * C + 2 * L + B): { SIDE(C,L,P); break; }
#define CONFIG(C) CASE(C,0,reference,0); CASE(C,0,candidate,1); CASE(C,1,reference,0); CASE(C,1,candidate,1)
    switch (4 * cfg + 2 * lane + candidate) {
        CONFIG(0); CONFIG(1); CONFIG(2); CONFIG(3);
        default: throw std::runtime_error("bad observation port");
    }
#undef CONFIG
#undef CASE
#undef SIDE
    return o;
}

struct Coverage {
    uint64_t cycles = 0, offers = 0, captured = 0, consumed = 0, held = 0, replaced = 0;
    uint64_t cancel = 0, cancelNoCredit = 0, cancelReplace = 0, staleCancel = 0, invalidHeld = 0;
    uint64_t invalidOperandDifference = 0, storeWhileFull = 0, dualForward = 0, loadPriority = 0;
    uint64_t x0 = 0, rangeRead = 0, prfReuse = 0, zeroOwner = 0, wrap = 0, resets = 0;
    std::array<uint64_t, 3> reserveDenied{}, completionBlocked{};
    unsigned classes = 0;
};

class Bench {
public:
    SRegisteredExecutionOperandPairGsim dut;
    std::array<Entry, slots> rows{};
    std::array<bool, slots> programmed{};
    std::array<uint64_t, registers> words{};
    std::array<std::array<State, 2>, 4> state{};
    Coverage cover;
    unsigned mutation = 0;
    uint64_t actualCorruptions = 0;
    std::string phase, mode;
    explicit Bench(std::string m, unsigned control) : mutation(control), mode(std::move(m)) {
        static_assert(std::is_trivially_copyable_v<SRegisteredExecutionOperandPairGsim>);
        std::memset(&dut, 0, sizeof(dut));
        dut.LOG_START = 1; dut.activateAll();
    }
    void require(bool pass, const std::string& reason) const {
        if (!pass) throw std::runtime_error(reason + " phase=" + phase + " cycle=" + std::to_string(cover.cycles));
    }
    uint64_t word(unsigned source) const { return source && source < registers ? words[source] : 0; }
    bool baseReady(const Input& in, unsigned source) const { return source < registers && ((in.ready >> source) & 1); }
    bool hit(const Wake& wake, unsigned source) const { return wake.valid && wake.destination == source; }
    bool issueReady(const Input& in, unsigned source) const {
        return baseReady(in, source) || hit(in.load, source) || hit(in.alu[0], source) || hit(in.alu[1], source);
    }
    uint64_t forwarding(const Input& in, unsigned source) const {
        if (hit(in.load, source)) return in.load.data;
        uint64_t value = 0; bool available = false;
        for (const auto& wake : in.alu) if (hit(wake, source)) { available = true; value |= wake.data; }
        return available ? value : word(source);
    }
    unsigned eligible(const Input& in) const {
        unsigned mask = 0;
        for (unsigned i = 0; i < slots; ++i) {
            if (!(in.pending & (1U << i))) continue;
            require(programmed[i], "host enabled an unprogrammed owner");
            const auto& row = rows[i];
            if (get(row, f::system) || get(row, f::mulDiv)) continue;
            const bool memory = get(row, f::memory);
            const bool preparation = memory && get(row, f::store) && !(in.prepared & (1U << i)) && i != in.head;
            if (memory && !preparation) continue;
            const unsigned first = get(row, f::source1), second = get(row, f::source2);
            const bool firstReady = get(row, f::usePc) || (memory ? baseReady(in, first) : issueReady(in, first));
            const bool secondReady = get(row, f::useImmediate) || (memory ? baseReady(in, second) : issueReady(in, second));
            if (!firstReady || (!secondReady && !(preparation && !(in.addressKnown & (1U << i))))) continue;
            if (in.preparationBusy & (1U << i)) continue;
            if (in.branchRedirect && get(row, f::controlFlow)) continue;
            mask |= 1U << i;
        }
        return mask;
    }
    std::array<int, 2> ranks(unsigned mask, unsigned head) const {
        std::array<int, 2> result{-1, -1}; unsigned count = 0;
        // Independent cyclic walk, not a prefix/tree/masked priority encoder.
        for (unsigned age = 0; age < slots && count < 2; ++age) {
            const unsigned index = (head + age) % slots;
            if (mask & (1U << index)) result[count++] = int(index);
        }
        return result;
    }
    Observation expected(const Input& in, unsigned cfg, unsigned lane, bool direct) const {
        Observation out;
        out.eligible = eligible(in);
        const auto choices = ranks(out.eligible, in.head);
        const int selected = choices[lane == 0 ? 1 : 0];
        out.rankValid = selected >= 0;
        out.index = out.rankValid ? unsigned(selected) : 0;
        out.owner = out.rankValid ? 1U << out.index : 0;
        Entry entry = out.rankValid ? rows[out.index] : Entry{};
        if (cfg & 2) put(entry, f::expanded, 0);
        const unsigned first = get(entry, f::source1), second = get(entry, f::source2);
        const bool memory = get(entry, f::memory), store = memory && get(entry, f::store);
        const uint64_t left = forwarding(in, first), right = forwarding(in, second);
        const uint64_t dispatchLeft = memory ? word(first) : left;
        const uint64_t dispatchRight = memory ? word(second) : right;
        const bool forwardable = get(entry, f::writesRd) && !get(entry, f::controlFlow) &&
            !get(entry, f::fetchFault) && !get(entry, f::fetchPageFault) && legal(entry);
        out.offered = pack(entry, direct ? left : dispatchLeft, direct ? right : dispatchRight, forwardable);
        out.opportunity = out.rankValid && (lane != 0 || (!in.branchRedirect &&
            !in.reserve[0] && !in.reserve[1] && !in.reserve[2]));
        out.enqValid = out.opportunity && !store && !(in.killed & (1U << out.index)) && !in.pendingException;
        const auto& saved = state[cfg][lane];
        const Entry old = unpack(saved.payload);
        const unsigned oldIndex = saved.occupied ? get(old, f::index) : 0;
        const bool sameOwner = get(old, f::index) == get(rows[oldIndex], f::index) &&
            get(old, f::tag) == get(rows[oldIndex], f::tag);
        out.cancel = saved.occupied && ((in.killed & (1U << oldIndex)) || !sameOwner);
        out.deqReady = in.sinkReady[lane] && (lane != 0 ||
            (!in.complete[0] && !in.complete[1] && !in.complete[2])) &&
            (!in.branchRedirect || !get(old, f::controlFlow));
        out.occupied = saved.occupied;
        out.enqReady = !saved.occupied || out.deqReady;
        out.enqFire = out.enqValid && out.enqReady;
        out.deqValid = saved.occupied && !out.cancel;
        out.deqFire = out.deqValid && out.deqReady;
        out.held = saved.payload;
        out.prepare = out.opportunity && store && !(in.killed & (1U << out.index)) && !in.headException;
        out.storeBase = dispatchLeft; out.storeData = dispatchRight;
        out.storeAddress = dispatchLeft + get(entry, f::immediate);
        return out;
    }
    void check(const Observation& got, const Observation& want, const std::string& side) const {
        const std::string label = "REGISTERED_EXECUTION_OPERAND_ORACLE " + side + " ";
        // This witness must reject the actual remove-store-exclusion mutant,
        // independently of whether both payload operands happen to be equal.
        require(!got.enqValid || !get(unpack(got.offered), f::memory), label + "valid offer must be nonmemory");
        require(got.eligible == want.eligible && got.owner == want.owner && got.index == want.index &&
            got.rankValid == want.rankValid, label + "eligibility/rank/owner");
        require(got.opportunity == want.opportunity && got.enqValid == want.enqValid &&
            got.enqReady == want.enqReady && got.enqFire == want.enqFire, label + "input grant/credit");
        require(got.occupied == want.occupied && got.cancel == want.cancel && got.deqValid == want.deqValid &&
            got.deqReady == want.deqReady && got.deqFire == want.deqFire, label + "held owner/control");
        require(got.offered == want.offered, label + "all offered payload bits");
        require(got.held == want.held, label + "all stored payload bits including invalid held output");
        require(got.prepare == want.prepare && got.storeBase == want.storeBase &&
            got.storeData == want.storeData && got.storeAddress == want.storeAddress,
            label + "unchanged shared store preparation");
    }
    void drive(const Input& in, bool reset) {
        dut.set_reset(reset);
        dut.set_io$$in$$mutation(reset ? 0 : mutation);
        dut.set_io$$in$$rowValid(in.rowValid); dut.set_io$$in$$rowIndex(in.rowIndex);
#define ROW(N) dut.set_io$$in$$rowWord##N(in.row[N])
        ROW(0); ROW(1); ROW(2); ROW(3); ROW(4); ROW(5); ROW(6); ROW(7);
#undef ROW
#define WRITE(N) \
        dut.set_io$$in$$write##N##$$valid(in.writes[N].valid); \
        dut.set_io$$in$$write##N##$$address(in.writes[N].address); \
        dut.set_io$$in$$write##N##$$data(in.writes[N].data)
        WRITE(0); WRITE(1);
#undef WRITE
#define SET(F) dut.set_io$$in$$##F(in.F)
        SET(head); SET(pending); SET(prepared); SET(addressKnown); SET(preparationBusy); SET(ready); SET(killed);
        SET(pendingException); SET(headException); SET(branchRedirect);
#undef SET
        dut.set_io$$in$$reserveSystem(in.reserve[0]); dut.set_io$$in$$reserveMemory(in.reserve[1]);
        dut.set_io$$in$$reserveMulDiv(in.reserve[2]); dut.set_io$$in$$completeSystem(in.complete[0]);
        dut.set_io$$in$$completeMemory(in.complete[1]); dut.set_io$$in$$completeMulDiv(in.complete[2]);
        dut.set_io$$in$$sinkReady0(in.sinkReady[0]); dut.set_io$$in$$sinkReady1(in.sinkReady[1]);
#define WAKE(P,W) \
        dut.set_io$$in$$##P##$$valid(W.valid); dut.set_io$$in$$##P##$$destination(W.destination); \
        dut.set_io$$in$$##P##$$data(W.data)
        WAKE(load,in.load); WAKE(alu0,in.alu[0]); WAKE(alu1,in.alu[1]);
#undef WAKE
    }
    void tick(const Input& in, const std::string& label, bool reset = false) {
        phase = label;
        drive(in, reset); dut.step();
        if (reset) {
            words.fill(0); state = {}; ++cover.resets;
        } else {
            ++cover.cycles;
            // Record actual RTL corruption before checks can reject the run.
            // A negative control is accepted only with this nonzero marker and
            // a nonzero process status at the corresponding independent check.
            for (unsigned cfg = 0; cfg < 4; ++cfg) for (unsigned lane = 0; lane < 2; ++lane) {
                if (read(dut, cfg, lane, true).mutationApplied) {
                    ++actualCorruptions;
                    std::cerr << "ACTUAL_CORRUPTION count=" << actualCorruptions << " mode=" << mode
                              << " kind=RTL cfg=" << cfg << " lane=" << lane << '\n';
                }
            }
            for (unsigned cfg = 0; cfg < 4; ++cfg) for (unsigned lane = 0; lane < 2; ++lane) {
                const auto reference = read(dut, cfg, lane, false), candidate = read(dut, cfg, lane, true);
                const auto want = expected(in, cfg, lane, false), direct = expected(in, cfg, lane, true);
                require(!reference.mutationApplied, "reference enabled a test mutation");
                check(reference, want, "reference cfg=" + std::to_string(cfg) + " lane=" + std::to_string(lane));
                check(candidate, direct, "candidate cfg=" + std::to_string(cfg) + " lane=" + std::to_string(lane));
                auto comparable = candidate;
                if (!candidate.enqValid) {
                    // Precisely the two invalid combinational operand fields
                    // may differ. Entry, forwardable and padding remain exact.
                    put(comparable.offered, {1, 64}, get(reference.offered, {1, 64}));
                    put(comparable.offered, {65, 64}, get(reference.offered, {65, 64}));
                }
                require(comparable == reference, "REGISTERED_EXECUTION_OPERAND_PAIR cycle/state parity");
                if (cfg == 0) count(in, want, direct, lane);
                auto& next = state[cfg][lane];
                if (want.cancel || want.deqFire) next.occupied = false;
                if (want.enqFire) { next.occupied = true; next.payload = want.offered; }
            }
            for (unsigned i = 0; i < slots; ++i) if (in.pending & (1U << i)) {
                const unsigned classes = unsigned(get(rows[i], f::memory)) |
                    (unsigned(get(rows[i], f::store)) << 1) | (unsigned(get(rows[i], f::system)) << 2) |
                    (unsigned(get(rows[i], f::mulDiv)) << 3);
                cover.classes |= 1U << classes;
            }
            for (const auto& write : in.writes) if (write.valid && write.address && write.address < registers) {
                cover.prfReuse += words[write.address] != 0;
                words[write.address] = write.data; // Higher completion lane wins.
            }
        }
        if (in.rowValid) { rows[in.rowIndex] = in.row; programmed[in.rowIndex] = true; }
    }
    void count(const Input& in, const Observation& o, const Observation& direct, unsigned lane) {
        cover.offers += o.enqValid; cover.captured += o.enqFire; cover.consumed += o.deqFire;
        cover.held += o.occupied && !o.deqReady; cover.replaced += o.occupied && o.enqFire;
        cover.cancel += o.cancel; cover.cancelNoCredit += o.cancel && !o.enqReady && o.enqValid;
        cover.cancelReplace += o.cancel && o.enqFire;
        const auto old = unpack(o.held);
        cover.staleCancel += o.cancel && get(old, f::tag) != get(rows[get(old, f::index)], f::tag);
        cover.invalidHeld += !o.occupied && o.held != Payload{};
        cover.invalidOperandDifference += !o.enqValid && o.offered != direct.offered;
        cover.storeWhileFull += o.prepare && o.occupied && !o.enqReady;
        cover.zeroOwner += !o.rankValid; cover.wrap += o.rankValid && o.index < in.head;
        const auto entry = unpack(o.offered);
        const unsigned first = get(entry, f::source1), second = get(entry, f::source2);
        if (o.enqValid) {
            for (unsigned source : {first, second}) {
                cover.x0 += source == 0; cover.rangeRead += source >= registers;
                cover.loadPriority += hit(in.load, source) && (hit(in.alu[0], source) || hit(in.alu[1], source));
            }
            cover.dualForward += (hit(in.load, first) && (hit(in.alu[0], second) || hit(in.alu[1], second))) ||
                (hit(in.load, second) && (hit(in.alu[0], first) || hit(in.alu[1], first)));
        }
        if (lane == 0) for (unsigned kind = 0; kind < 3; ++kind) {
            cover.reserveDenied[kind] += in.reserve[kind] && o.rankValid && !o.opportunity;
            cover.completionBlocked[kind] += in.complete[kind] && o.occupied && !o.deqReady;
        }
    }
    void reset() { tick({}, "reset", true); tick({}, "reset", true); tick({}, "after-reset"); }
    void program(unsigned index, Entry row) {
        require(get(row, f::index) == index, "allocation token index does not match its slot");
        Input in; in.rowValid = true; in.rowIndex = index; in.row = row; tick(in, "write-real-metadata-and-payload");
    }
};

Entry row(std::mt19937_64& rng, unsigned index, unsigned classes = 0) {
    Entry r; for (auto& word : r) word = rng(); r.back() &= (1U << 14) - 1;
    put(r, f::index, index); put(r, f::tag, rng());
    put(r, f::source1, 5); put(r, f::source2, 6);
    put(r, f::operation, 0); put(r, f::word, 0);
    put(r, f::memory, classes & 1); put(r, f::store, (classes >> 1) & 1);
    put(r, f::system, (classes >> 2) & 1); put(r, f::mulDiv, (classes >> 3) & 1);
    put(r, f::usePc, 0); put(r, f::useImmediate, 0); put(r, f::controlFlow, 0);
    put(r, f::fetchFault, 0); put(r, f::fetchPageFault, 0); put(r, f::writesRd, 1);
    return r;
}
} // namespace

int main(int argc, char** argv) {
    try {
        const std::array<std::string, 5> modes{"--mutate-store-exclusion", "--mutate-load-priority",
            "--mutate-store-forwarding", "--mutate-valid-payload", "--mutate-invalid-held"};
        if (argc > 2) throw std::runtime_error("usage: run [one known --mutate-* control]");
        const std::string mode = argc == 2 ? argv[1] : "";
        unsigned mutation = 0;
        for (unsigned i = 0; i < modes.size(); ++i) if (mode == modes[i]) mutation = i + 1;
        if (!mode.empty() && !mutation) throw std::runtime_error("unknown corruption control: " + mode);
        Bench b(mode, mutation); b.reset(); std::mt19937_64 rng(0x6578656375746531ULL);
        for (unsigned i = 0; i < slots; ++i) b.program(i, row(rng, i, i));
        for (unsigned address = 0; address < registers; ++address) {
            Input in;
            in.writes = {{{true, address, 0x1234000000000000ULL + address},
                          {true, address, 0xcafe000000000000ULL + address}}};
            b.tick(in, "initialize-real-prf-higher-lane-wins-including-x0");
        }
        Input in; in.head = 2; in.pending = 0xffff;
        b.tick(in, "all-16-malformed-class-combinations-store-is-second-rank");
        b.tick({}, "drain"); b.tick({}, "invalid-output-must-retain-all-bits");
        for (unsigned head = 0; head < slots; ++head) {
            in = {}; in.head = head; in.pending = 0xffff;
            b.tick(in, "circular-class-exhaustion");
            in.prepared = 0xffff; b.tick(in, "prepared-store-excluded");
            in.prepared = 0; in.preparationBusy = 0xffff; b.tick(in, "preparation-busy-excluded");
            in.preparationBusy = 0; in.ready = 1; in.addressKnown = 0xffff;
            b.tick(in, "unready-source-store-address-known");
        }
        for (unsigned i = 0; i < slots; ++i) b.program(i, row(rng, i, i == 2 || i == 3 ? 3 : 0));
        in = {}; in.pending = 3; in.ready = 1;
        in.load = {true, 5, 0x1010101010101010ULL};
        in.alu = {{{true, 5, 0xeeeeeeeeeeeeeeeeULL}, {true, 6, 0x6262626262626262ULL}}};
        // Same-destination overlap is a helper priority stress outside legal
        // backend live-producer ownership. The full-backend gate separately
        // exercises legal simultaneous load/ALU forwarding to distinct sources.
        b.tick(in, "component-only-dual-forwarding-overlap-load-priority");
        in.sinkReady = {false, false};
        for (unsigned n = 0; n < 5; ++n) {
            in.load.data ^= rng(); in.alu[1].data ^= rng(); b.tick(in, "valid-offer-backpressured-held-bits-stable");
        }
        in.pending = 12; in.ready = (uint64_t(1) << registers) - 1;
        b.tick(in, "store-preparation-uses-shared-prf-while-both-execution-slots-full");
        in.headException = true; b.tick(in, "head-fault-blocks-store-preparation");
        in.headException = false; in.pendingException = true; in.pending = 3;
        b.tick(in, "pending-fault-blocks-execution-offer");
        in.pendingException = false; in.pending = (1U << 4) | (1U << 5); in.killed = 3;
        b.tick(in, "cancel-full-slot-cannot-lend-credit-to-surviving-owner");
        in.killed = 0; b.tick(in, "post-cancel-empty-refill");
        in.sinkReady = {true, true}; in.pending = 3; in.killed = (1U << 4) | (1U << 5);
        b.tick(in, "cancel-and-independent-same-edge-replacement");
        in.killed = 0;
        for (unsigned n = 0; n < 16; ++n) b.tick(in, "continuous-two-lane-II-one-turnover");
        for (unsigned kind = 0; kind < 3; ++kind) {
            in.reserve[kind] = true; b.tick(in, "memory-system-m-unit-reservation"); in.reserve[kind] = false;
            b.tick(in, "refill-before-completion-conflict");
            in.complete[kind] = true; b.tick(in, "memory-system-m-unit-completion-holds-lane-zero");
            in.complete[kind] = false;
        }
        // Full token mismatch after a row rewrite cancels the old stage owner;
        // its old operand snapshot must not be replaced by new PRF/row contents.
        in.sinkReady = {false, false}; b.tick(in, "hold-before-token-reuse");
        in.rowValid = true; in.rowIndex = 0; in.row = b.rows[0];
        put(in.row, f::tag, get(in.row, f::tag) ^ (uint64_t(1) << 63));
        in.writes[0] = {true, 5, 0x5555aaaaffff0000ULL};
        b.tick(in, "rewrite-full-token-and-prf-while-old-owner-held");
        in.rowValid = false; in.writes = {}; b.tick(in, "stale-generation-cancel-no-borrowed-credit");
        in.sinkReady = {true, true}; b.tick(in, "new-generation-refill");
        // Branch holding/filtering and kill all selected offers.
        Entry branch = b.rows[0]; put(branch, f::controlFlow, 1); b.program(0, branch);
        in = {}; in.pending = 3; b.tick(in, "capture-branch-and-ordinary-owner");
        in.branchRedirect = true; b.tick(in, "branch-redirect-filters-ranks-and-holds-branch");
        in.killed = 0xffff; b.tick(in, "recovery-kills-all-offers-and-held-owners");
        Entry zero = b.rows[4]; put(zero, f::source1, 0); put(zero, f::source2, 63);
        put(zero, f::useImmediate, 1); b.program(4, zero);
        in = {}; in.pending = 1U << 4; b.tick(in, "x0-and-out-of-range-stored-operands");
        for (unsigned n = 0; n < 1536; ++n) {
            in = {}; in.pending = rng() & 0xffff; in.head = rng() % slots;
            in.prepared = rng() & 0xffff; in.addressKnown = rng() & 0xffff;
            in.preparationBusy = rng() & rng() & 0xffff; in.ready = (rng() & ((uint64_t(1) << registers) - 1)) | 1;
            in.killed = rng() % 4 ? 0 : rng() & 0xffff;
            in.pendingException = rng() % 17 == 0; in.headException = rng() % 19 == 0;
            in.branchRedirect = rng() % 7 == 0;
            for (unsigned kind = 0; kind < 3; ++kind) {
                in.reserve[kind] = rng() % 9 == 0; in.complete[kind] = rng() % 7 == 0;
            }
            in.sinkReady = {rng() % 3 != 0, rng() % 3 != 0};
            in.load = {bool(rng() & 1), 1 + unsigned(rng() % 47), rng()};
            for (auto& wake : in.alu) wake = {bool(rng() & 1), 1 + unsigned(rng() % 47), rng()};
            if (n % 5 == 0) in.alu[0].destination = in.load.destination;
            // Distinct ALU owners, but deliberate overlap with the load.
            if (in.alu[0].destination == in.alu[1].destination) in.alu[1].valid = false;
            for (auto& write : in.writes) write = {bool(rng() & 1), unsigned(rng() % registers), rng()};
            if (n % 3 == 0) {
                in.rowValid = true; in.rowIndex = rng() % slots; in.row = row(rng, in.rowIndex, rng() & 15);
                put(in.row, f::source1, rng() & 63); put(in.row, f::source2, rng() & 63);
                put(in.row, f::usePc, rng() & 1); put(in.row, f::useImmediate, rng() & 1);
                put(in.row, f::controlFlow, rng() % 3 ? 0 : rng() & 15);
                put(in.row, f::operation, rng() % 5 ? rng() % 12 : 63); put(in.row, f::word, rng() & 1);
                put(in.row, f::fetchFault, rng() % 11 == 0); put(in.row, f::fetchPageFault, rng() % 13 == 0);
                put(in.row, f::writesRd, rng() & 1);
            }
            b.tick(in, "seeded-malformed-metadata-state-and-forwarding");
        }
        b.tick({}, "final-drain"); b.tick({}, "final-stale-output");
        b.reset(); // Stage reset zeros every bit, PRF initialization resets; payload RAM persists.
        in = {}; in.pending = 0xffff; b.tick(in, "post-reset-stale-queue-and-uninitialized-prf");
        b.tick({}, "post-reset-drain"); b.tick({}, "post-reset-invalid-output");
        const auto& c = b.cover;
        b.require(c.offers && c.captured && c.consumed && c.held && c.replaced && c.cancel && c.cancelNoCredit &&
            c.cancelReplace && c.staleCancel && c.invalidHeld && c.invalidOperandDifference && c.storeWhileFull &&
            c.dualForward && c.loadPriority && c.x0 && c.rangeRead && c.prfReuse && c.zeroOwner && c.wrap &&
            c.classes == 0xffff && c.resets == 4, "directed proof coverage incomplete");
        for (unsigned kind = 0; kind < 3; ++kind)
            b.require(c.reserveDenied[kind] && c.completionBlocked[kind], "reservation/completion class untested");
        // A negative run must never be reported as a pass, even if a check was
        // accidentally weakened enough to let an activated mutation survive.
        b.require(mode.empty(), b.actualCorruptions ? "requested RTL corruption escaped independent checks" :
            "requested RTL corruption was never activated");
        std::cout << "REGISTERED_EXECUTION_OPERAND_PAIR_PASS configs=4 rank_modes=2 payload_modes=2 lanes=2"
                  << " stored_bits_per_lane=" << payloadBits << " cycles=" << c.cycles
                  << " offers=" << c.offers << " captured=" << c.captured << " consumed=" << c.consumed
                  << " held=" << c.held << " replaced=" << c.replaced << " cancels=" << c.cancel
                  << " cancel_no_credit=" << c.cancelNoCredit << " cancel_replace=" << c.cancelReplace
                  << " stale_cancel=" << c.staleCancel << " invalid_held=" << c.invalidHeld
                  << " invalid_operand_difference=" << c.invalidOperandDifference
                  << " store_while_full=" << c.storeWhileFull << " dual_forward=" << c.dualForward
                  << " load_priority=" << c.loadPriority << " x0=" << c.x0 << " range_read=" << c.rangeRead
                  << " prf_reuse=" << c.prfReuse << " malformed_class_mask=" << c.classes << '\n';
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "REGISTERED_EXECUTION_OPERAND_PAIR_FAIL " << e.what() << '\n';
        return 1;
    }
}
