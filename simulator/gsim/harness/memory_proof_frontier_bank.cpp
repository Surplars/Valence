#include "MemoryProofFrontierBankGsim.h"
#include "memory_proof_frontier_reference.h"
#include <algorithm>
#include <deque>
#include <iostream>
#include <optional>
#include <set>
#include <tuple>
using namespace memory_proof_reference;
struct Reply { uint64_t due, data; };
struct Request { uint64_t address; bool write; };
class Bench {
    SMemoryProofFrontierBankGsim d;
    std::deque<Reply> ptes, physical;
    std::optional<Request> warm;
    bool allocateValid = false, consumeValid = false, selectedValid = false, accepted = false;
    Proof allocation;
    Token consume, selected;
public:
    Tables tables;
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
            require(pa >= ram && pa < ram + ramBytes, "warm actual request has unexpected physical address");
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
                require(tables.normalAllowed(address, write, size), "query hit lacks independently authored page/normal authority");
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
            require(frontier == expected[frontier.token.index], "frontier full tuple differs from host owner/permission model");
        }
        ++cycle;
    }
    void warmPage(uint64_t address, bool write) {
        const unsigned target = warmResponses + 1;
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
    void runClosure(bool injectTuple, bool transfer = true) {
        warmPage(va, false); warmPage(va + 4096, true);
        const unsigned initialWalks = walks, initialRequests = warmRequests;
        for (unsigned i = 0; i < 8; ++i) add(i, va + 4096 + 8 * i, true);
        for (unsigned i = 0; i < 7; ++i) add(i + 8, va + 8 + 8 * i, false);
        add(15, va + 64, false);
        if (injectTuple) expected[15].token.tag ^= 1ULL << 63;
        live |= 1ULL << 63; ordinary |= 1ULL << 63; canonical |= 1ULL << 63;
        oldValid = true; pause = false; eligible = 65535;
        const uint64_t first = cycle;
        for (unsigned n = 0; n < 120 && !sawFrontier; ++n) tick();
        require(sawFrontier && frontier.token.index == 15, "far candidate not reached past seven same-line loads");
        require(cycle - first <= 55, "uncontended 16-proof closure exceeded reviewed 55-cycle target");
        require(d.get_io$$allowedCount() == 16 && maxReserved > 0, "closure did not retain 16 actual credits");
        require(firstAdmission && allAllowed && *allAllowed - *firstAdmission <= 20,
                "uncontended sixteen-proof capture exceeded reviewed 20-cycle target");
        std::cout << "MEMORY_PROOF_BANK_TIMING first_admit=" << *firstAdmission << " first_query=" << *firstQuery
                  << " last_query=" << *lastQuery << " all16_allowed=" << *allAllowed << " first_grant=" << *firstGrant
                  << " proof_span=" << *allAllowed - *firstAdmission
                  << " scan_span=UNOBSERVED_NO_SCAN_START_PORT\n";
        require(positiveWrites >= 8 && positiveReads >= 8, "missing actual read/write proof queries");
        require(walks == initialWalks && warmRequests == initialRequests, "speculative query initiated a demand/walk");
        if (!transfer) return;
        consume = frontier.token; consumeValid = accepted = true; tick();
        consumeValid = accepted = false; pending &= ~(1ULL << 15); tick();
        require(d.get_io$$allowedCount() == 15 && d.get_io$$boundCount() == 15, "transfer did not atomically bind 15 older owners");
    }
    void cancellation(unsigned age) {
        warmPage(va, false);
        for (unsigned i = 0; i < 16; ++i) add(i, va + 8 * i, false);
        eligible = 65535; pause = false;
        for (unsigned i = 0; i <= age; ++i) tick();
        // GSIM exposes pre-edge state with this edge's combinational admission.
        // At age0 the real admission just fired; reservedCount still shows the old zero.
        std::cout << "MEMORY_PROOF_BANK_CANCEL_SETUP age=" << age << " cycle=" << cycle
                  << " admissions=" << admissions << " reserved_preedge=" << unsigned(d.get_io$$reservedCount())
                  << " allowed_preedge=" << unsigned(d.get_io$$allowedCount()) << "\n";
        require(admissions > 0, "cancellation did not observe a real query-admission event; age=" + std::to_string(age) +
                " cycle=" + std::to_string(cycle) + " reserved=" + std::to_string(d.get_io$$reservedCount()) +
                " allowed=" + std::to_string(d.get_io$$allowedCount()));
        cancel = true; pause = true; tick(); tick();
        require(d.get_io$$reservedCount() == 0 && d.get_io$$allowedCount() == 0,
                "pipeline cancellation leaked query credit or accepted a canceled result");
        cancel = false; tick(); pause = false;
        for (unsigned i = 0; i < 90 && d.get_io$$allowedCount() != 16; ++i) tick();
        require(d.get_io$$allowedCount() == 16 && d.get_io$$reservedCount() == 0,
                "same-row/token/epoch re-admission lost or duplicated canceled credit");
    }
    void accessKeyMiss() {
        warmPage(va, false);
        add(0, va, true); eligible = 1; pause = false;
        const unsigned oldWalks = walks, oldRequests = warmRequests;
        for (unsigned i = 0; i < 18; ++i) tick();
        require(queries > 0 && d.get_io$$allowedCount() == 0 && positiveWrites == 0,
                "read-key-only warmth created write authority");
        require(walks == oldWalks && warmRequests == oldRequests, "cold write peek started real demand/walker");
        cancel = pause = true; tick(); tick(); cancel = false;
        warmPage(va, true); pause = false;
        for (unsigned i = 0; i < 30 && d.get_io$$allowedCount() == 0; ++i) tick();
        require(d.get_io$$allowedCount() == 1 && positiveWrites > 0, "genuine write warm did not open its own key");
    }
    void pmpWriteDenied() {
        warmPage(va, true);
        pmpCfg = 0x1d; // NAPOT R/X allowed, W denied; separate from leaf RW bits.
        for (unsigned i = 0; i < 6; ++i) tick();
        add(0, va, true); eligible = 1; pause = false;
        const unsigned before = warmRequests;
        for (unsigned i = 0; i < 18; ++i) tick();
        require(queries > 0 && d.get_io$$allowedCount() == 0 && warmRequests == before,
                "physical write PMP denial escaped into retained authority");
    }
    void aliasAndUncovered(bool alias) {
        warmPage(va, false);
        if (alias) warmPage(va + 8192, true); // Distinct VPN, identical physical page.
        add(0, alias ? va + 8192 + 64 : va + 4096, true);
        add(1, va + 64, false);
        live |= 1ULL << 63; ordinary |= 1ULL << 63; canonical |= 1ULL << 63;
        oldValid = true; pause = false; eligible = alias ? 3 : 2;
        if (alias) require(!disjoint(expected[0], expected[1]), "authored alias fixture is not actually aliased");
        for (unsigned i = 0; i < 90; ++i) tick();
        require(!sawFrontier, alias ? "different-VA full physical store alias was crossed" : "older unqueried store was crossed");
        require(d.get_io$$allowedCount() == (alias ? 2U : 1U), "negative alias/missing-proof case did not reach its intended proof state");
    }
    void outsideBankOwner() {
        warmPage(va, false); warmPage(va + 4096, true);
        for (unsigned i = 0; i < 8; ++i) add(i, va + 4096 + 8 * i, true);
        for (unsigned i = 0; i < 7; ++i) add(i + 8, va + 8 + 8 * i, false);
        add(15, va + 4096 + 64, true); // Live older owner with unresolved readiness.
        add(16, va + 64, false);
        live |= 1ULL << 63; ordinary |= 1ULL << 63; canonical |= 1ULL << 63;
        oldValid = true; pause = false; eligible = 0x17fff;
        for (unsigned i = 0; i < 100; ++i) tick();
        require(d.get_io$$allowedCount() == 16 && !sawFrontier,
                "full 16-row bank covered an unproved seventeenth older owner");
    }
    void readyDependencyLoss() {
        runClosure(false, false);
        for (unsigned i = 0; i < 1025; ++i) tick();
        require(d.get_io$$frontier$$valid(), "internal READY grant did not remain available while no LSU issue slot was granted");
        sawFrontier = false;
        clear = 1; pending &= ~1ULL; ordinary &= ~1ULL; live &= ~1ULL;
        tick();
        require(!d.get_io$$frontier$$valid(), "same-edge dependency removal left stale READY VALID");
        clear = 0;
    }
    void readyLineReplacement() {
        runClosure(false, false);
        // The LSU slot stays valid while its owner/physical line is replaced.
        oldLine = (ram + 64) >> 6;
        tick();
        require(!d.get_io$$frontier$$valid(), "READY ignored valid-to-valid LSU line/set replacement");
    }
    void survivingBoundPrefix() {
        runClosure(false);
        cancel = pause = true; clear = 1ULL << 15; tick(); tick();
        require(d.get_io$$allowedCount() == 15 && d.get_io$$boundCount() == 15,
                "query/recovery cancellation discarded surviving bound prefix");
    }
    void boundEpochPoison() {
        runClosure(false);
        pause = true; flush = true;
        for (unsigned i = 0; i < 8; ++i) tick();
        require(false, "surviving-bound epoch mutation reached no production assertion");
    }
};
int main(int argc, char **argv) {
    try {
        const std::string mode = argc == 2 ? argv[1] : "";
        if (mode == "--assert-bound-epoch") { Bench b; b.boundEpochPoison(); }
        Bench b; b.runClosure(mode == "--inject-token");
        std::cout << "MEMORY_PROOF_BANK_CASE name=closure status=PASS\n";
        for (unsigned age = 0; age < 3; ++age) { Bench c; c.cancellation(age);
            std::cout << "MEMORY_PROOF_BANK_CASE name=cancel_age" << age << " status=PASS\n"; }
        { Bench c; c.accessKeyMiss(); std::cout << "MEMORY_PROOF_BANK_CASE name=access_key status=PASS\n"; }
        { Bench c; c.pmpWriteDenied(); std::cout << "MEMORY_PROOF_BANK_CASE name=pmp_write_deny status=PASS\n"; }
        { Bench c; c.readyDependencyLoss(); std::cout << "MEMORY_PROOF_BANK_CASE name=ready_1025_dependency_loss status=PASS\n"; }
        { Bench c; c.survivingBoundPrefix(); std::cout << "MEMORY_PROOF_BANK_CASE name=bound_prefix status=PASS\n"; }
        { Bench c; c.readyLineReplacement(); std::cout << "MEMORY_PROOF_BANK_CASE name=ready_line_replacement status=PASS\n"; }
        { Bench c; c.aliasAndUncovered(true); std::cout << "MEMORY_PROOF_BANK_CASE name=physical_alias status=PASS\n"; }
        { Bench c; c.aliasAndUncovered(false); std::cout << "MEMORY_PROOF_BANK_CASE name=missing_store_proof status=PASS\n"; }
        { Bench c; c.outsideBankOwner(); std::cout << "MEMORY_PROOF_BANK_CASE name=outside_bank_owner status=PASS\n"; }
        std::cout << "MEMORY_PROOF_FRONTIER_BANK_PASS queries=" << b.queries
                  << " read=" << b.positiveReads << " write=" << b.positiveWrites << " cases=12\n";
        return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << "\n"; return 1; }
}
