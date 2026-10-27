#ifndef VALENCE_BUFFERED_SOURCE_LIFETIME_OBSERVER_H
#define VALENCE_BUFFERED_SOURCE_LIFETIME_OBSERVER_H

#include <array>
#include <compare>
#include <cstdint>
#include <map>
#include <optional>
#include <ostream>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>

// Passive verification of accepted-allocation source provenance. This does not
// independently validate rename, ISA semantics, or the values produced by the CPU.
// It never drives a DUT input. Run observe(dut) immediately after each normal
// GSIM step, excluding constructor reset steps. GSIM commits previous NEXT values
// before computing the sampled pre-edge events; we check our prior event shadow,
// then apply the sampled events for the next observation.
namespace buffered_source_lifetime {
struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    auto operator<=>(const Token &) const = default;
};
struct Candidate {
    bool valid = false;
    Token token;
    uint64_t address = 0;
    unsigned size = 0;
};
struct Owner : Candidate { unsigned epoch = 0; };
struct Allocation {
    bool valid = false;
    Token token;
    unsigned source = 0;
    uint64_t immediate = 0;
    unsigned size = 0;
    bool ordinary = false;
};
struct Event { bool valid = false; unsigned address = 0; };
struct Write : Event { uint64_t data = 0; };
struct Frame {
    std::array<Allocation, 2> allocations{};
    std::array<Write, 2> writes{};
    std::array<Event, 3> wakes{};
    std::array<Event, 2> reserves{};
    std::array<Candidate, 3> candidates{}; // Independent current, rank2, rank3 VAs.
    std::array<Owner, 5> owners{};          // Raw D0,D1,T,R0,R1.
    uint16_t pending = 0, memoryLive = 0, killed = 0;
    uint64_t ready = 0;
    unsigned live = 0;
    bool capture = false, queryAccept = false, queryFromDescriptor = false;
    unsigned captureLookahead = 0;
};
struct Counts {
    uint64_t cycles = 0, allocations = 0, ordinaryAllocations = 0;
    uint64_t writes = 0, reserves = 0, wakes = 0, sameAddressWrites = 0;
    uint64_t candidates = 0, current = 0, rank2 = 0, rank3 = 0;
    uint64_t captures = 0, rank2Captures = 0, rank3Captures = 0, directQueries = 0;
    uint64_t protectedChecks = 0, liveOwners = 0, deadOwners = 0, zeroSources = 0;
    uint64_t producedSourceCaptures = 0, producerBeforeCapture = 0;
};

class Observer {
    struct Captured { unsigned source; uint64_t immediate, value, address; unsigned size; };
    std::array<uint64_t, 48> values_{};
    std::array<bool, 48> initialized_{};
    std::array<uint64_t, 48> lastWriteCycle_{};
    uint64_t ready_ = UINT64_C(0xffffffff);
    std::array<std::optional<Allocation>, 16> latest_{};
    std::set<Token> allocated_;
    std::map<Token, Captured> captured_;
    Counts counts_;

    void require(bool ok, const std::string &why) const {
        if (!ok) throw std::runtime_error("BUFFERED_SOURCE_LIFETIME_FAIL cycle=" +
            std::to_string(counts_.cycles) + " " + why);
    }
    const Allocation *lookup(Token token) const {
        if (token.index >= latest_.size()) return nullptr;
        const auto &a = latest_[token.index];
        return a && a->token == token ? &*a : nullptr;
    }
    bool registeredLive(const Frame &f, const Candidate &c) const {
        const auto *a = lookup(c.token);
        return a && a->ordinary && a->size == c.size &&
            ((f.pending >> c.token.index) & 1U) && ((f.memoryLive >> c.token.index) & 1U);
    }
    uint64_t value(unsigned source) const {
        return source && source < values_.size() && initialized_[source] ? values_[source] : 0;
    }
    void protect(const Frame &f, const Candidate &c, const Allocation &a) {
        // Same-edge killed owners may be discarded without a source-stability promise.
        if (!registeredLive(f, c) || ((f.killed >> c.token.index) & 1U)) return;
        require(a.source < values_.size(), "surviving source outside physical capacity");
        require((ready_ >> a.source) & 1U, "surviving source not registered ready");
        if (a.source) {
            for (const auto &w : f.writes)
                require(!w.valid || w.address != a.source, "accepted write touches surviving ready source");
            for (const auto &r : f.reserves)
                require(!r.valid || r.address != a.source, "accepted reserve reallocates surviving source");
        } else ++counts_.zeroSources;
        ++counts_.protectedChecks;
    }
    const Allocation &verifyCandidate(const Frame &f, const Candidate &c) {
        require(c.token.index < 16, "candidate ROB index outside capacity");
        const auto *a = lookup(c.token);
        require(a != nullptr, "candidate lacks matching accepted allocation");
        require(a->ordinary && a->size == c.size, "candidate class/size differs from allocation");
        require(a->source < 48, "candidate source outside physical capacity");
        require(registeredLive(f, c), "candidate lacks registered full-token pending memory owner");
        require(c.address == value(a->source) + a->immediate,
            "independent allocation/PRF VA differs from candidate VA");
        protect(f, c, *a);
        return *a;
    }
    void remember(const Frame &f, const Candidate &c) {
        require(c.valid, "capture/query selected an invalid independent candidate");
        const auto &a = verifyCandidate(f, c);
        const Captured incoming{a.source, a.immediate, value(a.source), c.address, c.size};
        auto [it, fresh] = captured_.emplace(c.token, incoming);
        require(fresh || (it->second.source == incoming.source &&
            it->second.immediate == incoming.immediate && it->second.address == incoming.address &&
            it->second.size == incoming.size && it->second.value == incoming.value),
            "accepted allocation source/immediate/value changed across reservations");
        if (a.source && initialized_[a.source]) {
            ++counts_.producedSourceCaptures;
            require(lastWriteCycle_[a.source] < counts_.cycles,
                "capture used same-cycle producer rather than registered source");
            ++counts_.producerBeforeCapture;
        }
    }
public:
    Observer() = default;
    const Counts &counts() const { return counts_; }
    void reset() { *this = Observer{}; }

    void observeFrame(const Frame &f) {
        require(f.ready == ready_, "PRF ready shadow / GSIM event phase mismatch");
        require(!f.wakes[2].valid, "fast-load wake unexpectedly enabled in qualified profile");
        for (unsigned i = 0; i < f.candidates.size(); ++i) if (f.candidates[i].valid) {
            verifyCandidate(f, f.candidates[i]);
            ++counts_.candidates;
            if (i == 0) ++counts_.current;
            else if (i == 1) ++counts_.rank2;
            else ++counts_.rank3;
        }
        for (unsigned i = 0; i < f.owners.size(); ++i) {
            const auto &o = f.owners[i];
            if (!o.valid) continue; // Invalid payload is unspecified, including invalid indices.
            require(o.token.index < 16, "raw valid owner index outside capacity");
            const bool live = registeredLive(f, o);
            require(bool((f.live >> i) & 1U) == live, "owner-live metadata differs from allocation shadow");
            if (!live) { ++counts_.deadOwners; continue; }
            const auto *a = lookup(o.token);
            require(a != nullptr, "live owner lacks accepted allocation");
            require(a->source < 48, "live owner source outside capacity");
            // Source value is reconstructed from accepted producer writes, never from proof VA.
            require(o.address == value(a->source) + a->immediate,
                "independent allocation/PRF VA differs from held proof VA");
            const auto old = captured_.find(o.token);
            require(old != captured_.end(), "raw live proof lacks prior capture/query provenance");
            require(old->second.source == a->source && old->second.immediate == a->immediate &&
                old->second.address == o.address && old->second.size == o.size &&
                old->second.value == value(a->source), "held proof source lifetime changed");
            protect(f, o, *a);
            ++counts_.liveOwners;
        }
        if (f.capture) {
            require(f.captureLookahead < 2, "capture lookahead index outside two opportunities");
            remember(f, f.candidates[f.captureLookahead + 1]);
            ++counts_.captures;
            if (f.captureLookahead) ++counts_.rank3Captures; else ++counts_.rank2Captures;
        }
        if (f.queryAccept && !f.queryFromDescriptor) {
            remember(f, f.candidates[0]);
            ++counts_.directQueries;
        }

        // Apply this edge's events only after checking all pre-edge observations.
        if (f.writes[0].valid && f.writes[1].valid && f.writes[0].address == f.writes[1].address)
            ++counts_.sameAddressWrites;
        for (const auto &w : f.writes) if (w.valid) {
            ++counts_.writes;
            if (w.address && w.address < 48) {
                values_[w.address] = w.data; initialized_[w.address] = true;
                lastWriteCycle_[w.address] = counts_.cycles;
            }
        }
        for (const auto &w : f.wakes) if (w.valid) {
            ++counts_.wakes;
            if (w.address < 48) ready_ |= UINT64_C(1) << w.address;
        }
        for (const auto &r : f.reserves) if (r.valid) {
            ++counts_.reserves;
            if (r.address < 48) ready_ &= ~(UINT64_C(1) << r.address);
        }
        for (const auto &a : f.allocations) if (a.valid) {
            require(a.token.index < 16 && a.source < 48, "accepted allocation outside geometry");
            require(allocated_.insert(a.token).second, "accepted full allocation token duplicated");
            latest_[a.token.index] = a;
            ++counts_.allocations;
            counts_.ordinaryAllocations += a.ordinary;
        }
        ++counts_.cycles;
    }

    template<class Dut> void observe(Dut &dut) {
        Frame f;
#define BUFFERED_ALLOC(N) \
        f.allocations[N] = {bool(dut.get_bufferedProof$$allocation##N##$$valid()), \
            {unsigned(dut.get_bufferedProof$$allocation##N##$$bits$$token$$index()), \
             uint64_t(dut.get_bufferedProof$$allocation##N##$$bits$$token$$tag())}, \
            unsigned(dut.get_bufferedProof$$allocation##N##$$bits$$source1()), \
            uint64_t(dut.get_bufferedProof$$allocationImmediate##N()), \
            unsigned(dut.get_bufferedProof$$allocationSize##N()), \
            bool(dut.get_bufferedProof$$allocationOrdinary##N())};
        BUFFERED_ALLOC(0); BUFFERED_ALLOC(1);
#undef BUFFERED_ALLOC
#define BUFFERED_WRITE(N) \
        f.writes[N] = {{bool(dut.get_bufferedProof$$write##N##$$valid()), \
            unsigned(dut.get_bufferedProof$$write##N##$$bits$$address())}, \
            uint64_t(dut.get_bufferedProof$$write##N##$$bits$$data())};
        BUFFERED_WRITE(0); BUFFERED_WRITE(1);
#undef BUFFERED_WRITE
#define BUFFERED_EVENT(KIND, N, FIELD) \
        f.FIELD[N] = {bool(dut.get_bufferedProof$$##KIND##N##$$valid()), \
            unsigned(dut.get_bufferedProof$$##KIND##N##$$bits())};
        BUFFERED_EVENT(wake, 0, wakes); BUFFERED_EVENT(wake, 1, wakes); BUFFERED_EVENT(wake, 2, wakes);
        BUFFERED_EVENT(reserve, 0, reserves); BUFFERED_EVENT(reserve, 1, reserves);
#undef BUFFERED_EVENT
#define BUFFERED_CANDIDATE(PREFIX) Candidate{bool(dut.get_##PREFIX##$$valid()), \
        {unsigned(dut.get_##PREFIX##$$bits$$token$$index()), uint64_t(dut.get_##PREFIX##$$bits$$token$$tag())}, \
        uint64_t(dut.get_##PREFIX##$$bits$$address()), unsigned(dut.get_##PREFIX##$$bits$$size())}
        f.candidates[0] = BUFFERED_CANDIDATE(proof$$current);
        f.candidates[1] = BUFFERED_CANDIDATE(proof$$lookahead);
        f.candidates[2] = BUFFERED_CANDIDATE(bufferedProof$$lookaheadThird);
#define BUFFERED_OWNER(N, NAME) \
        f.owners[N] = {BUFFERED_CANDIDATE(bufferedProof$$##NAME), \
            unsigned(dut.get_bufferedProof$$##NAME##$$bits$$epoch())};
        BUFFERED_OWNER(0, descriptor0); BUFFERED_OWNER(1, descriptor1);
        BUFFERED_OWNER(2, translated); BUFFERED_OWNER(3, prepared0); BUFFERED_OWNER(4, prepared1);
#undef BUFFERED_OWNER
#undef BUFFERED_CANDIDATE
        f.pending = dut.get_bufferedProof$$pending();
        f.memoryLive = dut.get_bufferedProof$$memoryLive();
        f.killed = dut.get_bufferedProof$$killed();
        f.ready = dut.get_bufferedProof$$ready();
        f.live = dut.get_bufferedProof$$live();
        f.capture = dut.get_bufferedProof$$descriptorCapture();
        f.captureLookahead = dut.get_bufferedProof$$captureLookaheadIndex();
        f.queryAccept = dut.get_proof$$queryAccept();
        f.queryFromDescriptor = dut.get_proof$$queryFromDescriptor();
        observeFrame(f);
    }

    void report(std::ostream &out, const std::string &guest) const {
        out << "BUFFERED_SOURCE_LIFETIME_PASS guest=" << guest
            << " cycles=" << counts_.cycles << " allocations=" << counts_.allocations
            << " ordinary_allocations=" << counts_.ordinaryAllocations << " writes=" << counts_.writes
            << " wakes=" << counts_.wakes << " reserves=" << counts_.reserves
            << " same_address_writes=" << counts_.sameAddressWrites
            << " candidate_checks=" << counts_.candidates << " current_checks=" << counts_.current
            << " rank2_checks=" << counts_.rank2 << " rank3_checks=" << counts_.rank3
            << " captures=" << counts_.captures << " rank2_captures=" << counts_.rank2Captures
            << " rank3_captures=" << counts_.rank3Captures << " direct_queries=" << counts_.directQueries
            << " protected_checks=" << counts_.protectedChecks << " live_owner_checks=" << counts_.liveOwners
            << " dead_owner_ignored=" << counts_.deadOwners << " zero_source_checks=" << counts_.zeroSources
            << " produced_source_captures=" << counts_.producedSourceCaptures
            << " producer_before_capture=" << counts_.producerBeforeCapture
            << " scope=accepted_allocation_source_lifetime_not_ISA_or_rename\n";
    }
};
} // namespace buffered_source_lifetime
#endif
