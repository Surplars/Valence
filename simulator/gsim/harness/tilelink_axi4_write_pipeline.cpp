// Independent traffic/byte scoreboard: no DUT-internal ownership is inspected.
#define main mixed_regression_main
#include "tilelink_axi4_mixed.cpp"
#undef main

static bool injectWriteMismatch = false;
static bool requireAwLead = false;

// Constant AW-to-W service latency models address preparation in a pipelined
// subordinate. Both revisions receive the same transactions and service law.
static void writePipeline(STileLinkAxi4Bridge& d, unsigned beats, unsigned prepare,
                          bool stress, bool mixed, bool resetFirst = true) {
    if (resetFirst) reset(d);
    constexpr unsigned count = 128;
    struct Owner { unsigned n, id, beat, due; };
    std::deque<Owner> aw, replies;
    std::vector<Owner> reads;
    std::optional<unsigned> heldRead, heldReply;
    std::array<bool, 8> sourceLive{};
    std::array<bool, count> accepted{}, completed{}, addressed{};
    std::array<unsigned, count> acceptedAt{}, firstAwAt{}, dBeat{};
    unsigned sent = 0, aBeat = 0, done = 0, wBeats = 0, rBeats = 0, dBeats = 0;
    unsigned cycle = 0, maxAwPending = 0, awAheadOfW = 0, overlapCycles = 0;
    unsigned writeStart = 0, writeFinish = 0, activePeak = 0, aStalls = 0, totalLatency = 0, maxLatency = 0;
    unsigned expectedWrites = 0, expectedReads = 0;
    std::optional<unsigned> dOwner;
    std::optional<std::tuple<uint64_t, unsigned, unsigned>> stalledAw, stalledAr;
    std::optional<std::tuple<uint64_t, unsigned, bool>> stalledW;
    std::optional<std::tuple<uint64_t, unsigned, unsigned, bool>> stalledD;
    auto isWrite = [&](unsigned n) { return !mixed || n % 4 < 2; };
    auto address = [&](unsigned n) { return uint64_t(n) * 256; };
    auto readValue = [&](unsigned n, unsigned b) { return initial(address(n) + b * 8); };
    auto dataValue = [&](unsigned n, unsigned b) { return payload(n, b); };
    auto byteMask = [&](unsigned n, unsigned b) { return stress ? mask(n, b) : 255U; };
    for (unsigned n = 0; n < count; ++n) (isWrite(n) ? expectedWrites : expectedReads)++;
    for (; cycle < 200000 && done < count; ++cycle) {
        const unsigned n = std::min(sent, count - 1), src = n % 8;
        const bool av = sent < count && (!sourceLive[src] || aBeat > 0);
        const bool awr = !stress || cycle % 13 < 8;
        const bool arr = !stress || cycle % 11 < 7;
        const bool wr = !aw.empty() && cycle >= aw.front().due && (!stress || cycle % 7 < 4);
        const bool dr = !stress || cycle % 17 < 11;
        if (!heldRead) for (auto it = reads.rbegin(); it != reads.rend(); ++it)
            if (cycle >= it->due) { heldRead = it->id; break; }
        auto rp = std::find_if(reads.begin(), reads.end(), [&](auto& r) { return heldRead && r.id == *heldRead; });
        const bool rv = rp != reads.end();
        const auto offeredRead = rv ? *rp : Owner{};
        if (!heldReply) for (auto it = replies.rbegin(); it != replies.rend(); ++it)
            if (cycle >= it->due) { heldReply = it->id; break; }
        auto bp = std::find_if(replies.begin(), replies.end(), [&](auto& b) { return heldReply && b.id == *heldReply; });
        const bool bv = bp != replies.end();
        const unsigned bId = bv ? bp->id : 0;
        d.set_io$$tl$$a$$valid(av); d.set_io$$tl$$a$$bits$$opcode(isWrite(n) ? 1 : 4);
        d.set_io$$tl$$a$$bits$$param(0); d.set_io$$tl$$a$$bits$$size(size(beats));
        d.set_io$$tl$$a$$bits$$source(src); d.set_io$$tl$$a$$bits$$address(base + address(n));
        d.set_io$$tl$$a$$bits$$mask(isWrite(n) ? byteMask(n, aBeat) : 255);
        d.set_io$$tl$$a$$bits$$data(dataValue(n, aBeat)); d.set_io$$tl$$a$$bits$$corrupt(0);
        d.set_io$$tl$$d$$ready(dr); d.set_io$$axi$$aw$$ready(awr); d.set_io$$axi$$w$$ready(wr);
        d.set_io$$axi$$ar$$ready(arr); d.set_io$$axi$$b$$valid(bv); d.set_io$$axi$$b$$bits$$id(bId);
        d.set_io$$axi$$b$$bits$$resp(0); d.set_io$$axi$$r$$valid(rv);
        d.set_io$$axi$$r$$bits$$id(rv ? offeredRead.id : 0);
        d.set_io$$axi$$r$$bits$$data(rv ? readValue(offeredRead.n, offeredRead.beat) : 0);
        d.set_io$$axi$$r$$bits$$resp(0); d.set_io$$axi$$r$$bits$$last(rv && offeredRead.beat + 1 == beats);
        d.step();
        const bool awv = d.get_io$$axi$$aw$$valid(), arv = d.get_io$$axi$$ar$$valid();
        const bool wv = d.get_io$$axi$$w$$valid(), dv = d.get_io$$tl$$d$$valid();
        auto awBits = std::tuple{uint64_t(d.get_io$$axi$$aw$$bits$$addr()), unsigned(d.get_io$$axi$$aw$$bits$$id()), unsigned(d.get_io$$axi$$aw$$bits$$len())};
        auto arBits = std::tuple{uint64_t(d.get_io$$axi$$ar$$bits$$addr()), unsigned(d.get_io$$axi$$ar$$bits$$id()), unsigned(d.get_io$$axi$$ar$$bits$$len())};
        auto wBits = std::tuple{uint64_t(d.get_io$$axi$$w$$bits$$data()), unsigned(d.get_io$$axi$$w$$bits$$strb()), bool(d.get_io$$axi$$w$$bits$$last())};
        auto dBits = std::tuple{uint64_t(d.get_io$$tl$$d$$bits$$data()), unsigned(d.get_io$$tl$$d$$bits$$source()), unsigned(d.get_io$$tl$$d$$bits$$opcode()), bool(d.get_io$$tl$$d$$bits$$denied())};
        if (stalledAw) check(awv && awBits == *stalledAw, "pipeline stalled AW changed");
        if (stalledAr) check(arv && arBits == *stalledAr, "pipeline stalled AR changed");
        if (stalledW) check(wv && wBits == *stalledW, "pipeline stalled W changed");
        if (stalledD) check(dv && dBits == *stalledD, "pipeline stalled D changed");
        stalledAw = awv && !awr ? std::optional{awBits} : std::nullopt;
        stalledAr = arv && !arr ? std::optional{arBits} : std::nullopt;
        stalledW = wv && !wr ? std::optional{wBits} : std::nullopt;
        stalledD = dv && !dr ? std::optional{dBits} : std::nullopt;
        if (av && d.get_io$$tl$$a$$ready()) {
            if (!aBeat) { check(!sourceLive[src], "pipeline source reused"); sourceLive[src] = true; accepted[n] = true; acceptedAt[n] = cycle; }
            if (!isWrite(n) || ++aBeat == beats) { ++sent; aBeat = 0; }
        } else if (av) ++aStalls;
        // Process W using the AW owners that existed at the beginning of this
        // cycle: WREADY was computed before this cycle's new AW acceptance.
        if (wv && wr) {
            check(!aw.empty(), "pipeline W has no AW owner"); auto& q = aw.front();
            check(std::get<0>(wBits) == (dataValue(q.n, q.beat) ^ (injectWriteMismatch ? 1ULL : 0ULL)) &&
                std::get<1>(wBits) == byteMask(q.n, q.beat) && std::get<2>(wBits) == (q.beat + 1 == beats),
                "pipeline independent W pairing/data mismatch");
            if (!wBeats) writeStart = cycle; ++wBeats; writeFinish = cycle;
            if (++q.beat == beats) { auto b = q; b.due = cycle + 3 + (stress && q.n % 2 ? 17 : 0); replies.push_back(b); aw.pop_front(); }
        }
        auto captureAddress = [&](auto bits, bool write) {
            const uint64_t offset = std::get<0>(bits); const unsigned owner = offset / 256, id = std::get<1>(bits);
            check(offset % 256 == 0 && owner < count && accepted[owner] && !addressed[owner] && isWrite(owner) == write &&
                std::get<2>(bits) + 1 == beats && id < 4, "pipeline AXI address ownership mismatch");
            for (auto& q : aw) check(q.id != id, "pipeline duplicate live AW ID");
            for (auto& q : replies) check(q.id != id, "pipeline duplicate B-pending ID");
            for (auto& q : reads) check(q.id != id, "pipeline duplicate R-pending ID");
            addressed[owner] = true;
            if (write) { awAheadOfW += !aw.empty(); aw.push_back({owner, id, 0, cycle + prepare}); firstAwAt[owner] = cycle; }
            else reads.push_back({owner, id, 0, cycle + 12 + (stress && owner % 3 == 0 ? 19 : 0)});
        };
        if (awv && awr) captureAddress(awBits, true);
        if (arv && arr) captureAddress(arBits, false);
        if (rv && d.get_io$$axi$$r$$ready()) {
            auto q = std::find_if(reads.begin(), reads.end(), [&](auto& r) { return r.id == offeredRead.id; });
            check(q != reads.end(), "pipeline R owner vanished"); if (++q->beat == beats) reads.erase(q); heldRead.reset(); ++rBeats;
        }
        if (bv && d.get_io$$axi$$b$$ready()) {
            auto q = std::find_if(replies.begin(), replies.end(), [&](auto& b) { return b.id == bId; });
            check(q != replies.end(), "pipeline B owner vanished"); replies.erase(q); heldReply.reset();
        }
        maxAwPending = std::max(maxAwPending, unsigned(aw.size()));
        overlapCycles += !reads.empty() && (!aw.empty() || !replies.empty());
        activePeak = std::max(activePeak, unsigned(std::count(sourceLive.begin(), sourceLive.end(), true)));
        if (dv && dr) {
            const unsigned source = std::get<1>(dBits);
            unsigned owner = count;
            for (unsigned k = 0; k < count; ++k) if (accepted[k] && !completed[k] && k % 8 == source) { check(owner == count, "pipeline duplicate TL source"); owner = k; }
            check(owner < count && sourceLive[source], "pipeline D has no live owner");
            if (dOwner) check(*dOwner == owner, "pipeline D interleaved"); else dOwner = owner;
            check(!std::get<3>(dBits) && !d.get_io$$tl$$d$$bits$$corrupt() && d.get_io$$tl$$d$$bits$$size() == size(beats) &&
                std::get<2>(dBits) == (isWrite(owner) ? 0 : 1) &&
                std::get<0>(dBits) == (isWrite(owner) ? 0 : readValue(owner, dBeat[owner])), "pipeline independent TL D oracle mismatch");
            ++dBeat[owner]; ++dBeats;
            if (isWrite(owner) || dBeat[owner] == beats) {
                completed[owner] = true; sourceLive[source] = false; dOwner.reset(); ++done;
                const unsigned latency = cycle - acceptedAt[owner] + 1; totalLatency += latency; maxLatency = std::max(maxLatency, latency);
            }
        }
    }
    check(done == count && sent == count && wBeats == expectedWrites * beats && rBeats == expectedReads * beats &&
        dBeats == expectedWrites + expectedReads * beats && aw.empty() && replies.empty() && reads.empty(), "pipeline lost/duplicated transaction or starvation");
    if (requireAwLead && beats == 8 && prepare == 12 && !stress)
        check(maxAwPending >= 2 && awAheadOfW > 0, "independent AW pipeline did not advance ahead of W");
    std::cout << "WRITE_PIPELINE_PASS beats=" << beats << " prepare=" << prepare << " stress=" << stress << " mixed=" << mixed
        << " cycles=" << cycle << " transactions=" << done << " wbeats=" << wBeats << " rbeats=" << rBeats
        << " active_peak=" << activePeak << " aw_pending_peak=" << maxAwPending << " aw_ahead_of_w=" << awAheadOfW
        << " rw_overlap_cycles=" << overlapCycles << " a_stalls=" << aStalls << " max_latency=" << maxLatency
        << " latency_sum=" << totalLatency << " useful_beats_per_cycle=" << double(wBeats + rBeats) / cycle
        << " w_window_beats_per_cycle=" << double(wBeats) / (writeFinish - writeStart + 1) << "\n";
}

static void deniedTail(STileLinkAxi4Bridge& d) {
    reset(d);
    unsigned a = 0, w = 0, aw = 0, b = 0, replies = 0, id = 0, ar = 0, readId = 0, r = 0;
    bool readBypassed = false;
    std::array<bool, 3> reply{};
    // The denied younger write must keep both tokens alive behind stalled W.
    // An unrelated completed read must still bypass it in unordered mode.
    for (unsigned c = 0; c < 300 && replies < 3; ++c) {
        const bool bv = aw && w == 2 && !b, rv = ar && !r && c >= 20;
        d.set_io$$tl$$a$$valid(a < 5); d.set_io$$tl$$a$$bits$$opcode(a < 4 ? 1 : 4); d.set_io$$tl$$a$$bits$$param(0);
        d.set_io$$tl$$a$$bits$$size(a < 4 ? 4 : 3); d.set_io$$tl$$a$$bits$$source(a < 4 ? a / 2 : 2);
        d.set_io$$tl$$a$$bits$$address(a < 2 ? base : a < 4 ? base + window : base + 0x1000);
        d.set_io$$tl$$a$$bits$$mask(255); d.set_io$$tl$$a$$bits$$data(payload(a / 2, a % 2));
        d.set_io$$tl$$a$$bits$$corrupt(0); d.set_io$$tl$$d$$ready(1);
        d.set_io$$axi$$aw$$ready(1); d.set_io$$axi$$w$$ready(c >= 100); d.set_io$$axi$$ar$$ready(1);
        d.set_io$$axi$$r$$valid(rv); d.set_io$$axi$$r$$bits$$id(readId);
        d.set_io$$axi$$r$$bits$$data(initial(0x1000)); d.set_io$$axi$$r$$bits$$last(1); d.set_io$$axi$$r$$bits$$resp(0);
        d.set_io$$axi$$b$$valid(bv); d.set_io$$axi$$b$$bits$$id(id); d.set_io$$axi$$b$$bits$$resp(0); d.step();
        if (a < 5 && d.get_io$$tl$$a$$ready()) ++a;
        if (d.get_io$$axi$$aw$$valid()) { check(!aw && d.get_io$$axi$$aw$$bits$$addr() == 0, "denied tail emitted AW"); ++aw; id = d.get_io$$axi$$aw$$bits$$id(); }
        if (d.get_io$$axi$$ar$$valid()) { check(!ar && d.get_io$$axi$$ar$$bits$$addr() == 0x1000, "denied tail AR mismatch"); ++ar; readId = d.get_io$$axi$$ar$$bits$$id(); }
        if (d.get_io$$axi$$w$$valid() && c >= 100) {
            check(w < 2 && d.get_io$$axi$$w$$bits$$data() == payload(0, w), "denied tail emitted/mispaired W"); ++w;
        }
        if (bv && d.get_io$$axi$$b$$ready()) ++b;
        if (rv && d.get_io$$axi$$r$$ready()) ++r;
        if (d.get_io$$tl$$d$$valid()) {
            const unsigned src = d.get_io$$tl$$d$$bits$$source();
            check(src < 3 && !reply[src] && d.get_io$$tl$$d$$bits$$denied() == (src == 1), "denied tail D ownership mismatch");
            if (src == 2) {
                check(d.get_io$$tl$$d$$bits$$data() == initial(0x1000), "denied tail read data mismatch");
                readBypassed = c < 100;
            }
            reply[src] = true; ++replies;
        }
    }
    check(a == 5 && w == 2 && aw == 1 && b == 1 && ar == 1 && r == 1 && replies == 3 && readBypassed,
        "denied tail failed drain or blocked unrelated read");
    // No reset here: immediately reuse sources/slots to expose stale tokens.
    writePipeline(d, 2, 4, true, true, false);
    std::cout << "DENIED_WRITE_TAIL_RECOVERY_PASS read_bypassed=1 source_reused_without_reset=1\n";
}
static void resetSkew(STileLinkAxi4Bridge& d, bool addressesFirst) {
    reset(d);
    unsigned a = 0, aw = 0, w = 0;
    for (unsigned c = 0; c < 100; ++c) {
        d.set_io$$tl$$a$$valid(a < 4); d.set_io$$tl$$a$$bits$$opcode(1); d.set_io$$tl$$a$$bits$$param(0);
        d.set_io$$tl$$a$$bits$$size(4); d.set_io$$tl$$a$$bits$$source(a / 2);
        d.set_io$$tl$$a$$bits$$address(base + (a / 2) * 128);
        d.set_io$$tl$$a$$bits$$mask(255); d.set_io$$tl$$a$$bits$$data(payload(a / 2, a % 2));
        d.set_io$$tl$$a$$bits$$corrupt(0); d.set_io$$tl$$d$$ready(1);
        d.set_io$$axi$$aw$$ready(addressesFirst); d.set_io$$axi$$w$$ready(!addressesFirst);
        d.set_io$$axi$$ar$$ready(1); d.set_io$$axi$$r$$valid(0); d.set_io$$axi$$b$$valid(0); d.step();
        if (a < 4 && d.get_io$$tl$$a$$ready()) ++a;
        if (d.get_io$$axi$$aw$$valid() && addressesFirst) { check(aw < 2 && d.get_io$$axi$$aw$$bits$$addr() == aw * 128, "skew AW mismatch"); ++aw; }
        if (d.get_io$$axi$$w$$valid() && !addressesFirst) {
            check(w < 4 && d.get_io$$axi$$w$$bits$$data() == payload(w / 2, w % 2), "skew W mismatch"); ++w;
        }
        check(!d.get_io$$tl$$d$$valid(), "skew write retired without B");
        if ((addressesFirst && aw == 2) || (!addressesFirst && w == 4)) {
            check(a == 4 && (addressesFirst ? w == 0 : aw == 0), "skew setup accepted both channels");
            reset(d); writePipeline(d, 2, 4, true, true, false);
            std::cout << "RESET_SKEW_PASS addresses_first=" << addressesFirst << "\n"; return;
        }
    }
    throw std::runtime_error("independent AW pipeline did not advance ahead of W");
}
int main(int argc, char** argv) {
    try {
        STileLinkAxi4Bridge d;
        const std::string arg = argc > 1 ? argv[1] : "";
        if (arg == "--reset-skew") { resetSkew(d, true); resetSkew(d, false); return 0; }
        requireAwLead = arg == "--require-aw-lead";
        if (arg == "--denied-tail") { deniedTail(d); return 0; }
        injectWriteMismatch = arg == "--inject-w";
        for (unsigned beats : {1U, 2U, 8U, 16U}) for (unsigned prepare : {0U, 12U})
            writePipeline(d, beats, prepare, false, false);
        writePipeline(d, 8, 12, true, false);
        writePipeline(d, 8, 12, false, true);
        writePipeline(d, 8, 12, true, true);
        if (arg == "--inject-w") throw std::runtime_error("write mutation escaped oracle");
        std::cout << "WRITE_PIPELINE_ALL_PASS\n"; return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << "\n"; return 1; }
}
