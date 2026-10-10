#pragma once
#include "guest.h"
#include <algorithm>
#include <map>
#include <set>
#include <tuple>

// Host-only directed coverage oracle. Initial facts are decoded from raw ROM;
// observed member tokens must join their earlier independent CPU launch. The
// existing Board ledger separately validates full owner/cohort/reservation,
// proof authorization, actual SRAM words, bus ownership and final DDR bytes.
namespace posted_seal_regression {
namespace guest = posted_board_guest;
struct Token {
    uint64_t tag = 0, index = 0;
    bool operator==(const Token &o) const { return tag == o.tag && index == o.index; }
    bool operator<(const Token &o) const { return std::tie(tag, index) < std::tie(o.tag, o.index); }
};
struct Owner {
    uint64_t slot = 0, generation = 0;
    bool operator==(const Owner &o) const { return slot == o.slot && generation == o.generation; }
};
struct Line {
    std::set<uint64_t> expectedPcs, retiredPcs;
    std::set<Token> members;
    Owner owner;
    bool ownerObserved = false, installed = false, released = false;
    uint64_t firstMemberCycle = 0, lastMemberCycle = 0, installCycle = 0, releaseCycle = 0;
    uint64_t ordinaryHeadCycles = 0, sealedOrdinaryHeadCycles = 0;
};
class Witness {
    struct Launch { uint64_t pc, line, cycle; };
    const guest::Program &program;
    std::map<Token, Launch> launches;
    std::map<uint64_t, Token> launchedPcs;
public:
    std::map<uint64_t, Line> lines;
    explicit Witness(const guest::Program &p) : program(p) {
        for (const auto address : guest::directedLines) lines.emplace(address, Line{});
        for (const auto &entry : program.intents) {
            const auto &intent = entry.second;
            const uint64_t address = intent.address & ~UINT64_C(63);
            if (intent.store && lines.count(address)) lines.at(address).expectedPcs.insert(intent.pc);
        }
        for (const auto &entry : lines) guest::require(entry.second.expectedPcs.size() == guest::directedStoresPerLine,
            "directed seal witness lacks eight independently decoded stores per cold line");
    }
    bool directed(uint64_t line) const { return lines.count(line); }
    void launch(Token token, uint64_t pc, uint64_t cycle) {
        const auto found = program.intents.find(pc);
        guest::require(found != program.intents.end(), "directed launch PC is not a decoded memory instruction");
        const auto &intent = found->second;
        const uint64_t line = intent.address & ~UINT64_C(63);
        if (!intent.store || !directed(line)) return;
        guest::require(launches.emplace(token, Launch{pc, line, cycle}).second && launchedPcs.emplace(pc, token).second,
            "directed seal witness repeats original launch token or raw store PC");
    }
    void member(Token token, uint64_t pc, uint64_t address, Owner owner, uint64_t cycle) {
        if (!directed(address)) return;
        auto &line = lines.at(address);
        const auto found = launches.find(token);
        guest::require(found != launches.end() && found->second.pc == pc && found->second.line == address &&
            found->second.cycle <= cycle && line.expectedPcs.count(pc),
            "directed member lacks original full-token/raw-PC cold-line launch");
        guest::require(!line.installed && !line.released,
            "directed member appeared after real original owner installation/release");
        if (!line.ownerObserved) {
            line.ownerObserved = true; line.owner = owner; line.firstMemberCycle = cycle;
        }
        guest::require(line.owner == owner && line.members.insert(token).second,
            "directed members changed full owner generation or repeated a token");
        line.lastMemberCycle = cycle;
    }
    void install(uint64_t address, Owner owner, uint64_t cycle) {
        if (!directed(address)) return;
        auto &line = lines.at(address);
        guest::require(line.ownerObserved && line.owner == owner && !line.installed &&
            !line.released && line.lastMemberCycle < cycle,
            "directed install lacks an immutable original owner and earlier accepted members");
        line.installed = true; line.installCycle = cycle;
    }
    void release(uint64_t address, Owner owner, uint64_t cycle) {
        if (!directed(address)) return;
        auto &line = lines.at(address);
        guest::require(line.installed && line.owner == owner && !line.released && line.installCycle <= cycle,
            "directed release preceded installation or changed/repeated original full owner");
        line.released = true; line.releaseCycle = cycle;
    }
    void retire(Token token, uint64_t pc) {
        const auto found = program.intents.find(pc);
        if (found == program.intents.end() || !found->second.store) return;
        const uint64_t address = found->second.address & ~UINT64_C(63);
        if (!directed(address)) return;
        auto &line = lines.at(address);
        guest::require(launches.count(token) && launches.at(token).pc == pc &&
            line.retiredPcs.insert(pc).second, "directed store retirement changed/duplicated original full token");
    }
    void head(uint64_t pc, uint32_t instruction, bool sealed) {
        const unsigned opcode = instruction & 127;
        if (opcode != 0x13 && opcode != 0x63) return;
        for (auto &entry : lines) {
            auto &line = entry.second;
            if (!line.ownerObserved || line.released || pc <= *line.expectedPcs.begin() || pc >= *line.expectedPcs.rbegin()) continue;
            guest::require(program.rawInstruction(pc, instruction), "ordinary head witness is not an authored raw instruction");
            ++line.ordinaryHeadCycles;
            line.sealedOrdinaryHeadCycles += sealed;
        }
    }
    unsigned allEightLines() const {
        unsigned result = 0;
        for (const auto &entry : lines) result += entry.second.members.size() == guest::directedStoresPerLine;
        return result;
    }
    void finish() const {
        // This threshold is fixed before old/fixed RTL execution. Every cold
        // line must pass; the qualified prelude's unrelated join cannot help.
        static_assert(guest::minimumDirectedMembers == 2, "directed regression threshold changed");
        for (const auto &entry : lines) {
            const auto &line = entry.second;
            guest::require(line.ownerObserved && line.installed && line.released &&
                line.retiredPcs == line.expectedPcs,
                "directed cold line lacks complete original owner/eight-store retirement lineage");
            guest::require(line.members.size() >= guest::minimumDirectedMembers &&
                line.members.size() <= guest::directedStoresPerLine,
                "DIRECTED_SEAL_WITNESS_REJECT line=" + std::to_string(entry.first) +
                " members_before_install=" + std::to_string(line.members.size()) + " required_minimum=2");
        }
    }
};
} // namespace posted_seal_regression
