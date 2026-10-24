#include "FetchCompletionLedgerGsim.h"
#include <deque>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
struct Owner { uint64_t token, data, due; unsigned slot, errors, pages; bool done; };
int main(int argc, char **argv) { try {
    const std::string mode = argc == 2 ? argv[1] : "";
    check(argc <= 2 && (mode.empty() || mode == "--wrong-generation" || mode == "--duplicate" ||
        mode == "--unowned" || mode == "--inject-result"), "bad ledger argument");
    SFetchCompletionLedgerGsim d;
    d.set_io$$allocate(0); d.set_io$$token(0); d.set_io$$terminal(0); d.set_io$$complete(0);
    d.set_io$$completeSlot(0); d.set_io$$completeToken(0); d.set_io$$data(0);
    d.set_io$$errors(0); d.set_io$$pages(0); d.set_io$$resultReady(0);
    d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    std::deque<Owner> live;
    unsigned accepted = 0, retired = 0, tail = 0, reordered = 0, held = 0, simultaneous = 0, full = 0;
    for (uint64_t cycle = 0; cycle < 10000; ++cycle) {
        const bool ready = cycle % 13 >= 5;
        const bool result = !live.empty() && live.front().done;
        const bool release = result && ready;
        const bool take = accepted < 256 && (live.size() < 2 || release);
        const bool terminal = accepted % 7 == 6;
        std::optional<Owner> completion;
        for (const auto &o : live) if (!o.done && cycle >= o.due) completion = o; // young ready first
        if (mode == "--unowned" && cycle == 0) completion = Owner{99, 0, 0, 1, 0, 0, false};
        if (mode == "--duplicate" && result && !ready) completion = live.front();
        uint64_t token = completion ? completion->token : 0;
        if (completion && mode == "--wrong-generation") { std::cerr << "INJECT generation\n"; token ^= 1; }
        if (completion && mode == "--unowned") std::cerr << "INJECT unowned\n";
        if (completion && completion->done && mode == "--duplicate") std::cerr << "INJECT duplicate\n";
        d.set_io$$allocate(accepted < 256); d.set_io$$token(1000 + accepted); d.set_io$$terminal(terminal);
        d.set_io$$complete(bool(completion)); d.set_io$$completeSlot(completion ? completion->slot : 0);
        d.set_io$$completeToken(token); d.set_io$$data(completion ? completion->data : 0);
        d.set_io$$errors(completion ? completion->errors : 0); d.set_io$$pages(completion ? completion->pages : 0);
        d.set_io$$resultReady(ready); d.step();
        check(bool(d.get_io$$allocationReady()) == (live.size() < 2 || release), "ledger credit mismatch");
        check(d.get_io$$allocationSlot() == tail, "allocation slot sequence mismatch");
        check(bool(d.get_io$$idle()) == live.empty(), "ledger idle owner mismatch");
        check(bool(d.get_io$$resultValid()) == result, "younger completion passed old head");
        if (result) {
            auto observed = d.get_io$$resultToken();
            if (mode == "--inject-result") { std::cerr << "INJECT result\n"; observed ^= 1; }
            const auto &o = live.front();
            check(observed == o.token && d.get_io$$resultData() == o.data &&
                d.get_io$$resultErrors() == o.errors && d.get_io$$resultPages() == o.pages,
                "independent ordered ledger result mismatch");
            held += !ready;
        }
        if (completion) {
            check(mode != "--wrong-generation" && mode != "--unowned" && !completion->done,
                "bad completion was not rejected by hardware");
            reordered += completion->token != live.front().token;
            for (auto &o : live) if (o.token == completion->token) o.done = true;
        }
        full += live.size() == 2;
        if (release) { live.pop_front(); ++retired; }
        if (take) {
            const uint64_t t = 1000 + accepted;
            live.push_back({t, terminal ? 0 : (t * UINT64_C(0x102030405)),
                cycle + (accepted % 2 ? 1 : 17), tail,
                terminal ? 0U : accepted % 4, terminal ? 0U : (accepted / 4) % 4, terminal});
            tail ^= 1; ++accepted; simultaneous += release;
        }
        if (retired == 256 && live.empty()) break;
    }
    check(mode.empty() && accepted == 256 && retired == 256 && reordered > 30 && held > 20 &&
        simultaneous > 30 && full > 100, "ledger coverage/drain incomplete");
    std::cout << "PASS A2_FETCH_LEDGER accepted=" << accepted << " retired=" << retired
        << " younger_completions=" << reordered << " held=" << held << " turnover=" << simultaneous
        << " full=" << full << '\n'; return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
