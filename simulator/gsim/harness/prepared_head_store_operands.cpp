// Finite independent shelf scoreboard. No DUT output selects an expected owner,
// drives a later input, or grants memory/retirement authority.
#include "PreparedHeadStoreOperandsGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>

namespace {
struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    bool operator==(const Token &) const = default;
};
struct Item {
    Token token;
    uint64_t address = 0, data = 0;
    unsigned size = 0;
    bool operator==(const Item &) const = default;
};
struct Control { bool live = true, head = false, flush = false; };
struct Shelf { bool valid = false, known = false; Item item; };
struct Coverage {
    uint64_t cycles = 0, captures = 0, refreshes = 0, held = 0, consumes = 0;
    uint64_t deadReplacements = 0, deadDrops = 0, flushes = 0, rawKills = 0;
    uint64_t flushCaptures = 0, missingCandidates = 0, indexWraps = 0, tagWraps = 0;
};

class Oracle {
    SPreparedHeadStoreOperandsGsim dut;
    std::array<Shelf, 2> expected{};
    Coverage coverage;
    bool injectObservation;

    void require(bool ok, const std::string &message) const {
        if (!ok) throw std::runtime_error("cycle=" + std::to_string(coverage.cycles) + " " + message);
    }
    static Item narrow(Item value, unsigned arm) {
        if (arm) { value.token.index &= 7; value.token.tag &= 511; }
        return value;
    }
    void drive(Control c, const std::optional<Item> &candidate, const std::optional<Token> &consume) {
        const Item item = candidate.value_or(Item{});
        const Token token = consume.value_or(Token{});
        dut.set_io$$candidateValid(candidate.has_value());
        dut.set_io$$candidateIndex(item.token.index); dut.set_io$$candidateTag(item.token.tag);
        dut.set_io$$candidateAddress(item.address); dut.set_io$$candidateData(item.data);
        dut.set_io$$candidateSize(item.size);
        dut.set_io$$ownerLive(c.live); dut.set_io$$atHead(c.head); dut.set_io$$flush(c.flush);
        dut.set_io$$consumeValid(consume.has_value());
        dut.set_io$$consumeIndex(token.index); dut.set_io$$consumeTag(token.tag);
    }
    void observe() {
        const std::array<bool, 2> valid{bool(dut.get_io$$standard$$valid()), bool(dut.get_io$$compact$$valid())};
        std::array<Item, 2> items{{
            {{unsigned(dut.get_io$$standard$$index()), dut.get_io$$standard$$tag()},
                dut.get_io$$standard$$address(), dut.get_io$$standard$$data(), unsigned(dut.get_io$$standard$$size())},
            {{unsigned(dut.get_io$$compact$$index()), dut.get_io$$compact$$tag()},
                dut.get_io$$compact$$address(), dut.get_io$$compact$$data(), unsigned(dut.get_io$$compact$$size())}
        }};
        if (injectObservation && coverage.cycles == 20) {
            std::cerr << "PREPARED_HEAD_STORE_OBSERVATION_REACHED cycle=20 mutation=sampled_data\n";
            items[0].data ^= 1;
        }
        for (unsigned arm = 0; arm < expected.size(); ++arm) {
            const std::string shape = arm ? " compact" : " standard";
            require(valid[arm] == expected[arm].valid, "raw registered validity mismatch" + shape);
            // Even invalid payload is checked after first capture. Flush changes
            // publication only; consume and live-head hold cannot rewrite bits.
            if (expected[arm].known)
                require(items[arm] == expected[arm].item, "independent raw payload mismatch" + shape);
        }
    }
public:
    explicit Oracle(bool inject) : injectObservation(inject) {
        dut.LOG_START = 1; dut.activateAll(); drive({}, {}, {});
        dut.set_reset(true); dut.step(); dut.step(); dut.set_reset(false);
    }
    static Item make(unsigned index, uint64_t tag) {
        return {{index & 15, tag}, UINT64_C(0x80000000) ^ (tag << 3) ^ (uint64_t(index) << 37),
            UINT64_C(0xd1b54a32d192ed03) * (tag + 1) ^ uint64_t(index), unsigned(tag & 3)};
    }
    bool tick(Control c = {}, std::optional<Item> candidate = {}, std::optional<Token> consume = {}) {
        const Shelf old = expected[0];
        drive(c, candidate, consume); dut.step(); observe();
        const bool held = old.valid && c.live && c.head;
        const bool install = candidate.has_value() && !held;
        ++coverage.cycles;
        coverage.held += held && candidate.has_value();
        coverage.captures += install;
        coverage.refreshes += install && old.valid && c.live;
        coverage.consumes += consume.has_value();
        coverage.deadReplacements += install && old.valid && !c.live;
        coverage.deadDrops += old.valid && !c.live && !candidate;
        coverage.flushes += c.flush;
        coverage.rawKills += old.valid && (c.flush || consume.has_value());
        coverage.flushCaptures += c.flush && install;
        coverage.missingCandidates += !candidate.has_value();
        coverage.indexWraps += install && old.known && old.item.token.index == 15 && candidate->token.index == 0;
        coverage.tagWraps += install && old.known && old.item.token.tag == UINT64_MAX && candidate->token.tag == 0;
        for (unsigned arm = 0; arm < expected.size(); ++arm) {
            Shelf &row = expected[arm];
            const Token prior = row.item.token;
            const bool retainAtHead = row.valid && c.live && c.head;
            // Contract expressed as shelf operations, independent of RTL helpers.
            if (!retainAtHead && candidate) { row.item = narrow(*candidate, arm); row.known = true; }
            if (c.flush) row.valid = false;
            else if (consume && narrow(Item{*consume}, arm).token == prior) row.valid = false;
            else if (!retainAtHead && candidate) row.valid = true;
            else if (!c.live) row.valid = false;
        }
        return install;
    }
    void directed() {
        tick(); // Empty publication cannot bypass candidate.
        require(tick({}, make(15, UINT64_MAX - 3)), "initial capture missing");
        // Independent continuously offered candidates replace pre-head contents
        // every edge, including index and allocation-tag rollover.
        for (unsigned i = 0; i < 64; ++i)
            require(tick({}, make(i & 15, UINT64_MAX - 2 + i)), "pre-head continuous-supply II=1 lost capture");
        tick();
        const Item head = make(6, UINT64_C(0x80000000000000fe));
        tick({}, head);
        for (unsigned i = 0; i < 16; ++i)
            require(!tick({.head = true}, make(i, 700 + i)), "live head overwritten under consumer backpressure");
        tick({.head = true}); // No candidate still retains live head.
        const Item next = make(7, UINT64_C(0x10000000000000ff));
        require(!tick({.head = true}, next, head.token), "consume enabled same-edge recapture");
        require(!expected[0].valid && expected[0].item == head, "consume did not leave empty unchanged payload");
        require(tick({}, next), "next-cycle reload blocked");
        tick({.head = true}); // Reload becomes visible only after its edge.
        tick({.live = false}); // Stale owner disappears without a replacement.
        tick();
        const Item stale = make(9, 511), reused = make(9, 512);
        tick({}, stale);
        require(tick({.live = false, .head = true}, reused), "dead owner prevented same-index new-generation capture");
        tick({.head = true});
        tick({.head = true, .flush = true}, make(10, 513)); // Held payload does not recapture on flush.
        tick();
        tick({}, make(15, UINT64_MAX));
        tick({.flush = true}, make(0, 0)); // Early payload captures; flush suppresses only valid publication.
        tick(); tick(); // Hidden flush payload must not later publish without a new candidate.
        tick({}, make(2, UINT64_C(1) << 63));
        tick(); tick(); // Optional missing preparation never creates input/issue credit.
        tick({.head = true});
        require(tick({}, make(3, (UINT64_C(1) << 63) + 1)), "owner leaving head prevented pre-head refresh");
        tick({.flush = true}); tick();
    }
    void random() {
        std::mt19937_64 rng(UINT64_C(0x199e4da47));
        for (unsigned cycle = 0; cycle < 4000; ++cycle) {
            const Control c{rng() % 7 != 0, rng() % 3 == 0, rng() % 29 == 0};
            std::optional<Item> candidate;
            if (rng() % 5 != 0) candidate = make(rng() % 16, rng());
            std::optional<Token> consume;
            if (expected[0].valid && c.live && c.head && !c.flush && rng() % 4 == 0)
                consume = expected[0].item.token;
            tick(c, candidate, consume);
        }
        tick({.flush = true}); tick();
    }
    void illegal(const std::string &mode) {
        const Item item = make(3, UINT64_C(0x80000000000001a5));
        tick({}, item);
        // Keep a known matching payload while invalid, isolating the empty-row
        // assertion from any unspecified unreset payload or token mismatch.
        if (mode == "empty") tick({.head = true, .flush = true});
        Control c{.head = true};
        Token consume = item.token;
        if (mode == "dead") c.live = false;
        else if (mode == "prehead") c.head = false;
        else if (mode == "index") consume.index ^= 1;
        else if (mode == "tag") consume.tag ^= 1;
        else if (mode == "high-tag") consume.tag ^= UINT64_C(1) << 63;
        else if (mode == "flush") c.flush = true;
        else require(mode == "empty", "unknown illegal mode");
        std::cerr << "PREPARED_HEAD_STORE_NEGATIVE_REACHED case=" << mode << '\n';
        tick(c, make(4, 7), consume);
        throw std::runtime_error("illegal consume unexpectedly returned without hardware rejection");
    }
    void finish() {
        require(!injectObservation, "observation negative unexpectedly survived");
        require(coverage.captures > 100 && coverage.refreshes > 64 && coverage.held > 16 &&
            coverage.consumes > 1 && coverage.deadReplacements > 1 && coverage.deadDrops > 0 &&
            coverage.flushes > 1 && coverage.rawKills > 1 && coverage.flushCaptures > 0 &&
            coverage.missingCandidates > 1 && coverage.indexWraps > 0 && coverage.tagWraps > 0,
            "bounded coverage obligations missing");
        std::cout << "PREPARED_HEAD_STORE_OPERANDS_PASS cycles=" << coverage.cycles
            << " captures=" << coverage.captures << " refreshes=" << coverage.refreshes
            << " live_head_holds=" << coverage.held << " consumes=" << coverage.consumes
            << " dead_replacements=" << coverage.deadReplacements << " dead_drops=" << coverage.deadDrops
            << " flushes=" << coverage.flushes << " raw_kill_snapshots=" << coverage.rawKills
            << " flush_payload_captures=" << coverage.flushCaptures << " missing_candidates=" << coverage.missingCandidates
            << " index_wraps=" << coverage.indexWraps << " tag_wraps=" << coverage.tagWraps
            << " token_shapes=16x64,8x9 continuous_refreshes=64 minimum_latency=1 capacity=1"
            << " head_consume_same_edge_recapture=0 backend_connected=0\n";
    }
};
}

int main(int argc, char **argv) {
    try {
        const std::string mode = argc == 2 ? argv[1] : "";
        if (argc > 2) throw std::runtime_error("usage: prepared-row [--inject-observation|--illegal-CASE]");
        Oracle oracle(mode == "--inject-observation");
        if (mode.starts_with("--illegal-")) oracle.illegal(mode.substr(10));
        else if (!mode.empty() && mode != "--inject-observation") throw std::runtime_error("unknown mode");
        oracle.directed(); oracle.random(); oracle.finish();
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "PREPARED_HEAD_STORE_OPERANDS_FAIL " << error.what() << '\n';
        return 1;
    }
}
