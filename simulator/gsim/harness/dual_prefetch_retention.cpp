// Additive focused driver. Compile with the same generated real cache/home
// objects and flags as dual_prefetch_tracking.cpp. The original ten-case main
// is compiled under another name and never called by this three-case gate.
#define main dual_prefetch_tracking_original_main
#include "dual_prefetch_tracking.cpp"
#undef main

namespace dual_prefetch_retention {
using namespace dual_prefetch;
bool injectLineage = false;
bool injectExpectation = false;

struct RetentionWitness {
    Gate& g;
    uint64_t demand, target, dirtyVictim, cleanVictim;
    Token other;
    Key demandKey{};
    std::optional<unsigned> dirtySlot, cleanSlot;
    uint64_t candidateCycle = 0, captureCycle = 0, lastDirtyCycle = 0, allocationCycle = 0;
    unsigned candidates = 0, capturePending = 0, sendPending = 0, pendingDirtyBeats = 0;
    unsigned dirtyCaptures = 0, dirtyBeats = 0, dirtyAcks = 0, cleanBeats = 0, cleanAcks = 0;
    unsigned readAllocations = 0, readRefills = 0, demandRefills = 0;
    bool armed = true;

    void observe() {
        if (!armed) return;
        auto& d = g.t.d;
#define O(field) d.get_io$$storePfObs$$##field()
        check(g.present(g.token[1]) && g.token[1]->address == other.address &&
            g.token[1]->index == other.index && g.token[1]->store,
            "dirty-demand retention cleared the opposite store token");
        if (O(candidate)) {
            check(!O(candidateStore) && O(demandAlloc) &&
                line(O(demandAllocAddress)) == demand && d.get_io$$miss(),
                "retention candidate lacks the actual triggering read miss");
            check(O(wbCapture) && O(wbCaptureDirect) && O(wbCaptureFromMiss) &&
                O(wbCaptureDirty) && O(wbCaptureAddress) == dirtyVictim,
                "read candidate did not coincide with actual dirty-demand capture");
            ++candidates; candidateCycle = g.t.cycles;
        }
        if (O(wbCapture) && O(wbCaptureAddress) == dirtyVictim) {
            const unsigned slot = O(wbCaptureSlot), mshr = O(wbCaptureMshr);
            check(slot < 2 && mshr < 2 && g.active[mshr] && g.wb[slot],
                "retention dirty capture lacks actual saved ownership");
            demandKey = *g.active[mshr]; const auto& o = g.owners.at(demandKey);
            bool reportedPrefetch = O(wbCapturePrefetch);
            if (injectLineage) {
                reportedPrefetch = !reportedPrefetch;
                std::cerr << "DUAL_PREFETCH_RETENTION_MUTATION_TRIGGER demand-lineage\n";
            }
            check(!reportedPrefetch && !o.pf && !o.store && o.address == demand &&
                O(wbCaptureDirty) && g.wb[slot]->key == demandKey && !g.wb[slot]->pf,
                "dirty-demand retention WB inherited speculative lineage");
            check(!dirtySlot, "retention captured its dirty victim twice");
            dirtySlot = slot; captureCycle = g.t.cycles; ++dirtyCaptures;
        }
        if (O(pendingCandidateValid)) {
            check(!O(pendingCandidateStore) && O(pendingCandidateAddress) == target &&
                O(candidateVictimAllowed) && O(candidateVictimValid) && !O(candidateVictimDirty) &&
                O(candidateVictimAddress) == cleanVictim && O(candidateVictimIndex) != other.index,
                "retained candidate lost permission or selected its opposite-origin token");
            // The next sampled edge after direct dirty capture is the actual
            // capture stage. Later C-valid samples witness the real send stage.
            if (g.t.cycles == captureCycle + 1) {
                check(!O(cValid), "direct-capture successor unexpectedly offered C"); ++capturePending;
            }
            if (O(cValid) && O(cOpcode) == 7 && d.get_io$$releaseAddress() == dirtyVictim) {
                ++sendPending; pendingDirtyBeats += bool(O(cReady));
            }
        }
        if (O(cValid) && O(cReady) && (O(cOpcode) == 6 || O(cOpcode) == 7)) {
            const auto address = d.get_io$$releaseAddress();
            if (address == dirtyVictim) {
                check(dirtySlot && d.get_io$$releaseSource() == 2 + *dirtySlot && O(cOpcode) == 7,
                    "dirty-demand C burst changed saved source/opcode");
                ++dirtyBeats; lastDirtyCycle = g.t.cycles;
            } else if (address == cleanVictim) {
                check(O(cOpcode) == 6 && readAllocations == 1, "read PF captured a dirty or unallocated victim");
                ++cleanBeats;
            }
        }
        if (O(allocated)) {
            check(!O(allocatedStore) && O(allocatedAddress) == target && dirtySlot &&
                dirtyBeats == 8 && g.t.cycles > lastDirtyCycle && g.wb[*dirtySlot] &&
                g.wb[*dirtySlot]->sent && g.wb[*dirtySlot]->key == demandKey && !g.wb[*dirtySlot]->pf,
                "retained read PF did not allocate after full dirty C while exact demand Ack remained owned");
            allocationCycle = g.t.cycles; ++readAllocations;
        }
        if (O(wbCapture) && O(wbCaptureAddress) == cleanVictim) {
            check(O(wbCapturePrefetch) && !O(wbCaptureDirty) && readAllocations == 1,
                "retained read PF clean release lacks independent origin");
            cleanSlot = O(wbCaptureSlot);
        }
        if (d.get_io$$releaseAckFire()) {
            const unsigned source = d.get_io$$releaseAckSource();
            if (dirtySlot && source == 2 + *dirtySlot) {
                check(dirtyBeats == 8, "dirty-demand Ack preceded eight actual C beats"); ++dirtyAcks;
            } else if (cleanSlot && source == 2 + *cleanSlot) {
                check(cleanBeats == 1, "retained PF clean Ack preceded its actual C beat"); ++cleanAcks;
            }
        }
        if (O(refill)) {
            if (line(O(refillAddress)) == demand) {
                check(!O(refillPrefetch) && !O(refillError), "original dirty-demand refill changed origin/error");
                ++demandRefills;
            } else if (line(O(refillAddress)) == target) {
                check(O(refillPrefetch) && !O(refillError) && g.present(g.token[0]) &&
                    g.token[0]->address == target && !g.token[0]->store,
                    "retained read refill failed to install its distinct resident token");
                ++readRefills;
            }
        }
#undef O
    }
};

static void dirty_demand_retains_read_candidate() {
    check(split && CACHE_WAYS == 2, "focused retention requires actual split-ON/two-way model");
    constexpr bool retained = PF_CANDIDATE_CYCLES == 16;
    Gate g;
    const uint64_t target = base + 128, demand = target - 64, previous = target - 128;
    const uint64_t storeToken = target + stride, cleanVictim = target + 2 * stride;
    const uint64_t dirtyVictim = demand + stride, dirtyOther = demand + 2 * stride;

    // Real store-origin refill establishes the protected clean way zero.
    g.prepare(storeToken, true); g.trigger(storeToken, true); g.settle();
    check(g.present(g.token[1]) && g.token[1]->address == storeToken && !g.present(g.token[0]),
        "retention seed failed to establish the opposite store token");
    const Token protectedToken = *g.token[1];
    g.permission(false);
    g.send({cleanVictim});
    for (const auto address : {dirtyVictim, dirtyOther})
        for (unsigned word = 0; word < 8; ++word) g.store(address + word * 8, word & 1 ? 0xaa : 0x55);
    g.store(previous, 0x55); g.settle();
    check(!g.find(demand) && !g.find(target), "retention trigger/next line was already resident");
    const auto demandChoice = g.choose(demand, false, false);
    const auto pfChoice = g.choose(target, true, false);
    check(demandChoice.allowed && demandChoice.victim.valid && demandChoice.victim.dirty &&
        demandChoice.victim.address == dirtyVictim &&
        pfChoice.allowed && pfChoice.victim.valid && !pfChoice.victim.dirty &&
        pfChoice.victim.address == cleanVictim && pfChoice.index != protectedToken.index &&
        protectedToken.index / sets == 0,
        "authored LRU/clean-first seed did not require dirty demand and protected read-PF victim selection");
    g.permission(true); g.send({previous}); g.settle();
    check(g.n("read_candidate") == 0 && g.n("read_alloc") == 0,
        "retention seed generated an unrelated read prediction");

    RetentionWitness witness{g, demand, target, dirtyVictim, cleanVictim, protectedToken};
    const auto originalObserver = g.t.observer;
    g.t.observer = [&] { originalObserver(); witness.observe(); };
    g.hold(false, false, false, true);
    g.send({demand}, false);
    g.until([&] { return g.t.cpuExpected.empty() && !g.active[0] && !g.active[1] &&
        g.sources.empty() && !g.t.d.get_io$$storePfObs$$pendingCandidateValid(); },
        "retention case failed to retire demand/read-PF while exact ReleaseAcks were held");
    check(witness.candidates == 1 && witness.dirtyCaptures == 1 && witness.capturePending == 1 &&
        witness.candidateCycle == witness.captureCycle && witness.dirtyBeats == 8 && witness.dirtyAcks == 0 &&
        witness.demandRefills == 1 && witness.dirtySlot && g.wb[*witness.dirtySlot] &&
        g.wb[*witness.dirtySlot]->key == witness.demandKey && g.wb[*witness.dirtySlot]->sent,
        "actual retention dirty-release ownership timeline differs from authored expectation");
    if (injectExpectation)
        std::cerr << "DUAL_PREFETCH_RETENTION_MUTATION_TRIGGER retention-expectation"
            << " dirty_c_beats=" << witness.dirtyBeats << " demand_refill=" << witness.demandRefills
            << " actual_read_alloc=" << witness.readAllocations << '\n';
    check(witness.readAllocations == unsigned(retained != injectExpectation),
        "retention allocation differs from explicit lifetime expectation");
    check(witness.readRefills == unsigned(retained) && witness.cleanBeats == unsigned(retained) &&
        witness.cleanAcks == 0, "retained PF did not complete its actual clean victim/refill path");
    check(retained ? witness.sendPending >= 8 && witness.pendingDirtyBeats == 8 :
        witness.sendPending == 0 && witness.pendingDirtyBeats == 0,
        "lifetime retention was not observed across the actual eight-beat dirty send");
    check(g.present(g.token[0]) == retained && g.present(g.token[1]),
        "lifetime result lost one of its expected resident origins");
    g.hold(false, false, false, false); g.settle();
    check(witness.dirtyAcks == 1 && witness.cleanAcks == unsigned(retained),
        "retention did not discharge exact dirty-demand/PF ReleaseAck obligations");
    witness.armed = false;
    g.permission(false);
    // Consume the preserved store token first. This gives ordinary LRU the
    // clean other way for the life1 demand fallback, making authored traffic
    // and final bytes identical without imposing PF protection on demands.
    g.send({storeToken}); check(g.lastHit, "opposite store token did not survive to a useful hit");
    g.send({target}); check(g.lastHit == retained && g.lastMiss == !retained,
        "actual read-target demand did not distinguish canceled versus retained PF");
    g.settle(); check(g.n("store_useful") == 1 && g.n("read_useful") == unsigned(retained),
        "retention result lacks actual useful consumption of independent origins");
    std::cout << "DUAL_PREFETCH_RETENTION_RESULT lifetime=" << PF_CANDIDATE_CYCLES
        << " candidate_capture_same_cycle=1 capture_pending=" << witness.capturePending
        << " send_pending=" << witness.sendPending << " pending_dirty_beats=" << witness.pendingDirtyBeats
        << " dirty_c_beats=" << witness.dirtyBeats << " dirty_acks=" << witness.dirtyAcks
        << " clean_pf_beats=" << witness.cleanBeats << " clean_pf_acks=" << witness.cleanAcks
        << " read_alloc=" << witness.readAllocations << " read_refill=" << witness.readRefills
        << " read_useful=" << g.n("read_useful") << " store_useful=" << g.n("store_useful")
        << " candidate_cycle=" << witness.candidateCycle << " dirty_last_cycle=" << witness.lastDirtyCycle
        << " read_alloc_cycle=" << witness.allocationCycle << " original_dirty_owner_preserved=1\n";
    g.finish("dirty_demand_read_candidate_retention");
}
} // namespace dual_prefetch_retention

int main(int argc, char** argv) {
    using namespace dual_prefetch;
    using namespace dual_prefetch_retention;
    try {
        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--inject-mismatch") injectMismatch = true;
            else if (arg == "--inject-demand-lineage") injectLineage = true;
            else if (arg == "--inject-retention-expectation") injectExpectation = true;
            else if (arg.rfind("--images=", 0) == 0) imageDirectory = arg.substr(9);
            else throw std::runtime_error("unknown focused retention option: " + arg);
        }
        check(unsigned(injectMismatch) + unsigned(injectLineage) + unsigned(injectExpectation) <= 1,
            "run retention negative controls separately");
        dirty_demand_retains_read_candidate();
        cancel_candidate(false); cancel_candidate(true);
        check(!injectLineage && !injectExpectation, "requested retention mutation did not fail");
        std::cout << "DUAL_PREFETCH_RETENTION_PASS split=1 store_lru=" << lru
            << " lifetime=" << PF_CANDIDATE_CYCLES << " cases=" << completedCases
            << " dirty_demand_c8_ack=1 opposite_token=1 original_demand_flush_cancel=1"
            << " actual_cache_home=1 full_flush=1 executing_cpu=0 performance_qualification=0\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "DUAL_PREFETCH_RETENTION_FAIL " << error.what() << '\n'; return 1;
    }
}
