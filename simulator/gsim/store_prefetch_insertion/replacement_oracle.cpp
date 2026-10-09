// Independent host-only specification. No DUT source, generated model, or RTL is included.
// Recency is an explicit oldest-to-newest list, deliberately not the DUT's victim bit.
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

enum class Origin { Demand, ReadPrefetch, StorePrefetch };
enum class Fault { None, StoreLru, ReadMru, LiveOrigin, StaleDemand, ErrorTouches };
static unsigned checks = 0;
static void check(bool okay, const std::string& why) {
    ++checks;
    if (!okay) throw std::runtime_error(why);
}

struct Entry { bool valid = false; std::uint64_t line = 0; };
class SetState {
public:
    std::vector<Entry> entries;
    std::vector<std::size_t> oldestFirst;
    explicit SetState(unsigned ways) : entries(ways) {
        check(ways == 1 || ways == 2, "unsupported associativity");
        if (ways == 2) oldestFirst = {0, 1};
    }
    std::size_t victim() const {
        for (std::size_t i = 0; i < entries.size(); ++i)
            if (!entries[i].valid) return i;
        return entries.size() == 1 ? 0 : oldestFirst.front();
    }
    bool contains(std::uint64_t line) const {
        return std::any_of(entries.begin(), entries.end(), [line](const Entry& e) {
            return e.valid && e.line == line;
        });
    }
    void install(std::size_t slot, std::uint64_t line, bool newest) {
        check(slot < entries.size(), "installation outside set");
        entries[slot] = {true, line};
        if (entries.size() == 1) return;
        oldestFirst.erase(std::find(oldestFirst.begin(), oldestFirst.end(), slot));
        if (newest) oldestFirst.push_back(slot);
        else oldestFirst.insert(oldestFirst.begin(), slot);
    }
};

struct Owner { bool busy = false; Origin origin = Origin::Demand; unsigned generation = 0; };
struct Completion { Origin origin; bool demandResponse; };
class OwnerPool {
    std::vector<Owner> owners;
    bool storeMru;
    Fault fault;
public:
    Origin currentCandidate = Origin::ReadPrefetch;
    explicit OwnerPool(unsigned capacity, bool policy, Fault injected = Fault::None)
        : owners(capacity), storeMru(policy), fault(injected) {
        check(capacity == 2 || capacity == 4, "prefetch requires capacity two or four");
    }
    const Owner& at(unsigned slot) const { return owners.at(slot); }
    unsigned allocate(unsigned slot, Origin origin) {
        auto& owner = owners.at(slot);
        check(!owner.busy, "attempted live-owner reuse");
        owner.busy = true;
        if (!(fault == Fault::StaleDemand && origin == Origin::Demand && owner.generation != 0))
            owner.origin = origin;
        return ++owner.generation;
    }
    Completion complete(unsigned slot, unsigned generation, SetState& set,
                        std::size_t way, std::uint64_t line, bool success = true) {
        auto& owner = owners.at(slot);
        check(owner.busy && owner.generation == generation, "completion lacks matching live owner");
        auto origin = owner.origin;
        if (fault == Fault::LiveOrigin && origin != Origin::Demand) origin = currentCandidate;
        const bool newest = origin == Origin::Demand ||
            (origin == Origin::StorePrefetch && storeMru && fault != Fault::StoreLru) ||
            (origin == Origin::ReadPrefetch && fault == Fault::ReadMru);
        if (success || fault == Fault::ErrorTouches) set.install(way, line, newest);
        owner.busy = false; // Retain stale origin deliberately; allocation must overwrite it.
        return {origin, origin == Origin::Demand};
    }
};

static Completion fill(OwnerPool& pool, SetState& set, unsigned owner, Origin origin,
                       std::size_t way, std::uint64_t line, bool success = true) {
    if (origin != Origin::Demand) pool.currentCandidate = origin;
    const auto generation = pool.allocate(owner, origin);
    return pool.complete(owner, generation, set, way, line, success);
}
static SetState seed(unsigned ways = 2) {
    SetState set(ways);
    set.install(0, 10, true);
    if (ways == 2) set.install(1, 20, true);
    return set;
}
static void conflict(unsigned capacity, bool policy, Fault fault) {
    OwnerPool pool(capacity, policy, fault);
    auto set = seed();
    // Authored A/B sequence: way 0 is the chosen clean PF victim; way 1 is alternate.
    fill(pool, set, 0, Origin::StorePrefetch, 0, 30); // Future B line.
    const auto victim = set.victim();
    check(victim == (policy ? 1u : 0u), "store PF A/B conflict selected wrong victim");
    fill(pool, set, 1, Origin::Demand, victim, 40); // Same-set A demand.
    check(set.contains(30) == policy, "A/B trace did not preserve/evict B as specified");
    check(set.contains(20) != policy, "A/B trace did not evict/preserve alternate as specified");
    check(set.contains(40), "A demand did not install");
    // The next B-store lookup is a hit only for MRU. This is not a timing claim.
}
static void readOrigin(unsigned capacity, bool policy, Fault fault) {
    OwnerPool pool(capacity, policy, fault);
    auto set = seed();
    fill(pool, set, 0, Origin::ReadPrefetch, 0, 30);
    check(set.victim() == 0, "read-origin prefetch must remain oldest with both policies");
}
static void capturedOrigin(unsigned capacity, Fault fault) {
    for (auto origin : {Origin::StorePrefetch, Origin::ReadPrefetch}) {
        OwnerPool pool(capacity, true, fault);
        auto set = seed();
        pool.currentCandidate = origin;
        const auto generation = pool.allocate(0, origin);
        pool.currentCandidate = origin == Origin::StorePrefetch ? Origin::ReadPrefetch : Origin::StorePrefetch;
        const auto result = pool.complete(0, generation, set, 0, 30);
        check(result.origin == origin, "refill followed current candidate rather than captured origin");
        check(set.victim() == (origin == Origin::StorePrefetch ? 1u : 0u), "captured insertion wrong");
        check(!result.demandResponse, "prefetch invented a demand response");
    }
}
static void reuseAndError(unsigned capacity, bool policy, Fault fault) {
    OwnerPool pool(capacity, policy, fault);
    auto set = seed();
    fill(pool, set, 0, Origin::StorePrefetch, 0, 30);
    check(!pool.at(0).busy && pool.at(0).origin == Origin::StorePrefetch, "stale-owner fixture absent");
    const auto result = fill(pool, set, 0, Origin::Demand, 0, 40);
    check(result.origin == Origin::Demand && result.demandResponse, "demand inherited freed PF origin");
    check(set.victim() == 1, "reused demand owner failed to install newest");
    set.entries[0].valid = false; // Victim invalidation precedes refill; model snapshots afterward.
    const auto order = set.oldestFirst;
    fill(pool, set, 0, Origin::StorePrefetch, 0, 50, false);
    check(set.oldestFirst == order, "error changed replacement metadata");
    check(!set.entries[0].valid && !set.contains(50), "error installed a line");
    check(set.entries[1].valid && set.entries[1].line == 20, "error changed alternate line");
}
static void oneWay(unsigned capacity, bool policy, Fault fault) {
    OwnerPool pool(capacity, policy, fault);
    auto set = seed(1);
    for (auto origin : {Origin::Demand, Origin::ReadPrefetch, Origin::StorePrefetch}) {
        fill(pool, set, 0, origin, 0, 30);
        check(set.oldestFirst.empty(), "one-way cache acquired replacement metadata");
        check(set.victim() == 0 && set.contains(30), "one-way placement changed");
    }
}
static void fullCapacity(unsigned capacity, bool policy, Fault fault) {
    for (auto pfOrigin : {Origin::ReadPrefetch, Origin::StorePrefetch}) {
        OwnerPool pool(capacity, policy, fault);
        std::vector<SetState> sets(capacity, seed());
        std::vector<unsigned> generations;
        for (unsigned i = 0; i < capacity; ++i)
            generations.push_back(pool.allocate(i, i == capacity - 1 ? pfOrigin : Origin::Demand));
        // Separate sets, one live PF, reverse completion order. No merging is implied.
        for (unsigned i = capacity; i-- > 0;) {
            const auto origin = i == capacity - 1 ? pfOrigin : Origin::Demand;
            pool.currentCandidate = pfOrigin == Origin::ReadPrefetch ? Origin::StorePrefetch : Origin::ReadPrefetch;
            const auto result = pool.complete(i, generations[i], sets[i], 0, 100 + i);
            check(result.origin == origin, "out-of-order fill changed owner origin");
            check(result.demandResponse == (origin == Origin::Demand), "response ownership changed");
            const bool newest = origin == Origin::Demand || (origin == Origin::StorePrefetch && policy);
            check(sets[i].victim() == (newest ? 1u : 0u), "capacity changed insertion");
        }
        for (unsigned i = 0; i < capacity; ++i) check(!pool.at(i).busy, "owner pool failed to drain");
    }
}
int main(int argc, char** argv) {
    try {
        Fault fault = Fault::None;
        if (argc == 2) {
            const std::string arg(argv[1]);
            if (arg == "--mutate-store-lru") fault = Fault::StoreLru;
            else if (arg == "--mutate-read-mru") fault = Fault::ReadMru;
            else if (arg == "--mutate-live-origin") fault = Fault::LiveOrigin;
            else if (arg == "--mutate-stale-demand") fault = Fault::StaleDemand;
            else if (arg == "--mutate-error-touches") fault = Fault::ErrorTouches;
            else throw std::runtime_error("unknown mutation");
        } else if (argc != 1) throw std::runtime_error("usage: replacement_oracle [--mutate-...]");
        for (unsigned capacity : {2u, 4u}) {
            for (bool policy : {false, true}) {
                conflict(capacity, policy, fault);
                readOrigin(capacity, policy, fault);
                reuseAndError(capacity, policy, fault);
                oneWay(capacity, policy, fault);
                fullCapacity(capacity, policy, fault);
            }
            capturedOrigin(capacity, fault);
        }
        std::cout << "HOST_ORACLE_PASS checks=" << checks << " capacities=2,4 ways=1,2 policies=off,on\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "HOST_ORACLE_FAIL checks=" << checks << " reason=" << error.what() << '\n';
        return 1;
    }
}
