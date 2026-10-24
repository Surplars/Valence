#include "A1FetchSupplyGsim.h"
#include "oracle.h"
#include <iostream>
#include <optional>
#include <sstream>
#include <tuple>
#include <vector>

using namespace a1_fetch_oracle;
using Dut = SA1FetchSupplyGsim;
static constexpr uint64_t romBase = 0x80000000ULL, ramBase = 0x80200000ULL;
static constexpr uint64_t vaBase = 0x40000000ULL, rootTable = 0x80400000ULL;
static std::string injection;

struct Scenario {
    std::string name;
    Pattern pattern = Pattern::plain32;
    bool ram = false, vm = false, stalls = false, redirect = false;
    uint64_t start = 0, instructions = 128;
    unsigned serviceLatency = 7;
    bool pageFault = false, pmpFault = false, busFault = false;
};

struct Driver {
    Dut dut;
    Scenario scenario;
    Image image;
    Counters counts;
    OrderedOwners virtualOwners, physicalOwners;
    TlOwners tlOwners;
    struct Transaction { uint64_t address, due; unsigned size, source, beat = 0; };
    std::deque<Transaction> memory;
    struct Beat { unsigned source, size; uint64_t data; bool denied; };
    std::optional<Beat> offeredD;
    struct PteReply { uint64_t address, due, data; };
    std::optional<PteReply> pte;
    using Offer = std::tuple<uint64_t, unsigned, unsigned, unsigned>;
    std::optional<Offer> heldA;
    std::optional<uint64_t> heldPte;
    uint64_t cycle = 0, generation = 0, expectedPc = 0, verified = 0, faults = 0, workCycles = 0;
    uint64_t pteAccepted = 0, pteCompleted = 0, instructionHash = UINT64_C(1469598103934665603);
    uint64_t tlHash = UINT64_C(1469598103934665603);
    bool starting = true, redirected = false, redirectNext = false, draining = false, injected = false;

    explicit Driver(Scenario s) : scenario(std::move(s)) {
        image.physicalBase = scenario.ram ? ramBase : romBase;
        image.virtualBase = scenario.vm ? vaBase : image.physicalBase;
        image.pattern = scenario.pattern;
        expectedPc = image.virtualBase + scenario.start;
        dut.set_io$$enable(0); dut.set_io$$pause(1); dut.set_io$$budget(0);
        dut.set_io$$restart(0); dut.set_io$$restartPc(expectedPc); dut.set_io$$invalidate(0);
        dut.set_io$$flushTlb(0); dut.set_io$$satp(0); dut.set_io$$privilege(3);
        dut.set_io$$pmpCfg0(0); dut.set_io$$pmpAddr0(0);
        dut.set_io$$aReady(0); dut.set_io$$dValid(0); dut.set_io$$dData(0);
        dut.set_io$$dSize(3); dut.set_io$$dSource(0); dut.set_io$$dDenied(0);
        dut.set_io$$pteReady(0); dut.set_io$$pteResponseValid(0);
        dut.set_io$$pteData(0); dut.set_io$$pteError(0);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    }
    static void hash(uint64_t &h, uint64_t value) {
        for (unsigned byte = 0; byte < 8; ++byte) { h ^= (value >> (8 * byte)) & 255; h *= UINT64_C(1099511628211); }
    }
    std::string where(const std::string &message) const {
        return scenario.name + " cycle=" + std::to_string(cycle) + " " + message;
    }
    uint64_t pteValue(uint64_t address) const {
        require((address & 7) == 0, where("unaligned PTE request"));
        const auto table = address & ~uint64_t(4095);
        const auto index = (address & 4095) / 8;
        if (table == rootTable) return index == 1 ? (((rootTable + 4096) >> 12) << 10) | 1 : 0;
        if (table == rootTable + 4096) return index == 0 ? (((rootTable + 8192) >> 12) << 10) | 1 : 0;
        require(table == rootTable + 8192, where("unexpected PTE table address"));
        if (scenario.pageFault && index == 1) return 0;
        // Sv39 level-zero leaf: V,R,X,A; no writable or user permission.
        return (((image.physicalBase >> 12) + index) << 10) | 0x4b;
    }
    unsigned parcelFault(uint64_t pc) const {
        const auto offset = pc - image.virtualBase;
        if (scenario.pageFault && (offset >> 12) == 1) return 2;
        if (scenario.pmpFault && offset >= 4096) return 1;
        if (scenario.busFault && (offset & ~uint64_t(7)) == 4096) return 1;
        return 0;
    }
    void verifyLane(unsigned lane) {
        const bool valid = lane ? dut.get_io$$lane1$$valid() : dut.get_io$$lane0$$valid();
        auto pc = lane ? dut.get_io$$lane1$$bits$$pc() : dut.get_io$$lane0$$bits$$pc();
        auto data = lane ? dut.get_io$$lane1$$bits$$instruction() : dut.get_io$$lane0$$bits$$instruction();
        const bool access = lane ? dut.get_io$$lane1$$bits$$accessFault() : dut.get_io$$lane0$$bits$$accessFault();
        const bool page = lane ? dut.get_io$$lane1$$bits$$pageFault() : dut.get_io$$lane0$$bits$$pageFault();
        auto faultAddress = lane ? dut.get_io$$lane1$$bits$$faultAddress() : dut.get_io$$lane0$$bits$$faultAddress();
        const auto next = lane ? dut.get_io$$lane1$$bits$$nextPc() : dut.get_io$$lane0$$bits$$nextPc();
        if (!injected && injection == "--inject-pc") { pc ^= 2; injected = true; }
        require(valid && pc == expectedPc, where("consumed PC duplicated, skipped, or from old path"));
        unsigned fault = parcelFault(pc);
        uint64_t expectedFault = pc;
        if (!fault && image.length(pc) == 4) { fault = parcelFault(pc + 2); expectedFault = pc + 2; }
        require(access == (fault == 1) && page == (fault == 2), where("fault class differs from parcel oracle"));
        if (fault) {
            if (!injected && injection == "--inject-tval") { faultAddress ^= 2; injected = true; }
            require(faultAddress == expectedFault, where("fault tval is not first failing required parcel"));
            ++faults;
        } else {
            if (!injected && injection == "--inject-data") { data ^= 4; injected = true; }
            require(data == image.instruction(pc), where("instruction differs from independent memory bytes"));
            require(next == pc + image.length(pc), where("sequential instruction successor"));
        }
        hash(instructionHash, pc - image.virtualBase); hash(instructionHash, fault ? 0 : data);
        hash(instructionHash, unsigned(access) | (unsigned(page) << 1));
        if (fault) hash(instructionHash, faultAddress - image.virtualBase);
        expectedPc += image.length(pc); ++verified;
    }

    bool tick() {
        const bool restart = starting || redirectNext;
        if (redirectNext) { expectedPc = image.virtualBase + 384; redirected = true; }
        if (restart) ++generation;
        const bool ready = !scenario.stalls || (cycle % 7 != 1 && cycle % 7 != 2);
        const bool pteReady = !scenario.stalls || cycle % 5 != 1;
        if (!offeredD && !memory.empty() && cycle >= memory.front().due &&
            (!scenario.stalls || cycle % 5 != 2)) {
            const auto &request = memory.front();
            const auto address = (request.address & ~uint64_t(7)) + 8 * request.beat;
            offeredD = Beat{request.source, request.size, image.beat(address),
                scenario.busFault && address == image.physicalBase + 4096};
        }
        const bool pteValid = pte && cycle >= pte->due;
        unsigned budget = draining ? 0 : unsigned(std::min(uint64_t(2), scenario.instructions - verified));
        if (scenario.stalls && cycle % 23 < 9) budget = 0;
        // The deliberate fault case consumes just the crossing instruction;
        // younger speculative faults never become architectural work here.
        dut.set_io$$enable(1); dut.set_io$$pause(draining); dut.set_io$$budget(budget);
        dut.set_io$$restart(restart); dut.set_io$$restartPc(expectedPc); dut.set_io$$invalidate(restart);
        dut.set_io$$flushTlb(0);
        dut.set_io$$satp(scenario.vm ? (UINT64_C(8) << 60) | (rootTable >> 12) : 0);
        dut.set_io$$privilege(scenario.vm || scenario.pmpFault ? 1 : 3);
        dut.set_io$$pmpCfg0(0x0f);
        dut.set_io$$pmpAddr0(scenario.pmpFault ? (image.physicalBase + 4096) >> 2 : (UINT64_C(1) << 54) - 1);
        dut.set_io$$aReady(ready);
        dut.set_io$$dValid(bool(offeredD)); dut.set_io$$dData(offeredD ? offeredD->data : 0);
        dut.set_io$$dSize(offeredD ? offeredD->size : 3);
        dut.set_io$$dSource(offeredD ? offeredD->source : 0);
        dut.set_io$$dDenied(offeredD && offeredD->denied);
        dut.set_io$$pteReady(pteReady); dut.set_io$$pteResponseValid(pteValid);
        dut.set_io$$pteData(pteValid ? pte->data : 0); dut.set_io$$pteError(0);
        dut.step();
        starting = false; redirectNext = false;

        const unsigned consumed = dut.get_io$$consumedCount();
        require(consumed <= budget && (!restart || consumed == 0), where("consumer budget/recovery violation"));
        for (unsigned lane = 0; lane < consumed; ++lane) verifyLane(lane);
        if (!draining) {
            counts.sample(dut.get_io$$rawCount(), dut.get_io$$capturedCount(), consumed,
                          dut.get_io$$occupancy(), dut.get_io$$cacheClass());
            counts.tlbHits += dut.get_io$$tlbHit(); counts.walks += dut.get_io$$walkStart();
        }

        // Old returns are accounted before a same-cycle request reuses credit.
        if (dut.get_io$$virtualResponse()) virtualOwners.response(cycle, generation);
        if (dut.get_io$$physicalResponse()) physicalOwners.response(cycle, generation);
        if (dut.get_io$$virtualRequest()) virtualOwners.request(dut.get_io$$virtualAddress(), cycle, generation);
        if (dut.get_io$$physicalRequest()) {
            const auto address = dut.get_io$$physicalAddress();
            if (scenario.pageFault || scenario.pmpFault)
                require(address < image.physicalBase + 4096, where("faulting page generated physical instruction request"));
            physicalOwners.request(address, cycle, generation);
        }
        if (offeredD && dut.get_io$$dReady()) {
            auto source = offeredD->source;
            if (!injected && injection == "--inject-source") { source ^= 7; injected = true; }
            tlOwners.response(source, offeredD->size, cycle);
            auto &request = memory.front();
            if (++request.beat == (request.size == 6 ? 8U : 1U)) memory.pop_front();
            else request.due = cycle + 1;
            offeredD.reset();
        }
        const bool aValid = dut.get_io$$aValid();
        const Offer offer{dut.get_io$$aAddress(), dut.get_io$$aSize(), dut.get_io$$aSource(), dut.get_io$$aMask()};
        require(!heldA || (aValid && *heldA == offer), where("TL A changed/withdrew under backpressure"));
        if (aValid && ready) {
            const auto [address, size, source, mask] = offer;
            require((address >= romBase && address < romBase + 128 * 1024) ||
                    (address >= ramBase && address < ramBase + (UINT64_C(2) << 30)), where("Get outside executable apertures"));
            tlOwners.request(source, address, size, mask, cycle);
            memory.push_back({address, cycle + scenario.serviceLatency, size, source, 0});
            hash(tlHash, address - image.physicalBase); hash(tlHash, size);
            if (!draining) { counts.get4 += size == 2; counts.get8 += size == 3; counts.get64 += size == 6; }
            heldA.reset();
            if (scenario.redirect && !redirected && !restart) redirectNext = true;
        } else if (aValid) heldA = offer;

        if (pteValid && dut.get_io$$pteResponseReady()) { pte.reset(); ++pteCompleted; }
        const bool readPte = dut.get_io$$pteValid();
        const uint64_t pteAddress = dut.get_io$$pteAddress();
        require(!heldPte || (readPte && *heldPte == pteAddress), where("PTE read changed/withdrew under backpressure"));
        if (readPte && pteReady) {
            require(!pte, where("second external PTE read before prior response"));
            pte = PteReply{pteAddress, cycle + 3, pteValue(pteAddress)};
            ++pteAccepted; if (!draining) ++counts.pteReads; heldPte.reset();
        } else if (readPte) heldPte = pteAddress;

        ++cycle;
        if (!draining && verified == scenario.instructions) { draining = true; workCycles = cycle; }
        return draining && dut.get_io$$quiescent() && memory.empty() && !offeredD && !pte &&
            !heldA && !heldPte && virtualOwners.owners.empty() && physicalOwners.owners.empty();
    }
    void run() {
        bool drained = false;
        while (cycle < 20000 && !(drained = tick())) {}
        require(drained, where("bounded fixture did not finish and drain"));
        require(verified == scenario.instructions && counts.consumed == verified, where("fixed work count differs"));
        require(tlOwners.owners.empty() && tlOwners.requests == tlOwners.responses && pteAccepted == pteCompleted,
                where("external owners not drained exactly once"));
        require((faults == 1) == (scenario.pageFault || scenario.pmpFault || scenario.busFault), where("fault coverage"));
        if (scenario.redirect)
            require(redirected && virtualOwners.staleReplies > 0, where("redirect did not cover accepted old-path reply"));
        if (scenario.vm) require(counts.walks > 0 && counts.pteReads > 0, where("actual ITLB/PTW miss not exercised"));
        counts.validate();
        std::cout << "A1_FETCH_SUPPLY scenario=" << scenario.name << " verified=" << verified
                  << " work_cycles=" << workCycles << " total_cycles_with_drain=" << cycle
                  << " faults=" << faults << " vrequests=" << virtualOwners.accepted
                  << " vlatency_sum=" << virtualOwners.latencySum << " vmax_inflight=" << virtualOwners.maximum
                  << " prequests=" << physicalOwners.accepted << " platency_sum=" << physicalOwners.latencySum
                  << " pmax_inflight=" << physicalOwners.maximum << " old_path_replies=" << virtualOwners.staleReplies
                  << " gets=" << tlOwners.requests << " dbeats=" << tlOwners.beats
                  << " roi_get4=" << counts.get4 << " roi_get8=" << counts.get8 << " roi_get64=" << counts.get64
                  << " tlb_hits=" << counts.tlbHits << " walks=" << counts.walks << " pte_reads=" << counts.pteReads
                  << " instruction_hash=" << instructionHash << " get_extent_hash=" << tlHash;
        for (unsigned i = 0; i < 3; ++i)
            std::cout << " raw" << i << '=' << counts.raw[i] << " captured" << i << '=' << counts.captured[i]
                      << " consumed" << i << '=' << counts.consume[i] << " cache" << i << '=' << counts.cache[i];
        for (unsigned i = 0; i < 5; ++i) std::cout << " occupancy" << i << '=' << counts.occupancy[i];
        std::cout << '\n';
    }
};

int main(int argc, char **argv) {
    try {
        if (argc == 2) injection = argv[1];
        require(argc <= 2 && (injection.empty() || injection == "--inject-pc" || injection == "--inject-data" ||
                injection == "--inject-tval" || injection == "--inject-source"), "unknown fixture argument");
        const std::vector<Scenario> scenarios = {
            {"rom32", Pattern::plain32},
            {"ram32", Pattern::plain32, true},
            {"ram_rvc_boundary", Pattern::mixed, true, false, false, false, 6, 256},
            {"ram_backpressure", Pattern::mixed, true, false, true, false, 62, 256},
            {"rom_redirect_old_reply", Pattern::mixed, false, false, true, true, 6, 128, 17},
            {"sv39_cross_page", Pattern::mixed, true, true, true, false, 4094, 128},
            {"sv39_second_parcel_fault", Pattern::mixed, true, true, false, false, 4094, 1, 7, true},
            {"pmp_second_parcel_fault", Pattern::mixed, true, false, false, false, 4094, 1, 7, false, true},
            {"rom_second_parcel_fault", Pattern::mixed, false, false, false, false, 4094, 1, 7, false, false, true}
        };
        for (auto scenario : scenarios) { Driver driver(scenario); driver.run(); }
        require(injection.empty(), "requested negative did not reach its witness");
        std::cout << "PASS A1_FETCH_SUPPLY byte-stream, precise faults, backpressure, real ITLB/PTW, old replies; not CPU IPC\n";
        return 0;
    } catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
