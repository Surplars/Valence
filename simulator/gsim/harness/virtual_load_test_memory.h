#pragma once
#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>

// RISC-V Sv39 software page tables. This oracle does not import hardware
// permission/range helpers or decode DUT-private TLB/certificate state.
namespace virtual_load_test {
constexpr uint64_t ram = 0x80010000ULL, ramBytes = 65536;
constexpr uint64_t va = 0x40000000ULL, root = 0x81000000ULL;
constexpr uint64_t satp = (8ULL << 60) | (7ULL << 44) | (root >> 12);
constexpr uint64_t allPmp = (1ULL << 54) - 1;
inline void require(bool value, const std::string &message) {
    if (!value) throw std::runtime_error(message);
}
inline uint64_t readValue(uint64_t address) {
    return 0x3a197fe20864bd55ULL ^ ((address & ~7ULL) * 0x0102040810204081ULL);
}
struct Mapping { uint64_t physical; unsigned flags = 0xc7, pbmt = 0; };
struct PageTables {
    std::map<unsigned, Mapping> pages;
    uint64_t rootAddress = root;
    PageTables() {
        pages[0] = {ram}; pages[1] = {ram + 4096}; pages[2] = {ram};
        pages[3] = {0x10000000ULL}; pages[4] = {ram + 8192, 0xc7, 1};
        pages[5] = {ram + 12288, 0xc9}; pages[6] = {ram + 16384, 0xd7};
        pages[7] = {ram + ramBytes}; pages[8] = {ram + 20480};
    }
    uint64_t pte(uint64_t address) const {
        if (address == rootAddress + 8) return (((rootAddress + 4096) >> 12) << 10) | 1;
        if (address == rootAddress + 4096) return (((rootAddress + 8192) >> 12) << 10) | 1;
        if (address >= rootAddress + 8192 && address < rootAddress + 12288 && !(address & 7)) {
            auto entry = pages.find(unsigned((address - rootAddress - 8192) / 8));
            if (entry == pages.end()) return 0;
            return ((entry->second.physical >> 12) << 10) | entry->second.flags |
                (uint64_t(entry->second.pbmt) << 61);
        }
        throw std::runtime_error("unexpected page-table read address " + std::to_string(address));
    }
    uint64_t physical(uint64_t address) const {
        auto entry = pages.find(unsigned((address - va) / 4096));
        require(entry != pages.end(), "missing expected software mapping");
        return entry->second.physical | (address & 4095);
    }
};
}
