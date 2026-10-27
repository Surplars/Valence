#pragma once
#include "buffered_return_flow_observer.h"
#include <cstdlib>
#include <iostream>
#include <fstream>

// ONLY the sealed 7daf119 OFF/ROB16 generated layout is supported. No fallback
// for absent raw fields and no writes after the pristine reset-only injection.
namespace buffered_index_initial_state {
using buffered_return_flow::Row;
using buffered_return_flow::require;
class Observer {
    bool injected = false;
    std::array<bool, 16> written{};
    std::array<Row, 16> allocated{};
    unsigned pattern = 0;
    std::ofstream trace;
    uint64_t cycles = 0, liveChecks = 0, allocations = 0, digest = 1469598103934665603ULL;
public:
    void hash(uint64_t value) { digest ^= value; digest *= 1099511628211ULL; }
    void record(uint64_t value) {
        hash(value);
        for (unsigned byte = 0; byte < 8; ++byte) trace.put(char((value >> (8 * byte)) & 255));
        require(bool(trace), "INDEX_TRACE_WRITE_FAILED");
    }
    template<class D> void initialize(D &d, const std::string &name) {
        require(!injected && cycles == 0 && allocations == 0, "INDEX_POISON_NOT_PRISTINE");
        const char *text = std::getenv("A1_INDEX_INITIAL_PATTERN");
        require(text && text[0] >= '0' && text[0] <= '3' && text[1] == '\0', "INDEX_POISON_EXACT_PATTERN_REQUIRED");
        pattern = unsigned(text[0] - '0');
        require(d.get_bufferedProof$$pending() == 0 && d.get_bufferedProof$$memoryLive() == 0 &&
            !d.get_bufferedProof$$allocation0$$valid() && !d.get_bufferedProof$$allocation1$$valid(),
            "INDEX_POISON_LIVE_ALLOCATION_AT_INITIALIZATION");
#define EMPTY_STATE(NAME) require(!d.tile$core$core$core$backend$##NAME && \
    !d.tile$core$core$core$backend$##NAME##$NEXT, "INDEX_POISON_RETAINED_" #NAME)
        EMPTY_STATE(systemProtected); EMPTY_STATE(memoryProtected); EMPTY_STATE(stagedMemoryValid);
        EMPTY_STATE(replayPendingValid); EMPTY_STATE(ledger$count);
#undef EMPTY_STATE
        require(d.get_supply$$states() == 0 && !d.get_io$$memoryBusy(), "INDEX_POISON_EXISTING_EXECUTION_OWNER");
        for (unsigned i = 0; i < 16; ++i) {
            require(!d.tile$core$core$core$backend$pending[i] &&
                !d.tile$core$core$core$backend$pending$NEXT[i] &&
                !d.tile$core$core$core$backend$memoryLive[i] &&
                !d.tile$core$core$core$backend$memoryLive$NEXT[i], "INDEX_POISON_CURRENT_NEXT_AUTHORITY");
            const uint8_t poison = pattern == 0 ? 0 : pattern == 1 ? i : pattern == 2 ? 15-i : i ^ 10;
            d.tile$core$core$core$backend$queue$$renamed$$token$$index[i] = poison;
            d.tile$core$core$core$backend$queue$$renamed$$token$$index$NEXT[i] = poison;
        }
        const char *prefix = std::getenv("A1_INDEX_TRACE_PREFIX");
        require(prefix && *prefix, "INDEX_TRACE_PREFIX_REQUIRED");
        require(name.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") == std::string::npos,
                "INDEX_TRACE_SAFE_GUEST_NAME");
        const std::string path = std::string(prefix) + "-" + name + ".bin";
        require(!std::ifstream(path).good(), "INDEX_TRACE_REFUSE_OVERWRITE");
        trace.open(path, std::ios::binary | std::ios::out);
        require(bool(trace), "INDEX_TRACE_OPEN_FAILED");
        injected = true;
    }
    template<class D> void observe(D &d) {
        require(injected, "INDEX_POISON_MISSING_INITIALIZATION");
        const uint16_t live = d.get_bufferedProof$$pending() | d.get_bufferedProof$$memoryLive();
        for (unsigned i = 0; i < 16; ++i) {
            if (written[i]) require(d.tile$core$core$core$backend$queue$$renamed$$token$$index[i] == i,
                                    "INDEX_WRITTEN_ROW_ADDRESS_INVARIANT");
            if ((live >> i) & 1) {
                ++liveChecks; require(written[i], "INDEX_LIVE_ROW_UNWRITTEN");
                const Row actual{d.tile$core$core$core$backend$queue$$renamed$$token$$tag[i],
                    unsigned(d.tile$core$core$core$backend$queue$$renamed$$source1[i]),
                    unsigned(d.tile$core$core$core$backend$queue$$renamed$$source2[i]),
                    unsigned(d.tile$core$core$core$backend$queue$$renamed$$destination[i]),
                    bool(d.tile$core$core$core$backend$queue$$renamed$$writesRd[i])};
                require(actual == allocated[i], "INDEX_LIVE_ROW_FULL_TAG_SOURCE_OWNER");
            }
        }
        require(!(d.get_bufferedProof$$allocation0$$valid() && d.get_bufferedProof$$allocation1$$valid() &&
            d.get_bufferedProof$$allocation0$$bits$$token$$index() == d.get_bufferedProof$$allocation1$$bits$$token$$index()),
            "INDEX_DUAL_ROW_ALIAS");
#define ACCEPT(N) if (d.get_bufferedProof$$allocation##N##$$valid()) { \
    const unsigned i = d.get_bufferedProof$$allocation##N##$$bits$$token$$index(); \
    require(i < 16, "INDEX_ACCEPTED_ALLOCATION_GEOMETRY"); \
    allocated[i] = {uint64_t(d.get_bufferedProof$$allocation##N##$$bits$$token$$tag()), \
        unsigned(d.get_bufferedProof$$allocation##N##$$bits$$source1()), \
        unsigned(d.get_bufferedProof$$allocation##N##$$bits$$source2()), \
        unsigned(d.get_bufferedProof$$allocation##N##$$bits$$destination()), \
        bool(d.get_bufferedProof$$allocation##N##$$bits$$writesRd())}; \
    written[i] = true; ++allocations; }
        ACCEPT(0); ACCEPT(1);
#undef ACCEPT
        // Generated exhaustive top-output schema: all ready/valid/control are
        // unconditional, protocol payloads are compared throughout valid stalls.
        traceOutputs(d);
        ++cycles;
    }
    template<class D> void traceOutputs(D &d);
    void report(std::ostream &out, const std::string &name) {
        trace.close();
        require(bool(trace), "INDEX_TRACE_CLOSE_FAILED");
        require(injected && cycles && allocations && liveChecks, "INDEX_EMPTY_TRACE");
        out << "INDEX_INITIAL_STATE name=" << name << " pattern=" << pattern << " cycles=" << cycles
            << " allocations=" << allocations << " live_checks=" << liveChecks << " digest=" << digest << '\n';
    }
};
}
