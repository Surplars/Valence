#include "RecoveryControlGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

#ifndef ROB_ENTRIES
#define ROB_ENTRIES 16
#endif
struct Token { unsigned index; uint64_t tag; };
struct Request { bool valid; Token token; bool inclusive; };
static bool equal(Token a, Token b) { return a.index == b.index && a.tag == b.tag; }

int main(int argc, char **argv) { try {
    const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    constexpr unsigned N = ROB_ENTRIES;
    SRecoveryControlGsim d;
    std::array<uint64_t, N> tags{};
    uint64_t checked = 0, acceptedCases = 0, externalCases = 0, localCases = 0;
    uint64_t shrinkCases = 0, ties = 0, staleLocalBlocks = 0, highTagRejects = 0, trapOverrides = 0;
    d.set_io$$tagWrite(0); d.set_io$$tagIndex(0); d.set_io$$tagValue(0);
    d.set_io$$head(0); d.set_io$$count(0); d.set_io$$recovering(0); d.set_io$$keepCount(0);
    d.set_io$$external$$valid(0); d.set_io$$external$$bits$$token$$index(0);
    d.set_io$$external$$bits$$token$$tag(0); d.set_io$$external$$bits$$inclusive(0);
    d.set_io$$local$$valid(0); d.set_io$$local$$bits$$token$$index(0);
    d.set_io$$local$$bits$$token$$tag(0); d.set_io$$local$$bits$$inclusive(0);
    d.set_io$$localRedirect$$valid(0); d.set_io$$localRedirect$$bits$$index(0);
    d.set_io$$localRedirect$$bits$$tag(0); d.set_io$$trapRedirect$$valid(0);
    d.set_io$$trapRedirect$$bits$$index(0); d.set_io$$trapRedirect$$bits$$tag(0);
    d.set_io$$query0$$index(0); d.set_io$$query0$$tag(0);
    d.set_io$$query1$$index(0); d.set_io$$query1$$tag(0);
    auto tick = [&] { d.set_clock(0); d.step(); d.set_clock(1); d.step(); d.set_clock(0); d.step(); };
    d.set_reset(1); tick(); tick(); d.set_reset(0); tick();
    std::mt19937_64 rng(0x202610020adULL + N);
    auto refresh = [&] {
        for (unsigned slot = 0; slot < N; ++slot) {
            tags[slot] = rng();
            d.set_io$$tagWrite(1); d.set_io$$tagIndex(slot); d.set_io$$tagValue(tags[slot]); tick();
        }
        d.set_io$$tagWrite(0); tick();
    };
    refresh();
    auto check = [&](unsigned head, unsigned count, bool recovering, unsigned keep, Request e, Request l,
                     bool lv, Token lt, bool tv, Token tt, Token q0, Token q1) {
        d.set_io$$head(head); d.set_io$$count(count); d.set_io$$recovering(recovering); d.set_io$$keepCount(keep);
        d.set_io$$external$$valid(e.valid); d.set_io$$external$$bits$$token$$index(e.token.index);
        d.set_io$$external$$bits$$token$$tag(e.token.tag); d.set_io$$external$$bits$$inclusive(e.inclusive);
        d.set_io$$local$$valid(l.valid); d.set_io$$local$$bits$$token$$index(l.token.index);
        d.set_io$$local$$bits$$token$$tag(l.token.tag); d.set_io$$local$$bits$$inclusive(l.inclusive);
        d.set_io$$localRedirect$$valid(lv); d.set_io$$localRedirect$$bits$$index(lt.index);
        d.set_io$$localRedirect$$bits$$tag(lt.tag); d.set_io$$trapRedirect$$valid(tv);
        d.set_io$$trapRedirect$$bits$$index(tt.index); d.set_io$$trapRedirect$$bits$$tag(tt.tag);
        d.set_io$$query0$$index(q0.index); d.set_io$$query0$$tag(q0.tag);
        d.set_io$$query1$$index(q1.index); d.set_io$$query1$$tag(q1.tag); d.step();
        // Procedural oracle implements the ORIGINAL serialized algorithm: admit
        // external, select by original priority, then re-check the selected token.
        auto age = [&](unsigned slot) { return (slot + N - head) % N; };
        auto admit = [&](Request r) {
            if (!r.valid || age(r.token.index) >= count || tags[r.token.index] != r.token.tag) return false;
            unsigned retained = age(r.token.index) + (r.inclusive ? 0 : 1);
            return !recovering || retained < keep;
        };
        bool ea = admit(e);
        bool ew = ea && (!l.valid || age(e.token.index) <= age(l.token.index));
        Request selected = ew ? e : l;
        selected.valid = ew || l.valid;
        bool accepted = admit(selected);
        unsigned active = accepted ? age(selected.token.index) + (selected.inclusive ? 0 : 1) : keep;
        uint64_t killed = 0, survives = 0;
        for (unsigned slot = 0; slot < N; ++slot) {
            if (accepted && (age(slot) > age(selected.token.index) ||
                (selected.inclusive && slot == selected.token.index))) killed |= uint64_t{1} << slot;
            if (!(recovering || accepted) || age(slot) < active) survives |= uint64_t{1} << slot;
        }
        // Match after selecting the original redirect; trap overrides local even
        // when it does not match a query that the local candidate would match.
        bool redirectValid = tv || lv;
        Token redirect = tv ? tt : lt;
        bool match0 = redirectValid && equal(redirect, q0), match1 = redirectValid && equal(redirect, q1);
        if (inject && checked == 100) killed ^= 1;
        if (bool(d.get_io$$externalAccepted()) != ea || bool(d.get_io$$externalWins()) != ew ||
            bool(d.get_io$$selected$$valid()) != selected.valid ||
            d.get_io$$selected$$bits$$token$$index() != selected.token.index ||
            d.get_io$$selected$$bits$$token$$tag() != selected.token.tag ||
            bool(d.get_io$$selected$$bits$$inclusive()) != selected.inclusive ||
            bool(d.get_io$$accepted()) != accepted || d.get_io$$activeKeep() != active ||
            d.get_io$$killed() != killed || d.get_io$$survives() != survives ||
            bool(d.get_io$$match0()) != match0 || bool(d.get_io$$match1()) != match1)
            throw std::runtime_error("recovery control oracle mismatch");
        ++checked; acceptedCases += accepted; externalCases += accepted && ew;
        localCases += accepted && !ew; shrinkCases += accepted && recovering;
        ties += ea && l.valid && age(e.token.index) == age(l.token.index);
        staleLocalBlocks += ea && l.valid && age(l.token.index) < age(e.token.index) && !admit(l);
        highTagRejects += e.valid && (e.token.tag ^ tags[e.token.index]) == (uint64_t{1} << 63);
        trapOverrides += tv && lv && equal(lt, q0) && !equal(tt, q0);
    };
    for (unsigned head = 0; head < N; ++head)
        for (unsigned count = 0; count <= N; ++count)
            for (unsigned a = 0; a < N; ++a)
                for (unsigned flags = 0; flags < 16; ++flags) {
                    unsigned b = (a + count + 1) % N;
                    Request e{bool(flags & 1), {a, tags[a]}, bool(flags & 4)};
                    Request l{bool(flags & 2), {b, tags[b]}, bool(flags & 8)};
                    Token lt{a, tags[a]}, tt{b, tags[b]};
                    check(head, count, false, count, e, l, true, lt, true, tt, lt, tt);
                }
    for (unsigned n = 0; n < 100000; ++n) {
        if (n && n % 10000 == 0) refresh();
        unsigned head = rng() % N, count = rng() % (N + 1), keep = rng() % (count + 1);
        bool recovering = rng() & 1;
        unsigned a = rng() % N, b = rng() % N;
        uint64_t flipE = (rng() % 4 == 0) ? (uint64_t{1} << (rng() % 64)) : 0;
        uint64_t flipL = (rng() % 4 == 0) ? (uint64_t{1} << (rng() % 64)) : 0;
        Request e{bool(rng() & 1), {a, tags[a] ^ flipE}, bool(rng() & 1)};
        Request l{bool(rng() & 1), {b, tags[b] ^ flipL}, bool(rng() & 1)};
        Token lt{a, rng()}, tt{b, rng()}, q0 = lt, q1 = tt;
        if (n % 4 == 0) q0.tag ^= uint64_t{1} << 63;
        if (n % 4 == 1) q1.index = (q1.index + 1) % N;
        bool lv = rng() & 1, tv = rng() & 1;
        check(head, count, recovering, keep, e, l, lv, lt, tv, tt, q0, q1);
    }
    if (!acceptedCases || !externalCases || !localCases || !shrinkCases || !ties ||
        !staleLocalBlocks || !highTagRejects || !trapOverrides)
        throw std::runtime_error("recovery control coverage incomplete");
    std::cout << "GSIM recovery control: PASS rob=" << N << " tagBits=64 vectors=" << checked
              << " accepted=" << acceptedCases << " external=" << externalCases << " local=" << localCases
              << " recovery_shrink=" << shrinkCases << " ties=" << ties
              << " stale_local_blocks_external=" << staleLocalBlocks << " high_tag_rejects=" << highTagRejects
              << " trap_override=" << trapOverrides << '\n';
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
