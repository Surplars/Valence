#include "host/supply_ledger.h"
#include "policy_oracle.h"
#include "mock.h"
#include <iostream>
#include <string>

int main(int argc, char **argv) {
    const std::string mode = argc > 1 ? argv[1] : "";
    try {
        SupplyLedger ledger;
        unsigned cases = 0;
        for (unsigned valid = 0; valid < 4; ++valid)
        for (unsigned dirty = 0; dirty < 4; ++dirty)
        for (unsigned oldest = 0; oldest < 2; ++oldest)
        for (unsigned store = 0; store < 2; ++store)
        for (unsigned tokenKinds = 0; tokenKinds < 4; ++tokenKinds)
        for (unsigned consumed = 0; consumed < 2; ++consumed)
        for (unsigned alias = 0; alias < 4; ++alias)
        for (unsigned tokenWay = 0; tokenWay < 2; ++tokenWay) {
            // Independent authored access history establishes residency and LRU.
            const uint64_t target = 0x80400000ULL + 37 * 64;
            const uint64_t resident[2] = {target + 0x1000000, target + 0x2000000};
            lru_victim_oracle::Policy policy(256, STORE_PREFETCH_LRU_VICTIM);
            for (unsigned way = 0; way < 2; ++way)
                policy.install(resident[way], way, dirty & (1U << way), false, false, false);
            policy.hit(resident[1-oldest], false);
            for (unsigned way = 0; way < 2; ++way)
                if (!(valid & (1U << way))) policy.invalidate(resident[way]);
            const auto &state = policy.state(target);
            auto choice = policy.choose(target, true, store);
            const unsigned preferred = choice.slot;
            const unsigned opposite = 1-store;
            const bool relevant = tokenKinds & (1U << opposite);
            const uint64_t tokenPa = resident[tokenWay] + (alias == 1 ? 0x10000 : 0);
            const unsigned tokenIndex = policy.slot(target, tokenWay) +
                (alias == 2 ? (tokenWay ? -256 : 256) : alias == 3 ? 1 : 0);
            auto protectedWay = [&](unsigned way) {
                return relevant && !consumed && state.ways[way].valid &&
                    tokenIndex == policy.slot(target, way) && tokenPa == state.ways[way].address;
            };
            if (protectedWay(choice.way)) choice.way = 1-choice.way;
            choice.slot = policy.slot(target, choice.way);
            const auto victim = state.ways[choice.way];
            Mock d;
            for (unsigned way = 0; way < 2; ++way) {
                const unsigned slot = policy.slot(target, way);
                d.board$platform$privateCache$valid[slot] = state.ways[way].valid;
                d.board$platform$privateCache$dirty[slot] = dirty & (1U << way);
                (way ? d.board$platform$privateCache$tagBanks_1 : d.board$platform$privateCache$tagBanks_0)[37] = resident[way] >> 14;
                d.tokenValid[way] = tokenKinds & (1U << way);
                d.tokenConsumed[way] = consumed;
                d.tokenPa[way] = tokenPa; d.tokenIndex[way] = tokenIndex;
            }
            d.board$platform$privateCache$replacement[37] = state.oldest;
            // Deliberately corrupt observation, not oracle expectations. Each injection
            // has a non-vacuous full-set witness and must fail the unchanged comparison.
            bool inject = false;
            if (valid == 3 && dirty == 3 && store && tokenKinds == 0 && mode == "--wrong-lru") {
                d.board$platform$privateCache$replacement[37] ^= 1; inject = true;
            }
            if (valid == 3 && tokenKinds == 0 && mode == "--wrong-pa") {
                d.board$platform$privateCache$tagBanks_0[37] ^= 4; inject = true;
            }
            if (valid == 3 && relevant && !consumed && alias == 0 &&
                tokenWay == preferred / 256 && mode == "--wrong-protection") {
                d.tokenConsumed[opposite] = true; inject = true;
            }
            if (inject) std::cerr << "POLICY_INJECTION_REACHED " << mode << '\n';
            auto got = ledger.guard(d, target, store);
            if (got.preferred != preferred || got.index != choice.slot)
                throw std::runtime_error("victim identity mismatch");
            for (unsigned way = 0; way < 2; ++way) {
                if (got.address[way] != (state.ways[way].valid ? state.ways[way].address : 0))
                    throw std::runtime_error("full PA mismatch");
                if (bool(got.allowedMask & (1U << way)) != !protectedWay(way))
                    throw std::runtime_error("token protection mismatch");
            }
            if (got.validMask != valid || got.dirtyMask != (valid & dirty) ||
                got.replacement != state.oldest ||
                (got.address[choice.way] != (victim.valid ? victim.address : 0)))
                throw std::runtime_error("residency metadata mismatch");
            if (inject) throw std::runtime_error("negative unexpectedly survived comparison");
            ++cases;
        }
        if (!mode.empty()) throw std::runtime_error("injection unreachable");
        std::cout << "POLICY_GUARD_PASS lru=" << STORE_PREFETCH_LRU_VICTIM << " cases=" << cases << '\n';
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "POLICY_GUARD_FAIL " << e.what() << '\n'; return 1;
    }
}
