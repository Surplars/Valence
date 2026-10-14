#pragma once

#include "retirement_slot_rob_oracle.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <string>

namespace rob_payload_ram {
using retirement_intent_rob::require;
struct Write { bool valid = false; unsigned index = 0; uint64_t next_pc = 0, tval = 0; };
struct Input { unsigned head = 0; std::array<Write, 2> write{}; };
struct Output { uint64_t next_pc0 = 0, next_pc1 = 0, tval = 0; };
struct Row { bool known = false; uint64_t next_pc = 0, tval = 0; };

template<class Model> void drive(Model &m, const Input &in = {}) {
    m.set_io$$ram$$head(in.head);
#define RAM_WRITE(N) \
    m.set_io$$ram$$write##N##$$valid(in.write[N].valid); \
    m.set_io$$ram$$write##N##$$bits$$index(in.write[N].index); \
    m.set_io$$ram$$write##N##$$bits$$nextPc(in.write[N].next_pc); \
    m.set_io$$ram$$write##N##$$bits$$tval(in.write[N].tval)
    RAM_WRITE(0); RAM_WRITE(1);
#undef RAM_WRITE
}
template<class Model> std::array<Output, 4> sample(Model &m) {
#define RAM_READ(N) Output{uint64_t(m.get_io$$ram$$rows##N##$$nextPc0()), \
    uint64_t(m.get_io$$ram$$rows##N##$$nextPc1()), uint64_t(m.get_io$$ram$$rows##N##$$tval())}
    return {RAM_READ(4), RAM_READ(8), RAM_READ(16), RAM_READ(32)};
#undef RAM_READ
}

template<class Model> void run(Model &m) {
    idle_retirement_rob(m); drive(m);
    m.set_reset(1); m.step(); m.step(); m.set_reset(0);
    constexpr std::array<unsigned, 4> sizes{4, 8, 16, 32};
    std::array<std::array<Row, 32>, 4> expected{};
    std::array<uint64_t, 4> reads{}, wraps{}, read_before_write{}, same_parity{}, writer_mask{};
    uint64_t cycles = 0;
    auto tick = [&](const Input &in) {
        drive(m, in); m.step(); const auto actual = sample(m);
        for (unsigned fixture = 0; fixture < sizes.size(); ++fixture) {
            const unsigned size = sizes[fixture], head = in.head % size, next = (head + 1) % size;
            auto &rows = expected[fixture];
            const auto &out = actual[fixture];
            const std::string context = "RAW_PAYLOAD_RAM entries=" + std::to_string(size) +
                " cycle=" + std::to_string(cycles) + " head=" + std::to_string(head);
            // Compare PRE-edge state before applying this input's writes. No
            // uninitialized value is assumed; each read is guarded by a known
            // row established only through an earlier public write.
            if (rows[head].known) {
                require(out.next_pc0 == rows[head].next_pc && out.tval == rows[head].tval,
                    context + " saved head payload or read-before-edge mismatch");
                ++reads[fixture];
                for (const auto &write : in.write) if (write.valid && write.index % size == head &&
                        (write.next_pc != rows[head].next_pc || write.tval != rows[head].tval))
                    ++read_before_write[fixture];
            }
            if (rows[next].known) {
                require(out.next_pc1 == rows[next].next_pc, context + " saved head+1 payload mismatch");
                ++reads[fixture]; wraps[fixture] += head == size - 1;
            }
            if (in.write[0].valid && in.write[1].valid) {
                require(in.write[0].index % size != in.write[1].index % size,
                    "fixture generated illegal duplicate RAM writers");
                same_parity[fixture] += ((in.write[0].index ^ in.write[1].index) & 1) == 0;
            }
            for (unsigned port = 0; port < 2; ++port) if (in.write[port].valid) {
                const auto &w = in.write[port];
                rows[w.index % size] = {true, w.next_pc, w.tval};
                writer_mask[fixture] |= 1u << (2 * port + (w.index & 1));
            }
        }
        ++cycles;
    };
    for (unsigned index = 0; index < 32; ++index) {
        Input in; in.head = (index + 7) % 32;
        in.write[0] = {true, index, UINT64_C(0xa75c3819d6200000) ^ index, UINT64_C(0xfedcba9876540000) ^ index};
        in.write[1] = {true, index ^ 1, UINT64_C(0x183947a6d5ef0000) ^ index, UINT64_C(0x0123456789ab0000) ^ index};
        tick(in);
    }
    for (unsigned bit = 0; bit < 64; ++bit) for (unsigned mode = 0; mode < 4; ++mode) {
        Input in; in.head = (bit + 7 * mode) % 32;
        in.write[0] = {mode != 2, in.head, UINT64_C(1) << bit, ~(UINT64_C(1) << bit)};
        in.write[1] = {mode != 3, in.head ^ (mode & 1 ? 1u : 2u), ~(UINT64_C(1) << bit), UINT64_C(1) << bit};
        tick(in);
    }
    std::mt19937_64 rng(UINT64_C(0x524f425041594c44));
    for (unsigned cycle = 0; cycle < 256; ++cycle) {
        Input in; in.head = rng() % 32; const unsigned index = rng() % 32;
        in.write[0] = {rng() % 4 != 0, index, rng(), rng()};
        in.write[1] = {rng() % 4 != 0, index ^ (rng() & 1 ? 1u : 2u), rng(), rng()};
        tick(in);
    }
    for (unsigned head = 0; head < 32; ++head) { Input in; in.head = head; tick(in); }
    for (unsigned i = 0; i < sizes.size(); ++i) {
        require(reads[i] && wraps[i] && read_before_write[i] && same_parity[i] && writer_mask[i] == 15,
            "primitive RAM coverage missing entries=" + std::to_string(sizes[i]));
        std::cout << "ROB_PAYLOAD_RAM_ORACLE_PASS entries=" << sizes[i] << " cycles=" << cycles
            << " reads=" << reads[i] << " wraps=" << wraps[i] << " readBeforeWrite=" << read_before_write[i]
            << " sameParityDualWrite=" << same_parity[i] << " writerParityMask=" << writer_mask[i] << '\n';
    }
    drive(m);
}
} // namespace rob_payload_ram
