#pragma once

#include <array>
#include <cstdint>
#include <deque>
#include <stdexcept>
#include <string>
#include <vector>

namespace older_prefix {
constexpr unsigned capacity = 16, recovery_width = 4;
struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    bool operator==(const Token &) const = default;
};
struct Request {
    bool valid = false;
    uint64_t pc = 0;
    uint32_t instruction = 0;
};
struct Completion {
    bool valid = false;
    Token token;
    uint64_t data = 0, next_pc = 0;
    bool exception = false;
    uint64_t cause = 0, tval = 0;
};
struct Input {
    std::array<Request, 2> allocate{};
    std::array<Completion, 2> complete{};
    unsigned same_cycle = 3;
    Completion fast;
    bool limit_valid = false;
    Token limit;
    bool dispatch = true, commit = false;
    bool recover = false, inclusive = false, head_trap = false, head_system = false;
    Token boundary;
};
struct Entry {
    Token token;
    Request request;
    bool done = false;
    Completion result;
};
struct Commit {
    bool valid = false;
    Token token;
    uint64_t pc = 0, data = 0, next_pc = 0;
    uint32_t instruction = 0;
};
struct Observation {
    std::array<bool, 2> allocated{}, completed{};
    std::array<Token, 2> allocated_token{};
    std::array<Commit, 2> retired{};
    bool recovery_accepted = false, trap_accepted = false, system_accepted = false;
    bool recovering = false, head_exception = false;
    unsigned occupancy = 0;
    Token system_token, exception_token;
    uint64_t exception_pc = 0, cause = 0, tval = 0;
};
inline void require(bool value, const std::string &message) {
    if (!value) throw std::runtime_error(message);
}
inline int locate(const std::deque<Entry> &program, Token token) {
    for (unsigned n = 0; n < program.size(); ++n)
        if (program[n].token == token) return int(n);
    return -1;
}
// A named live instruction is an exclusive stop marker in PROGRAM ORDER. There
// is no subtraction, mask, circular-distance comparator or DUT index output here.
inline unsigned older_count(const std::deque<Entry> &program, bool valid, Token stop) {
    if (!valid) return unsigned(program.size());
    unsigned count = 0;
    for (const auto &entry : program) {
        if (entry.token == stop) return count;
        ++count;
    }
    return 0; // An unknown owner is never permission to retire anything.
}
inline void compare(const Observation &actual, const Observation &expected) {
    require(actual.occupancy == expected.occupancy, "occupancy oracle mismatch");
    require(actual.recovering == expected.recovering, "recovery state oracle mismatch");
    require(actual.recovery_accepted == expected.recovery_accepted &&
        actual.trap_accepted == expected.trap_accepted && actual.system_accepted == expected.system_accepted,
        "recovery acceptance oracle mismatch");
    require(actual.head_exception == expected.head_exception, "head exception oracle mismatch");
    if (expected.head_exception) require(actual.exception_token == expected.exception_token &&
        actual.exception_pc == expected.exception_pc && actual.cause == expected.cause && actual.tval == expected.tval,
        "exception payload oracle mismatch");
    for (unsigned lane = 0; lane < 2; ++lane) {
        require(actual.completed[lane] == expected.completed[lane], "completion ownership oracle mismatch");
        require(actual.allocated[lane] == expected.allocated[lane], "allocation prefix oracle mismatch");
        if (expected.allocated[lane]) require(actual.allocated_token[lane] == expected.allocated_token[lane],
            "allocation token oracle mismatch");
        const auto &a = actual.retired[lane];
        const auto &e = expected.retired[lane];
        require(a.valid == e.valid, "strict older-prefix oracle mismatch lane=" + std::to_string(lane));
        if (e.valid) require(a.token == e.token && a.pc == e.pc && a.instruction == e.instruction &&
            a.data == e.data && a.next_pc == e.next_pc, "retirement identity/payload oracle mismatch");
    }
}

// Independent FIFO of issued transactions. Physical ROB indices are assigned
// only when predicting allocations; age/retirement are defined by deque order.
class Oracle {
    unsigned tail = 0;
    uint64_t serial = 0;
    unsigned keep = 0;
public:
    std::deque<Entry> program;
    bool recovering = false;
    void reset() { program.clear(); tail = 0; serial = 0; keep = 0; recovering = false; }
    Observation advance(const Input &in) {
        Observation expected;
        expected.occupancy = unsigned(program.size());
        expected.recovering = recovering;
        if (!program.empty()) expected.system_token = program.front().token;
        const int boundary = locate(program, in.boundary);
        const unsigned requested_keep = boundary < 0 ? 0 : unsigned(boundary) + !in.inclusive;
        const bool ordinary = in.recover && boundary >= 0 && (!recovering || requested_keep < keep);
        expected.trap_accepted = in.head_trap && !program.empty() && (!recovering || keep != 0);
        expected.system_accepted = in.head_system && !program.empty() && !expected.trap_accepted &&
            !(ordinary && boundary == 0) && (!recovering || keep > 1);
        expected.recovery_accepted = expected.trap_accepted || expected.system_accepted || ordinary;
        const bool rollback = recovering || expected.recovery_accepted;
        if (expected.recovery_accepted)
            keep = expected.trap_accepted ? 0 : expected.system_accepted ? 1 : requested_keep;
        expected.head_exception = !program.empty() && program.front().done &&
            program.front().result.exception && !rollback;
        if (expected.head_exception) {
            const auto &entry = program.front();
            expected.exception_token = entry.token;
            expected.exception_pc = entry.request.pc;
            expected.cause = entry.result.cause;
            expected.tval = entry.result.tval;
        }
        const auto before = program;
        std::array<int, 2> accepted_position{-1, -1};
        for (unsigned lane = 0; lane < 2; ++lane) {
            const auto &c = in.complete[lane];
            const int pos = locate(program, c.token);
            const bool duplicate = lane == 1 && in.complete[0].valid && in.complete[0].token == c.token;
            const bool accepted = c.valid && pos >= 0 && !before[pos].done && !duplicate &&
                (!rollback || unsigned(pos) < keep);
            expected.completed[lane] = accepted;
            if (accepted) {
                accepted_position[lane] = pos;
                program[pos].done = true;
                program[pos].result = c;
            }
        }
        unsigned retired = 0;
        const unsigned permitted = older_count(before, in.limit_valid, in.limit);
        bool prefix = in.commit && !rollback;
        for (unsigned lane = 0; lane < 2 && lane < program.size(); ++lane) {
            const auto &entry = program[lane];
            bool ready = before[lane].done && !before[lane].result.exception;
            Completion data = before[lane].result;
            if (!before[lane].done) {
                for (unsigned port = 0; port < 2; ++port)
                    if (accepted_position[port] == int(lane) && ((in.same_cycle >> port) & 1) &&
                        !in.complete[port].exception) { ready = true; data = in.complete[port]; }
                if (lane == 0 && in.fast.valid && in.fast.token == entry.token) {
                    require(!in.fast.exception, "fixture fast-head fault is outside producer contract");
                    ready = true; data = in.fast;
                }
            }
            const bool valid = prefix && lane < permitted && ready;
            if (valid) {
                expected.retired[lane] = {true, entry.token, entry.request.pc, data.data,
                    data.next_pc, entry.request.instruction};
                ++retired;
            }
            prefix = valid && (entry.request.instruction & 127) != 0x73;
        }
        require(!in.fast.valid || expected.retired[0].valid,
            "fixture fast-head producer must be authorized to retire current head");
        std::vector<Entry> allocated;
        bool allocate_prefix = in.dispatch && !rollback;
        for (unsigned lane = 0; lane < 2; ++lane) {
            const bool valid = allocate_prefix && in.allocate[lane].valid && before.size() + lane < capacity;
            allocate_prefix = valid;
            expected.allocated[lane] = valid;
            if (valid) {
                const Token token{tail, serial++};
                tail = (tail + 1) % capacity;
                expected.allocated_token[lane] = token;
                allocated.push_back({token, in.allocate[lane], false, {}});
            }
        }
        if (rollback) {
            for (unsigned n = 0; n < recovery_width && program.size() > keep; ++n) {
                program.pop_back();
                tail = (tail + capacity - 1) % capacity;
            }
            recovering = program.size() > keep;
        } else {
            for (unsigned n = 0; n < retired; ++n) program.pop_front();
            for (const auto &entry : allocated) program.push_back(entry);
        }
        return expected;
    }
};
} // namespace older_prefix
