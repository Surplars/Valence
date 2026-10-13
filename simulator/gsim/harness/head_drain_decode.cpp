#include "head_drain_oracle.h"

#include <array>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>

#ifndef HEAD_DRAIN_ORACLE_ONLY
#include "HeadDrainDecodeGsim.h"
#endif

using namespace head_drain_oracle;

namespace {

constexpr uint32_t csr(unsigned address, unsigned function, unsigned source, unsigned rd = 0) {
    return (address << 20) | (source << 15) | (function << 12) | (rd << 7) | 0x73U;
}

constexpr uint32_t sfence(unsigned rs1, unsigned rs2, unsigned rd = 0, unsigned function = 0) {
    return 0x12000073U | (rs2 << 20) | (rs1 << 15) | (function << 12) | (rd << 7);
}

constexpr uint32_t fence(unsigned immediate, unsigned source, unsigned rd, unsigned function = 1) {
    return (immediate << 20) | (source << 15) | (function << 12) | (rd << 7) | 0x0fU;
}

void require(bool condition, const std::string &message) {
    if (!condition) throw std::runtime_error(message);
}

struct Golden {
    const char *name;
    uint32_t original;
    uint32_t expanded;
    unsigned classes;
};

// Literal expected output masks: bits 0/1/2/3 correspond to profiles above.
// These are host contract checks, separate from the catalog-generated sweep.
constexpr Golden golden[]{
    {"integer-nonmatch", 0x00000013U, 0x30200073U, 0x0},
    {"mret", 0x30200073U, 0x00000013U, 0xf},
    {"sret", 0x10200073U, 0x00000013U, 0xf},
    {"wfi-nonmatch", 0x10500073U, 0x30200073U, 0x0},
    {"pmp-disabled", 0x3a001073U, 0x00000013U, 0xe},
    {"pmp-cfg2-8", 0x3a201073U, 0x00000013U, 0xe},
    {"pmp-reserved-funct3", 0x3a004073U, 0x00000013U, 0xe},
    {"pmp-read-source-zero", 0x3a002073U, 0x00000013U, 0xe},
    {"pmp-cfg1-nonmatch", 0x3a101073U, 0x00000013U, 0x0},
    {"pmp-lower-nonmatch", 0x3af01073U, 0x00000013U, 0x0},
    {"pmp-first", 0x3b001073U, 0x00000013U, 0xe},
    {"pmp-8-last", 0x3b701073U, 0x00000013U, 0xe},
    {"pmp-8-upper-bound", 0x3b801073U, 0x00000013U, 0xc},
    {"pmp-16-last", 0x3bf01073U, 0x00000013U, 0xc},
    {"pmp-16-upper-bound", 0x3c001073U, 0x00000013U, 0x0},
    {"pmp-funct3-zero", 0x3a000073U, 0x00000013U, 0x0},
    {"satp-zero-csrrw", 0x18001073U, 0x00000013U, 0xe},
    {"satp-zero-csrrwi", 0x18005073U, 0x00000013U, 0xe},
    {"satp-zero-csrrs", 0x18002073U, 0x00000013U, 0x0},
    {"satp-zero-csrrc", 0x18003073U, 0x00000013U, 0x0},
    {"satp-zero-csrrsi", 0x18006073U, 0x00000013U, 0x0},
    {"satp-zero-csrrci", 0x18007073U, 0x00000013U, 0x0},
    {"satp-nonzero-csrrs", 0x1800a073U, 0x00000013U, 0xe},
    {"satp-nonzero-csrrc", 0x1800b073U, 0x00000013U, 0xe},
    {"satp-nonzero-csrrsi", 0x1800e073U, 0x00000013U, 0xe},
    {"satp-nonzero-csrrci", 0x1800f073U, 0x00000013U, 0xe},
    {"satp-reserved-zero", 0x18004073U, 0x00000013U, 0x0},
    {"satp-reserved-funct3", 0x1800c073U, 0x00000013U, 0xe},
    {"vm-disabled", 0x12000073U, 0x00000013U, 0xe},
    {"sfence-operands", 0x13ff8073U, 0x00000013U, 0xe},
    {"sfence-malformed-rd", 0x120000f3U, 0x00000013U, 0x0},
    {"sfence-malformed-funct3", 0x12001073U, 0x00000013U, 0x0},
    {"sfence-neighbor-funct7", 0x14000073U, 0x00000013U, 0x0},
    {"fence-i", 0x0000100fU, 0x00000013U, 0xf},
    {"fence-i-broad", 0xffff9f8fU, 0x00000013U, 0xf},
    {"fence-other-funct3", 0x0000000fU, 0x00000013U, 0x0},
    {"fp-nonmatch", 0x00000053U, 0x30200073U, 0x0},
    {"fp-load-nonmatch", 0x00003007U, 0x30200073U, 0x0},
    {"fp-store-nonmatch", 0x00003027U, 0x30200073U, 0x0},
    {"compressed-expanded", 0x00000001U, 0x30200073U, 0x8},
    {"compressed-pmp-expanded", 0x00000000U, 0x3a004073U, 0x8},
    {"compressed-sfence-expanded", 0x00000002U, 0x13ff8073U, 0x8},
    {"compressed-original-poison", 0x30200070U, 0x00000013U, 0x0},
    {"uncompressed-expanded-poison", 0x00000013U, 0x30200073U, 0x0},
    {"compressed-fp-expanded", 0x00006000U, 0x00003007U, 0x0},
    {"compressed-zero-satp", 0x00000001U, 0x18002073U, 0x0},
};

struct Mutation {
    const char *name;
    const char *caseName;
    unsigned output;
};

// Each control changes an output actually sampled from GSIM, after checking
// that the unmodified observation agrees with the oracle. Expectations never
// change. The directed case makes every control fire before the large sweep.
constexpr Mutation mutations[]{
    {"pmp-disabled", "pmp-disabled", 0},
    {"pmp-cfg2-8", "pmp-cfg2-8", 1},
    {"pmp-reserved-funct3", "pmp-reserved-funct3", 2},
    {"pmp-8-upper-bound", "pmp-8-upper-bound", 1},
    {"pmp-16-upper-bound", "pmp-16-upper-bound", 2},
    {"satp-zero-csrrw", "satp-zero-csrrw", 2},
    {"satp-zero-csrrwi", "satp-zero-csrrwi", 2},
    {"satp-zero-csrrs", "satp-zero-csrrs", 2},
    {"satp-reserved-funct3", "satp-reserved-funct3", 2},
    {"vm-disabled", "vm-disabled", 0},
    {"mret", "mret", 0},
    {"sret", "sret", 0},
    {"sfence-operands", "sfence-operands", 2},
    {"sfence-malformed-rd", "sfence-malformed-rd", 2},
    {"sfence-malformed-funct3", "sfence-malformed-funct3", 2},
    {"fence-i-broad", "fence-i-broad", 0},
    {"fence-other-funct3", "fence-other-funct3", 0},
    {"fp-nonmatch", "fp-nonmatch", 2},
    {"compressed-expanded", "compressed-expanded", 3},
    {"compressed-original-poison", "compressed-original-poison", 3},
    {"uncompressed-expanded-poison", "uncompressed-expanded-poison", 3},
};

constexpr uint32_t expansionCatalog[]{
    0x00000013U, 0x30200073U, 0x10200073U, 0x3a004073U,
    0x3b801073U, 0x3c001073U, 0x18001073U, 0x18002073U,
    0x1800c073U, 0x13ff8073U, 0x120000f3U, 0xffff9f8fU,
    0x00003007U, 0x00003027U, 0x00000053U, 0x00000000U,
};

// Pure host checks validate independently written examples and table sanity;
// no mock hardware or generated GSIM model is used in ORACLE_ONLY mode.
unsigned hostContract() {
    unsigned checks = 0;
    for (const auto &g : golden) {
        require(pack(classify(g.original, g.expanded)) == g.classes,
            std::string("host golden mismatch: ") + g.name);
        ++checks;
    }
    for (const auto &m : mutations) {
        unsigned matches = 0;
        for (const auto &g : golden) matches += std::string_view(m.caseName) == g.name;
        require(matches == 1 && m.output < profiles.size(),
            std::string("host mutation target missing or ambiguous: ") + m.name);
        ++checks;
    }
    return checks;
}

template <typename Check>
void corpus(Check check) {
    for (const auto &g : golden) check(g.name, g.original, g.expanded);

    // Every CSR address and raw function, each zero/nonzero source and rd.
    for (unsigned address = 0; address < 4096; ++address)
        for (unsigned function = 0; function < 8; ++function)
            for (unsigned source : {0U, 31U})
                for (unsigned rd : {0U, 31U})
                    check("csr-address-function", csr(address, function, source, rd), 0x30200073U);

    // All 32 rs1/uimm values and rd values at selected membership boundaries.
    constexpr unsigned boundaries[]{
        0x17f, 0x180, 0x181, 0x39f, 0x3a0, 0x3a1, 0x3a2,
        0x3a3, 0x3af, 0x3b0, 0x3b7, 0x3b8, 0x3bf, 0x3c0,
    };
    for (unsigned address : boundaries)
        for (unsigned function = 0; function < 8; ++function)
            for (unsigned source = 0; source < 32; ++source)
                for (unsigned rd = 0; rd < 32; ++rd)
                    check("csr-boundary-operands", csr(address, function, source, rd), 0x00000013U);

    for (unsigned rs1 = 0; rs1 < 32; ++rs1)
        for (unsigned rs2 = 0; rs2 < 32; ++rs2)
            check("sfence-all-registers", sfence(rs1, rs2), 0x00000013U);
    for (unsigned function = 0; function < 8; ++function)
        for (unsigned rd = 0; rd < 32; ++rd)
            for (unsigned rs1 : {0U, 31U})
                for (unsigned rs2 : {0U, 31U})
                    check("sfence-malformed-fields", sfence(rs1, rs2, rd, function), 0x30200073U);

    // Broad FENCE.I includes every top-12-bit value. Further cross products
    // expose rd/rs1/funct3 dependence that the existing class must not acquire.
    for (unsigned immediate = 0; immediate < 4096; ++immediate)
        for (unsigned source : {0U, 31U})
            for (unsigned rd : {0U, 31U})
                check("fence-all-immediates", fence(immediate, source, rd), 0x00000013U);
    for (unsigned function = 0; function < 8; ++function)
        for (unsigned source = 0; source < 32; ++source)
            for (unsigned rd = 0; rd < 32; ++rd)
                for (unsigned immediate : {0U, 0x120U, 0x180U, 0xfffU})
                    check("fence-operand-function", fence(immediate, source, rd, function), 0x30200073U);

    // Single-bit neighbors check exact returns, opcode/funct7/rd/funct3 edges,
    // and words that legitimately move into another broad class.
    for (uint32_t word : expansionCatalog) {
        check("encoding-catalog", word, ~word);
        for (unsigned bit = 0; bit < 32; ++bit)
            check("encoding-one-bit-neighbor", word ^ (uint32_t(1) << bit), word);
        for (unsigned opcode = 0; opcode < 128; ++opcode)
            check("encoding-all-opcodes", (word & ~0x7fU) | opcode, word);
    }

    // Representative FP families, including loads/stores and fused opcodes.
    for (unsigned opcode : {0x07U, 0x27U, 0x43U, 0x47U, 0x4bU, 0x4fU, 0x53U})
        for (unsigned function = 0; function < 8; ++function)
            for (unsigned top : {0U, 0x102U, 0x120U, 0x180U, 0x302U, 0x3a0U, 0x3b0U, 0xfffU})
                check("fp-poison-fields", (top << 20) | (31U << 15) | (function << 12) |
                    (31U << 7) | opcode, 0x30200073U);

    // All 16-bit originals, with poisoned upper bits and alternating expanded
    // classes. Includes quadrant 3: expanded must then be ignored. This tests
    // selection only; expandedInstruction is intentionally supplied directly.
    for (unsigned low = 0; low < 65536; ++low) {
        const uint32_t upper = expansionCatalog[(low >> 4) % 16] & 0xffff0000U;
        check("compressed-all-halfwords", upper | low, expansionCatalog[(low >> 2) % 16]);
    }
    for (uint32_t original : expansionCatalog)
        for (uint32_t expanded : expansionCatalog)
            for (unsigned quadrant = 0; quadrant < 4; ++quadrant)
                check("compressed-selection-poison", (original & ~3U) | quadrant, expanded);
}

struct Coverage {
    uint64_t vectors = 0;
    std::array<uint64_t, 4> drains{};
    std::array<uint64_t, 4> clears{};
    std::array<uint64_t, 4> reasons{};
    uint64_t compressedExpansionChanges = 0;

    void record(uint32_t original, uint32_t expanded, const Classes &expected) {
        ++vectors;
        for (unsigned i = 0; i < profiles.size(); ++i) {
            ++(expected[i] ? drains[i] : clears[i]);
            const auto classified = catalogs()[i].reasons(original, expanded);
            for (unsigned bit = 0; bit < reasons.size(); ++bit)
                if (classified & (1U << bit)) ++reasons[bit];
        }
        if (expected[2] != expected[3]) ++compressedExpansionChanges;
    }

    void verify() const {
        require(vectors == 366590, "head drain corpus count changed; review coverage accounting");
        for (unsigned i = 0; i < profiles.size(); ++i)
            require(drains[i] && clears[i], std::string("missing both outcomes for ") + profiles[i].name);
        for (auto count : reasons) require(count, "missing a drain reason from corpus");
        require(compressedExpansionChanges > 10000, "missing compressed selection coverage");
    }

    void print() const {
        std::cout << " vectors=" << vectors << " comparisons=" << vectors * profiles.size();
        for (unsigned i = 0; i < profiles.size(); ++i)
            std::cout << ' ' << profiles[i].name << "=" << drains[i] << '/' << clears[i];
        std::cout << " reasons-pmp-return-vm-fence=" << reasons[0] << ',' << reasons[1] << ','
            << reasons[2] << ',' << reasons[3]
            << " compressed-selection-changes=" << compressedExpansionChanges;
    }
};

#ifndef HEAD_DRAIN_ORACLE_ONLY
void compare(const Classes &actual, const Classes &expected, const char *caseName,
             uint32_t original, uint32_t expanded, uint64_t vector) {
    for (unsigned i = 0; i < actual.size(); ++i) {
        if (actual[i] == expected[i]) continue;
        std::ostringstream detail;
        detail << "head-drain-class-mismatch output=" << profiles[i].name << " case=" << caseName
            << " vector=" << vector << " original=0x" << std::hex << std::setw(8) << std::setfill('0')
            << original << " expanded=0x" << std::setw(8) << expanded << std::dec
            << " expected=" << expected[i] << " observed=" << actual[i];
        throw std::runtime_error(detail.str());
    }
}
#endif

} // namespace

int main(int argc, char **argv) {
    std::string mutationName;
    bool mutationFired = false;
    try {
        if (argc == 2 && std::string_view(argv[1]) == "--list-mutations") {
            for (const auto &m : mutations) std::cout << m.name << '\n';
            return 0;
        }
        const unsigned hostChecks = hostContract();
        Coverage coverage;
#ifdef HEAD_DRAIN_ORACLE_ONLY
        require(argc == 1, "oracle-only mode does not execute GSIM or hardware mutation controls");
        corpus([&](const char *, uint32_t original, uint32_t expanded) {
            coverage.record(original, expanded, classify(original, expanded));
        });
        coverage.verify();
        std::cout << "HEAD_DRAIN_ORACLE_HOST: PASS golden-and-target-checks=" << hostChecks;
        coverage.print();
        std::cout << " hardware=NOT_RUN\n";
#else
        const Mutation *mutation = nullptr;
        if (argc == 2 && std::string_view(argv[1]).substr(0, 9) == "--mutate=") {
            mutationName = argv[1] + 9;
            for (const auto &m : mutations) if (mutationName == m.name) mutation = &m;
            require(mutation != nullptr, "unknown mutation: " + mutationName);
        } else require(argc == 1, "usage: run [--list-mutations | --mutate=NAME]");

        SHeadDrainDecodeGsim d;
        corpus([&](const char *caseName, uint32_t original, uint32_t expanded) {
            const Classes expected = classify(original, expanded);
            d.set_io$$original(original);
            d.set_io$$expanded(expanded);
            d.step();
            Classes observed{{bool(d.get_io$$class0()), bool(d.get_io$$class8()),
                bool(d.get_io$$class16()), bool(d.get_io$$classCompressed())}};
            compare(observed, expected, caseName, original, expanded, coverage.vectors);
            if (mutation && !mutationFired && std::string_view(mutation->caseName) == caseName) {
                observed[mutation->output] = !observed[mutation->output];
                mutationFired = true;
                compare(observed, expected, caseName, original, expanded, coverage.vectors);
            }
            coverage.record(original, expanded, expected);
        });
        require(mutation == nullptr, "negative control did not fire: " + mutationName);
        coverage.verify();
        std::cout << "GSIM_HEAD_DRAIN_DECODE: PASS golden-and-target-checks=" << hostChecks;
        coverage.print();
        std::cout << '\n';
#endif
        return 0;
    } catch (const std::exception &error) {
#ifdef HEAD_DRAIN_ORACLE_ONLY
        std::cerr << "HEAD_DRAIN_ORACLE_HOST: FAIL ";
#else
        std::cerr << "GSIM_HEAD_DRAIN_DECODE: FAIL ";
#endif
        std::cerr << error.what() << " mutation=" << (mutationName.empty() ? "none" : mutationName)
            << " fired=" << mutationFired << '\n';
        return 1;
    }
}
