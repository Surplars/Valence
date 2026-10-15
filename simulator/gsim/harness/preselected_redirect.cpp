#include "PreselectedRedirectGsim.h"
#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <type_traits>

struct Token { unsigned index; uint64_t tag; };
static bool equal(Token a, Token b) { return a.index == b.index && a.tag == b.tag; }
int main(int argc, char **argv) try {
    const unsigned mutation = argc == 2 ? unsigned(std::stoul(argv[1])) : 0;
    if (mutation > 3) throw std::runtime_error("invalid mutation");
    SPreselectedRedirectGsim d;
    static_assert(std::is_trivially_copyable_v<SPreselectedRedirectGsim>);
    std::memset(&d, 0, sizeof(d)); d.LOG_START = 1; d.activateAll();
    std::mt19937_64 rng(0xc020261015ULL);
    unsigned cases = 0, requestNotAccepted = 0, trapBlocks = 0, highTag = 0;
    auto check = [&](bool l, bool s, bool request, bool t, Token local, Token system, Token trap,
                     Token q0, Token q1) {
        d.set_io$$localAccepted(l); d.set_io$$systemAccepted(s); d.set_io$$systemRequest(request);
        d.set_io$$trapAccepted(t); d.set_io$$mutation(mutation);
        d.set_io$$localToken$$index(local.index); d.set_io$$localToken$$tag(local.tag);
        d.set_io$$systemToken$$index(system.index); d.set_io$$systemToken$$tag(system.tag);
        d.set_io$$trapToken$$index(trap.index); d.set_io$$trapToken$$tag(trap.tag);
        d.set_io$$query0$$index(q0.index); d.set_io$$query0$$tag(q0.tag);
        d.set_io$$query1$$index(q1.index); d.set_io$$query1$$tag(q1.tag);
        d.set_clock(0); d.step(); d.set_clock(1); d.step(); d.set_clock(0); d.step();
        // Independent scalar priority, not the DUT Boolean expression.
        const bool valid = t || s || l;
        const Token chosen = t ? trap : s ? system : local;
        const bool e0 = valid && equal(chosen, q0), e1 = valid && equal(chosen, q1);
        if (d.get_io$$baseline0() != e0 || d.get_io$$baseline1() != e1 ||
            d.get_io$$candidate0() != e0 || d.get_io$$candidate1() != e1)
            throw std::runtime_error("independent accepted-token priority/full-tag mismatch case=" + std::to_string(cases));
        ++cases; requestNotAccepted += request && !s;
        trapBlocks += t && !equal(trap, q0) && l && equal(local, q0);
        highTag += chosen.index == q0.index && (chosen.tag ^ q0.tag) == (uint64_t(1) << 63);
    };
    const Token a{3, 0x1234}, b{3, 0x8000000000001234ULL}, c{7, 0x99};
    // Reviewer counterexamples: request is not acceptance; high trap mismatch blocks fallback.
    check(true, false, true, false, a, b, c, a, b);
    check(true, true, true, true, a, b, c, a, c);
    // An already keep=1 system boundary can keep requesting without new acceptance.
    for (unsigned n = 0; n < 8; ++n) check(false, false, true, false, a, b, c, b, a);
    for (unsigned bit = 0; bit < 64; ++bit) {
        Token stale = a; stale.tag ^= uint64_t(1) << bit;
        check(true, false, false, false, a, b, c, stale, a);
        check(true, true, true, false, a, b, c, a, b); // system mismatch blocks matching local
    }
    for (unsigned control = 0; control < 16; ++control)
        for (Token q : std::array<Token,3>{a,b,c})
            check(control&1, control&2, control&4, control&8, a,b,c,q,b);
    for (unsigned n = 0; n < 50000; ++n) {
        Token l{unsigned(rng()%16), rng()}, s{unsigned(rng()%16), rng()}, t{unsigned(rng()%16), rng()};
        const unsigned control = unsigned(rng()%16);
        Token q = n%3 == 0 ? l : n%3 == 1 ? s : t;
        if (n%5 == 0) q.tag ^= uint64_t(1) << 63;
        check(control&1,control&2,control&4,control&8,l,s,t,q,l);
    }
    if (!requestNotAccepted || !trapBlocks || !highTag) throw std::runtime_error("missing directed coverage");
    std::cout << "PRESELECT_REDIRECT_PASS cases=" << cases << " request_not_accepted=" << requestNotAccepted
              << " trap_mismatch_blocks=" << trapBlocks << " high_tag_rejects=" << highTag << '\n';
    return 0;
} catch (const std::exception &e) { std::cerr << "PRESELECT_REDIRECT_FAIL " << e.what() << '\n'; return 1; }
