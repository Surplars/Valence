#pragma once

#include <array>
#include <cstdint>
#include <stdexcept>

// Independent encoding catalog for the EXISTING fetch-drain equivalence class.
// This is deliberately not an ISA legality checker. In particular, PMP reads,
// reserved nonzero CSR funct3 values, pmpcfg2 with eight entries, and FENCE.I
// words with arbitrary immediate/rs1/rd fields remain in the old broad class.
// No DUT helper, generated decoder, or production control table is included.
namespace head_drain_oracle {

enum Reason : unsigned { None = 0, Pmp = 1, Return = 2, Vm = 4, FenceI = 8 };

struct Profile {
    unsigned pmpEntries;
    bool virtualMemory;
    bool compressed;
    const char *name;
};

inline constexpr std::array<Profile, 4> profiles{{
    {0, false, false, "class0"},
    {8, true, false, "class8"},
    {16, true, false, "class16"},
    {16, true, true, "classCompressed"},
}};

// Explicit CSR address inventory; the model builds a table, not the DUT's
// interval comparison. pmpcfg0/pmpcfg2 are members whenever PMP is configured.
inline constexpr std::array<unsigned, 2> pmpConfigCsrs{{0x3a0, 0x3a2}};
inline constexpr std::array<unsigned, 16> pmpAddressCsrs{{
    0x3b0, 0x3b1, 0x3b2, 0x3b3, 0x3b4, 0x3b5, 0x3b6, 0x3b7,
    0x3b8, 0x3b9, 0x3ba, 0x3bb, 0x3bc, 0x3bd, 0x3be, 0x3bf,
}};

// Rows are raw funct3 values 0..7; columns are zero / nonzero rs1 or uimm.
// The reserved row 4 is intentional: only SATP with source zero is excluded.
inline constexpr std::array<std::array<unsigned, 2>, 8> csrFunctionCatalog{{
    {{None, None}},
    {{Pmp | Vm, Pmp | Vm}},
    {{Pmp, Pmp | Vm}},
    {{Pmp, Pmp | Vm}},
    {{Pmp, Pmp | Vm}},
    {{Pmp | Vm, Pmp | Vm}},
    {{Pmp, Pmp | Vm}},
    {{Pmp, Pmp | Vm}},
}};

struct Encoding {
    uint32_t significant;
    uint32_t value;
    unsigned reason;
    bool needsVirtualMemory;
};

inline constexpr std::array<Encoding, 4> instructionCatalog{{
    {0xffffffffU, 0x30200073U, Return, false}, // MRET, exact word
    {0xffffffffU, 0x10200073U, Return, false}, // SRET, exact word
    {0xfe007fffU, 0x12000073U, Vm, true},     // SFENCE.VMA, any rs1/rs2
    {0x0000707fU, 0x0000100fU, FenceI, false}, // broad existing FENCE.I class
}};

class Catalog {
    Profile profile_;
    std::array<unsigned, 4096> csrCatalog_{};

public:
    explicit Catalog(Profile profile) : profile_(profile) {
        if (profile.pmpEntries > pmpAddressCsrs.size())
            throw std::runtime_error("head drain oracle supports at most 16 PMP entries");
        if (profile.pmpEntries) {
            for (unsigned address : pmpConfigCsrs) csrCatalog_[address] = Pmp;
            for (unsigned i = 0; i < profile.pmpEntries; ++i)
                csrCatalog_[pmpAddressCsrs[i]] = Pmp;
        }
        if (profile.virtualMemory) csrCatalog_[0x180] = Vm;
    }

    uint32_t select(uint32_t original, uint32_t expanded) const {
        return profile_.compressed && original % 4 != 3 ? expanded : original;
    }

    unsigned reasons(uint32_t instruction) const {
        unsigned result = None;
        for (const auto &encoding : instructionCatalog) {
            if ((!encoding.needsVirtualMemory || profile_.virtualMemory) &&
                (instruction & encoding.significant) == encoding.value)
                result |= encoding.reason;
        }
        if ((instruction & 0x7fU) == 0x73U) {
            const unsigned address = instruction >> 20;
            const unsigned function = (instruction >> 12) & 7U;
            const unsigned sourceNonzero = ((instruction >> 15) & 31U) != 0;
            result |= csrCatalog_[address] & csrFunctionCatalog[function][sourceNonzero];
        }
        return result;
    }

    unsigned reasons(uint32_t original, uint32_t expanded) const {
        return reasons(select(original, expanded));
    }

    bool drain(uint32_t original, uint32_t expanded) const {
        return reasons(original, expanded) != None;
    }
};

using Classes = std::array<bool, 4>;

inline const std::array<Catalog, 4> &catalogs() {
    static const std::array<Catalog, 4> value{{
        Catalog(profiles[0]), Catalog(profiles[1]), Catalog(profiles[2]), Catalog(profiles[3]),
    }};
    return value;
}

inline Classes classify(uint32_t original, uint32_t expanded) {
    Classes result{};
    for (unsigned i = 0; i < result.size(); ++i) result[i] = catalogs()[i].drain(original, expanded);
    return result;
}

inline unsigned pack(const Classes &classes) {
    unsigned result = 0;
    for (unsigned i = 0; i < classes.size(); ++i) result |= unsigned(classes[i]) << i;
    return result;
}

} // namespace head_drain_oracle
