// Focused real-cache/home gate. Reuse the independent request, resident, byte,
// MSHR-generation and saved-writeback ledgers, never a synthetic cache model.
#ifndef READ_PF_DIRTY_RETRY
#error "explicit READ_PF_DIRTY_RETRY=0|1 must match the generated model"
#endif
#if READ_PF_DIRTY_RETRY != 0 && READ_PF_DIRTY_RETRY != 1
#error "READ_PF_DIRTY_RETRY must be 0 or 1"
#endif
#define main dual_prefetch_tracking_original_main
#include "dual_prefetch_tracking.cpp"
#undef main

namespace read_prefetch_dirty_retry {
using namespace dual_prefetch;
constexpr bool enabled = READ_PF_DIRTY_RETRY != 0;
std::string negative;
bool triggered = false;

static void trigger(const char* name, uint64_t address, uint64_t detail) {
    triggered = true;
    std::cerr << "READ_PREFETCH_DIRTY_RETRY_MUTATION_TRIGGER " << name
        << " address=" << address << " witness=" << detail << '\n';
}

// Read history is independently reconstructed from accepted authored requests.
// No hidden history register or DUT-generated selector drives this oracle.
struct History {
    Gate& g;
    bool valid = false, enteredSequentially = false;
    uint64_t previous = 0;
    unsigned retries = 0;
    explicit History(Gate& gate) : g(gate) {
        const auto original = g.t.observer;
        g.t.observer = [&, original] {
            const bool accepted = g.t.cpuAccepted != g.accepted;
            const auto q = g.offered;
            if (g.flushing) { valid = false; enteredSequentially = false; }
            if (accepted && q) {
                const auto current = line(q->address);
                if (q->uncached) enteredSequentially = false;
                else if (!q->write) {
                    const bool sequential = valid && current == previous + 64 && current != 0;
                    const bool repeat = valid && current == previous && enteredSequentially;
                    if (g.t.d.get_io$$storePfObs$$candidate() &&
                        !g.t.d.get_io$$storePfObs$$candidateStore()) {
                        bool legal = sequential || (enabled && repeat);
                        if (!triggered && negative == "history" && !sequential && repeat) {
                            trigger("history", current, g.t.cpuAccepted); legal = false;
                        }
                        check(legal, "candidate lacks independent accepted sequential-entry history");
                        if (!sequential) ++retries;
                    }
                    enteredSequentially = sequential || (valid && current == previous && enteredSequentially);
                    previous = current; valid = true;
                }
            }
            original();
        };
    }
};

struct Seed {
    uint64_t target = base + 128;
    uint64_t source = target - 64;
    uint64_t previous = target - 128;
    uint64_t dirty = target + 2 * stride;
    uint64_t storeToken = target + stride;
    Token protectedToken{};
};

static Seed seed(Gate& g) {
    Seed s;
    g.permission(false);
    for (unsigned word = 0; word < 8; ++word)
        g.store(s.dirty + 8 * word, word & 1 ? 0xaa : 0x55);
    g.prepare(s.target, false);
    g.permission(true);
    g.prepare(s.storeToken, true); g.trigger(s.storeToken, true); g.settle();
    check(g.present(g.token[1]) && g.token[1]->address == s.storeToken && !g.present(g.token[0]),
        "seed lacks a real clean store-prefetch resident token");
    s.protectedToken = *g.token[1];
    check(!g.resident[s.protectedToken.index].dirty && !g.find(s.target),
        "seed target already resident or protected store token dirty");
    const auto demand = g.choose(s.target, false, false);
    const auto prefetch = g.choose(s.target, true, false);
    check(demand.allowed && demand.victim.valid && demand.victim.dirty && demand.victim.address == s.dirty &&
        demand.index != s.protectedToken.index && prefetch.allowed == enabled &&
        (!enabled || prefetch.index == demand.index),
        "seed does not force the same ordinary-demand dirty victim and preserve the clean store way");
    // Enter the source sequentially while its current authorization is denied.
    // The second denied read proves the remembered transition grants no permission.
    g.permission(false); g.send({s.source}); g.send({s.source + 8}); g.settle();
    check(!g.n("read_candidate") && !g.n("read_alloc"),
        "denied current request used historical authorization");
    return s;
}

static void drainExceptAck(Gate& g) {
    g.until([&] { return !g.offered && !g.t.cpuRequest && g.t.cpuExpected.empty() &&
        !g.active[0] && !g.active[1] && g.sources.empty() &&
        !g.t.d.get_io$$storePfObs$$pendingCandidateValid(); },
        "accepted request/refill did not retire while saved ReleaseAck was held");
    g.ticks(2);
}

struct DirtyWitness {
    Gate& g;
    const Seed& s;
    bool failedRefill;
    std::optional<unsigned> slot;
    Key saved{};
    unsigned captures = 0, beats = 0, acks = 0, refills = 0, reused = 0;
    uint64_t captureCycle = 0, lastBeatCycle = 0;
    bool protect = true, armed = true;
    DirtyWitness(Gate& gate, const Seed& selected, bool failed) : g(gate), s(selected), failedRefill(failed) {
        const auto original = g.t.observer;
        g.t.observer = [&, original] {
            auto& d = g.t.d;
            if (!armed) { original(); return; }
            // Inspect saved Ack ownership before the generic ledger retires it.
            if (slot && d.get_io$$releaseAckFire() && d.get_io$$releaseAckSource() == 2 + *slot) {
                check(g.wb[*slot] && g.wb[*slot]->key == saved && g.wb[*slot]->sent && beats == 8,
                    "dirty retry ReleaseAck lost its saved generation or full C burst");
                bool savedOrigin = g.wb[*slot]->pf;
                if (!triggered && negative == "release-owner" && enabled && reused) {
                    trigger("release-owner", s.dirty, reused); savedOrigin = false;
                }
                check(savedOrigin == enabled, "ReleaseAck inherited reused MSHR demand origin");
                ++acks;
            }
            original();
#define O(field) d.get_io$$storePfObs$$##field()
            if (protect)
                check(g.present(g.token[1]) && g.token[1]->address == s.storeToken &&
                    g.token[1]->index == s.protectedToken.index && !g.resident[s.protectedToken.index].dirty,
                    "dirty read retry lost the protected full-PA clean store token");
            if (O(wbCapture) && O(wbCaptureAddress) == s.dirty) {
                check(!slot && O(wbCaptureFromMiss) && O(wbCaptureDirty),
                    "dirty retry victim captured twice or outside a miss owner");
                slot = O(wbCaptureSlot); check(*slot < 2 && g.wb[*slot], "dirty capture has no saved owner");
                saved = g.wb[*slot]->key;
                const auto& owner = g.owners.at(saved);
                bool origin = O(wbCapturePrefetch);
                if (!triggered && negative == "lineage" && enabled) {
                    trigger("lineage", s.dirty, saved.second); origin = false;
                }
                check(origin == enabled && owner.pf == enabled && !owner.store &&
                    owner.address == s.target && owner.choice.victim.address == s.dirty &&
                    owner.choice.index != s.protectedToken.index,
                    "dirty retry changed read origin or ordinary-demand victim identity");
                ++captures; captureCycle = g.t.cycles;
            }
            if (O(cValid) && O(cReady) && O(cOpcode) == 7 && d.get_io$$releaseAddress() == s.dirty) {
                check(slot && d.get_io$$releaseSource() == 2 + *slot && beats < 8,
                    "dirty retry C changed saved source or beat count");
                uint64_t observed = O(cData);
                if (!triggered && negative == "dirty-data") {
                    trigger("dirty-data", s.dirty, beats); observed ^= 1;
                }
                check(observed == g.words(s.dirty)[beats], "dirty retry C disagrees with independent byte image");
                ++beats; lastBeatCycle = g.t.cycles;
            }
            if (O(demandAlloc) && slot && g.wb[*slot]) {
                const unsigned m = O(demandAllocSlot);
                if (m == saved.first && g.active[m] && g.active[m]->second > saved.second) {
                    check(g.wb[*slot]->key == saved && g.wb[*slot]->pf == enabled,
                        "MSHR reuse rewrote pending dirty-release owner");
                    ++reused;
                }
            }
            if (O(refill) && O(refillAddress) == s.target && O(refillPrefetch)) {
                check(enabled && bool(O(refillError)) == failedRefill,
                    "dirty retry PF refill changed error/origin classification");
                ++refills;
            }
#undef O
        };
    }
};

static void early_dirty_release(bool error) {
    Gate g; History history(g); const auto s = seed(g); DirtyWitness witness(g, s, error);
    const auto replies = g.t.cpuReturned;
    if (error) g.t.ddr.denyReadAddress = uint32_t(s.target - base);
    g.permission(true); g.hold(true, false, false, true);
    // Ordinary read masks may be zero, as in the measured CPU source stream.
    g.send({s.source + 16, false, 0, 0}, false);
    if (enabled) {
        g.until([&] { return witness.captures == 1 && g.t.d.get_io$$storePfObs$$cValid(); },
            "fresh same-line retry did not capture and offer its dirty victim");
        g.ticks(4); check(!witness.beats, "held first dirty C beat advanced");
        g.hold(false, false, false, true);
        g.until([&] { return witness.beats == 3; }, "dirty retry failed to reach third C beat");
        g.hold(true, false, false, true); g.ticks(3);
        check(witness.beats == 3, "held middle dirty C beat advanced");
        g.hold(false, false, false, true);
    } else g.hold(false, false, false, true);
    drainExceptAck(g);
    unsigned early = witness.captures;
    if (!triggered && negative == "early-expectation") {
        trigger("early-expectation", s.dirty, early); early ^= 1;
    }
    check(early == unsigned(enabled) && witness.beats == 8U * unsigned(enabled) && !witness.acks &&
        witness.refills == unsigned(enabled) && g.n("read_alloc") == unsigned(enabled) &&
        g.n("pf_error") == unsigned(enabled && error),
        "OFF/ON early dirty-writeback expectation differs");
    check(g.t.cpuReturned == replies + 1 && g.present(g.token[0]) == (enabled && !error),
        "prefetch fabricated a CPU response or installed a failed refill");
    const auto allocations = g.n("read_alloc"), candidates = g.n("read_candidate");
    // Duplicate retry is blocked by the live token or the independently held
    // ReleaseAck, including when its speculative refill failed.
    g.send({s.source + 24}); drainExceptAck(g);
    check(g.n("read_alloc") == allocations && g.n("read_candidate") == candidates,
        "duplicate retry crossed resident-token or saved-release ownership");
    g.t.ddr.denyReadAddress.reset(); g.permission(false);
    g.send({s.target}); drainExceptAck(g);
    check(g.lastHit == (enabled && !error) && g.lastMiss == (!enabled || error),
        "target demand did not distinguish early refill from OFF/failed fallback");
    // Same authored demand stream in OFF and ON. This new miss reuses the PF
    // MSHR while its distinct WB source is still awaiting ReleaseAck.
    g.send({base + 8192}); drainExceptAck(g);
    check(witness.captures == 1 && witness.beats == 8 && !witness.acks && witness.slot &&
        witness.reused && g.wb[*witness.slot] && g.wb[*witness.slot]->key == witness.saved &&
        g.t.d.get_io$$prefetchBusy() == enabled,
        "dirty release did not survive retired/reused MSHR with exact saved ownership");
    g.hold(false, false, false, false); g.settle();
    check(witness.acks == 1 && g.n("read_useful") == unsigned(enabled && !error),
        "dirty retry ReleaseAck or useful-read accounting differs");
    witness.protect = false;
    g.send({s.storeToken}); check(g.lastHit && g.n("store_useful") == 1,
        "preserved store token did not subsequently produce its independent useful hit");
    // The original release retired above; later mutation traffic may reuse its
    // WB slot legitimately and must not be mistaken for the saved episode.
    witness.armed = false;
    if (!triggered && negative == "cpu-byte") {
        // Arm only after the dirty owner/refill witness exists. The next real
        // CPU response must fail the unchanged independent architectural oracle.
        trigger("cpu-byte", s.dirty, witness.beats); injectMismatch = true;
        g.send({s.dirty});
    }
    std::cout << "READ_PREFETCH_DIRTY_RETRY_RESULT enabled=" << enabled << " error=" << error
        << " early_dirty_capture=" << unsigned(enabled) << " actual_dirty_capture=" << witness.captures
        << " dirty_c_beats=" << witness.beats << " dirty_ack=" << witness.acks
        << " retry_candidates=" << history.retries << " mshr_reuse=" << witness.reused
        << " read_useful=" << g.n("read_useful") << " store_useful=" << g.n("store_useful")
        << " capture_cycle=" << witness.captureCycle << " last_c_cycle=" << witness.lastBeatCycle
        << " same_demand_victim=1 saved_release_owner=1 no_pf_cpu_response=1\n";
    g.finish(error ? "read_retry_dirty_pf_error" : "read_retry_early_dirty_release");
}

static void cancel_retry(bool flush) {
    Gate g; History history(g); const auto s = seed(g);
    g.permission(true); g.send({s.source + 16}, false);
    check(g.n("read_candidate") == unsigned(enabled), "cancel case lacks OFF/ON accepted retry witness");
    if (flush) g.startFlush();
    else {
        // Preserve the already-authorized pending retry, but prevent this
        // sequential cancellation demand from authorizing a different target.
        g.permission(false); g.begin({s.target});
    }
    g.tick(); check(!g.n("read_alloc"), "read retry crossed actual demand/flush priority");
    if (flush) g.finishFlush();
    g.settle(); check(!g.n("read_alloc"), "canceled retry resurrected later");
    g.finish(flush ? "read_retry_pending_flush_cancel" : "read_retry_demand_priority_cancel");
}

static void blocked_offer() {
    Gate g; History history(g); const auto s = seed(g);
    g.t.blockCpu = true;
    g.send({s.source + 16}, false); g.send({s.source + 24}, false);
    check(g.t.cpuExpected.size() == 2, "backpressure seed did not fill actual response credits");
    g.permission(true); g.begin({s.source + 32});
    const auto accepted = g.t.cpuAccepted; g.ticks(5);
    check(g.t.cpuAccepted == accepted && g.offered && !g.n("read_candidate"),
        "unaccepted held retry altered read history or created speculation");
    g.t.blockCpu = false; g.settle();
    check(g.n("read_candidate") == unsigned(enabled) && g.n("read_alloc") == unsigned(enabled),
        "accepted retry after response backpressure lost its fresh permission/history");
    g.finish("read_retry_accepted_after_backpressure");
}

static void no_sequential_entry() {
    Gate g; History history(g); const auto s = seed(g);
    g.send({base + 2048}); g.send({s.source});
    g.permission(true); g.send({s.source + 16}); g.settle();
    check(!g.n("read_candidate") && !g.n("read_alloc"),
        "same-line access without sequential entry fabricated a retry");
    g.finish("read_retry_requires_sequential_entry");
}

static void page_boundary() {
    Gate g; History history(g); const uint64_t source = base + 4096 - 64;
    g.permission(false); g.store(source - 64, 0x55); g.store(source, 0xaa);
    g.send({source - 64}); g.send({source});
    g.permission(true); g.send({source + 8}); g.send({source + 16}); g.settle();
    check(!g.n("read_candidate") && !g.n("read_alloc"), "same-line retry crossed the current page boundary");
    g.finish("read_retry_current_page_boundary");
}

static void no_protected_store_token() {
    Gate g; History history(g); const uint64_t target = base + 128;
    g.permission(false); g.store(target + stride, 0x55); g.store(target + 2 * stride, 0xaa);
    g.prepare(target, false); g.send({target - 64});
    g.permission(true); g.send({target - 56}); g.settle();
    check(g.n("read_candidate") == unsigned(enabled) && !g.n("read_alloc") &&
        g.n("candidate_no_victim") == unsigned(enabled),
        "dirty retry widened eligibility without a protected clean store token");
    g.finish("read_retry_without_store_token_veto");
}

// Exercise ordinary clean ways with no valid store token, including a token
// whose old resident index has been remapped to another complete physical PA.
static void lost_store_protection(unsigned mode) {
    Gate g; History history(g); const auto s = seed(g);
    const uint64_t replacement = s.target + 3 * stride;
    if (mode == 0) g.send({s.storeToken});
    else if (mode == 1 || mode == 2) {
        g.dma({s.storeToken}); g.settle();
        if (mode == 2) {
            g.send({replacement}); g.settle();
            check(g.find(replacement) && *g.find(replacement) == s.protectedToken.index &&
                replacement != s.storeToken && set(replacement) == set(s.storeToken),
                "stale-token test did not remap identical resident index to another full PA");
        }
    }
    if (mode != 3) {
        check(!g.present(g.token[1]), "lost-protection seed retained an effective token");
        g.send({s.previous}); g.send({s.source});
    }
    g.permission(true); g.send({s.source + 16}, false);
    if (mode == 3) {
        // A useful accepted read consumes the alternate token on the candidate
        // decision edge. It may be a clean victim, but cannot authorize dirt.
        g.begin({s.storeToken}); g.tick();
    }
    g.settle();
    check(g.n("read_candidate") == unsigned(enabled) && !g.n("dirty_pf_capture") && g.find(s.dirty),
        "consumed/invalidated/remapped token authorized a dirty read victim");
    if (mode == 0 || mode == 3) check(g.n("store_useful") == 1,
        "lost-protection case lacks actual accepted useful store-token consumption");
    const char* names[] = {"read_retry_clean_way_consumed_token", "read_retry_invalidated_store_token",
        "read_retry_same_index_different_full_pa", "read_retry_simultaneous_store_token_consume"};
    g.finish(names[mode]);
}

static void flush_overlap() {
    Gate g; History history(g); const auto s = seed(g);
    g.permission(true); g.hold(false, false, true, true); g.send({s.source + 16});
    if (enabled) {
        g.until([&] { return g.t.d.get_io$$grantAckOffer(); }, "dirty retry failed to reach held GrantAck");
        check(g.n("dirty_pf_beats") == 8 && !g.n("dirty_pf_acks"),
            "flush overlap lacks completed dirty release and held Ack");
    }
    g.startFlush(); g.ticks(3);
    check(!g.t.d.get_io$$flushDone(), "flush crossed held accepted dirty ownership");
    g.hold(false, false, false, false); g.finishFlush(); g.settle();
    check(g.n("pf_refill_under_flush") == unsigned(enabled) &&
        !g.present(g.token[0]) && !g.present(g.token[1]) &&
        g.n("dirty_pf_capture") == unsigned(enabled) && g.n("dirty_pf_beats") == 8U * unsigned(enabled) &&
        g.n("dirty_pf_acks") == unsigned(enabled),
        "dirty retry flush lost exactly-once dirty release/Ack or resurrected a token");
    g.finish("read_retry_flush_accepted_refill");
}

static void probe_overlap() {
    Gate g; History history(g); const auto s = seed(g);
    unsigned overlap = 0;
    const auto original = g.t.observer;
    g.t.observer = [&, original] {
        original();
        overlap += bool(g.t.d.get_io$$probeOffer() && g.t.d.get_io$$prefetchBusy());
    };
    g.permission(true); g.hold(true, false, false, true); g.send({s.source + 16});
    if (enabled) g.until([&] { return g.t.d.get_io$$storePfObs$$cValid(); },
        "probe overlap lacks a real dirty-release C offer");
    g.t.dmaRequest = Request{s.storeToken};
    if (enabled) g.until([&] { return g.t.d.get_io$$probeOffer(); },
        "accepted dirty retry did not overlap a real probe offer");
    g.ticks(3);
    g.hold(false, false, false, false); g.settle();
    check(g.n("real_probe") >= 1 && !g.present(g.token[1]) && (!enabled || overlap),
        "real probe did not overlap accepted retry or clear its exact store token");
    check(g.n("dirty_pf_capture") == unsigned(enabled) && g.n("dirty_pf_beats") == 8U * unsigned(enabled) &&
        g.n("dirty_pf_acks") == unsigned(enabled), "probe overlap duplicated or lost dirty release/Ack");
    g.permission(false); g.send({s.dirty}); g.settle();
    g.finish("read_retry_probe_dirty_release_overlap");
}
} // namespace read_prefetch_dirty_retry

int main(int argc, char** argv) {
    using namespace dual_prefetch;
    using namespace read_prefetch_dirty_retry;
    try {
        check(split && CACHE_WAYS == 2 && !lru && PF_CANDIDATE_CYCLES == 16,
            "focused retry fixture requires split-ON two-way clean-first lifetime-sixteen model");
        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg.rfind("--images=", 0) == 0) imageDirectory = arg.substr(9);
            else if (arg.rfind("--inject-", 0) == 0) {
                check(negative.empty(), "run negative controls separately"); negative = arg.substr(9);
            } else throw std::runtime_error("unknown focused retry option: " + arg);
        }
        check(negative.empty() || negative == "history" || negative == "lineage" ||
            negative == "release-owner" || negative == "dirty-data" ||
            negative == "early-expectation" || negative == "cpu-byte", "unknown retry negative control");
        check(enabled || (negative != "history" && negative != "lineage" && negative != "release-owner"),
            "selected mutation requires an actual enabled retry event");
        early_dirty_release(false); early_dirty_release(true);
        cancel_retry(false); cancel_retry(true); blocked_offer(); no_sequential_entry();
        page_boundary(); no_protected_store_token();
        for (unsigned mode = 0; mode < 4; ++mode) lost_store_protection(mode);
        flush_overlap(); probe_overlap();
        check(negative.empty(), "requested retry mutation failed to exercise and fail its oracle");
        check(completedCases == 14, "focused retry invocation omitted an authored case");
        std::cout << "READ_PREFETCH_DIRTY_RETRY_PASS enabled=" << enabled << " cases=" << completedCases
            << " actual_cache_home=1 independent_history=1 independent_bytes=1 independent_owners=1"
            << " full_pa=1 full_flush=1 executing_cpu=0 physical_qualification=0\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "READ_PREFETCH_DIRTY_RETRY_FAIL " << error.what() << '\n'; return 1;
    }
}
