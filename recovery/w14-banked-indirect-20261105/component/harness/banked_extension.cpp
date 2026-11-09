// W14-only extension. The original randomized and directed suites remain unchanged.
static void bankedIndirect(SPredictionTrainingGsim& d, int argc, char** argv) {
    static_assert(TRAIN_WIDTH == 2 && COMPRESSED == 1 && DELAYED_TRAINING == 1);
    bool injectStaleHit = false;
    for (int i = 1; i < argc; ++i)
        injectStaleHit |= std::string_view(argv[i]) == "--inject-bank-stale-hit";
    struct Entry { bool valid = false; uint64_t pc = 0, target = 0; };
    std::array<Entry, 16> table{};
    Packet pending{};
    unsigned cycles = 0, queries = 0, hits = 0, misses = 0;
    unsigned staleMiss = 0, ownerFlip = 0, samePc = 0, sameIndex = 0;
    unsigned parallelSameParity = 0, continuous = 0, resetCancelled = 0;
    unsigned rowCoverage = 0, owner0Coverage = 0, owner1Coverage = 0;
    auto event = [](uint64_t pc, uint64_t target) {
        Commit c; c.valid = true; c.indirect = true;
        c.pc = pc; c.next = target; c.instruction = 0x00008067; return c;
    };
    auto reset = [&](const Packet& offered = Packet{}) {
        for (unsigned lane = 0; lane < 2; ++lane) drive(d, lane, offered[lane], 0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        table = {}; pending = {};
    };
    // Independent logical row oracle: no physical bank, owner or DUT internal ABI.
    // Check cached old Q, then apply pending in lane order, then capture offered.
    auto tick = [&](const Packet& offered, uint64_t q0, uint64_t q1,
                    unsigned expectedHitMask, const char* label) {
        const std::array<uint64_t, 2> query{q0, q1};
        for (unsigned lane = 0; lane < 2; ++lane) drive(d, lane, offered[lane], query[lane]);
        d.step();
        for (unsigned lane = 0; lane < 2; ++lane) {
            const Entry& e = table[(query[lane] >> 1) & 15];
            const bool expected = e.valid && e.pc == query[lane];
            check(expected == bool(expectedHitMask & (1u << lane)),
                "banked vector/model hit precondition mismatch");
            Answer actual = read(d, lane);
            // This exact window has valid owner1/B and stale owner0/A, not an invalid row.
            if (injectStaleHit && lane == 0 && std::string_view(label) == "owner-0-to-1-stale-A") {
                check(e.valid && !expected, "stale-bank negative precondition");
                actual.hit = true; injectStaleHit = false;
            }
            if (actual.hit != expected || (expected && actual.target != e.target)) {
                std::cerr << "banked=" << label << " cycle=" << cycles << " lane=" << lane
                    << " pc=" << std::hex << query[lane] << " expected_target=" << e.target
                    << " actual_target=" << actual.target << std::dec
                    << " expected_hit=" << expected << " actual_hit=" << actual.hit << '\n';
                throw std::runtime_error(actual.hit != expected ?
                    "banked indirect table hit mismatch" : "banked indirect table target mismatch");
            }
            ++queries; if (expected) ++hits; else ++misses;
        }
        for (unsigned lane = 0; lane < 2; ++lane) {
            const auto& c = pending[lane];
            if (c.valid && c.indirect) {
                const unsigned row = (c.pc >> 1) & 15;
                table[row] = {true, c.pc, c.next};
                rowCoverage |= 1u << row;
                (lane == 0 ? owner0Coverage : owner1Coverage) |= 1u << row;
            }
        }
        pending = offered;
        ++cycles;
    };
    const uint64_t a = 0x0000000012345602ULL;
    const uint64_t b = a ^ (uint64_t(1) << 63);
    const uint64_t c = a ^ (uint64_t(1) << 40);
    const uint64_t t0 = 0x0000000087654320ULL;
    const uint64_t t1 = t0 ^ (uint64_t(1) << 63);
    reset();
    tick({event(a, t0), Commit{}}, a, b, 0, "seed-owner0-c");
    tick({}, a, b, 0, "seed-owner0-c+1");
    tick({}, a, b, 1, "seed-owner0-c+2");
    tick({Commit{}, event(b, t1)}, a, b, 1, "owner-0-to-1-c");
    tick({}, a, b, 1, "owner-0-to-1-c+1");
    tick({}, a, b, 2, "owner-0-to-1-stale-A"); ++staleMiss; ++ownerFlip;
    tick({event(c, t0 + 2), Commit{}}, b, c, 1, "owner-1-to-0-c");
    tick({}, b, c, 1, "owner-1-to-0-c+1");
    tick({}, b, c, 2, "owner-1-to-0-stale-B"); ++staleMiss; ++ownerFlip;
    // Both queries remain fixed on one PC while the owner changes and target differs.
    tick({Commit{}, event(c, t1 + 4)}, c, c, 3, "same-PC-owner1-c");
    tick({}, c, c, 3, "same-PC-owner1-c+1-old-target");
    tick({}, c, c, 3, "same-PC-owner1-c+2-new-target"); ++samePc; ++ownerFlip;
    tick({event(c, t0 + 6), Commit{}}, c, c, 3, "same-PC-owner0-c");
    tick({}, c, c, 3, "same-PC-owner0-c+1-old-target");
    tick({}, c, c, 3, "same-PC-owner0-c+2-new-target"); ++samePc; ++ownerFlip;
    tick({event(a, t0 + 8), event(b, t1 + 10)}, a, b, 0, "dual-same-index-c");
    tick({}, a, b, 0, "dual-same-index-c+1");
    tick({}, a, b, 2, "dual-same-index-lane1-wins"); ++sameIndex; ++staleMiss;
    // Indices 3 and 5 have the same parity: no accidental parity-bank arbitration.
    tick({event(a + 4, t0 + 12), event(a + 8, t1 + 14)}, a + 4, a + 8, 0, "dual-same-parity-c");
    tick({}, a + 4, a + 8, 0, "dual-same-parity-c+1");
    tick({}, a + 4, a + 8, 3, "dual-same-parity-result"); ++parallelSameParity;
    for (unsigned i = 0; i < 6; ++i) {
        Packet offered{};
        offered[i & 1] = event(c, (i & 1 ? t1 : t0) + 32 + 2 * i);
        tick(offered, b, c, i < 2 ? 1 : 2, "continuous-owner-flip");
        ++continuous;
    }
    tick({}, b, c, 2, "continuous-drain-c+1");
    tick({}, c, c, 3, "continuous-drain-c+2");
    // Reset overlaps a valid pending packet and a different valid offered packet.
    tick({event(a, t0 + 64), event(b, t1 + 66)}, c, c, 3, "reset-pending-offer");
    check(pending[0].valid && pending[1].valid, "banked reset pending precondition");
    reset({event(c, t0 + 68), event(a, t1 + 70)});
    tick({}, a, b, 0, "reset-no-old-bank-hit");
    tick({}, c, a, 0, "reset-no-offered-resurrection");
    tick({}, a, b, 0, "reset-no-pending-resurrection"); ++resetCancelled;
    // Cover all 16 rows under both owners, without peeking at RAM or owner state.
    for (unsigned row = 0; row < 16; row += 2) {
        const uint64_t x = 0x60000000ULL + 2 * row, y = x + 2;
        tick({event(x, t0 + row), event(y, t1 + row)}, x, y, 0, "all-rows-seed-c");
        tick({}, x, y, 0, "all-rows-seed-c+1");
        tick({}, x, y, 3, "all-rows-seed-c+2");
        tick({event(y, t0 + row + 2), event(x, t1 + row + 2)}, x, y, 3, "all-rows-swap-c");
        tick({}, x, y, 3, "all-rows-swap-c+1");
        tick({}, x, y, 3, "all-rows-swap-c+2");
    }
    check(staleMiss == 3 && ownerFlip == 4 && samePc == 2 && sameIndex == 1 &&
        parallelSameParity == 1 && continuous == 6 && resetCancelled == 1 &&
        rowCoverage == 0xffff && owner0Coverage == 0xffff && owner1Coverage == 0xffff,
        "banked indirect coverage incomplete");
    check(!injectStaleHit, "requested stale-bank negative control did not fire");
    std::cout << "GSIM banked indirect: PASS cycles=" << cycles << " queries=" << queries
        << " hits=" << hits << " misses=" << misses << " staleMiss=" << staleMiss
        << " ownerFlip=" << ownerFlip << " samePc=" << samePc << " sameIndex=" << sameIndex
        << " parallelSameParity=" << parallelSameParity << " continuous=" << continuous
        << " resetCancelled=" << resetCancelled << " rows=" << rowCoverage
        << " owner0Rows=" << owner0Coverage << " owner1Rows=" << owner1Coverage << '\n';
}

