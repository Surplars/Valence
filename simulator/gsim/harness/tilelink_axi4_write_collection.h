#pragma once
#ifndef WRITE_COLLECTION_FLOW
#define WRITE_COLLECTION_FLOW 0
#endif

// Authored traffic/credit oracle: only external A/AW/W/B/D handshakes,
// never the DUT's capture pointers, credit count, payload RAM or state.
static void collectionCase(STileLinkAxi4Bridge& d, unsigned beats, unsigned gap,
                           unsigned awDelay, unsigned wDelay, bool bError,
                           unsigned oneMask = 256, bool injectCredit = false) {
    reset(d);
    unsigned a = 0, w = 0, aw = 0, b = 0, done = 0, id = 0, concurrent = 0;
    unsigned lastA = 0, firstAw = 0, firstW = 0, bAt = 0, cycle = 0;
    bool heldA = false;
    std::optional<std::tuple<uint64_t, unsigned, unsigned, unsigned>> stalledAw;
    std::optional<std::tuple<uint64_t, unsigned, bool>> stalledW;
    std::optional<std::tuple<unsigned, unsigned, unsigned, bool>> stalledD;
    auto strobe = [&](unsigned beat) {
        return oneMask < 256 ? oneMask : beat % 4 == 0 ? 0U : beat % 3 == 0 ? 0x55U : 0xffU;
    };
    for (; cycle < 2000 && !done; ++cycle) {
        const unsigned capturedBefore = a;
        const bool av = a < beats && (heldA || cycle % gap == 0);
        const bool awr = cycle >= awDelay, wr = cycle >= wDelay && cycle % 7 != 5;
        const bool bv = aw == 1 && w == beats && !b;
        const bool dr = cycle % 11 < 6;
        d.set_io$$tl$$a$$valid(av); d.set_io$$tl$$a$$bits$$opcode(1);
        d.set_io$$tl$$a$$bits$$param(0); d.set_io$$tl$$a$$bits$$source(5);
        d.set_io$$tl$$a$$bits$$size(size(beats)); d.set_io$$tl$$a$$bits$$address(base + 0x2000);
        d.set_io$$tl$$a$$bits$$mask(strobe(a));
        d.set_io$$tl$$a$$bits$$data(av ? payload(41, a) : (0xdeadbeefULL ^ cycle));
        d.set_io$$tl$$a$$bits$$corrupt(0); d.set_io$$tl$$d$$ready(dr);
        d.set_io$$axi$$ar$$ready(1); d.set_io$$axi$$r$$valid(0);
        d.set_io$$axi$$aw$$ready(awr); d.set_io$$axi$$w$$ready(wr);
        d.set_io$$axi$$b$$valid(bv); d.set_io$$axi$$b$$bits$$id(id);
        d.set_io$$axi$$b$$bits$$resp(bError ? 2 : 0); d.step();
        const bool af = av && d.get_io$$tl$$a$$ready();
        const bool awv = d.get_io$$axi$$aw$$valid(), wv = d.get_io$$axi$$w$$valid();
        const bool dv = d.get_io$$tl$$d$$valid();
        auto abits = std::tuple{uint64_t(d.get_io$$axi$$aw$$bits$$addr()),
            unsigned(d.get_io$$axi$$aw$$bits$$id()), unsigned(d.get_io$$axi$$aw$$bits$$len()),
            unsigned(d.get_io$$axi$$aw$$bits$$size())};
        auto wbits = std::tuple{uint64_t(d.get_io$$axi$$w$$bits$$data()),
            unsigned(d.get_io$$axi$$w$$bits$$strb()), bool(d.get_io$$axi$$w$$bits$$last())};
        auto dbits = std::tuple{unsigned(d.get_io$$tl$$d$$bits$$source()),
            unsigned(d.get_io$$tl$$d$$bits$$size()), unsigned(d.get_io$$tl$$d$$bits$$opcode()),
            bool(d.get_io$$tl$$d$$bits$$denied())};
        if (stalledAw) check(awv && abits == *stalledAw, "collection AW changed while stalled");
        if (stalledW) check(wv && wbits == *stalledW, "collection W changed while producer wrote future words");
        if (stalledD) check(dv && dbits == *stalledD, "collection D changed while stalled");
        stalledAw = awv && !awr ? std::optional{abits} : std::nullopt;
        stalledW = wv && !wr ? std::optional{wbits} : std::nullopt;
        stalledD = dv && !dr ? std::optional{dbits} : std::nullopt;
        heldA = av && !af;
        check(!d.get_io$$axi$$ar$$valid(), "collection write emitted AR");
        if (awv && awr) {
            check(!aw && std::get<0>(abits) == 0x2000 && std::get<2>(abits) + 1 == beats &&
                std::get<3>(abits) == 3 && capturedBefore > 0, "collection AW ownership mismatch");
            id = std::get<1>(abits); firstAw = cycle; ++aw;
        }
        if (wv && wr) {
            check(w < (injectCredit ? 0U : capturedBefore), "collection consumed unaccepted A beat");
            check(w < beats && std::get<0>(wbits) == payload(41, w) &&
                std::get<1>(wbits) == strobe(w) && std::get<2>(wbits) == (w + 1 == beats),
                "collection independent data/strobe/last mismatch");
            if (!w) firstW = cycle;
            ++w;
            concurrent += af;
        }
        if (af) { ++a; lastA = cycle; }
        if (bv && d.get_io$$axi$$b$$ready()) { bAt = cycle; ++b; }
        if (dv) check(a == beats && aw == 1 && w == beats && b == 1 && cycle > bAt,
                      "collection acknowledged before accepted AW/W/B drain");
        if (dv && dr) {
            check(std::get<0>(dbits) == 5 && std::get<1>(dbits) == size(beats) &&
                std::get<2>(dbits) == 0 && std::get<3>(dbits) == bError &&
                !d.get_io$$tl$$d$$bits$$corrupt() && !d.get_io$$tl$$d$$bits$$data(),
                "collection D metadata/error mismatch");
            ++done;
        }
    }
    check(done == 1 && a == beats && aw == 1 && w == beats && b == 1,
          "collection transaction lost/duplicated or failed bounded progress");
    if (!WRITE_COLLECTION_FLOW) check(firstAw > lastA && firstW > lastA, "default path began before collection");
    if (WRITE_COLLECTION_FLOW && beats >= 8 && gap == 3 && !awDelay)
        check(firstAw < lastA, "collection AW did not overlap producer gaps");
    if (WRITE_COLLECTION_FLOW && beats >= 8 && gap == 3 && !wDelay)
        check(firstW < lastA, "collection W did not overlap producer gaps");
    // With sparse A offers and registered credits, W normally fires on the
    // following edge rather than the same edge. Same-edge throughput belongs
    // to the continuous-producer case, not to an imposed three-cycle gap.
    if (WRITE_COLLECTION_FLOW && beats >= 8 && gap == 1 && !wDelay)
        check(concurrent > 0, "continuous collection did not accept A and W on the same edge");
    if (oneMask == 256)
        std::cout << "WRITE_COLLECTION_CASE_PASS beats=" << beats << " gap=" << gap
            << " aw_delay=" << awDelay << " w_delay=" << wDelay << " b_error=" << bError
            << " cycles=" << cycle << " first_aw=" << firstAw << " first_w=" << firstW
            << " last_a=" << lastA << " concurrent_a_w=" << concurrent << "\n";
}

static void collectionCases(STileLinkAxi4Bridge& d) {
    unsigned cases = 0;
    for (unsigned beats : {1U, 2U, 8U, 16U}) for (unsigned gap : {1U, 3U})
        for (const auto& delay : {std::pair{0U, 0U}, std::pair{40U, 0U}, std::pair{0U, 40U}})
            for (bool error : {false, true}) {
                collectionCase(d, beats, gap, delay.first, delay.second, error);
                ++cases;
            }
    for (unsigned mask = 0; mask < 256; ++mask) collectionCase(d, 1, 1, 0, 0, false, mask);
    std::cout << "WRITE_COLLECTION_ALL_PASS cases=" << cases << " masks=256"
        << " flow=" << WRITE_COLLECTION_FLOW << "\n";
}
