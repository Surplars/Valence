// Host-only tests. They do not simulate a CPU/cache or claim an old/fixed result.
#include "directed_seal_witness.h"
#include <iostream>

using namespace posted_seal_regression;
int main() {
    try {
        const auto program = guest::interpret();
        unsigned controls = 0;
        auto rejects = [&](const auto &run) {
            bool caught = false;
            try { run(); } catch (const std::runtime_error &) { caught = true; }
            guest::require(caught, "directed witness negative control escaped");
            ++controls;
        };
        auto tokenFor = [](uint64_t pc) { return Token{UINT64_C(0x100000000) + (pc - guest::romBase) / 4,
            ((pc - guest::romBase) / 4) & 15}; };
        auto build = [&](const std::array<unsigned, 4> &counts) {
            Witness witness(program);
            unsigned ordinal = 0;
            for (const auto address : guest::directedLines) {
                const Owner owner{ordinal % 2, 10 + ordinal};
                const auto pcs = witness.lines.at(address).expectedPcs;
                unsigned member = 0;
                for (const auto pc : pcs) {
                    const auto token = tokenFor(pc);
                    witness.launch(token, pc, 10 + member);
                    if (member < counts.at(ordinal)) witness.member(token, pc, address, owner, 30 + member);
                    witness.retire(token, pc);
                    ++member;
                }
                witness.install(address, owner, 100);
                witness.release(address, owner, 120);
                ++ordinal;
            }
            return witness;
        };
        auto complete = build({8, 8, 8, 8}); complete.finish();
        guest::require(complete.allEightLines() == 4, "eight-of-eight positive witness changed");
        auto threshold = build({2, 2, 2, 2}); threshold.finish();
        rejects([&] { auto oldPattern = build({3, 1, 1, 1}); oldPattern.finish(); });
        rejects([&] { auto globalJoin = build({8, 8, 8, 1}); globalJoin.finish(); });
        rejects([&] { Witness missing(program); missing.finish(); });
        const auto address = guest::directedLines[0];
        const auto pc = *complete.lines.at(address).expectedPcs.begin();
        const auto pc2 = *std::next(complete.lines.at(address).expectedPcs.begin());
        const auto token = tokenFor(pc), token2 = tokenFor(pc2);
        const Owner owner{0, 10};
        rejects([&] { Witness w(program); w.launch(token, pc, 10); w.launch(token, pc, 11); });
        rejects([&] { Witness w(program); w.launch(token, pc, 10);
            w.member({token.tag ^ (UINT64_C(1) << 32), token.index}, pc, address, owner, 20); });
        rejects([&] { Witness w(program); w.launch(token, pc, 10);
            w.member(token, pc, guest::directedLines[1], owner, 20); });
        rejects([&] { Witness w(program); w.launch(token, pc, 10); w.member(token, pc, address, owner, 20);
            w.member(token, pc, address, owner, 21); });
        rejects([&] { Witness w(program); w.launch(token, pc, 10); w.launch(token2, pc2, 11);
            w.member(token, pc, address, owner, 20); w.member(token2, pc2, address, {owner.slot, owner.generation + 1}, 21); });
        rejects([&] { Witness w(program); w.launch(token, pc, 10); w.launch(token2, pc2, 11);
            w.member(token, pc, address, owner, 20); w.install(address, owner, 30); w.member(token2, pc2, address, owner, 31); });
        rejects([&] { Witness w(program); w.launch(token, pc, 10); w.member(token, pc, address, owner, 20);
            w.install(address, {owner.slot, owner.generation + 1}, 30); });
        rejects([&] { Witness w(program); w.launch(token, pc, 10); w.member(token, pc, address, owner, 20);
            w.release(address, owner, 30); });
        rejects([&] { Witness w(program); w.launch(token, pc, 10); w.retire({token.tag + 1, token.index}, pc); });
        std::cout << "DIRECTED_SEAL_HOST_ONLY_PASS raw_instructions=" << program.trace.size()
            << " cold_lines=4 authored_stores_per_line=8 required_members_per_line=2 positive_controls=2"
            << " rejected_controls=" << controls << " rtl_executed=0\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "DIRECTED_SEAL_HOST_ONLY_FAIL " << error.what() << '\n';
        return 1;
    }
}
