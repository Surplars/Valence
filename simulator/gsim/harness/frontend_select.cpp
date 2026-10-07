#include "FrontendSelectGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>
using D = SFrontendSelectGsim;
using BaseSetter = void (D::*)(uint64_t);
using ContextSetter = void (D::*)(uint8_t);
static constexpr std::array<BaseSetter, 32> baseSetters{&D::set_io$$base0,
    &D::set_io$$base1,
    &D::set_io$$base2,
    &D::set_io$$base3,
    &D::set_io$$base4,
    &D::set_io$$base5,
    &D::set_io$$base6,
    &D::set_io$$base7,
    &D::set_io$$base8,
    &D::set_io$$base9,
    &D::set_io$$base10,
    &D::set_io$$base11,
    &D::set_io$$base12,
    &D::set_io$$base13,
    &D::set_io$$base14,
    &D::set_io$$base15,
    &D::set_io$$base16,
    &D::set_io$$base17,
    &D::set_io$$base18,
    &D::set_io$$base19,
    &D::set_io$$base20,
    &D::set_io$$base21,
    &D::set_io$$base22,
    &D::set_io$$base23,
    &D::set_io$$base24,
    &D::set_io$$base25,
    &D::set_io$$base26,
    &D::set_io$$base27,
    &D::set_io$$base28,
    &D::set_io$$base29,
    &D::set_io$$base30,
    &D::set_io$$base31};
static constexpr std::array<ContextSetter, 32> contextSetters{&D::set_io$$context0,
    &D::set_io$$context1,
    &D::set_io$$context2,
    &D::set_io$$context3,
    &D::set_io$$context4,
    &D::set_io$$context5,
    &D::set_io$$context6,
    &D::set_io$$context7,
    &D::set_io$$context8,
    &D::set_io$$context9,
    &D::set_io$$context10,
    &D::set_io$$context11,
    &D::set_io$$context12,
    &D::set_io$$context13,
    &D::set_io$$context14,
    &D::set_io$$context15,
    &D::set_io$$context16,
    &D::set_io$$context17,
    &D::set_io$$context18,
    &D::set_io$$context19,
    &D::set_io$$context20,
    &D::set_io$$context21,
    &D::set_io$$context22,
    &D::set_io$$context23,
    &D::set_io$$context24,
    &D::set_io$$context25,
    &D::set_io$$context26,
    &D::set_io$$context27,
    &D::set_io$$context28,
    &D::set_io$$context29,
    &D::set_io$$context30,
    &D::set_io$$context31};
static uint64_t signExtend(uint64_t value, unsigned bits) {
    const uint64_t sign = uint64_t(1) << (bits - 1);
    return (value ^ sign) - sign;
}

int main(int argc, char **argv) { try {
    bool injectControl = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    bool injectQualification = argc == 2 && std::string_view(argv[1]) == "--inject-qualification";
    bool injectLookup = argc == 2 && std::string_view(argv[1]) == "--inject-lookup";
    bool injectShiftedLookup = argc == 2 && std::string_view(argv[1]) == "--inject-shifted-lookup";
    if (argc > 2 || (argc == 2 && !injectControl && !injectQualification && !injectLookup && !injectShiftedLookup))
        throw std::runtime_error("unknown frontend-select argument");
    D d;
    d.set_reset(0); d.set_io$$instruction(0); d.set_io$$pc(0);
    d.set_io$$upperImmediate(0); d.set_io$$indirectImmediate(0);
    d.set_io$$priorShort(0); d.set_io$$shortInstruction(0);
    d.set_io$$address(0); d.set_io$$context(0); d.set_io$$valid(0);
    for (unsigned slot = 0; slot < 32; ++slot) {
        (d.*baseSetters[slot])(0); (d.*contextSetters[slot])(0);
    }
    std::mt19937_64 rng(0x20261002f20aULL);
    uint64_t decoded = 0, qualified = 0, lookups = 0, sequential = 0, wraps = 0;
    uint64_t controlCases = 0, rejectedBranch = 0, hits = 0, dualHits = 0, misses = 0;
    uint64_t shiftedLookups = 0, shiftedHits = 0, shiftedDualHits = 0, shiftedMisses = 0, shiftedWraps = 0;
    auto verifyAdjacent = [&](uint64_t address, uint8_t context, uint32_t valid,
        const std::array<uint64_t, 32>& bases, const std::array<uint8_t, 32>& contexts) {
        const std::array<unsigned, 3> actuals = {d.get_io$$hitsNext(), d.get_io$$hitsNextTwo(),
            d.get_io$$hitsNextThree()};
        for (unsigned offset = 1; offset <= 3; ++offset) {
            // Literal modulo64 query arithmetic and original tags/set scan:
            // independent of fill-side subtraction or the DUT's short set adder.
            const uint64_t target = address + 8 * offset;
            unsigned expected = 0;
            for (unsigned way = 0; way < 2; ++way) {
                const unsigned slot = 2 * ((target >> 3) & 15) + way;
                if (((valid >> slot) & 1) && bases[slot] == target && contexts[slot] == context)
                    expected |= 1U << way;
            }
            unsigned actual = actuals[offset - 1];
            if (injectShiftedLookup && shiftedLookups == 100) actual ^= 1;
            if (actual != expected)
                throw std::runtime_error("adjacent fetch tag full64 selected-set oracle mismatch");
            ++shiftedLookups; shiftedHits += expected != 0; shiftedDualHits += expected == 3;
            shiftedMisses += expected == 0; shiftedWraps += target < address;
        }
    };
    auto decode = [&](uint32_t inst) {
        // Architectural encoding oracle, not DUT tables or old/new equality alone.
        unsigned opcode = inst & 127, f = (inst >> 12) & 7;
        unsigned expected = 0; uint64_t immediate = 0;
        if (opcode == 0x17) {
            expected = 1; immediate = signExtend(inst & 0xfffff000U, 32);
        } else if (opcode == 0x6f) {
            expected = 4;
            uint64_t j = ((uint64_t(inst >> 31) & 1) << 20) |
                (((inst >> 12) & 255) << 12) | (((inst >> 20) & 1) << 11) |
                (((inst >> 21) & 1023) << 1);
            immediate = signExtend(j, 21);
        } else if (opcode == 0x67 && f == 0) {
            expected = 8; immediate = signExtend(inst >> 20, 12);
        } else if (opcode == 0x63 && (f == 0 || f == 1 || f == 4 || f == 5 || f == 6 || f == 7)) {
            expected = 2;
            uint64_t b = ((uint64_t(inst >> 31) & 1) << 12) | (((inst >> 7) & 1) << 11) |
                (((inst >> 25) & 63) << 5) | (((inst >> 8) & 15) << 1);
            immediate = signExtend(b, 13);
        }
        unsigned actual = d.get_io$$control(); // sampled again after input evaluation below
        d.set_io$$instruction(inst); d.step(); actual = d.get_io$$control();
        if (injectControl && decoded == 100) actual ^= 1;
        if (actual != expected || d.get_io$$baselineControl() != expected ||
            d.get_io$$rd() != ((inst >> 7) & 31) || d.get_io$$rs1() != ((inst >> 15) & 31) ||
            d.get_io$$immediate() != immediate ||
            (expected && d.get_io$$baselineImmediate() != immediate))
            throw std::runtime_error("frontend control encoding oracle mismatch");
        ++decoded; controlCases += expected != 0;
        rejectedBranch += opcode == 0x63 && (f == 2 || f == 3);
    };
    for (unsigned opcode = 0; opcode < 128; ++opcode) for (unsigned f = 0; f < 8; ++f)
        for (unsigned rd : {0U, 1U, 5U, 31U}) for (unsigned rs1 : {0U, 1U, 5U, 31U})
            for (unsigned upper : {0U, 1U, 0x7ffU, 0x800U, 0xfffU})
                decode((upper << 20) | (rs1 << 15) | (f << 12) | (rd << 7) | opcode);
    for (unsigned i = 0; i < 50000; ++i) decode(uint32_t(rng()));

    auto qualify = [&](uint64_t pc, uint32_t upper, uint16_t indirect, bool priorShort, bool shortInstruction) {
        // Literal full64 modulo arithmetic, independently of narrow cancellation.
        uint64_t partial = pc + signExtend(upper, 32);
        uint64_t sum = partial + signExtend(indirect, 12);
        uint64_t target = sum & ~uint64_t(1);
        uint64_t successor = pc + (priorShort ? 2 : 4) + (shortInstruction ? 2 : 4);
        d.set_io$$pc(pc); d.set_io$$upperImmediate(upper); d.set_io$$indirectImmediate(indirect);
        d.set_io$$priorShort(priorShort); d.set_io$$shortInstruction(shortInstruction); d.step();
        bool different = d.get_io$$differentSuccessor();
        if (injectQualification && qualified == 100) different = !different;
        if (!d.get_io$$aligned16() || bool(d.get_io$$aligned32()) != ((target & 3) == 0) ||
            different != (target != successor))
            throw std::runtime_error("AUIPC qualification full64 arithmetic oracle mismatch");
        ++qualified; sequential += target == successor; wraps += partial < pc || sum < partial;
    };
    const uint64_t pcs[]{0, 1, 2, 3, 4, 0x80000000ULL, 0x80200002ULL,
        0x7ffffffffffffffeULL, 0x8000000000000000ULL, UINT64_MAX - 4, UINT64_MAX - 2, UINT64_MAX};
    const uint32_t uppers[]{0, 1, 2, 4, 6, 8, 0x7ffff000, 0x7fffffff, 0x80000000, 0xfffff000, 0xffffffff};
    const uint16_t indirects[]{0, 1, 2, 3, 4, 6, 8, 0x7ff, 0x800, 0xffe, 0xfff};
    for (auto pc : pcs) for (auto upper : uppers) for (auto indirect : indirects)
        for (bool a : {false, true}) for (bool b : {false, true}) qualify(pc, upper, indirect, a, b);
    for (unsigned i = 0; i < 100000; ++i) {
        auto pc = rng(); auto upper = uint32_t(rng()); auto indirect = uint16_t(rng() & 4095);
        bool a = rng() & 1, b = rng() & 1; qualify(pc, upper, indirect, a, b);
    }

    for (unsigned i = 0; i < 40000; ++i) {
        std::array<uint64_t, 32> bases; std::array<uint8_t, 32> contexts;
        for (unsigned slot = 0; slot < 32; ++slot) { bases[slot] = rng() & ~uint64_t(7); contexts[slot] = rng() & 7; }
        uint32_t valid = rng(); uint8_t context = rng() & 7;
        unsigned set = rng() & 15, way = rng() & 1, slot = 2 * set + way;
        uint64_t address = (rng() & ~uint64_t(127)) | (uint64_t(set) << 3);
        if (i % 128 == 0) address = 0xfffffffffffffff8ULL;
        set = (address >> 3) & 15; slot = set * 2 + way;
        unsigned mode = i % 9;
        if (mode) { bases[slot] = address; contexts[slot] = context; valid |= uint32_t(1) << slot; }
        if (mode == 3) {
            bases[slot ^ 1] = address; contexts[slot ^ 1] = context; valid |= uint32_t(1) << (slot ^ 1);
        }
        if (mode == 4) contexts[slot] ^= 1;
        if (mode == 5) valid &= ~(uint32_t(1) << slot);
        if (mode == 6) {
            valid &= ~(uint32_t(1) << slot);
            unsigned alias = ((set + 1) % 16) * 2 + way;
            bases[alias] = address; contexts[alias] = context; valid |= uint32_t(1) << alias;
        }
        if (mode == 7) bases[slot] ^= 1; // malformed low bits, full address must reject
        if (mode == 8) bases[slot] ^= uint64_t(1) << 63; // high64 alias, never truncate tag
        // Direct selected-set scan, no one-hot reduction or DUT lookup copy.
        unsigned expected = 0;
        for (unsigned w = 0; w < 2; ++w) {
            unsigned index = 2 * ((address >> 3) & 15) + w;
            if (((valid >> index) & 1) && bases[index] == address && contexts[index] == context) expected |= 1U << w;
        }
        d.set_io$$address(address); d.set_io$$context(context); d.set_io$$valid(valid);
        for (unsigned s = 0; s < 32; ++s) {
            (d.*baseSetters[s])(bases[s]); (d.*contextSetters[s])(contexts[s]);
        }
        d.step(); unsigned actual = d.get_io$$hits();
        if (injectLookup && lookups == 100) actual ^= 1;
        if (actual != expected) throw std::runtime_error("parallel fetch tag selected-set oracle mismatch");
        ++lookups; hits += expected != 0; dualHits += expected == 3; misses += expected == 0;
        verifyAdjacent(address, context, valid, bases, contexts);
    }
    // Directed adjacent hits and rejection cases. Include noncanonical/high
    // addresses, set and XLEN wrap, malformed stored low bits, wrong context,
    // wrong set, invalid slots, and both ways present. No alignment assumption
    // may replace exact address equality in the helper.
    const std::array<uint64_t, 9> lookupAddresses = {0, 1, 0x78, 0x7f, 0x80000000ULL,
        0x7ffffffffffffff8ULL, 0x8000000000000001ULL, UINT64_MAX - 15, UINT64_MAX - 7};
    for (auto address : lookupAddresses) for (unsigned offset = 1; offset <= 3; ++offset)
        for (unsigned mode = 0; mode < 8; ++mode) for (unsigned way = 0; way < 2; ++way) {
            std::array<uint64_t, 32> bases{};
            std::array<uint8_t, 32> contexts{};
            const uint8_t context = 5;
            const uint64_t target = address + 8 * offset;
            const unsigned set = (target >> 3) & 15, slot = 2 * set + way;
            uint32_t valid = uint32_t(1) << slot;
            bases[slot] = target; contexts[slot] = context;
            if (mode == 1) {
                bases[slot ^ 1] = target; contexts[slot ^ 1] = context;
                valid |= uint32_t(1) << (slot ^ 1);
            }
            if (mode == 2) contexts[slot] ^= 4;
            if (mode == 3) valid = 0;
            if (mode == 4) {
                const unsigned alias = 2 * ((set + 1) & 15) + way;
                bases[alias] = target; contexts[alias] = context; valid = uint32_t(1) << alias;
            }
            if (mode == 5) bases[slot] ^= 1;
            if (mode == 6) bases[slot] ^= uint64_t(1) << 63;
            if (mode == 7) bases[slot] ^= 8; // malformed stored index bits
            d.set_io$$address(address); d.set_io$$context(context); d.set_io$$valid(valid);
            for (unsigned s = 0; s < 32; ++s) {
                (d.*baseSetters[s])(bases[s]); (d.*contextSetters[s])(contexts[s]);
            }
            d.step();
            verifyAdjacent(address, context, valid, bases, contexts);
    }
    if (!controlCases || !rejectedBranch || !sequential || !wraps || !hits || !dualHits || !misses)
        throw std::runtime_error("frontend selection coverage incomplete");
    if (!shiftedHits || !shiftedDualHits || !shiftedMisses || !shiftedWraps)
        throw std::runtime_error("adjacent fetch tag boundary coverage incomplete");
    std::cout << "GSIM frontend selection: PASS decode=" << decoded << " controls=" << controlCases
              << " reserved_branch=" << rejectedBranch << " full64_qualification=" << qualified
              << " sequential=" << sequential << " wrapping_additions=" << wraps << " tag_lookup=" << lookups
              << " hits=" << hits << " dual_hits=" << dualHits << " misses=" << misses
              << " adjacent_lookup=" << shiftedLookups << " adjacent_hits=" << shiftedHits
              << " adjacent_dual_hits=" << shiftedDualHits << " adjacent_misses=" << shiftedMisses
              << " adjacent_wraps=" << shiftedWraps << '\n';
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
