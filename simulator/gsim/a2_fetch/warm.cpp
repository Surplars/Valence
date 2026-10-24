// Reuse the unmodified byte/parcel oracle, driver, TL service law and counters.
// Only the explicit phase transition differs: normal redirect, not FENCE.I.
#define main original_supply_fixture_main
#include "../a1_fetch_supply/driver.cpp"
#undef main

// Same tick/byte/ownership checks and output fields, but a warm phase must
// observe zero walks rather than the original cold-VM scenario's required miss.
struct WarmDriver : Driver {
    using Driver::Driver;
    void runWarm() {
        bool drained = false;
        while (cycle < 20000 && !(drained = tick())) {}
        require(drained, where("bounded fixture did not finish and drain"));
        require(verified == scenario.instructions && counts.consumed == verified, where("fixed work count differs"));
        require(tlOwners.owners.empty() && tlOwners.requests == tlOwners.responses && pteAccepted == pteCompleted,
                where("external owners not drained exactly once"));
        require((faults == 1) == (scenario.pageFault || scenario.pmpFault || scenario.busFault), where("fault coverage"));
        if (scenario.redirect)
            require(redirected && virtualOwners.staleReplies > 0, where("redirect did not cover accepted old-path reply"));
        require(counts.walks == 0 && counts.pteReads == 0 && tlOwners.requests == 0,
                where("warm ROI must not acquire new external traffic"));
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

static void nextWarmPhase(Driver &d, const std::string &name) {
    require(d.dut.get_io$$quiescent() && d.virtualOwners.owners.empty() &&
        d.physicalOwners.owners.empty() && d.memory.empty() && !d.pte && !d.offeredD,
        "warm phase must drain every external obligation");
    d.dut.set_io$$pause(1); d.dut.set_io$$budget(0); d.dut.set_io$$restart(1);
    d.dut.set_io$$restartPc(d.image.virtualBase + d.scenario.start);
    d.dut.set_io$$invalidate(0); d.dut.set_io$$dValid(0); d.dut.set_io$$pteResponseValid(0);
    d.dut.step(); // Explicit cursor flush. Neither cache nor ITLB is invalidated.
    d.scenario.name = name;
    d.counts = {}; d.virtualOwners = {}; d.physicalOwners = {}; d.tlOwners = {};
    d.cycle = d.verified = d.faults = d.workCycles = d.pteAccepted = d.pteCompleted = 0;
    d.instructionHash = d.tlHash = UINT64_C(1469598103934665603);
    d.expectedPc = d.image.virtualBase + d.scenario.start;
    ++d.generation;
    d.starting = d.redirectNext = d.redirected = d.draining = false;
}

int main() { try {
    for (bool vm : {false, true}) {
        Scenario s{vm ? "warmup_sv39" : "warmup_bare", Pattern::plain32, true, vm};
        // 448B > 256B packet cache, but demand and bounded tail fit in 512B I$.
        s.instructions = 112;
        WarmDriver d(s); d.run();
        for (unsigned pass = 0; pass < 2; ++pass) {
            nextWarmPhase(d, std::string(vm ? "warm_sv39_" : "warm_bare_") + std::to_string(pass));
            d.runWarm();
            require(d.tlOwners.requests == 0 && d.pteAccepted == 0 && d.counts.walks == 0,
                "warm ROI must have zero TL Gets, walks and PTE traffic");
            require(d.virtualOwners.accepted >= 48, "warm ROI accidentally fits entirely in packet cache");
        }
    }
    std::cout << "PASS A2_WARM_SUPPLY retained real Icache/ITLB, unchanged service law and byte oracle\n";
    return 0;
} catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; } }
