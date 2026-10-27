// Independent finite row/selection scoreboard and byte-interval PMP oracle.
// The PMP oracle below retains the trailing-one/range algorithm from the existing
// pmp_checker.cpp; it does not call or translate DUT range/selection helpers.
// No DUT observation chooses a later input, expected token or permission.
#include "PreparedBareHeadStoreGsim.h"
#include "gsim_model_storage.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <memory>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#include <utility>

namespace {
using Wide = unsigned __int128;
constexpr uint64_t RamBase = UINT64_C(0x80200000), RamBytes = UINT64_C(0x80000000);
struct Token { unsigned index = 0; uint64_t tag = 0; bool operator==(const Token &) const = default; };
struct Item {
    Token token; uint64_t address = 0, data = 0; unsigned size = 0;
    bool operator==(const Item &) const = default;
};
struct Entry { unsigned cfg = 0; uint64_t addr = 0; };
using Entries = std::array<Entry, 16>;
struct Shelf { bool valid = false, known = false; Item item; };
struct Control {
    bool currentValid = false, headValid = false, headDone = false;
    Token current, head;
    bool memory = true, store = true, atomic = false, system = false, mulDiv = false;
    bool fetchFault = false, fetchPageFault = false, controlFlow = false, integerAdd = true;
    bool virtualized = false, flush = false, kill = false;
    bool sourceReady1 = true, sourceReady2 = true, credit = true, commit = true;
    bool barrier = false, pendingException = false;
    uint64_t normalAddress = RamBase + 0x1080;
    unsigned normalSize = 2, normalAccess = 1, privilege = 1;
    Entries entries{};
};

// Decode NAPOT by counting trailing ones, independently of the RTL mask formula.
static bool denied(const Entries &entries, uint64_t address, unsigned size, unsigned access, unsigned privilege) {
    const Wide start = address, end = start + (uint64_t(1) << size) - 1;
    for (unsigned i = 0; i < entries.size(); ++i) {
        const auto [cfg, encoded] = entries[i];
        const unsigned mode = (cfg >> 3) & 3;
        Wide low = 0, high = 0;
        if (mode == 0) continue;
        if (mode == 1) {
            low = i ? Wide(entries[i - 1].addr) << 2 : 0;
            const Wide top = Wide(encoded) << 2;
            if (top <= low) continue;
            high = top - 1;
        } else if (mode == 2) {
            low = Wide(encoded) << 2;
            high = low + 3;
        } else {
            unsigned trailing = 0;
            while (trailing < 54 && (encoded & (uint64_t(1) << trailing))) ++trailing;
            const Wide bytes = trailing >= 53 ? Wide(1) << 56 : Wide(8) << trailing;
            low = (Wide(encoded) << 2) & ~(bytes - 1);
            high = low + bytes - 1;
        }
        if (start > high || end < low) continue;
        const bool whole = start >= low && end <= high;
        const bool permission = access == 0 ? cfg & 1 : access == 1 ? cfg & 2 :
                                access == 2 ? cfg & 4 : (cfg & 3) == 3;
        return !whole || ((privilege != 3 || (cfg & 128)) && !permission);
    }
    return privilege != 3;
}
static Entry napot(uint64_t base, unsigned bytes, unsigned permissions, bool locked = false) {
    return {unsigned(0x18 | permissions | (locked ? 0x80 : 0)), (base >> 2) | (bytes / 8 - 1)};
}
static Control matching(const Item &item, bool atHead = true) {
    Control c; c.currentValid = true; c.headValid = atHead; c.current = item.token; c.head = item.token;
    c.entries[0] = napot(RamBase, 4096, 3);
    c.entries[1] = napot(RamBase + 4096, 4096, 5);
    return c;
}

class Test {
    std::unique_ptr<GsimModelStorage<SPreparedBareHeadStoreGsim>> storage;
    SPreparedBareHeadStoreGsim &dut;
    Shelf expected;
    std::string mutation;
    bool mutated = false;
    uint64_t cycles = 0, captures = 0, held = 0, consumes = 0, choices = 0, fallbacks = 0;
    uint64_t selectedDenied = 0, selectedAllowed = 0, fixtureBlocked = 0, pmpChecks = 0;
    uint64_t staleOwners = 0, wrongHeads = 0, virtualFallback = 0, unsafeAddressFallback = 0;
    uint64_t nonOrdinary = 0, permissionChanges = 0, preheadRefreshes = 0;

    void require(bool okay, const std::string &message) const {
        if (!okay) throw std::runtime_error("cycle=" + std::to_string(cycles) + " " + message);
    }
    void drive(const Control &c, const std::optional<Item> &candidate, const std::optional<Token> &consume) {
        const Item in = candidate.value_or(Item{}); const Token terminal = consume.value_or(Token{});
        dut.set_io$$candidateValid(candidate.has_value());
        dut.set_io$$candidateIndex(in.token.index); dut.set_io$$candidateTag(in.token.tag);
        dut.set_io$$candidateAddress(in.address); dut.set_io$$candidateData(in.data); dut.set_io$$candidateSize(in.size);
        dut.set_io$$currentValid(c.currentValid); dut.set_io$$currentIndex(c.current.index); dut.set_io$$currentTag(c.current.tag);
        dut.set_io$$headValid(c.headValid); dut.set_io$$headDone(c.headDone);
        dut.set_io$$headIndex(c.head.index); dut.set_io$$headTag(c.head.tag);
        dut.set_io$$memory(c.memory); dut.set_io$$store(c.store); dut.set_io$$atomic(c.atomic);
        dut.set_io$$system(c.system); dut.set_io$$mulDiv(c.mulDiv); dut.set_io$$fetchFault(c.fetchFault);
        dut.set_io$$fetchPageFault(c.fetchPageFault); dut.set_io$$controlFlow(c.controlFlow); dut.set_io$$integerAdd(c.integerAdd);
        dut.set_io$$virtualized(c.virtualized); dut.set_io$$normalAddress(c.normalAddress);
        dut.set_io$$normalSize(c.normalSize); dut.set_io$$normalAccess(c.normalAccess); dut.set_io$$privilege(c.privilege);
        dut.set_io$$flush(c.flush); dut.set_io$$kill(c.kill);
        dut.set_io$$consumeValid(consume.has_value()); dut.set_io$$consumeIndex(terminal.index); dut.set_io$$consumeTag(terminal.tag);
        dut.set_io$$sourceReady1(c.sourceReady1); dut.set_io$$sourceReady2(c.sourceReady2);
        dut.set_io$$strictSerialCredit(c.credit); dut.set_io$$commitEnable(c.commit);
        dut.set_io$$barrier(c.barrier); dut.set_io$$pendingException(c.pendingException);
#define PMP(N) dut.set_io$$cfg##N(c.entries[N].cfg); dut.set_io$$addr##N(c.entries[N].addr)
        PMP(0); PMP(1); PMP(2); PMP(3); PMP(4); PMP(5); PMP(6); PMP(7);
        PMP(8); PMP(9); PMP(10); PMP(11); PMP(12); PMP(13); PMP(14); PMP(15);
#undef PMP
    }
public:
    explicit Test(std::string mode)
        : storage(std::make_unique<GsimModelStorage<SPreparedBareHeadStoreGsim>>()),
          dut(storage->get()), mutation(std::move(mode)) {
        dut.LOG_START = 1; dut.activateAll(); drive({}, {}, {});
        dut.set_reset(true); dut.step(); dut.step(); dut.set_reset(false);
    }
    bool tick(const std::string &label, const Control &c, std::optional<Item> candidate = {},
              std::optional<Token> consume = {}) {
        const Shelf old = expected;
        const bool live = old.valid && c.currentValid && old.item.token == c.current;
        const bool head = c.headValid && old.item.token == c.head;
        const bool ordinary = c.memory && c.store && !c.atomic && !c.system && !c.mulDiv &&
            !c.fetchFault && !c.fetchPageFault && !c.controlFlow && c.integerAdd;
        const uint64_t length = uint64_t(1) << old.item.size;
        const bool aligned = (old.item.address % length) == 0;
        const bool inRam = Wide(old.item.address) >= RamBase &&
            Wide(old.item.address) + length <= Wide(RamBase) + RamBytes;
        const bool choice = old.valid && live && head && !c.headDone && ordinary && !c.virtualized && aligned && inRam;
        const uint64_t queryAddress = choice ? old.item.address : c.normalAddress;
        const unsigned querySize = choice ? old.item.size : c.normalSize;
        const unsigned queryAccess = choice ? 1 : c.normalAccess;
        const bool expectedDenied = denied(c.entries, queryAddress, querySize, queryAccess, c.privilege);
        const bool admission = choice && c.sourceReady1 && c.sourceReady2 && c.credit && c.commit &&
            !c.barrier && !c.pendingException && !c.flush && !c.kill;
        require(!consume || (old.valid && live && head && !c.flush && !c.kill && *consume == old.item.token),
            label + " test attempted illegal consume");
        drive(c, candidate, consume); dut.step();
        Item observed{{unsigned(dut.get_io$$rowIndex()), dut.get_io$$rowTag()},
            dut.get_io$$rowAddress(), dut.get_io$$rowData(), unsigned(dut.get_io$$rowSize())};
        bool observedChoice = dut.get_io$$choice(), observedDenied = dut.get_io$$denied();
        uint64_t observedAddress = dut.get_io$$queryAddress();
        if (!mutation.empty() && !mutated && label == "opposite-held-allow") {
            std::cerr << "PREPARED_BARE_HEAD_STORE_NEGATIVE_REACHED mode=" << mutation << " case=" << label << '\n';
            if (mutation == "choice") observedChoice = !observedChoice;
            else if (mutation == "query") observedAddress = c.normalAddress;
            else if (mutation == "permission") observedDenied = !observedDenied;
            else if (mutation == "payload") observed.token.tag ^= UINT64_C(1) << 63;
            else throw std::runtime_error("unknown mutation");
            mutated = true;
        }
        require(bool(dut.get_io$$rowValid()) == old.valid, label + " independent row validity mismatch");
        if (old.known) require(observed == old.item, label + " independent retained payload mismatch");
        require(bool(dut.get_io$$ownerLive()) == live, label + " independent full owner mismatch");
        if (old.known) require(bool(dut.get_io$$atHead()) == head, label + " independent full head mismatch");
        require(observedChoice == choice, label + " independent source choice mismatch");
        require(observedAddress == queryAddress && dut.get_io$$querySize() == querySize &&
            dut.get_io$$queryAccess() == queryAccess, label + " independent selected PMP query mismatch");
        require(observedDenied == expectedDenied, label + " independent byte-range PMP mismatch");
        require(bool(dut.get_io$$fixtureAdmission()) == admission, label + " fixture-only admission mismatch");
        ++cycles; ++pmpChecks; choices += choice; fallbacks += !choice;
        selectedDenied += choice && expectedDenied; selectedAllowed += choice && !expectedDenied;
        fixtureBlocked += choice && !admission;
        staleOwners += old.valid && !live; wrongHeads += old.valid && live && !head;
        virtualFallback += old.valid && live && head && c.virtualized;
        unsafeAddressFallback += old.valid && live && head && (!aligned || !inRam);
        nonOrdinary += old.valid && live && head && !ordinary;
        const bool retainingHead = old.valid && live && head;
        const bool capture = candidate.has_value() && !retainingHead;
        held += retainingHead && candidate.has_value(); captures += capture; consumes += consume.has_value();
        if (capture) { expected.item = *candidate; expected.known = true; }
        if (c.flush || c.kill || (consume && *consume == old.item.token)) expected.valid = false;
        else if (capture) expected.valid = true;
        else if (!live) expected.valid = false;
        return choice;
    }
    void load(const Item &item) {
        Control resetRow; resetRow.flush = true; tick("clear-before-case", resetRow);
        Control c = matching(item, false);
        require(!tick("empty-no-bypass", c, item), "candidate bypassed empty row");
        require(!tick("prehead-visible", c), "prehead row granted current-head choice");
    }
    void directed() {
        const Item item{{15, UINT64_C(0x80000000000001ff)}, RamBase + 0x80, UINT64_C(0xdeadbeef12345678), 3};
        load(item);
        Item prior = item;
        for (unsigned i = 0; i < 32; ++i) {
            const Item next{{i & 15, UINT64_C(0x8000000000010000) + i},
                RamBase + 8 * i, UINT64_C(0x5a5a000000000000) + i, 3};
            require(!tick("continuous-live-prehead-refresh", matching(prior, false), next),
                "prehead refresh granted current-head source choice");
            prior = next; ++preheadRefreshes;
        }
        tick("continuous-refresh-final-visible", matching(prior));
        load(item); Control c = matching(item);
        require(!denied(c.entries, item.address, item.size, 1, c.privilege) &&
            denied(c.entries, c.normalAddress, c.normalSize, c.normalAccess, c.privilege),
            "opposite-held-allow setup did not distinguish selected permission");
        require(tick("opposite-held-allow", c), "held row not selected");
        c.entries[0].cfg = 0x19; c.entries[1].cfg = 0x1b; ++permissionChanges;
        require(denied(c.entries, item.address, item.size, 1, c.privilege) &&
            !denied(c.entries, c.normalAddress, c.normalSize, c.normalAccess, c.privilege),
            "opposite-held-deny setup did not distinguish selected permission");
        require(tick("opposite-held-deny", c), "PMP denial fed source selection");
        c.normalAccess = 0; tick("held-forces-write-not-normal-read", c);
        c.virtualized = true; require(!tick("virtual-normal-fallback", c), "virtual row selected as Bare");
        c.virtualized = false; c.entries[0].cfg = 0x1b; ++permissionChanges;
        tick("current-pmp-permission-flip", c);
        c.privilege = 3; c.entries[0].cfg = 0x19; tick("machine-unlocked", c);
        c.entries[0].cfg |= 0x80; tick("machine-locked", c);
        c = matching(item);
        for (unsigned gate = 0; gate < 7; ++gate) {
            Control blocked = c;
            if (gate == 0) blocked.sourceReady1 = false;
            if (gate == 1) blocked.sourceReady2 = false;
            if (gate == 2) blocked.credit = false;
            if (gate == 3) blocked.commit = false;
            if (gate == 4) blocked.barrier = true;
            if (gate == 5) blocked.pendingException = true;
            if (gate == 6) blocked.headDone = true;
            tick("independent-late-gate-" + std::to_string(gate), blocked,
                Item{{0, 0}, RamBase + 0x100, 7, 0});
        }
        for (unsigned kind = 0; kind < 9; ++kind) {
            Control other = c;
            if (kind == 0) other.memory = false;
            if (kind == 1) other.store = false;
            if (kind == 2) other.atomic = true;
            if (kind == 3) other.system = true;
            if (kind == 4) other.mulDiv = true;
            if (kind == 5) other.fetchFault = true;
            if (kind == 6) other.fetchPageFault = true;
            if (kind == 7) other.controlFlow = true;
            if (kind == 8) other.integerAdd = false;
            require(!tick("excluded-class-" + std::to_string(kind), other), "nonordinary store selected");
        }
        Control wrongHead = c; wrongHead.head.tag ^= UINT64_C(1) << 63;
        tick("high-bit-head-mismatch", wrongHead);
        wrongHead = c; wrongHead.head.index = 0; tick("nonhead-index-wrap", wrongHead);
        Control stale = c; stale.current.tag ^= UINT64_C(1) << 63;
        tick("high-bit-owner-stale", stale); tick("stale-drop-visible", stale);
        load(item); c = matching(item); c.current.tag += 1;
        tick("same-index-generation-ABA", c);
        load(item); c = matching(item);
        const Item next{{0, UINT64_C(0xffffffffffffffff)}, RamBase + 0x180, 0x1234, 2};
        tick("consume-no-turnover", c, next, item.token);
        Control n = matching(next, false);
        require(!tick("consume-empty-no-bypass", n, next), "consume allowed empty bypass");
        tick("index-wrap-fresh-fulltag", matching(next));
        Control killed = matching(next); killed.kill = true;
        tick("same-edge-kill-raw-choice-no-admission", killed); tick("kill-cleared", matching(next));
        load(item); Control flushed = matching(item); flushed.flush = true;
        tick("same-edge-flush-raw-choice-no-admission", flushed); tick("flush-cleared", matching(item));
        // Every size, final contained transfer, unaligned and full-width aliases.
        for (unsigned size = 0; size < 4; ++size) {
            const uint64_t bytes = uint64_t(1) << size;
            for (uint64_t address : std::array<uint64_t, 7>{RamBase, RamBase + RamBytes - bytes,
                    RamBase + RamBytes, RamBase - 1, RamBase + RamBytes - 1,
                    RamBase | (UINT64_C(1) << 63), UINT64_MAX}) {
                Item edge{{unsigned(size), UINT64_C(0x1000000000000000) + cycles}, address, cycles, size};
                load(edge); tick("range-alignment-full-width", matching(edge));
            }
        }
        const Item mmio{{2, UINT64_C(0x8000000000000021)}, UINT64_C(0x10000000), 0x55, 2};
        load(mmio); require(!tick("MMIO-normal-path-only", matching(mmio)), "MMIO selected prepared Bare RAM source");
        // Priority, partial overlap, OFF predecessor TOR, last-entry, and M lock.
        load(item); c = matching(item);
        for (unsigned first = 0; first < 16; ++first) {
            c.entries = {}; c.entries[first] = {0x92, (item.address + 4) >> 2};
            if (first + 1 < 16) c.entries[first + 1] = napot(RamBase, 4096, 3);
            c.privilege = first % 2 ? 3 : 1;
            tick("first-overlap-partial-denial", c);
        }
        c.entries = {}; c.entries[0] = {0, RamBase >> 2};
        c.entries[1] = {0x8b, (RamBase + 4096) >> 2}; c.privilege = 1;
        tick("tor-off-predecessor", c);
        c.entries[1].addr = c.entries[0].addr; tick("empty-tor", c);
        c.entries = {}; c.entries[15] = napot(RamBase, 4096, 3);
        tick("entry15-matches", c);
        // Query fallback must preserve every address bit and its access/size.
        c.virtualized = true;
        for (uint64_t address : std::array<uint64_t, 5>{0, RamBase + 1, UINT64_C(1) << 56,
                (UINT64_C(1) << 63) | RamBase, UINT64_MAX}) {
            c.normalAddress = address; c.normalSize = 3; c.normalAccess = 3;
            tick("normal-query-high-address-overflow", c);
        }
    }
    void randomized() {
        const Item item{{3, UINT64_C(0xfedcba9876543210)}, RamBase + 0x100, UINT64_C(0x0123456789abcdef), 3};
        load(item); Control c = matching(item); std::mt19937_64 rng(UINT64_C(0x4241524553544f52));
        const unsigned permissions[] = {0, 1, 3, 4, 5, 7};
        for (unsigned n = 0; n < 512; ++n) {
            c.entries = {};
            for (Entry &entry : c.entries) {
                unsigned kind = rng() % 4;
                entry.cfg = (kind << 3) | permissions[rng() % 6] | ((rng() & 3) == 0 ? 128 : 0);
                const uint64_t base = RamBase + (rng() & 0x1fff);
                const unsigned bytes = 8u << (rng() % 10);
                entry.addr = kind == 3 ? ((base & ~uint64_t(bytes - 1)) >> 2) | (bytes / 8 - 1) : base >> 2;
            }
            c.virtualized = n % 3 == 0; c.privilege = n % 3 == 0 ? 3 : n % 2;
            c.normalAddress = n % 7 == 0 ? UINT64_MAX - (rng() & 7) : RamBase + (rng() & 0x3fff);
            c.normalSize = rng() % 4; c.normalAccess = rng() % 4;
            tick("bounded-independent-pmp-table", c);
        }
    }
    void finish() {
        require(mutation.empty(), "requested observation negative was not rejected");
        require(captures > 30 && held >= 7 && consumes == 1 && choices > 100 && fallbacks > 100 &&
            selectedDenied > 0 && selectedAllowed > 0 && fixtureBlocked >= 8 && staleOwners >= 2 &&
            wrongHeads >= 2 && virtualFallback > 0 && unsafeAddressFallback > 10 && nonOrdinary == 9 &&
            permissionChanges == 2 && preheadRefreshes == 32, "bounded directed coverage obligation missing");
        std::cout << "PREPARED_BARE_HEAD_STORE_PASS cycles=" << cycles << " captures=" << captures
            << " held=" << held << " consumes=" << consumes << " choices=" << choices << " fallbacks=" << fallbacks
            << " selected_denied=" << selectedDenied << " selected_allowed=" << selectedAllowed
            << " fixture_blocked=" << fixtureBlocked << " stale_owners=" << staleOwners << " wrong_heads=" << wrongHeads
            << " pmp_checks=" << pmpChecks << " continuous_prehead_refreshes=" << preheadRefreshes
            << " randomized_tables=512 token_bits=64 capacity=1 minimum_latency=1"
            << " empty_bypass=0 backend_connected=0 actual_lsu_execution=0 physical_write_authority=0\n";
    }
};
}
int main(int argc, char **argv) {
    try {
        std::string mutation;
        if (argc == 2) {
            const std::string mode = argv[1];
            if (mode == "--mutate-choice" || mode == "--mutate-query" || mode == "--mutate-permission" || mode == "--mutate-payload")
                mutation = mode.substr(9);
            else throw std::runtime_error("unknown mode");
        } else if (argc != 1) throw std::runtime_error("usage: prepared-bare-head-store [--mutate-choice|--mutate-query|--mutate-permission|--mutate-payload]");
        Test test(mutation); test.directed(); test.randomized(); test.finish(); return 0;
    } catch (const std::exception &error) {
        std::cerr << "PREPARED_BARE_HEAD_STORE_FAIL " << error.what() << '\n'; return 1;
    }
}
