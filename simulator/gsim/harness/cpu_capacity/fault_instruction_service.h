#pragma once
// Verbatim raw-byte service and independent ManagerOracle extraction.
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

constexpr uint64_t romBase = UINT64_C(0x80000000), ramBase = UINT64_C(0x80200000);
constexpr uint64_t romBytes = 128 * 1024, ramWindowBytes = 128 * 1024;
constexpr uint32_t nop = 0x00000013, ebreak = 0x00100073;
[[maybe_unused]] constexpr unsigned maxCycles = 30000;
constexpr unsigned serviceLatency = 3, maxTransactions = 16;
// isa_model.h is reused unchanged. Data-memory instructions are forbidden below.

void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}
std::string hex(uint64_t value) {
    std::ostringstream out; out << "0x" << std::hex << value; return out.str();
}
uint32_t imm(unsigned rd, unsigned rs, int value, unsigned function = 0) {
    return (uint32_t(value) & 0xfff) << 20 | rs << 15 | function << 12 | rd << 7 | 0x13;
}
uint32_t reg(unsigned rd, unsigned a, unsigned b, unsigned function = 0) {
    return b << 20 | a << 15 | function << 12 | rd << 7 | 0x33;
}
uint32_t branch(unsigned a, unsigned b, int offset, unsigned function) {
    const uint32_t value = uint32_t(offset) & 0x1fff;
    return ((value >> 12) & 1) << 31 | ((value >> 5) & 63) << 25 | b << 20 | a << 15 |
        function << 12 | ((value >> 1) & 15) << 8 | ((value >> 11) & 1) << 7 | 0x63;
}
struct Program {
    std::string name, placement;
    std::vector<uint32_t> code, boot;
    uint64_t base() const { return placement == "rom" ? romBase : ramBase; }
    unsigned setupInstructions = 0;
    bool alias() const { return name == "vm_alias"; }
    bool vm() const { return name.rfind("vm_", 0) == 0; }
    unsigned bootstrapInstructions() const { return unsigned(boot.size()) + setupInstructions; }
    bool architectural(uint64_t pc) const {
        return !(pc & 3) && ((pc >= base() && (pc - base()) / 4 < code.size()) ||
            (pc >= romBase && (pc - romBase) / 4 < boot.size()));
    }
    bool mapped(uint64_t address, uint64_t bytes) const {
        return bytes && ((address >= romBase && address - romBase <= romBytes - bytes) ||
            (address >= ramBase && address - ramBase <= ramWindowBytes - bytes));
    }
    uint32_t word(uint64_t pc) const {
        require(!(pc & 3) && mapped(pc, 4), "program read outside declared instruction windows: " + hex(pc));
        if (pc >= base() && (pc - base()) / 4 < code.size()) return code.at((pc - base()) / 4);
        if (pc >= romBase && (pc - romBase) / 4 < boot.size()) return boot.at((pc - romBase) / 4);
        // Defined NOPs cover speculative post-terminal/branch-path reads. They
        // are fixture bytes, never synthesized from DUT PCs or decoded values.
        return nop;
    }
    uint64_t beat(uint64_t address) const {
        require(!(address & 7), "unaligned physical beat read");
        return uint64_t(word(address)) | uint64_t(word(address + 4)) << 32;
    }
};
struct Request {
    uint64_t address = 0, data = 0;
    unsigned opcode = 0, param = 0, size = 0, source = 0, mask = 0;
    bool corrupt = false;
    auto tuple() const { return std::tie(address, data, opcode, param, size, source, mask, corrupt); }
    bool operator==(const Request &other) const { return tuple() == other.tuple(); }
};
struct Reply {
    uint64_t data = 0;
    unsigned source = 0, size = 0, opcode = 1, param = 0, sink = 0;
    bool denied = false, corrupt = false;
    auto tuple() const { return std::tie(data, source, size, opcode, param, sink, denied, corrupt); }
    bool operator==(const Reply &other) const { return tuple() == other.tuple(); }
};
struct Transaction { Request request; uint64_t due; unsigned beat = 0; };
unsigned beats(unsigned size) { return size <= 3 ? 1 : 1u << (size - 3); }

// Service production and checking have separate ownership state. The checker
// learns only accepted A requests, independently recomputes byte/beat contents,
// and rejects source reuse, unowned/wrong D, early replies and held changes.
class ManagerOracle {
    const Program &program;
    struct Owner { Request request; uint64_t due; unsigned beat = 0; };
    std::map<unsigned, Owner> owners;
    std::optional<Request> heldA;
    std::optional<Reply> heldD;
public:
    uint64_t accepted = 0, returned = 0, completed = 0;
    explicit ManagerOracle(const Program &p) : program(p) {}
    void a(bool valid, bool ready, const Request &request, uint64_t cycle) {
        if (heldA) require(valid && request == *heldA, "manager oracle A changed while stalled");
        if (!valid) { heldA.reset(); return; }
        require(request.opcode == 4 && request.param == 0 && !request.corrupt,
            "manager oracle requires legal uncorrupted Get");
        require((request.size == 2 || request.size == 3 || request.size == 6) &&
            request.source < maxTransactions, "manager oracle illegal size/source");
        const uint64_t bytes = UINT64_C(1) << request.size;
        require(!(request.address & (bytes - 1)) && program.mapped(request.address, bytes),
            "manager oracle request outside aligned ROM/RAM windows");
        const unsigned mask = request.size >= 3 ? 255 : 15u << (request.address & 7);
        require(request.mask == mask, "manager oracle incorrect byte mask");
        if (ready) {
            require(owners.count(request.source) == 0, "manager oracle source reused before last D beat");
            owners.emplace(request.source, Owner{request, cycle + serviceLatency, 0});
            ++accepted; heldA.reset();
        } else heldA = request;
    }
    void d(bool valid, bool ready, const Reply &reply, uint64_t cycle, bool negative = false) {
        const std::string prefix = negative ? "A1_MANAGER_NEGATIVE_REACHED " : "manager oracle ";
        if (heldD) require(valid && reply == *heldD, prefix + "D changed while stalled");
        if (!valid) { heldD.reset(); return; }
        const auto found = owners.find(reply.source);
        require(found != owners.end(), prefix + "D source has no accepted Get");
        Owner &owner = found->second;
        require(cycle >= owner.due, prefix + "reply earlier than fixed service latency");
        require(reply.opcode == 1 && reply.param == 0 && reply.sink == 0 &&
            !reply.denied && !reply.corrupt && reply.size == owner.request.size,
            prefix + "AccessAckData metadata");
        const uint64_t address = (owner.request.address & ~UINT64_C(7)) + 8 * owner.beat;
        require(reply.data == program.beat(address), prefix + "byte/beat mismatch");
        if (ready) {
            ++returned;
            if (++owner.beat == beats(owner.request.size)) { owners.erase(found); ++completed; }
            heldD.reset();
        } else heldD = reply;
    }
    bool idle() const { return owners.empty() && !heldA && !heldD; }
};
class InstructionManager {
    const Program &program;
    std::deque<Transaction> pending;
    std::set<unsigned> sources;
public:
    explicit InstructionManager(const Program &p) : program(p) {}
    bool ready() const { return pending.size() < maxTransactions; }
    std::optional<Reply> offer(uint64_t cycle) const {
        if (pending.empty() || cycle < pending.front().due) return {};
        const auto &entry = pending.front();
        return Reply{program.beat((entry.request.address & ~UINT64_C(7)) + 8 * entry.beat),
            entry.request.source, entry.request.size};
    }
    void accept(const Request &request, uint64_t cycle) {
        require(sources.insert(request.source).second, "service duplicated a live source");
        pending.push_back({request, cycle + serviceLatency, 0});
    }
    void consume() {
        require(!pending.empty(), "service consumed empty D queue");
        auto &entry = pending.front();
        if (++entry.beat == beats(entry.request.size)) {
            sources.erase(entry.request.source); pending.pop_front();
        }
    }
    bool idle() const { return pending.empty() && sources.empty(); }
};
struct ClearReply { unsigned owner; uint64_t due; bool clear = true; uint64_t data = 0; };
struct CacheOwner { Request request; uint64_t due; unsigned sink; };
