#include "MemoryProofFrontierExactRangeGsim.h"
#include "memory_proof_frontier_exact_reference.h"
#include <algorithm>
#include <deque>
#include <iostream>
#include <optional>
#include <set>
#include <tuple>
using namespace memory_proof_exact_reference;
struct RangeTables {
    uint64_t virtualBase = va, physicalBase = ram;
    uint64_t pte(uint64_t address) const {
        if (address == root + ((virtualBase >> 30) & 511) * 8) return (((root + 4096) >> 12) << 10) | 1;
        if (address == root + 4096 + ((virtualBase >> 21) & 511) * 8) return (((root + 8192) >> 12) << 10) | 1;
        if (address == root + 8192 + ((virtualBase >> 12) & 511) * 8) return ((physicalBase >> 12) << 10) | 0xc7;
        throw std::runtime_error("unexpected raw endpoint page-table address");
    }
    uint64_t physical(uint64_t address) const {
        require((address & ~4095ULL) == virtualBase, "endpoint host queried an unauthored page");
        return physicalBase + (address & 4095);
    }
    bool normalAllowed(uint64_t address, bool, unsigned size) const {
        const __uint128_t length = __uint128_t(1) << size;
        const bool canonical = (address >> 39) == (((address >> 38) & 1) ? ((1ULL << 25) - 1) : 0);
        const __uint128_t physicalBegin = physical(address), physicalEnd = physicalBegin + length;
        return size <= 3 && canonical && !(address & (uint64_t(length) - 1)) &&
            __uint128_t(address) + length <= (__uint128_t(1) << 64) &&
            physicalBegin >= ram && physicalEnd <= __uint128_t(ram) + ramBytes;
    }
};
struct Reply { uint64_t due, data; };
struct Request { uint64_t address; bool write; };
class Bench {
    SMemoryProofFrontierExactRangeGsim d;
    std::deque<Reply> ptes, physical;
    std::optional<Request> warm;
    bool allocateValid = false, consumeValid = false, selectedValid = false, accepted = false;
    Proof allocation;
    Token consume, selected;
public:
    RangeTables tables;
    uint64_t expectedWarmPa = 0;
    bool expectedAllowed = false;
    Bytes bytes;
    uint64_t cycle = 0, pending = 0, live = 0, ordinary = 0, stores = 0, eligible = 0, clear = 0;
    uint64_t canonical = 0, oldLine = ram >> 6;
    bool oldValid = false, pause = true, cancel = false, flush = false;
    unsigned head = 63, pmpCfg = 0x1f, warmResponses = 0, warmRequests = 0, walks = 0;
    unsigned admissions = 0, queries = 0, positiveReads = 0, positiveWrites = 0, maxReserved = 0;
    std::optional<uint64_t> firstAdmission, firstQuery, lastQuery, allAllowed, firstGrant;
    bool sawFrontier = false;
    Proof frontier;
    std::array<Proof, 64> expected{};
    explicit Bench() {
        drive(); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        for (unsigned i = 0; i < 5; ++i) tick();
    }
    void drive() {
        d.set_io$$head(head); d.set_io$$pending(pending); d.set_io$$memoryLive(live);
        d.set_io$$ordinary(ordinary); d.set_io$$stores(stores); d.set_io$$systems(0);
        d.set_io$$canonicalLoads(canonical); d.set_io$$canonicalStores(0);
        d.set_io$$checkedStore$$valid(0);
        d.set_io$$checkedStore$$bits$$origin$$token$$index(0);
        d.set_io$$checkedStore$$bits$$origin$$token$$tag(0);
        d.set_io$$checkedStore$$bits$$origin$$epoch(0);
        d.set_io$$checkedStore$$bits$$virtualAddress(0);
        d.set_io$$checkedStore$$bits$$physicalAddress(0);
        d.set_io$$checkedStore$$bits$$size(0); d.set_io$$checkedStore$$bits$$mask(0);
        d.set_io$$clearOwners(clear); d.set_io$$pause(pause); d.set_io$$cancelQueries(cancel);
        d.set_io$$queryEligible(eligible); d.set_io$$frontierAccepted(accepted);
        d.set_io$$allocate$$valid(allocateValid);
        d.set_io$$allocate$$bits$$token$$index(allocation.token.index);
        d.set_io$$allocate$$bits$$token$$tag(allocation.token.tag);
        d.set_io$$allocate$$bits$$address(allocation.original);
        d.set_io$$allocate$$bits$$write(allocation.write); d.set_io$$allocate$$bits$$size(allocation.size);
        d.set_io$$consume$$valid(consumeValid);
        d.set_io$$consume$$bits$$index(consume.index); d.set_io$$consume$$bits$$tag(consume.tag);
        d.set_io$$selected$$valid(selectedValid);
        d.set_io$$selected$$bits$$index(selected.index); d.set_io$$selected$$bits$$tag(selected.tag);
        d.set_io$$oldLine$$valid(oldValid); d.set_io$$oldLine$$bits$$token$$index(63);
        d.set_io$$oldLine$$bits$$token$$tag(0x8000000000000001ULL); d.set_io$$oldLine$$bits$$line(oldLine);
        d.set_io$$context$$satp(satp); d.set_io$$context$$dataPrivilege(1);
        d.set_io$$context$$sum(0); d.set_io$$context$$mxr(0);
        d.set_io$$pmpCfg(pmpCfg); d.set_io$$pmpAddress(allPmp); d.set_io$$flush(flush);
        d.set_io$$warm$$request$$valid(warm.has_value());
        d.set_io$$warm$$request$$bits$$address(warm ? warm->address : va);
        d.set_io$$warm$$request$$bits$$data(0); d.set_io$$warm$$request$$bits$$size(3);
        d.set_io$$warm$$request$$bits$$mask(255); d.set_io$$warm$$request$$bits$$write(warm && warm->write);
        d.set_io$$warm$$request$$bits$$atomic(0); d.set_io$$warm$$request$$bits$$atomicOp(0);
        d.set_io$$warm$$request$$bits$$virtualized(1); d.set_io$$warm$$request$$bits$$uncached(0);
        d.set_io$$warm$$request$$bits$$prefetchNextAllowed(0);
        d.set_io$$warm$$request$$bits$$precheckedLoad(0); d.set_io$$warm$$request$$bits$$translationEpoch(0);
        d.set_io$$warm$$response$$ready(1); d.set_io$$physical$$request$$ready(1);
        const bool pv = !physical.empty() && physical.front().due <= cycle;
        d.set_io$$physical$$response$$valid(pv);
        d.set_io$$physical$$response$$bits$$data(pv ? physical.front().data : 0);
        d.set_io$$physical$$response$$bits$$error(0); d.set_io$$physical$$response$$bits$$pageFault(0);
        const bool tv = !ptes.empty() && ptes.front().due <= cycle;
        d.set_io$$pte$$request$$ready(1); d.set_io$$pte$$response$$valid(tv);
        d.set_io$$pte$$response$$bits$$data(tv ? ptes.front().data : 0); d.set_io$$pte$$response$$bits$$error(0);
    }
    void tick() {
        const bool pv = !physical.empty() && physical.front().due <= cycle;
        const bool tv = !ptes.empty() && ptes.front().due <= cycle;
        drive(); d.step();
        if (pv && d.get_io$$physical$$response$$ready()) physical.pop_front();
        if (tv && d.get_io$$pte$$response$$ready()) ptes.pop_front();
        if (d.get_io$$pte$$request$$valid()) ptes.push_back({cycle + 2, tables.pte(d.get_io$$pte$$request$$bits())});
        if (warm && d.get_io$$warm$$request$$ready()) { warm.reset(); ++warmRequests; }
        if (d.get_io$$physical$$request$$valid()) {
            const uint64_t pa = d.get_io$$physical$$request$$bits$$address();
            require(pa == expectedWarmPa, "warm actual request differs from raw endpoint PTE mapping");
            physical.push_back({cycle + 4, bytes.read(pa, 3)});
        }
        if (d.get_io$$warm$$response$$valid()) {
            require(!d.get_io$$warm$$response$$bits$$error() && !d.get_io$$warm$$response$$bits$$pageFault(), "warm operation fault");
            ++warmResponses;
        }
        walks += d.get_io$$translationWalk();
        if (d.get_io$$queryOwner$$valid()) {
            require(pending & (1ULL << d.get_io$$queryOwner$$bits()), "query admission lacks pending host owner");
            if (!firstAdmission) firstAdmission = cycle;
            ++admissions;
        }
        if (d.get_io$$query$$valid()) {
            if (!firstQuery) firstQuery = cycle;
            lastQuery = cycle;
            const uint64_t address = d.get_io$$query$$bits$$address();
            const bool write = d.get_io$$query$$bits$$write();
            const unsigned size = d.get_io$$query$$bits$$size();
            ++queries;
            require(size == 3, "query shape diverged from host owner");
            if (d.get_io$$queryHit$$valid()) {
                // A legal translation hit outside normal RAM is expected; bank authority must still reject it.
                require(d.get_io$$queryHit$$bits$$physicalAddress() == tables.physical(address), "real query PA mismatch");
                require(d.get_io$$queryHit$$bits$$pbmt() == 0, "real query PBMT mismatch");
                write ? ++positiveWrites : ++positiveReads;
            }
        }
        require(d.get_io$$reservedCount() + d.get_io$$allowedCount() <= 16, "16 credits including reservations exceeded");
        maxReserved = std::max(maxReserved, unsigned(d.get_io$$reservedCount()));
        if (d.get_io$$allowedCount() == 16 && !allAllowed) allAllowed = cycle;
        if (d.get_io$$frontier$$valid()) {
            sawFrontier = true;
            if (!firstGrant) firstGrant = cycle;
            frontier = {{unsigned(d.get_io$$frontier$$bits$$token$$index()), uint64_t(d.get_io$$frontier$$bits$$token$$tag())},
                uint32_t(d.get_io$$frontier$$bits$$epoch()), uint64_t(d.get_io$$frontier$$bits$$payload$$address()),
                uint64_t(d.get_io$$frontier$$bits$$payload$$physicalAddress()), bool(d.get_io$$frontier$$bits$$payload$$write()),
                unsigned(d.get_io$$frontier$$bits$$payload$$size()), unsigned(d.get_io$$frontier$$bits$$payload$$mask())};
            require(expectedAllowed, "out-of-aperture or malformed query acquired actual frontier authority");
            require(frontier == expected[frontier.token.index], "frontier full tuple differs from host owner/permission model");
        }
        ++cycle;
    }
    void warmPage(uint64_t address, bool write) {
        const unsigned target = warmResponses + 1;
        expectedWarmPa = tables.physical(address);
        warm = Request{address, write};
        for (unsigned n = 0; n < 300 && warmResponses != target; ++n) tick();
        require(warmResponses == target, "real warm operation failed to complete");
        for (unsigned n = 0; n < 5; ++n) tick();
    }
    void add(unsigned index, uint64_t address, bool write) {
        allocation = {{index, (1ULL << 63) | (0x12340000ULL + index)}, uint32_t(d.get_io$$epoch()),
            address, tables.physical(address), write, 3, 255};
        expected[index] = allocation;
        allocateValid = true; clear = 1ULL << index; tick();
        allocateValid = false; clear = 0;
        pending |= 1ULL << index; live |= 1ULL << index; ordinary |= 1ULL << index;
        if (write) stores |= 1ULL << index;
        tick();
    }
    void endpoint(const std::string &name, uint64_t physicalBase, uint64_t offset, bool write,
                  bool allowed, bool highVirtual = false, bool poisonExpected = false, bool heldDenied = false) {
        tables.physicalBase = physicalBase;
        if (highVirtual) tables.virtualBase = ~4095ULL;
        // Real ordinary access installs only the exact VPN/access key, including outside-RAM pages.
        warmPage(tables.virtualBase, write);
        const unsigned beforeWalks = walks, beforeRequests = warmRequests;
        const uint64_t address = tables.virtualBase + offset;
        expectedAllowed = tables.normalAllowed(address, write, 3);
        require(expectedAllowed == allowed, "authored endpoint case disagrees with raw interval/shape model");
        add(0, address, write);
        if (poisonExpected) expected[0].physical ^= 8;
        pause = false; eligible = 1;
        for (unsigned n = 0; n < 48; ++n) {
            tick();
            // Actual admission is queryOwner.valid. Withdrawing future eligibility
            // does not clear pending/ordinary ownership or flush the admitted pipeline.
            if (!heldDenied && admissions) eligible = 0;
            if (!allowed) require(d.get_io$$allowedCount() == 0 && !d.get_io$$frontier$$valid(),
                    "denied endpoint temporarily acquired authority during query/retry");
        }
        if (heldDenied) {
            require(!allowed && admissions > 1, "held-denied control did not exercise real retries");
            std::cout << "MEMORY_PROOF_EXACT_RANGE_HELD name=" << name << " held_cycles=48 admissions=" << admissions
                      << " queries=" << queries << " reserved_at_withdrawal=" << unsigned(d.get_io$$reservedCount())
                      << " allowed_at_withdrawal=" << unsigned(d.get_io$$allowedCount()) << "\n";
            eligible = 0;
            for (unsigned n = 0; n < 12; ++n) {
                tick();
                require(d.get_io$$allowedCount() == 0 && !d.get_io$$frontier$$valid(),
                        "denied endpoint acquired authority after eligibility withdrawal");
            }
            require(queries == admissions && d.get_io$$reservedCount() == 0,
                    "held-denied admitted query credits did not fully return after withdrawal");
        } else require(queries == 1 && admissions == 1 && d.get_io$$reservedCount() == 0,
                "single-admission endpoint query did not reserve/return/drain exactly once");
        require(d.get_io$$allowedCount() == unsigned(allowed),
                "exact 2-GiB aperture proof result differs from independent interval expectation");
        if (allowed) {
            selected = expected[0].token; selectedValid = true;
            for (unsigned n = 0; n < 12 && !d.get_io$$selectedProof$$valid(); ++n) tick();
            require(d.get_io$$selectedProof$$valid(), "legal endpoint lacked actual selected proof");
            const Proof observed{{unsigned(d.get_io$$selectedProof$$bits$$token$$index()), uint64_t(d.get_io$$selectedProof$$bits$$token$$tag())},
                uint32_t(d.get_io$$selectedProof$$bits$$epoch()), uint64_t(d.get_io$$selectedProof$$bits$$payload$$address()),
                uint64_t(d.get_io$$selectedProof$$bits$$payload$$physicalAddress()), bool(d.get_io$$selectedProof$$bits$$payload$$write()),
                unsigned(d.get_io$$selectedProof$$bits$$payload$$size()), unsigned(d.get_io$$selectedProof$$bits$$payload$$mask())};
            require(observed == expected[0], "selected endpoint full tuple differs from raw owner/permission model");
        }
        // Only a pending load is a frontier candidate; a legal write remains a stored authority.
        if (!write) require(sawFrontier == allowed, "endpoint read frontier outcome differs from authority");
        require(walks == beforeWalks && warmRequests == beforeRequests,
                "endpoint speculative query initiated a forbidden walk or demand");
        require(warmRequests == warmResponses && ptes.empty() && physical.empty() && d.get_io$$idle(),
                "endpoint ordinary warm/query owners did not drain");
        std::cout << "MEMORY_PROOF_EXACT_RANGE_CASE name=" << name << " write=" << write
                  << " pa=" << tables.physical(address) << " allowed=" << allowed
                  << " query_hit=" << positiveReads + positiveWrites << " admissions=" << admissions
                  << " queries=" << queries << " final_reserved=" << unsigned(d.get_io$$reservedCount())
                  << " final_allowed=" << unsigned(d.get_io$$allowedCount()) << " status=PASS\n";
    }
};
int main(int argc, char **argv) {
    try {
        const bool poison = argc > 1 && std::string(argv[1]) == "--inject-pa";
        for (bool write : {false, true}) {
            { Bench b; b.endpoint("lower_first_word", ram, 0, write, true, false, poison); }
            { Bench b; b.endpoint("upper_last_word", ram + ramBytes - 4096, 4088, write, true); }
            { Bench b; b.endpoint("below_first_word", ram - 4096, 4088, write, false); }
            { Bench b; b.endpoint("above_first_word", ram + ramBytes, 0, write, false); }
            { Bench b; b.endpoint("cross_upper_unaligned", ram + ramBytes - 4096, 4092, write, false); }
            { Bench b; b.endpoint("virtual_overflow_unaligned", ram + ramBytes - 4096, 4092, write, false, true); }
        }
        { Bench b; b.endpoint("held_denied_then_drain", ram - 4096, 4088, false, false, false, false, true); }
        std::cout << "MEMORY_PROOF_FRONTIER_EXACT_RANGE_PASS cases=13 aperture_bytes=" << ramBytes << "\n";
        return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << "\n"; return 1; }
}
