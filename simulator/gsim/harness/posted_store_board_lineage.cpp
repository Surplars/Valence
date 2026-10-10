// Real Board/ROM/private-cache/coherent-home/DDR composition fixture.
// POSTED_BOARD_HOST_ONLY builds only the independent ISA/ledger controls. It is
// deliberately not a substitute for a generated Board model execution receipt.
#include "../posted_board_lineage/guest.h"
#include "../posted_board_lineage/directed_seal_witness.h"
#include <algorithm>
#include <deque>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <optional>
#include <set>
#include <tuple>
#include <unordered_map>

namespace guest = posted_board_guest;
using guest::require;
struct BoardOracleRejection : std::runtime_error {
    using std::runtime_error::runtime_error;
};

struct LineageToken {
    uint64_t tag = 0;
    unsigned index = 0;
    bool operator==(const LineageToken &other) const { return tag == other.tag && index == other.index; }
    bool operator<(const LineageToken &other) const { return std::tie(tag, index) < std::tie(other.tag, other.index); }
};
struct LineageWitness {
    LineageToken token;
    guest::Intent intent;
    uint64_t epoch = 0;
};
struct LineageRequest {
    uint64_t address = 0, data = 0, epoch = 0;
    unsigned mask = 0, size = 0, atomicOp = 0;
    bool write = false, atomic = false, virtualized = false, uncached = false;
    bool prechecked = false, prefetch = false;
    bool operator==(const LineageRequest &other) const {
        return std::tie(address, data, epoch, mask, size, atomicOp, write, atomic, virtualized,
            uncached, prechecked, prefetch) == std::tie(other.address, other.data, other.epoch,
            other.mask, other.size, other.atomicOp, other.write, other.atomic, other.virtualized,
            other.uncached, other.prechecked, other.prefetch);
    }
};
struct LineageProof {
    LineageToken token;
    uint64_t epoch = 0, address = 0, data = 0;
    unsigned mask = 0, size = 0;
    bool valid = false, head = false, pmp = false, physical = false;
    bool integer = false, legacy = false, checked = false;
    bool operator==(const LineageProof &other) const {
        return valid == other.valid && (!valid || (token == other.token &&
            std::tie(epoch, address, data, mask, size, head, pmp, physical, integer, legacy, checked) ==
            std::tie(other.epoch, other.address, other.data, other.mask, other.size, other.head,
                other.pmp, other.physical, other.integer, other.legacy, other.checked)));
    }
};
struct LineageBoundary {
    LineageRequest request;
    LineageProof proof;
    bool valid = false, ready = false, responseValid = false, responseReady = false;
    bool error = false, pageFault = false;
    uint64_t responseData = 0;
};
static void compareRequest(const LineageWitness &owner, const LineageBoundary &b, bool enabled) {
    const auto &i = owner.intent;
    require(b.request.address == i.address && b.request.mask == i.mask && b.request.size == i.size &&
        b.request.write == i.store && (!i.store || b.request.data == i.laneData) &&
        !b.request.atomic && !b.request.virtualized && !b.request.uncached && !b.request.prechecked,
        "cache request differs from independently decoded original CPU launch");
    require(b.proof.valid == (enabled && i.store), "missing/unexpected cache proof for original instruction");
    if (b.proof.valid) {
        require(b.proof.token == owner.token && b.proof.epoch == owner.epoch &&
            b.proof.address == i.address && b.proof.data == i.laneData && b.proof.mask == i.mask &&
            b.proof.size == i.size, "cache proof changed original full token/epoch/byte payload");
        require(b.proof.head && b.proof.pmp && b.proof.physical && b.proof.integer &&
            b.proof.legacy && b.proof.checked, "cache proof lacks CPU head/legacy/physical checked authority");
    }
}
static void compareFinalMemory(const guest::ByteMemory &expected,
    const std::unordered_map<uint32_t, uint64_t> &actual) {
    // Both memories define every absent byte as zero. Checking the union of
    // represented words therefore compares the entire sparse DDR aperture.
    std::set<uint32_t> words;
    for (const auto &byte : expected) words.insert(uint32_t((byte.first - guest::ddrBase) & ~UINT64_C(7)));
    for (const auto &word : actual) words.insert(word.first);
    for (uint32_t offset : words) {
        require(!(offset & 7), "DDR sparse memory contains an unaligned word key");
        const auto found = actual.find(offset);
        const uint64_t value = found == actual.end() ? 0 : found->second;
        require(value == guest::wordAt(expected, guest::ddrBase + offset),
            "final full sparse DDR byte mismatch at offset " + std::to_string(offset));
    }
}
static std::unordered_map<uint32_t, uint64_t> backing(const guest::ByteMemory &bytes) {
    std::unordered_map<uint32_t, uint64_t> result;
    for (uint64_t address = guest::memoryBegin; address < guest::memoryEnd; address += 8)
        result.emplace(uint32_t(address - guest::ddrBase), guest::wordAt(bytes, address));
    return result;
}
static void hostControls() {
    const auto program = guest::interpret();
    const auto &intent = program.intents.at(program.conflictPc);
    const LineageWitness witness{{0x100000009ULL, 9}, intent, 7};
    LineageBoundary b;
    b.valid = true; b.ready = true;
    b.request.address = intent.address; b.request.data = intent.laneData;
    b.request.mask = intent.mask; b.request.size = intent.size; b.request.write = true;
    b.proof = {witness.token, witness.epoch, intent.address, intent.laneData, intent.mask, intent.size,
        true, true, true, true, true, true, true};
    compareRequest(witness, b, true);
    auto rejects = [](const auto &run, const char *why) {
        bool rejected = false;
        try { run(); } catch (const std::runtime_error &) { rejected = true; }
        require(rejected, why);
    };
    auto mutated = b; mutated.proof.token.tag ^= UINT64_C(1) << 32;
    rejects([&] { compareRequest(witness, mutated, true); }, "host token high-bit mutation escaped");
    mutated = b; mutated.proof.token.index ^= 1;
    rejects([&] { compareRequest(witness, mutated, true); }, "host token index mutation escaped");
    mutated = b; mutated.proof.data ^= 1;
    rejects([&] { compareRequest(witness, mutated, true); }, "host proof byte mutation escaped");
    mutated = b; mutated.proof.epoch ^= 1;
    rejects([&] { compareRequest(witness, mutated, true); }, "host epoch mutation escaped");
    mutated = b; mutated.proof.legacy = false;
    rejects([&] { compareRequest(witness, mutated, true); }, "host missing authority escaped");
    auto bytes = backing(program.finalBytes);
    compareFinalMemory(program.finalBytes, bytes);
    bytes.at(uint32_t(guest::scratchC - guest::ddrBase)) ^= 1;
    rejects([&] { compareFinalMemory(program.finalBytes, bytes); }, "host final-byte mutation escaped");
    bytes = backing(program.finalBytes); bytes[0] = 1;
    rejects([&] { compareFinalMemory(program.finalBytes, bytes); }, "host extra-write mutation escaped");
    std::cout << "BOARD_POSTED_HOST_CONTROLS_PASS instructions=" << program.trace.size()
        << " stores=" << program.stores << " high_tag=1 index=1 proof_byte=1 epoch=1 authority=1"
        << " final_byte=1 extra_write=1 rtl_executed=0\n";
}

#ifndef POSTED_BOARD_HOST_ONLY
#include "../posted_board_lineage/axi_accounting.h"
#define BOARD_DDR_BYTES 0x80000000ULL
#define BOARD_CPU_HZ 100000000U
#define BOARD_UART_BAUD 460800U
#ifndef DDR_MODEL
#define DDR_MODEL
#endif
#ifndef DDR_MULTI_ID_MODEL
#define DDR_MULTI_ID_MODEL
#endif
#ifdef DDR_BENCHMARK_MODEL
#error "Board lineage requires the unchanged board_ddr_multiid.h memory model"
#endif
#define main unused_board_boot_main
#include "board_boot.cpp"
#undef main

struct LineageTrace {
    std::ofstream output;
    explicit LineageTrace(const std::string &path) : output(path) { require(bool(output), "cannot open Board trace"); }
    void event(uint64_t cycle, const char *kind,
        std::initializer_list<std::pair<const char *, uint64_t>> values) {
        output << "{\"cycle\":" << cycle << ",\"event\":\"" << kind << '"';
        for (const auto &field : values) output << ",\"" << field.first << "\":" << field.second;
        output << "}\n";
        output.flush();
        require(bool(output), "Board trace write failed");
    }
};
static void writeBinary(const std::filesystem::path &path, const std::vector<uint8_t> &bytes) {
    std::ofstream output(path, std::ios::binary);
    output.write(reinterpret_cast<const char *>(bytes.data()), bytes.size());
    require(bool(output), "cannot write raw Board fixture snapshot " + path.string());
}
static void writeMemory(const std::filesystem::path &directory, const std::string &name,
    const std::unordered_map<uint32_t, uint64_t> &memory) {
    std::vector<uint8_t> dense;
    for (uint64_t address = guest::memoryBegin; address < guest::memoryEnd; ++address) {
        const uint32_t offset = uint32_t(address - guest::ddrBase);
        const auto word = memory.find(offset & ~7U);
        dense.push_back(word == memory.end() ? 0 : uint8_t(word->second >> ((offset & 7) * 8)));
    }
    writeBinary(directory / (name + ".bin"), dense);
    // Canonical sparse representation covers the full configured DDR space:
    // omitted words are zero; keys are sorted, rebased byte addresses.
    std::map<uint32_t, uint64_t> sorted;
    for (const auto &word : memory) if (word.second) sorted.insert(word);
    std::ofstream output(directory / (name + "-sparse.json"));
    output << '{'; bool first = true;
    for (const auto &word : sorted) {
        if (!first) output << ',';
        first = false; output << '"' << word.first << "\":" << word.second;
    }
    output << "}\n";
    require(bool(output), "cannot write canonical sparse Board snapshot");
}
struct BoardOwnerKey {
    uint64_t slot = 0, generation = 0;
    bool operator==(const BoardOwnerKey &o) const { return slot == o.slot && generation == o.generation; }
    bool operator<(const BoardOwnerKey &o) const { return std::tie(slot, generation) < std::tie(o.slot, o.generation); }
};
struct BoardContext {
    BoardOwnerKey owner, cohort;
    uint64_t epoch = 0, line = 0;
    bool operator==(const BoardContext &o) const {
        return owner == o.owner && cohort == o.cohort && epoch == o.epoch && line == o.line;
    }
};
struct BoardReservation {
    uint64_t mshr = 0, set = 0, way = 0, victimAddress = 0;
    bool victimValid = false, victimDirty = false;
    bool operator==(const BoardReservation &o) const {
        return std::tie(mshr, set, way, victimAddress, victimValid, victimDirty) ==
            std::tie(o.mshr, o.set, o.way, o.victimAddress, o.victimValid, o.victimDirty);
    }
};
struct BoardOwnerEvent {
    BoardContext context;
    BoardReservation reservation;
    bool operator==(const BoardOwnerEvent &o) const { return context == o.context && reservation == o.reservation; }
};
struct BoardMember {
    BoardContext context;
    uint64_t ticket = 0;
    bool acknowledged = false, drained = false;
};
struct BoardOwner {
    BoardOwnerEvent event;
    std::array<uint8_t, 64> bytes{};
    std::set<LineageToken> members;
    bool acquired = false, grantAcked = false, refilled = false, installed = false, released = false;
    bool attached = false, sent = false, completed = false;
    uint64_t source = 0, sink = 0, grantBeats = 0, wbSlot = 0;
    BoardOwnerKey wbOwner;
};
struct BoardObservedWire {
    bool valid = false, ready = false;
    std::array<uint64_t, 10> payload{};
};
#define L(F) d.get_lineage$$##F()
#define OWNER_KEY(F) BoardOwnerKey{L(F##$$slot), L(F##$$generation)}
#define CONTEXT(F) BoardContext{OWNER_KEY(F##$$owner), OWNER_KEY(F##$$cohortRoot), L(F##$$epoch), L(F##$$lineAddress)}
#define RESERVATION(F) BoardReservation{L(F##$$mshr), L(F##$$set), L(F##$$way), L(F##$$victimAddress), \
    bool(L(F##$$victimValid)), bool(L(F##$$victimDirty))}
#define OWNER_EVENT(F) BoardOwnerEvent{CONTEXT(F##$$context), RESERVATION(F##$$reservation)}
#define LINE_WORDS(F) std::array<uint64_t, 8>{L(F##$$word0), L(F##$$word1), L(F##$$word2), L(F##$$word3), \
    L(F##$$word4), L(F##$$word5), L(F##$$word6), L(F##$$word7)}
static LineageBoundary readCache(SBoardSocGsim &d) {
    LineageBoundary b;
    b.valid = L(cache$$valid); b.ready = L(cache$$ready);
    b.request = {L(cache$$request$$address), L(cache$$request$$data), L(cache$$request$$translationEpoch),
        unsigned(L(cache$$request$$mask)), unsigned(L(cache$$request$$size)), unsigned(L(cache$$request$$atomicOp)),
        bool(L(cache$$request$$write)), bool(L(cache$$request$$atomic)), bool(L(cache$$request$$virtualized)),
        bool(L(cache$$request$$uncached)), bool(L(cache$$request$$precheckedLoad)),
        bool(L(cache$$request$$prefetchNextAllowed))};
    b.proof = {{L(cache$$proof$$bits$$token$$tag), unsigned(L(cache$$proof$$bits$$token$$index))},
        L(cache$$proof$$bits$$epoch), L(cache$$proof$$bits$$address), L(cache$$proof$$bits$$data),
        unsigned(L(cache$$proof$$bits$$mask)), unsigned(L(cache$$proof$$bits$$size)), bool(L(cache$$proof$$valid)),
        bool(L(cache$$proof$$bits$$headAuthorized)), bool(L(cache$$proof$$bits$$physicalPmpAllowed)),
        bool(L(cache$$proof$$bits$$originalPhysical)), bool(L(cache$$proof$$bits$$integerOrigin)),
        bool(L(cache$$proof$$bits$$legacyPostedAccepted)), bool(L(cache$$proof$$bits$$finalChecked))};
    b.responseValid = L(cache$$responseValid); b.responseReady = L(cache$$responseReady);
    b.responseData = L(cache$$response$$data); b.error = L(cache$$response$$error);
    b.pageFault = L(cache$$response$$pageFault);
    return b;
}
struct BoardLineageLedger {
    const guest::Program &program;
    Test &test;
    LineageTrace &trace;
    posted_seal_regression::Witness sealWitness;
    bool enabled = false, injectProofToken = false, tokenInjected = false;
    std::map<LineageToken, std::pair<uint64_t, uint32_t>> allocated;
    std::map<LineageToken, LineageWitness> launched;
    std::map<unsigned, LineageToken> lastRetired;
    std::set<LineageToken> completed, retiredMemory, cacheAccepted, cacheReturned;
    std::deque<LineageWitness> requestOwners, responseOwners;
    std::map<BoardOwnerKey, BoardOwner> owners;
    std::map<LineageToken, BoardMember> members;
    std::map<uint64_t, BoardOwnerKey> grantSources, grantSinks, wbSlots;
    std::set<LineageToken> fallbackTokens, fallbackAcked;
    posted_board::AxiAccounting axi;
    std::array<BoardObservedWire, 9> previousWires{};
    LineageBoundary previous;
    unsigned retired = 0, storeRequests = 0, loadRequests = 0, proofRequests = 0;
    uint64_t requestHolds = 0, responseHolds = 0, busyCycles = 0;
    uint64_t blockedLoad = 0, retiredWhileBPending = 0, reusedWhileBPending = 0;
    uint64_t firstWriteCycle = 0, firstBCycle = 0, firstAckCycle = 0, heldBCycles = 0;
    uint64_t releaseAddress = 0, releaseSource = 0, releaseBeats = 0;
    uint64_t delayedWrites = 0, lastDelayedWrite = 0, lastBusyState = UINT64_MAX;
    bool kernelStarted = false, flushStarted = false;
    bool firstWrite = false, firstB = false, firstAck = false, flushSeen = false;
    bool cacheFlushDoneSeen = false, fenceICommitted = false, done = false;
    bool postedDirtyVictimSeen = false;
    BoardLineageLedger(const guest::Program &p, Test &t, LineageTrace &log, bool on, bool inject)
        : program(p), test(t), trace(log), sealWitness(p), enabled(on), injectProofToken(inject) {}

    BoardOwner &owner(const BoardOwnerEvent &event) {
        const auto found = owners.find(event.context.owner);
        require(found != owners.end() && !found->second.released && found->second.event == event,
            "cache owner event changed original full generation/cohort/epoch/reservation");
        return found->second;
    }
    void ownerTrace(const char *kind, const BoardOwnerEvent &event) {
        trace.event(test.cycles, kind, {{"slot", event.context.owner.slot}, {"generation", event.context.owner.generation},
            {"cohort_slot", event.context.cohort.slot}, {"cohort_generation", event.context.cohort.generation},
            {"epoch", event.context.epoch}, {"line", event.context.line}, {"mshr", event.reservation.mshr},
            {"set", event.reservation.set}, {"way", event.reservation.way},
            {"victim_valid", event.reservation.victimValid}, {"victim_dirty", event.reservation.victimDirty},
            {"victim_address", event.reservation.victimAddress}});
    }
    void observeOwners(SBoardSocGsim &d, const std::optional<LineageWitness> &accepted) {
        const uint64_t cycle = test.cycles;
        if (L(owner$$accepted$$valid)) {
            require(enabled && accepted && accepted->intent.store, "posted member has no same-edge original cache store acceptance");
            const LineageToken token{L(owner$$accepted$$bits$$member$$token$$tag), unsigned(L(owner$$accepted$$bits$$member$$token$$index))};
            const auto context = CONTEXT(owner$$accepted$$bits$$member$$context);
            const auto reservation = RESERVATION(owner$$accepted$$bits$$reservation);
            const BoardOwnerEvent event{context, reservation};
            require(token == accepted->token && context.epoch == accepted->epoch &&
                context.line == (accepted->intent.address & ~UINT64_C(63)) &&
                reservation.set == ((context.line >> 6) & 255) && reservation.way < 2 && reservation.mshr < 2 &&
                (!reservation.victimDirty || reservation.victimValid), "posted acceptance changed raw CPU token/line/set/epoch");
            if (L(owner$$accepted$$bits$$newLine)) {
                for (const auto &item : owners) require(item.second.released ||
                    (item.second.event.context.owner.slot != context.owner.slot &&
                     item.second.event.reservation.mshr != reservation.mshr), "new owner reused a live line/MSHR resource");
                BoardOwner fresh; fresh.event = event;
                for (unsigned b = 0; b < 64; ++b) fresh.bytes[b] = guest::byteAt(program.initial, context.line + b);
                require(owners.emplace(context.owner, fresh).second, "full cache owner generation reused");
            }
            auto &entry = owner(event);
            require(!entry.refilled && !entry.installed, "new store merged after owner refill/install sealed the line");
            const uint64_t ticket = L(owner$$accepted$$bits$$member$$responseTicket);
            for (const auto &old : members) require(old.second.ticket != ticket ||
                old.second.acknowledged || cacheReturned.count(old.first),
                "response ticket reused before original member's real cache return");
            require(ticket < 2 && members.emplace(token, BoardMember{context, ticket}).second,
                "posted member token duplicated or response ticket outside actual capacity");
            entry.members.insert(token);
            sealWitness.member({token.tag, token.index}, accepted->intent.pc, context.line,
                {context.owner.slot, context.owner.generation}, cycle);
            const auto &intent = accepted->intent;
            for (unsigned b = 0; b < (1U << intent.size); ++b)
                entry.bytes.at(unsigned(intent.address - context.line) + b) = intent.rawData >> (b * 8);
            ownerTrace("owner_accept", event);
            trace.event(cycle, "owner_member", {{"tag", token.tag}, {"index", token.index},
                {"ticket", ticket}, {"new_line", L(owner$$accepted$$bits$$newLine)},
                {"owner_slot", context.owner.slot}, {"owner_generation", context.owner.generation}});
        }
        if (L(owner$$fallback$$valid)) {
            const LineageToken token{L(owner$$fallback$$bits$$token$$tag), unsigned(L(owner$$fallback$$bits$$token$$index))};
            require(enabled && accepted && accepted->token == token && fallbackTokens.insert(token).second,
                "fallback token lacks same-edge original cache acceptance");
        }
        if (L(owner$$fallbackAck$$valid)) {
            const LineageToken token{L(owner$$fallbackAck$$bits$$token$$tag), unsigned(L(owner$$fallbackAck$$bits$$token$$index))};
            require(fallbackTokens.count(token) && cacheReturned.count(token) && fallbackAcked.insert(token).second,
                "fallback acknowledgement changed or repeated its original token");
        }
        auto memberEvent = [&](LineageToken token, const BoardContext &context, uint64_t ticket, bool drain) {
            require(members.count(token), "posted member event has no original full-token member");
            auto &member = members.at(token);
            require(member.context == context && member.ticket == ticket, "member event changed its full original owner/ticket");
            auto &entry = owners.at(context.owner);
            require(!entry.released && cacheReturned.count(token), "member event preceded actual cache response or followed release");
            if (drain) { require(member.acknowledged && !member.drained && entry.installed,
                    "member drain duplicated or preceded original ack/install"); member.drained = true; }
            else { require(!member.acknowledged, "member acknowledgement duplicated"); member.acknowledged = true; }
            trace.event(cycle, drain ? "owner_member_drained" : "owner_member_ack", {{"tag", token.tag},
                {"index", token.index}, {"ticket", ticket}, {"slot", context.owner.slot}, {"generation", context.owner.generation}});
        };
#define MEMBER_EVENT(F, DRAIN) if (L(owner$$##F##$$valid)) memberEvent( \
    {L(owner$$##F##$$bits$$token$$tag), unsigned(L(owner$$##F##$$bits$$token$$index))}, \
    CONTEXT(owner$$##F##$$bits$$context), L(owner$$##F##$$bits$$responseTicket), DRAIN)
        MEMBER_EVENT(acknowledged, false);
#undef MEMBER_EVENT
        if (L(owner$$acquired$$valid)) {
            const auto event = OWNER_EVENT(owner$$acquired$$bits); auto &entry = owner(event);
            require(!entry.acquired && L(tlA$$valid) && L(tlA$$ready) && L(tlA$$bits$$opcode) == 6 &&
                L(tlA$$bits$$address) == event.context.line, "posted acquire lacks original real cache A handshake");
            entry.acquired = true; entry.source = L(tlA$$bits$$source);
            require(grantSources.emplace(entry.source, event.context.owner).second, "posted acquire reused a live TL source");
            ownerTrace("owner_acquired", event);
        }
        if (L(tlD$$valid) && L(tlD$$ready) && L(tlD$$bits$$opcode) == 5 && grantSources.count(L(tlD$$bits$$source))) {
            auto &entry = owners.at(grantSources.at(L(tlD$$bits$$source)));
            require(entry.grantBeats < 8 && !L(tlD$$bits$$denied) && !L(tlD$$bits$$corrupt) &&
                L(tlD$$bits$$data) == guest::wordAt(program.initial, entry.event.context.line + entry.grantBeats * 8),
                "posted real GrantData differs from independent initial byte memory");
            if (!entry.grantBeats) entry.sink = L(tlD$$bits$$sink);
            require(entry.sink == L(tlD$$bits$$sink), "posted GrantData changed original sink");
            if (++entry.grantBeats == 8) require(grantSinks.emplace(entry.sink, entry.event.context.owner).second,
                "posted GrantData reused live E acknowledgement sink");
        }
        if (L(tlE$$valid) && L(tlE$$ready) && grantSinks.count(L(tlE$$bits$$sink))) {
            const auto key = grantSinks.at(L(tlE$$bits$$sink)); auto &entry = owners.at(key);
            require(entry.grantBeats == 8 && !entry.grantAcked, "posted E acknowledgement duplicated/incomplete");
            entry.grantAcked = true; grantSources.erase(entry.source); grantSinks.erase(entry.sink);
            ownerTrace("owner_grant_ack", entry.event);
        }
        if (L(owner$$refillValid)) {
            const auto event = OWNER_EVENT(owner$$refillEvent); auto &entry = owner(event);
            require(entry.acquired && entry.grantAcked && !entry.refilled && !L(owner$$refillError),
                "posted refill preceded real A/Grant/E or repeated original owner");
            const auto words = LINE_WORDS(owner$$refill);
            for (unsigned b = 0; b < 8; ++b) require(words[b] == guest::wordAt(program.initial, event.context.line + b * 8),
                "posted refill words differ from independently observed backing bytes");
            entry.refilled = true; ownerTrace("owner_refilled", event);
        }
        if (L(owner$$installedValid)) {
            const auto event = OWNER_EVENT(owner$$installedEvent); auto &entry = owner(event);
            require(entry.refilled && !entry.installed && L(lineWriteValid) && L(lineWritePosted) &&
                L(lineWriteAddress) == event.context.line, "posted install lacks original refill/actual SRAM line write");
            const auto installed = LINE_WORDS(owner$$installed), written = LINE_WORDS(lineWrite);
            for (unsigned word = 0; word < 8; ++word) {
                uint64_t expected = 0;
                for (unsigned b = 0; b < 8; ++b) expected |= uint64_t(entry.bytes[word * 8 + b]) << (8 * b);
                require(installed[word] == expected && written[word] == expected,
                    "actual posted SRAM install differs from ordered independent raw-store byte merge");
                trace.event(cycle, "installed_word", {{"line", event.context.line}, {"word", word},
                    {"expected", expected}, {"installed", installed[word]}, {"written", written[word]}});
            }
            entry.installed = true;
            sealWitness.install(event.context.line, {event.context.owner.slot, event.context.owner.generation}, cycle);
            ownerTrace("owner_installed", event);
        }
        if (L(owner$$drained$$valid)) memberEvent(
            {L(owner$$drained$$bits$$token$$tag), unsigned(L(owner$$drained$$bits$$token$$index))},
            CONTEXT(owner$$drained$$bits$$context), L(owner$$drained$$bits$$responseTicket), true);
        auto writeback = [&](const char *kind, const BoardOwnerEvent &event, uint64_t slot,
            const BoardOwnerKey &ticketOwner, unsigned phase) {
            auto &entry = owner(event);
            require(event.reservation.victimValid && event.reservation.victimDirty && ticketOwner == event.context.owner && slot < 2,
                "posted writeback lacks its original dirty victim/full owner ticket");
            if (phase == 0) {
                require(!entry.attached && wbSlots.emplace(slot, event.context.owner).second,
                    "writeback attached twice or reused a live WB slot");
                entry.attached = true; entry.wbSlot = slot; entry.wbOwner = ticketOwner;
                require(event.context.line == guest::scratchC && (event.reservation.victimAddress == guest::scratchA ||
                    event.reservation.victimAddress == guest::scratchB), "posted dirty victim is not authored A/B conflict");
                postedDirtyVictimSeen = true;
            } else {
                require(entry.attached && entry.wbSlot == slot && entry.wbOwner == ticketOwner &&
                    wbSlots.count(slot) && wbSlots.at(slot) == event.context.owner, "posted writeback changed original full ticket");
                if (phase == 1) {
                    require(!entry.sent && L(tlC$$valid) && L(tlC$$ready) && L(tlC$$bits$$opcode) == 7 &&
                        L(tlC$$bits$$address) == event.reservation.victimAddress &&
                        L(tlC$$bits$$source) == slot + 2 && releaseBeats == 8,
                        "posted writeback sent event lacks real original C-last");
                    entry.sent = true;
                } else {
                    require(entry.sent && !entry.completed && firstAck && firstAckCycle == cycle &&
                        L(tlD$$valid) && L(tlD$$ready) && L(tlD$$bits$$opcode) == 6 && L(tlD$$bits$$source) == slot + 2,
                        "posted writeback completion lacks original final real ReleaseAck after DDR B");
                    entry.completed = true; wbSlots.erase(slot);
                }
            }
            ownerTrace(kind, event);
            trace.event(cycle, "writeback_ticket", {{"phase", phase}, {"slot", slot},
                {"owner_slot", ticketOwner.slot}, {"owner_generation", ticketOwner.generation}});
        };
#define WB_EVENT(F, PHASE) if (L(owner$$##F##$$valid)) writeback("owner_" #F, OWNER_EVENT(owner$$##F##$$bits), \
    L(owner$$##F##$$bits$$ticket$$slot), OWNER_KEY(owner$$##F##$$bits$$ticket$$owner), PHASE)
        WB_EVENT(attached, 0); WB_EVENT(sent, 1); WB_EVENT(completed, 2);
#undef WB_EVENT
        require(!L(owner$$cancelled$$valid), "authored deterministic dirty victim unexpectedly cancelled");
        if (L(owner$$released$$valid)) {
            const auto event = OWNER_EVENT(owner$$released$$bits); auto &entry = owner(event);
            require(entry.installed && (!event.reservation.victimDirty || entry.completed),
                "posted resource release preceded original SRAM install/final victim Ack");
            for (const auto &token : entry.members) require(members.at(token).acknowledged && members.at(token).drained,
                "posted owner released a live original store member");
            entry.released = true;
            sealWitness.release(event.context.line, {event.context.owner.slot, event.context.owner.generation}, cycle);
            ownerTrace("owner_released", event);
        }
    }

    void allocation(bool valid, LineageToken token, uint64_t pc, uint32_t instruction) {
        if (!valid) return;
        require(program.rawInstruction(pc, instruction), "Board allocation is not an authored raw ROM instruction");
        require(allocated.emplace(token, std::make_pair(pc, instruction)).second, "Board reused a full allocation token");
        if (firstWrite && !firstAck) {
            const auto old = lastRetired.find(token.index);
            if (old != lastRetired.end() && old->second.tag != token.tag) ++reusedWhileBPending;
        }
        trace.event(test.cycles, "allocation", {{"tag", token.tag}, {"index", token.index},
            {"pc", pc}, {"instruction", instruction}});
    }
    void commit(bool valid, LineageToken token, uint64_t pc, uint32_t instruction,
        unsigned rd, bool writes, uint64_t data, uint64_t next) {
        if (!valid) return;
        require(allocated.count(token) && allocated.at(token) == std::make_pair(pc, instruction),
            "Board retirement changed original allocation token/PC/raw instruction");
        const auto &e = done ? program.trace.back() : program.trace.at(retired);
        require(pc == e.pc && instruction == e.instruction && next == e.next &&
            rd == e.rd && writes == (e.rd != 0) && (!writes || data == e.value),
            "Board commit differs from independent RV64 interpreter at PC " + std::to_string(pc));
        if (e.memory) {
            require(launched.count(token) && completed.count(token), "Board memory retired without its full-token completion");
            require(retiredMemory.insert(token).second, "Board memory token retired twice");
            sealWitness.retire({token.tag, token.index}, pc);
        }
        if (e.fenceI) {
            require(flushSeen && cacheFlushDoneSeen && firstAck, "FENCE.I retired before real final flush/victim acknowledgement");
            fenceICommitted = true;
        }
        if (!done) { ++retired; done = e.done; }
        lastRetired[token.index] = token;
        if (firstWrite && !firstAck) ++retiredWhileBPending;
        trace.event(test.cycles, "commit", {{"tag", token.tag}, {"index", token.index},
            {"pc", pc}, {"instruction", instruction}, {"rd", rd}, {"writes_rd", writes},
            {"data", data}, {"next", next}});
    }
    void observe(SBoardSocGsim &d) {
        auto &ddr = test.ddr;
        const uint64_t cycle = test.cycles;
        posted_board::AxiSample sample;
        sample.arValid = d.get_io$$ddrAxi$$ar$$valid(); sample.arReady = ddr.arReady;
        sample.awValid = d.get_io$$ddrAxi$$aw$$valid(); sample.awReady = ddr.awReady;
        sample.wValid = d.get_io$$ddrAxi$$w$$valid(); sample.wReady = ddr.wReady;
        sample.rValid = ddr.rValid; sample.rReady = d.get_io$$ddrAxi$$r$$ready();
        sample.bValid = ddr.bValid; sample.bReady = d.get_io$$ddrAxi$$b$$ready();
        sample.arId = d.get_io$$ddrAxi$$ar$$bits$$id(); sample.arLen = d.get_io$$ddrAxi$$ar$$bits$$len();
        sample.arSize = d.get_io$$ddrAxi$$ar$$bits$$size(); sample.awId = d.get_io$$ddrAxi$$aw$$bits$$id();
        sample.awLen = d.get_io$$ddrAxi$$aw$$bits$$len(); sample.awSize = d.get_io$$ddrAxi$$aw$$bits$$size();
        sample.wLast = d.get_io$$ddrAxi$$w$$bits$$last(); sample.wStrobe = d.get_io$$ddrAxi$$w$$bits$$strb();
        sample.bId = ddr.wId;
        uint64_t rData = 0, rResponse = 0;
        if (ddr.rValid) {
            const auto selected = ddr.selected();
            require(selected != ddr.pendingReads.end(), "driven R lacks unchanged DDR model transaction");
            sample.rId = selected->id; sample.rLast = selected->beat + 1 == selected->count;
            rData = ddr.memory.at((selected->address + (selected->beat << selected->size)) & ~7U);
            rResponse = selected->error && sample.rLast ? 2 : 0;
        }
        if (!kernelStarted && L(startValid) && L(startReady)) {
            kernelStarted = true;
            trace.event(cycle, "kernel_window_begin_first_memory_launch", {});
        }
        if (kernelStarted && !flushStarted && (L(flushRequest) || (L(headValid) && L(headPc) == program.fenceIPc))) {
            flushStarted = true;
            trace.event(cycle, "flush_window_begin_fence_i_head", {});
        }
        trace.event(cycle, "edge", {{"ar_valid", sample.arValid}, {"ar_ready", sample.arReady},
            {"ar_address", d.get_io$$ddrAxi$$ar$$bits$$addr()}, {"ar_id", sample.arId},
            {"ar_len", sample.arLen}, {"ar_size", sample.arSize},
            {"aw_valid", sample.awValid}, {"aw_ready", sample.awReady},
            {"aw_address", d.get_io$$ddrAxi$$aw$$bits$$addr()}, {"aw_id", sample.awId},
            {"aw_len", sample.awLen}, {"aw_size", sample.awSize},
            {"w_valid", sample.wValid}, {"w_ready", sample.wReady}, {"w_last", sample.wLast},
            {"w_data", d.get_io$$ddrAxi$$w$$bits$$data()}, {"w_strb", sample.wStrobe},
            {"r_valid", sample.rValid}, {"r_ready", sample.rReady}, {"r_id", sample.rId},
            {"r_last", sample.rLast}, {"r_data", rData}, {"r_resp", rResponse},
            {"b_valid", sample.bValid}, {"b_ready", sample.bReady}, {"b_id", sample.bId},
            {"b_resp", ddr.writeError ? 2U : 0U}, {"ddr_writing", ddr.writing}, {"ddr_responding", ddr.responding},
            {"ddr_b_due", ddr.bDue}, {"cache_busy", L(cacheBusy)}, {"cpu_busy", L(cpuBusy)},
            {"seal", L(seal)}, {"end_episode", L(endEpisode)}, {"epoch", L(epoch)},
            {"head_valid", L(headValid)}, {"head_pc", L(headPc)}, {"head_tag", L(headToken$$tag)},
            {"head_index", L(headToken$$index)}, {"start_valid", L(startValid)}, {"start_ready", L(startReady)},
            {"flush_request", L(flushRequest)}, {"cache_flush_done", L(cacheFlushDone)}, {"flush_ready", L(flushReady)},
            {"tl_a_valid", L(tlA$$valid)}, {"tl_a_ready", L(tlA$$ready)}, {"tl_a_opcode", L(tlA$$bits$$opcode)},
            {"tl_a_address", L(tlA$$bits$$address)}, {"tl_a_source", L(tlA$$bits$$source)},
            {"tl_c_valid", L(tlC$$valid)}, {"tl_c_ready", L(tlC$$ready)}, {"tl_c_opcode", L(tlC$$bits$$opcode)},
            {"tl_c_address", L(tlC$$bits$$address)}, {"tl_c_source", L(tlC$$bits$$source)}, {"tl_c_data", L(tlC$$bits$$data)},
            {"tl_d_valid", L(tlD$$valid)}, {"tl_d_ready", L(tlD$$ready)}, {"tl_d_opcode", L(tlD$$bits$$opcode)},
            {"tl_d_source", L(tlD$$bits$$source)}, {"tl_d_sink", L(tlD$$bits$$sink)}, {"tl_d_data", L(tlD$$bits$$data)},
            {"tl_d_denied", L(tlD$$bits$$denied)}, {"tl_d_corrupt", L(tlD$$bits$$corrupt)},
            {"tl_e_valid", L(tlE$$valid)}, {"tl_e_ready", L(tlE$$ready)}, {"tl_e_sink", L(tlE$$bits$$sink)}});
        // Full payload stability complements the counting ledger's selected
        // metadata checks. Slave R/B come from the actual values drive() set.
        const std::array<BoardObservedWire, 9> wires{{
            {sample.arValid, sample.arReady, {sample.arId, d.get_io$$ddrAxi$$ar$$bits$$addr(), sample.arLen,
                sample.arSize, d.get_io$$ddrAxi$$ar$$bits$$burst(), d.get_io$$ddrAxi$$ar$$bits$$lock(),
                d.get_io$$ddrAxi$$ar$$bits$$cache(), d.get_io$$ddrAxi$$ar$$bits$$prot(), d.get_io$$ddrAxi$$ar$$bits$$qos()}},
            {sample.awValid, sample.awReady, {sample.awId, d.get_io$$ddrAxi$$aw$$bits$$addr(), sample.awLen,
                sample.awSize, d.get_io$$ddrAxi$$aw$$bits$$burst(), d.get_io$$ddrAxi$$aw$$bits$$lock(),
                d.get_io$$ddrAxi$$aw$$bits$$cache(), d.get_io$$ddrAxi$$aw$$bits$$prot(), d.get_io$$ddrAxi$$aw$$bits$$qos()}},
            {sample.wValid, sample.wReady, {d.get_io$$ddrAxi$$w$$bits$$data(), sample.wStrobe, sample.wLast}},
            {sample.rValid, sample.rReady, {sample.rId, rData, rResponse, sample.rLast}},
            {sample.bValid, sample.bReady, {sample.bId, ddr.writeError ? 2U : 0U}},
            {bool(L(tlA$$valid)), bool(L(tlA$$ready)), {L(tlA$$bits$$opcode), L(tlA$$bits$$param), L(tlA$$bits$$size),
                L(tlA$$bits$$source), L(tlA$$bits$$address), L(tlA$$bits$$mask), L(tlA$$bits$$data), L(tlA$$bits$$corrupt)}},
            {bool(L(tlC$$valid)), bool(L(tlC$$ready)), {L(tlC$$bits$$opcode), L(tlC$$bits$$param), L(tlC$$bits$$size),
                L(tlC$$bits$$source), L(tlC$$bits$$address), L(tlC$$bits$$data), L(tlC$$bits$$corrupt)}},
            {bool(L(tlD$$valid)), bool(L(tlD$$ready)), {L(tlD$$bits$$opcode), L(tlD$$bits$$param), L(tlD$$bits$$size),
                L(tlD$$bits$$source), L(tlD$$bits$$sink), L(tlD$$bits$$data), L(tlD$$bits$$denied), L(tlD$$bits$$corrupt)}},
            {bool(L(tlE$$valid)), bool(L(tlE$$ready)), {L(tlE$$bits$$sink)}}
        }};
        static constexpr const char *wireNames[] = {"axi_ar", "axi_aw", "axi_w", "axi_r", "axi_b",
            "tl_a", "tl_c", "tl_d", "tl_e"};
        for (unsigned n = 0; n < wires.size(); ++n) {
            const auto &wire = wires[n], &old = previousWires[n];
            if (wire.valid || (old.valid && !old.ready)) trace.event(cycle, wireNames[n], {
                {"valid", wire.valid}, {"ready", wire.ready}, {"field0", wire.payload[0]},
                {"field1", wire.payload[1]}, {"field2", wire.payload[2]}, {"field3", wire.payload[3]},
                {"field4", wire.payload[4]}, {"field5", wire.payload[5]}, {"field6", wire.payload[6]},
                {"field7", wire.payload[7]}, {"field8", wire.payload[8]}, {"field9", wire.payload[9]}});
            if (old.valid && !old.ready) require(wire.valid && wire.payload == old.payload,
                std::string("held full bus payload changed on ") + wireNames[n]);
        }
        previousWires = wires;
        axi.sample(sample, flushStarted ? posted_board::Window::Flush :
            kernelStarted ? posted_board::Window::Kernel : posted_board::Window::None);
        // This hook sees the evaluated DUT and the exact slave inputs drive()
        // supplied for this edge. At the first cycle after an accepted WLAST the
        // original model's three-cycle B latency still prevents BVALID. Extending
        // its due date delays an actual accepted write, not a synthetic owner.
        if (ddr.responding && ddr.writes != lastDelayedWrite) {
            require(!ddr.bValid && ddr.wBeat == ddr.wCount, "B delay was installed after response became valid");
            lastDelayedWrite = ddr.writes; ++delayedWrites;
            ddr.bDue = ddr.now + 256;
            trace.event(cycle, "real_write_response_delayed", {{"write_number", ddr.writes},
                {"address", ddr.wAddr}, {"id", ddr.wId}, {"w_beats", ddr.wBeat}, {"b_due", ddr.bDue}});
        }
        const uint64_t busyState = uint64_t(L(cacheBusy)) | (uint64_t(L(cpuBusy)) << 1) |
            (uint64_t(L(episodeActive)) << 2) | (uint64_t(L(prefetchBusy)) << 3);
        if (busyState != lastBusyState) {
            trace.event(cycle, "busy", {{"cache", L(cacheBusy)}, {"cpu", L(cpuBusy)},
                {"episode", L(episodeActive)}, {"prefetch", L(prefetchBusy)}});
            lastBusyState = busyState;
        }
        if (L(cacheBusy)) ++busyCycles;
        if (L(headValid)) sealWitness.head(L(headPc), L(headInstruction), L(seal));
#define ALLOC(N) allocation(L(alloc##N##$$valid), \
    {L(alloc##N##$$bits$$token$$tag), unsigned(L(alloc##N##$$bits$$token$$index))}, \
    L(alloc##N##$$bits$$pc), L(alloc##N##$$bits$$instruction))
        ALLOC(0); ALLOC(1);
#undef ALLOC
        const auto headIntent = program.intents.find(L(headPc));
        if (L(headValid) && headIntent != program.intents.end() && !headIntent->second.store && L(cacheBusy)) ++blockedLoad;
        if (L(startValid) && L(startReady)) {
            const LineageToken token{L(start$$token$$tag), unsigned(L(start$$token$$index))};
            require(allocated.count(token), "memory launch lacks original Board allocation token");
            const uint64_t pc = allocated.at(token).first;
            require(program.intents.count(pc), "memory launch PC does not decode to authored guest memory intent");
            const auto &intent = program.intents.at(pc);
            require(L(start$$pc) == pc && L(start$$address) == intent.address &&
                L(start$$size) == intent.size && bool(L(start$$store)) == intent.store &&
                (!intent.store || L(start$$data) == intent.rawData) && !L(start$$atomic) &&
                !L(start$$virtualized) && !L(start$$accessDenied) && !L(pmpDenied) && L(dataPrivilege) == 3,
                "Board memory launch differs from independent raw physical RV64 intent");
            if (intent.store) {
                const LineageToken head{L(headToken$$tag), unsigned(L(headToken$$index))};
                require(L(headValid) && head == token && L(headPc) == pc &&
                    L(headInstruction) == allocated.at(token).second,
                    "Board store launch was not the actual full-token ROB head");
            } else if (enabled) require(!L(cacheBusy), "ordinary load launched across real posted cache ownership");
            LineageWitness witness{token, intent, L(epoch)};
            require(launched.emplace(token, witness).second, "Board memory token launched twice");
            sealWitness.launch({token.tag, token.index}, pc, cycle);
            requestOwners.push_back(witness);
            trace.event(cycle, "cpu_memory_launch", {{"tag", token.tag}, {"index", token.index},
                {"pc", pc}, {"instruction", allocated.at(token).second}, {"address", intent.address},
                {"raw_data", intent.rawData}, {"lane_data", intent.laneData}, {"mask", intent.mask},
                {"size", intent.size}, {"store", intent.store}, {"epoch", witness.epoch}});
        }
        auto b = readCache(d);
        std::optional<LineageWitness> acceptedCache;
        if (previous.valid && !previous.ready) {
            require(b.valid && b.request == previous.request && b.proof == previous.proof,
                "Board held cache request/proof changed");
            ++requestHolds;
        }
        if (previous.responseValid && !previous.responseReady) {
            require(b.responseValid && b.responseData == previous.responseData &&
                b.error == previous.error && b.pageFault == previous.pageFault, "Board held cache response changed");
            ++responseHolds;
        }
        require(!b.proof.valid || b.valid, "Board cache proof has no real request");
        if (b.valid) {
            require(!requestOwners.empty(), "Board cache request has no independently decoded CPU launch owner");
            const auto owner = requestOwners.front();
            if (injectProofToken && b.proof.valid && !tokenInjected) {
                trace.event(cycle, "negative_token_mutation", {{"original_tag", b.proof.token.tag},
                    {"mutated_tag", b.proof.token.tag ^ (UINT64_C(1) << 32)}, {"index", b.proof.token.index}});
                b.proof.token.tag ^= UINT64_C(1) << 32; tokenInjected = true;
                try { compareRequest(owner, b, enabled); }
                catch (const std::runtime_error &error) {
                    require(std::string(error.what()) == "cache proof changed original full token/epoch/byte payload",
                        "token control failed at a different oracle");
                    throw BoardOracleRejection("token");
                }
                throw std::runtime_error("injected high tag bit escaped original-token oracle");
            }
            compareRequest(owner, b, enabled);
            trace.event(cycle, "cache_request", {{"ready", b.ready}, {"tag", owner.token.tag},
                {"index", owner.token.index}, {"pc", owner.intent.pc}, {"address", b.request.address},
                {"data", b.request.data}, {"mask", b.request.mask}, {"size", b.request.size},
                {"store", b.request.write}, {"proof", b.proof.valid}, {"proof_tag", b.proof.token.tag},
                {"proof_index", b.proof.token.index}, {"proof_epoch", b.proof.epoch},
                {"proof_address", b.proof.address}, {"proof_data", b.proof.data},
                {"proof_mask", b.proof.mask}, {"proof_size", b.proof.size},
                {"head_authorized", b.proof.head}, {"pmp_allowed", b.proof.pmp},
                {"physical", b.proof.physical}, {"integer", b.proof.integer},
                {"legacy_accepted", b.proof.legacy}, {"final_checked", b.proof.checked}});
            if (b.ready) {
                acceptedCache = owner;
                require(cacheAccepted.insert(owner.token).second, "Board cache accepted an original token twice");
                responseOwners.push_back(owner); requestOwners.pop_front();
                if (owner.intent.store) ++storeRequests; else ++loadRequests;
                if (b.proof.valid) ++proofRequests;
            }
        }
        if (b.responseValid) {
            require(!responseOwners.empty(), "Board cache response has no original accepted request");
            const auto &owner = responseOwners.front();
            require(!b.error && !b.pageFault && (owner.intent.store || b.responseData == owner.intent.responseData),
                "Board cache response differs from independent byte-memory load");
            trace.event(cycle, "cache_response", {{"ready", b.responseReady}, {"tag", owner.token.tag},
                {"index", owner.token.index}, {"data", b.responseData}, {"store", owner.intent.store}});
            if (b.responseReady) {
                require(cacheReturned.insert(owner.token).second, "Board cache response repeated an original token");
                responseOwners.pop_front();
            }
        }
        previous = b;
        if (L(completionValid) && L(completionReady)) {
            const LineageToken token{L(completion$$token$$tag), unsigned(L(completion$$token$$index))};
            require(launched.count(token) && completed.insert(token).second && !L(completion$$exception),
                "Board memory completion lacks a live nonfaulting original full token");
            const auto &owner = launched.at(token);
            if (!owner.intent.store) require(cacheReturned.count(token) && L(completion$$data) == owner.intent.responseData,
                "Board ordinary load completion changed independently expected data");
            trace.event(cycle, "memory_completion", {{"tag", token.tag}, {"index", token.index},
                {"data", L(completion$$data)}, {"next_pc", L(completion$$nextPc)}});
        }
        if (L(tlC$$valid) && L(tlC$$ready) && L(tlC$$bits$$opcode) == 7 && !firstAck) {
            if (!releaseBeats) {
                releaseAddress = L(tlC$$bits$$address); releaseSource = L(tlC$$bits$$source);
                require(releaseAddress == guest::scratchA || releaseAddress == guest::scratchB,
                    "third same-set store did not release an initialized dirty victim");
            }
            require(L(tlC$$bits$$address) == releaseAddress && L(tlC$$bits$$source) == releaseSource && releaseBeats < 8,
                "initial dirty ReleaseData changed line/source or beat count");
            ++releaseBeats;
            trace.event(cycle, "victim_release_beat", {{"address", releaseAddress}, {"source", releaseSource},
                {"beat", releaseBeats - 1}, {"data", L(tlC$$bits$$data)}});
        }
        if (d.get_io$$ddrAxi$$aw$$valid() && ddr.awReady && !firstWrite) {
            require(releaseBeats == 8 && d.get_io$$ddrAxi$$aw$$bits$$addr() + guest::ddrBase == releaseAddress,
                "first actual DDR write lacks the full dirty victim ReleaseData lineage");
            firstWrite = true; firstWriteCycle = cycle;
            trace.event(cycle, "victim_ddr_aw", {{"address", d.get_io$$ddrAxi$$aw$$bits$$addr()},
                {"id", d.get_io$$ddrAxi$$aw$$bits$$id()}, {"len", d.get_io$$ddrAxi$$aw$$bits$$len()}});
        }
        if (firstWrite && !firstAck && enabled) {
            require(L(cacheBusy) && L(cpuBusy), "real dirty victim responsibility disappeared before final ReleaseAck");
        }
        if (firstWrite && !firstB && ddr.responding && !ddr.bValid) ++heldBCycles;
        if (ddr.bValid && d.get_io$$ddrAxi$$b$$ready() && !firstB) {
            require(firstWrite && ddr.wAddr + guest::ddrBase == releaseAddress, "first B lost its original DDR write owner");
            firstB = true; firstBCycle = cycle;
            trace.event(cycle, "victim_ddr_b", {{"id", ddr.wId}, {"address", ddr.wAddr}});
        }
        if (L(tlD$$valid) && L(tlD$$ready) && L(tlD$$bits$$opcode) == 6 && !firstAck) {
            require(firstB && L(tlD$$bits$$source) == releaseSource &&
                !L(tlD$$bits$$denied) && !L(tlD$$bits$$corrupt), "ReleaseAck preceded/mismatched the actual DDR B");
            firstAck = true; firstAckCycle = cycle;
            trace.event(cycle, "victim_release_ack", {{"source", releaseSource}, {"address", releaseAddress}});
        }
        observeOwners(d, acceptedCache);
        require(!L(owner$$failed), "real cache posted owner entered failure state");
        if (L(flushRequest)) flushSeen = true;
        if (L(cacheFlushDone) && flushSeen) cacheFlushDoneSeen = true;
#define COMMIT(N) commit(L(commit##N##$$valid), \
    {L(commit##N##$$bits$$token$$tag), unsigned(L(commit##N##$$bits$$token$$index))}, \
    L(commit##N##$$bits$$pc), L(commit##N##$$bits$$instruction), L(commit##N##$$bits$$rd), \
    L(commit##N##$$bits$$writesRd), L(commit##N##$$bits$$data), L(commit##N##$$bits$$nextPc))
        COMMIT(0); COMMIT(1);
#undef COMMIT
    }
    static void callback(SBoardSocGsim &d, void *context) { static_cast<BoardLineageLedger *>(context)->observe(d); }
    bool drained(SBoardSocGsim &d) const {
        const auto &ddr = test.ddr;
        return done && fenceICommitted && firstAck && requestOwners.empty() && responseOwners.empty() &&
            !ddr.writing && !ddr.responding && ddr.pendingReads.empty() && !ddr.writeWaiting &&
            !L(cacheBusy) && !L(cpuBusy) && !L(prefetchBusy) && !L(cache$$valid) && !L(cache$$responseValid);
    }
    void finish() const {
        require(done && fenceICommitted && retired == program.trace.size(), "Board raw guest did not retire through final FENCE.I and done");
        require(launched.size() == program.intents.size() && completed.size() == launched.size() &&
            retiredMemory.size() == launched.size() && cacheAccepted.size() == launched.size() &&
            cacheReturned.size() == launched.size(), "Board full-token launch/cache/response/completion/retirement ledger is incomplete");
        require(storeRequests == program.stores && loadRequests == program.loads && proofRequests == (enabled ? program.stores : 0),
            "Board guest store/load/proof acceptance count changed");
        require(firstWrite && firstB && firstAck && releaseBeats == 8 && heldBCycles >= 256 && delayedWrites >= 3,
            "Board did not exercise actual delayed DDR B and all dirty final-flush writes");
        if (enabled) require(postedDirtyVictimSeen && busyCycles && blockedLoad &&
            retiredWhileBPending && reusedWhileBPending,
            "Board ON coverage incomplete: dirty_victim=" + std::to_string(postedDirtyVictimSeen) +
            " busy_cycles=" + std::to_string(busyCycles) + " blocked_load=" + std::to_string(blockedLoad) +
            " retire_during_write=" + std::to_string(retiredWhileBPending) +
            " reuse_during_write=" + std::to_string(reusedWhileBPending));
        for (const auto &entry : owners) require(entry.second.released, "final drain leaked full-generation cache owner");
        for (const auto &member : members) require(member.second.acknowledged && member.second.drained,
            "final drain leaked original full-token posted member");
        require(grantSources.empty() && grantSinks.empty() && wbSlots.empty() && fallbackTokens == fallbackAcked,
            "final drain leaked posted Grant/E/writeback/fallback ownership");
    }
};
#undef L
#undef OWNER_KEY
#undef CONTEXT
#undef RESERVATION
#undef OWNER_EVENT
#undef LINE_WORDS
#endif

int main(int argc, char **argv) {
    std::string failureTracePath;
    try {
        std::string variant, tracePath;
        bool controls = false, injectToken = false, injectByte = false;
        for (int n = 1; n < argc; ++n) {
            const std::string arg = argv[n];
            if (arg == "--self-test") controls = true;
            else if (arg.rfind("--variant=", 0) == 0) variant = arg.substr(10);
            else if (arg.rfind("--trace=", 0) == 0) tracePath = arg.substr(8);
            else if (arg == "--inject-proof-token") injectToken = true;
            else if (arg == "--inject-final-byte") injectByte = true;
            else throw std::runtime_error("unknown Board lineage argument " + arg);
        }
        if (controls) { hostControls(); return 0; }
#ifdef POSTED_BOARD_HOST_ONLY
        (void)injectToken; (void)injectByte;
        throw std::runtime_error("host-only build supports --self-test; no Board RTL was executed");
#else
        require((variant == "old-only" || variant == "off" || variant == "on") && !tracePath.empty(),
            "usage: --variant=old-only|off|on --trace=PATH [--inject-proof-token|--inject-final-byte]");
        require(!injectToken || variant == "on", "proof-token negative control needs the ON model");
        failureTracePath = tracePath;
        const auto program = guest::interpret();
        const auto artifactDirectory = std::filesystem::path(tracePath).parent_path();
        writeBinary(artifactDirectory / "guest.bin", program.bytes());
        LineageTrace trace(tracePath);
        trace.event(0, "case_begin", {{"enabled", variant == "on"}, {"inject_token", injectToken},
            {"inject_byte", injectByte}, {"ddr_base", guest::ddrBase}, {"dense_memory_begin", guest::memoryBegin},
            {"dense_memory_end", guest::memoryEnd}, {"guest_bytes", program.bytes().size()},
            {"b_delay_cycles", 256}, {"rtl_executed", 1}});
        for (const auto &e : program.trace) trace.event(0, "expected_instruction", {{"pc", e.pc},
            {"instruction", e.instruction}, {"next", e.next}, {"rd", e.rd}, {"value", e.value},
            {"memory", e.memory}, {"store", e.intent.store}, {"address", e.intent.address},
            {"raw_data", e.intent.rawData}, {"lane_data", e.intent.laneData}, {"mask", e.intent.mask},
            {"size", e.intent.size}, {"response_data", e.intent.responseData}});
        Test test(program.bytes());
        // MachinePlatform keeps the CPU reset while !ddrReady. Test enables
        // ddrReady immediately before returning, with no intervening tick.
        // Preload and observation thus precede the first active guest edge.
        test.ddr.memory = backing(program.initial);
        writeMemory(artifactDirectory, "initial-memory", test.ddr.memory);
        BoardLineageLedger ledger(program, test, trace, variant == "on", injectToken);
        test.observer = BoardLineageLedger::callback; test.observerContext = &ledger;
        unsigned settled = 0;
        const uint64_t deadline = test.cycles + 20000;
        while (test.cycles < deadline && settled < 16) {
            test.tick();
            settled = ledger.drained(*test.dut) ? settled + 1 : 0;
        }
        require(settled == 16, "Board guest/final real memory drain exceeded bounded cycle budget");
        trace.event(test.cycles, "coverage", {{"posted_dirty_victim", ledger.postedDirtyVictimSeen},
            {"busy_cycles", ledger.busyCycles}, {"blocked_load", ledger.blockedLoad},
            {"retire_during_write", ledger.retiredWhileBPending}, {"reuse_during_write", ledger.reusedWhileBPending},
            {"posted_owners", ledger.owners.size()}, {"posted_members", ledger.members.size()},
            {"held_b_cycles", ledger.heldBCycles}, {"loads", ledger.loadRequests}, {"stores", ledger.storeRequests}});
        ledger.finish();
        ledger.axi.finish();
        {
            std::ofstream output(artifactDirectory / "axi-metrics.json");
            output << "{\"kernel\":"; ledger.axi.kernel.json(output, "kernel");
            output << ",\"flush\":"; ledger.axi.flush.json(output, "flush"); output << "}\n";
            require(bool(output), "cannot write verified AXI accounting metrics");
        }
        if (injectByte) {
            const uint32_t offset = uint32_t(guest::scratchC - guest::ddrBase);
            const uint64_t original = test.ddr.memory.at(offset);
            test.ddr.memory.at(offset) ^= 1;
            trace.event(test.cycles, "negative_final_byte_mutation", {{"address", guest::scratchC},
                {"original", original}, {"mutated", test.ddr.memory.at(offset)}});
            writeMemory(artifactDirectory, "final-memory", test.ddr.memory);
            try { compareFinalMemory(program.finalBytes, test.ddr.memory); }
            catch (const std::runtime_error &error) {
                require(std::string(error.what()).find("final full sparse DDR byte mismatch") == 0,
                    "byte control failed at a different oracle");
                throw BoardOracleRejection("byte");
            }
            throw std::runtime_error("injected final byte escaped full-memory oracle");
        }
        compareFinalMemory(program.finalBytes, test.ddr.memory);
        writeMemory(artifactDirectory, "final-memory", test.ddr.memory);
        for (const auto &word : test.ddr.memory) trace.event(test.cycles, "final_memory", {
            {"address", guest::ddrBase + word.first}, {"actual", word.second},
            {"expected", guest::wordAt(program.finalBytes, guest::ddrBase + word.first)}});
        // Complete the original architecture/protocol/full-memory comparisons
        // before the directed coverage gate. A baseline that seals too early
        // should fail this specific witness, never masquerade as a byte fault.
        {
            std::ofstream coverage(artifactDirectory / "directed-cold-lines.json");
            coverage << "{\"authored_stores_per_line\":8,\"required_members_per_line\":2,\"lines\":[";
            bool first = true;
            for (const auto &entry : ledger.sealWitness.lines) {
                const auto &line = entry.second;
                trace.event(test.cycles, "directed_seal_coverage", {{"line", entry.first},
                    {"authored_stores", line.expectedPcs.size()}, {"retired_stores", line.retiredPcs.size()},
                    {"members_before_install", line.members.size()}, {"required_minimum", guest::minimumDirectedMembers},
                    {"owner_observed", line.ownerObserved}, {"owner_slot", line.owner.slot},
                    {"owner_generation", line.owner.generation}, {"installed", line.installed}, {"released", line.released},
                    {"install_cycle", line.installCycle}, {"release_cycle", line.releaseCycle},
                    {"ordinary_head_cycles", line.ordinaryHeadCycles}, {"sealed_ordinary_head_cycles", line.sealedOrdinaryHeadCycles},
                    {"final_full_memory_equal", 1}});
                if (!first) coverage << ',';
                first = false;
                coverage << "{\"line\":" << entry.first << ",\"members_before_install\":" << line.members.size()
                    << ",\"retired_stores\":" << line.retiredPcs.size() << ",\"installed\":" << line.installed
                    << ",\"released\":" << line.released << ",\"ordinary_head_cycles\":" << line.ordinaryHeadCycles
                    << ",\"sealed_ordinary_head_cycles\":" << line.sealedOrdinaryHeadCycles << '}';
            }
            coverage << "],\"all_eight_lines\":" << ledger.sealWitness.allEightLines()
                << ",\"final_full_memory_equal\":true}\n";
            require(bool(coverage), "cannot write directed per-cold-line coverage");
        }
        if (ledger.enabled) ledger.sealWitness.finish();
        trace.event(test.cycles, "pass", {{"enabled", variant == "on"}, {"commits", ledger.retired},
            {"stores", ledger.storeRequests}, {"loads", ledger.loadRequests}, {"proofs", ledger.proofRequests},
            {"delayed_writes", ledger.delayedWrites}, {"held_b_cycles", ledger.heldBCycles},
            {"blocked_load_cycles", ledger.blockedLoad}, {"reuse_during_write", ledger.reusedWhileBPending},
            {"retire_during_write", ledger.retiredWhileBPending}, {"reads", test.ddr.reads}, {"writes", test.ddr.writes}});
        std::cout << "POSTED_BOARD_LINEAGE_PASS variant=" << variant << " cycles=" << test.cycles
            << " stores=" << ledger.storeRequests << " loads=" << ledger.loadRequests << " proofs=" << ledger.proofRequests
            << " held_b_cycles=" << ledger.heldBCycles << " victim_aw=" << ledger.firstWriteCycle
            << " victim_b=" << ledger.firstBCycle << " victim_ack=" << ledger.firstAckCycle
            << " blocked_load=" << ledger.blockedLoad << " reuse_during_write=" << ledger.reusedWhileBPending
            << " retire_during_write=" << ledger.retiredWhileBPending << " final_full_memory_equal=1"
            << " directed_cold_lines=" << ledger.sealWitness.lines.size()
            << " directed_all_eight_lines=" << ledger.sealWitness.allEightLines() << '\n';
        return 0;
#endif
    } catch (const BoardOracleRejection &error) {
        if (!failureTracePath.empty()) {
            std::ofstream trace(failureTracePath, std::ios::app);
            trace << "{\"event\":\"expected_oracle_rejection\",\"control\":\"" << error.what() << "\"}\n";
        }
        std::cerr << "BOARD_ORACLE_REJECT " << error.what() << '\n';
        return 1;
    } catch (const std::exception &error) {
        if (!failureTracePath.empty()) {
            std::ofstream trace(failureTracePath, std::ios::app);
            // Error text remains in runtime.log; terminal trace stays valid JSON.
            trace << "{\"event\":\"terminal_failure\"}\n";
        }
        std::cerr << "BOARD_POSTED_LINEAGE_FAIL " << error.what() << '\n';
        return 1;
    }
}
