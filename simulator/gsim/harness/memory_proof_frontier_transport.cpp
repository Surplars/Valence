#include "MemoryProofFrontierTransportGsim.h"
#include "memory_proof_frontier_reference.h"
#include <deque>
#include <iostream>
#include <optional>
#include <tuple>
#ifndef MEMORY_PROOF_ENABLED
#define MEMORY_PROOF_ENABLED 0
#endif
using namespace memory_proof_reference;
struct PteReply { uint64_t due, data; };
struct Operation {
    uint64_t address = va, data = 0, expectedPa = ram;
    bool write = true, frozen = false, physicalError = false, expectedFault = false;
    unsigned mask = 255;
    Proof proof{};
};
class Bench {
    SMemoryProofFrontierTransportGsim d;
    std::deque<PteReply> ptes;
    std::optional<Operation> request, active;
    bool physicalPending = false, physicalAccepted = false;
    uint64_t physicalDue = 0, physicalData = 0;
    using Held = std::tuple<uint64_t, uint64_t, bool, uint64_t, unsigned, uint64_t, uint64_t, uint64_t, unsigned>;
    std::optional<Held> heldBuffer;
    std::optional<std::tuple<uint64_t, uint64_t, bool, unsigned>> heldPhysical;
public:
    Tables tables;
    Bytes bytes;
    uint64_t cycle = 0, holdPhysicalUntil = 0;
    unsigned requests = 0, responses = 0, physicalRequests = 0, physicalResponses = 0;
    unsigned walks = 0, checks = 0, holds = 0, pmpCfg = 0x1f;
    bool query = false, queryWrite = false, flush = false, poisonToken = false;
    uint64_t queryAddress = va;
    bool queryHit = false;
    uint64_t queryPa = 0;
    uint32_t epoch = 0;
    Bench() {
        drive(); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        for (unsigned i = 0; i < 6; ++i) tick();
    }
    void drive() {
        const Operation r = request.value_or(Operation{});
        d.set_io$$upstream$$request$$valid(request.has_value());
        d.set_io$$upstream$$request$$bits$$address(r.address);
        d.set_io$$upstream$$request$$bits$$data(r.data); d.set_io$$upstream$$request$$bits$$size(3);
        d.set_io$$upstream$$request$$bits$$mask(r.mask); d.set_io$$upstream$$request$$bits$$write(r.write);
        d.set_io$$upstream$$request$$bits$$atomic(0); d.set_io$$upstream$$request$$bits$$atomicOp(0);
        d.set_io$$upstream$$request$$bits$$virtualized(1); d.set_io$$upstream$$request$$bits$$uncached(0);
        d.set_io$$upstream$$request$$bits$$prefetchNextAllowed(0);
        d.set_io$$upstream$$request$$bits$$precheckedLoad(0); d.set_io$$upstream$$request$$bits$$translationEpoch(0);
        d.set_io$$upstream$$response$$ready(cycle % 7 != 4);
        d.set_io$$origin$$valid(request && r.write);
        d.set_io$$origin$$bits$$token$$index(r.proof.token.index);
        d.set_io$$origin$$bits$$token$$tag(r.proof.token.tag ^ (poisonToken ? 1ULL << 63 : 0));
        d.set_io$$origin$$bits$$epoch(r.proof.epoch);
        d.set_io$$frozen$$valid(request && r.frozen && MEMORY_PROOF_ENABLED);
        d.set_io$$frozen$$bits$$address(r.proof.original);
        d.set_io$$frozen$$bits$$physicalAddress(r.proof.physical);
        d.set_io$$frozen$$bits$$size(r.proof.size); d.set_io$$frozen$$bits$$mask(r.proof.mask);
        d.set_io$$physical$$request$$ready(cycle >= holdPhysicalUntil && cycle % 5 != 3);
        d.set_io$$physical$$response$$valid(physicalPending && cycle >= physicalDue);
        d.set_io$$physical$$response$$bits$$data(physicalData);
        d.set_io$$physical$$response$$bits$$error(active && active->physicalError);
        d.set_io$$physical$$response$$bits$$pageFault(0);
        const bool tv = !ptes.empty() && ptes.front().due <= cycle;
        d.set_io$$pte$$request$$ready(cycle % 3 != 2);
        d.set_io$$pte$$response$$valid(tv);
        d.set_io$$pte$$response$$bits$$data(tv ? ptes.front().data : 0);
        d.set_io$$pte$$response$$bits$$error(0);
        d.set_io$$context$$satp(satp); d.set_io$$context$$dataPrivilege(1);
        d.set_io$$context$$sum(0); d.set_io$$context$$mxr(0);
        d.set_io$$pmpCfg(pmpCfg); d.set_io$$pmpAddress(allPmp); d.set_io$$flush(flush);
        d.set_io$$query$$valid(query); d.set_io$$query$$bits$$address(queryAddress);
        d.set_io$$query$$bits$$write(queryWrite); d.set_io$$query$$bits$$size(3);
    }
    void tick() {
        const bool tv = !ptes.empty() && ptes.front().due <= cycle;
        const bool pv = physicalPending && cycle >= physicalDue;
        drive(); d.step();
        epoch = d.get_io$$epoch();
        if (tv && d.get_io$$pte$$response$$ready()) ptes.pop_front();
        if (d.get_io$$pte$$request$$valid() && cycle % 3 != 2)
            ptes.push_back({cycle + 2, tables.pte(d.get_io$$pte$$request$$bits())});
        walks += d.get_io$$translationWalk();
        queryHit = query && d.get_io$$queryHit$$valid();
        if (queryHit) queryPa = d.get_io$$queryHit$$bits$$physicalAddress();
        if (request && d.get_io$$upstream$$request$$ready()) { request.reset(); ++requests; }
        const bool bv = d.get_io$$bufferRequest$$valid();
        if (bv) {
        const bool originValid = d.get_io$$bufferOrigin$$valid();
        const bool frozenValid = d.get_io$$bufferFrozen$$valid();
        const Held now{d.get_io$$bufferRequest$$bits$$address(), d.get_io$$bufferRequest$$bits$$data(),
            bool(d.get_io$$bufferRequest$$bits$$virtualized()), originValid ? uint64_t(d.get_io$$bufferOrigin$$bits$$epoch()) : 0,
            originValid ? unsigned(d.get_io$$bufferOrigin$$bits$$token$$index()) : 0, originValid ? uint64_t(d.get_io$$bufferOrigin$$bits$$token$$tag()) : 0,
            frozenValid ? uint64_t(d.get_io$$bufferFrozen$$bits$$address()) : 0, frozenValid ? uint64_t(d.get_io$$bufferFrozen$$bits$$physicalAddress()) : 0,
            frozenValid ? unsigned(d.get_io$$bufferFrozen$$bits$$mask()) : 0};
        if (heldBuffer) require(bv && now == *heldBuffer, "held buffer request/frozen sideband changed");
        heldBuffer = bv && !d.get_io$$bufferFire() ? std::optional{now} : std::nullopt;
        } else { require(!heldBuffer, "held buffer VALID withdrawn"); }
        if (bv && active) {
            require(d.get_io$$bufferRequest$$bits$$virtualized() && !d.get_io$$bufferRequest$$bits$$precheckedLoad(),
                    "frozen store lost original virtual request class");
            require(d.get_io$$bufferRequest$$bits$$address() == active->address, "original VA changed at StoreBuffer");
            if (active->write) {
                require(d.get_io$$bufferOrigin$$valid() &&
                        d.get_io$$bufferOrigin$$bits$$token$$tag() == active->proof.token.tag &&
                        d.get_io$$bufferOrigin$$bits$$token$$index() == active->proof.token.index,
                        "independent full-token origin pairing mismatch");
            }
            require(bool(d.get_io$$bufferFrozen$$valid()) == (active->frozen && MEMORY_PROOF_ENABLED),
                    "frozen validity did not follow actual request");
        }
        if (d.get_io$$checked$$valid()) {
            require(active && active->write && !active->expectedFault, "unexpected checked store certificate");
            require(d.get_io$$checked$$bits$$physicalAddress() == active->expectedPa &&
                    d.get_io$$checked$$bits$$virtualAddress() == active->address &&
                    d.get_io$$checked$$bits$$origin$$token$$tag() == active->proof.token.tag &&
                    d.get_io$$checked$$bits$$origin$$token$$index() == active->proof.token.index,
                    "checked certificate differs from independent actual owner/PA");
            ++checks;
        }
        const bool valid = d.get_io$$physical$$request$$valid();
        if (valid) {
        const auto payload = std::make_tuple(uint64_t(d.get_io$$physical$$request$$bits$$address()),
            uint64_t(d.get_io$$physical$$request$$bits$$data()), bool(d.get_io$$physical$$request$$bits$$write()),
            unsigned(d.get_io$$physical$$request$$bits$$mask()));
        if (heldPhysical) require(valid && payload == *heldPhysical, "held physical request changed");
        const bool ready = cycle >= holdPhysicalUntil && cycle % 5 != 3;
        heldPhysical = valid && !ready ? std::optional{payload} : std::nullopt;
        holds += valid && !ready;
        if (valid && ready) {
            require(active && !active->expectedFault && !physicalAccepted, "duplicate/denied physical request");
            require(std::get<0>(payload) == active->expectedPa && std::get<2>(payload) == active->write &&
                    std::get<3>(payload) == active->mask && (!active->write || std::get<1>(payload) == active->data),
                    "actual physical bytes differ from independent frozen expectation");
            require(!d.get_io$$physical$$request$$bits$$virtualized() && !d.get_io$$physical$$request$$bits$$precheckedLoad(),
                    "private metadata escaped physical boundary");
            physicalAccepted = physicalPending = true;
            physicalDue = cycle + 19;
            physicalData = bytes.read(active->expectedPa, 3);
            ++physicalRequests;
        }
        } else { require(!heldPhysical, "held physical VALID withdrawn"); }
        if (pv && d.get_io$$physical$$response$$ready()) {
            require(active && physicalPending, "response owner lost");
            if (active->write && !active->physicalError) bytes.write(active->expectedPa, active->data, 3);
            physicalPending = false;
            ++physicalResponses;
        }
        if (d.get_io$$upstream$$response$$valid()) {
            require(active.has_value(), "duplicate or ownerless upstream response");
            require(active->expectedFault || (physicalAccepted && cycle >= physicalDue), "early local ACK before real response");
            require(bool(d.get_io$$upstream$$response$$bits$$error()) == (active->expectedFault || active->physicalError),
                    "precise response error mismatch");
            if (!active->write && !active->expectedFault && !active->physicalError)
                require(d.get_io$$upstream$$response$$bits$$data() == bytes.read(active->expectedPa, 3), "loaded data differs from golden bytes");
            if (cycle % 7 != 4) { ++responses; active.reset(); }
        }
        ++cycle;
    }
    void run(Operation op) {
        require(!active && !request && !physicalPending, "host attempted overlapping serial store fixture");
        active = request = op;
        physicalAccepted = false;
        const unsigned target = responses + 1;
        for (unsigned i = 0; i < 700 && responses < target; ++i) tick();
        require(responses == target, "operation failed to receive its real response");
        for (unsigned i = 0; i < 4; ++i) tick();
    }
    Operation ordinary(uint64_t address, bool write = true, uint64_t data = 0xA5) {
        Operation op; op.address = address; op.write = write; op.data = data;
        op.expectedPa = tables.physical(address);
        op.proof = {{unsigned(requests % 64), 0x8000000000000000ULL + requests + 1}, epoch,
            address, op.expectedPa, write, 3, 255};
        return op;
    }
    void test(bool injectToken, bool assertMask, bool assertEpoch) {
        // A genuine READ fills only the read key. A write peek must still miss.
        run(ordinary(va, false));
        query = true; queryWrite = true; tick();
        require(!queryHit, "read-key hit incorrectly authorized write query");
        query = false; run(ordinary(va));
        query = true; tick();
        require(queryHit && queryPa == ram, "genuine warm write proof missing");
        query = false;
        Operation frozen = ordinary(va, true, 0x8877665544332211ULL);
        frozen.frozen = true;
        const uint32_t savedEpoch = epoch;
        // Evict the write key with genuine ordinary translations. Same context,
        // different cached PTE availability is a controlled fixture, not SFENCE.
        for (unsigned i = 0; i < 17; ++i) {
            const unsigned page = 16 + i;
            tables.pages[page] = {ram + (i % 16) * 4096};
            run(ordinary(va + uint64_t(page) * 4096));
        }
        tables.pages[0].physical = ram + 4096;
        run(ordinary(va));
        require(epoch == savedEpoch, "fixture unexpectedly changed context epoch");
        frozen.expectedPa = MEMORY_PROOF_ENABLED ? ram : ram + 4096;
        const unsigned beforeWalks = walks;
        holdPhysicalUntil = cycle + 25;
        poisonToken = injectToken;
        if (assertMask) frozen.proof.mask ^= 1;
        if (assertEpoch) ++frozen.proof.epoch;
        run(frozen);
        require(walks == beforeWalks, "frozen or warm fallback operation unexpectedly walked");
        require(bytes.read(frozen.expectedPa, 3) == frozen.data, "accepted store bytes missing");
        require(holds > 0, "physical held boundary was not exercised");
        frozen.proof.token.tag += 100;
        frozen.physicalError = true;
        frozen.data ^= 0xFFFF;
        const uint64_t unchanged = bytes.read(frozen.expectedPa, 3);
        run(frozen);
        require(bytes.read(frozen.expectedPa, 3) == unchanged, "late store error altered memory bytes");
        require(requests == responses && physicalRequests == physicalResponses, "request/response counts failed to drain");
    }
};
int main(int argc, char **argv) {
    try {
        const std::string mode = argc > 1 ? argv[1] : "";
        Bench b; b.test(mode == "--inject-token", mode == "--assert-mask", mode == "--assert-epoch");
        std::cout << "MEMORY_PROOF_FRONTIER_TRANSPORT_PASS enabled=" << MEMORY_PROOF_ENABLED
                  << " requests=" << b.requests << " checked=" << b.checks << " holds=" << b.holds << "\n";
        return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << "\n"; return 1; }
}
