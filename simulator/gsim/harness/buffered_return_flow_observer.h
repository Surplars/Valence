#pragma once
#include <array>
#include <cstdint>
#include <deque>
#include <ostream>
#include <stdexcept>
#include <string>
#include <optional>
#include <vector>

// Candidate-only observation, not a permission or scheduling input.  Identity
// comes from accepted allocations; response ordering from accepted input beats.
namespace buffered_return_flow {
inline void require(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
struct Row {
    uint64_t tag = 0;
    unsigned source1 = 0, source2 = 0, destination = 0;
    bool writes = false;
    bool operator==(const Row &) const = default;
};
struct Allocation { bool valid = false; unsigned index = 0; Row row; };
struct Reply {
    uint64_t data = 0; bool error = false, pageFault = false;
    bool operator==(const Reply &) const = default;
};
struct Token {
    unsigned index = 0; uint64_t tag = 0;
    bool operator==(const Token &) const = default;
};
struct SlotOwner {
    Token token; uint64_t acceptedAt = 0;
    bool forwarded = false, replied = false;
};
struct SlotReplyEvent {
    Token token; uint64_t acceptedAt, cycle; unsigned slot;
    bool outerReplySameCycle, anyCompleteSameCycle;
};
struct Frame {
    std::array<Row, 16> rows{};
    std::array<Allocation, 2> allocations{};
    uint16_t pending = 0, memoryLive = 0;
    uint64_t rawIndices = 0, viewIndices = 0;
    unsigned occupancy = 0;
    unsigned startSlots = 0, completeSlots = 0, slotReplyAccepts = 0, liveSlots = 0;
    bool startValid = false, completeValid = false, startForwarded = false;
    Token startToken, completeToken;
    bool inputValid = false, inputReady = false, outputValid = false, outputReady = false;
    Reply input, output;
    bool adapterIdle = false, backendIdle = false, fpEpoch = false, integerBusy = false;
};
class Observer {
    std::array<Row, 16> allocated{};
    std::array<bool, 16> written{};
    std::deque<Reply> queued;
    std::array<std::optional<SlotOwner>, 4> slots{};
    std::vector<SlotReplyEvent> slotReplies;
    uint64_t slotStarts = 0, slotCompletions = 0, releasedWithoutCompletion = 0;
    static unsigned oneSlot(unsigned mask) {
        require(mask && mask < 16 && !(mask & (mask - 1)), "RETURN_FLOW_SLOT_ONEHOT");
        unsigned slot = 0; while (!(mask & (1U << slot))) ++slot; return slot;
    }
    uint64_t cycles = 0, allocations = 0, liveChecks = 0, accepted = 0, consumed = 0;
    uint64_t bypass = 0, captured = 0, queuedPops = 0, fullPop = 0, faults = 0, fp = 0;
public:
    void observeFrame(const Frame &f) {
        // Events are associated with the independently accepted start owner,
        // not with a DUT-provided reply token.  The mask is actual slot response
        // acceptance, NOT a promise that result Reg is written for every cancel.
        for (unsigned slot = 0; slot < 4; ++slot) if (slots[slot] && !(f.liveSlots & (1U << slot))) {
            require(slots[slot]->replied, "RETURN_FLOW_SLOT_DISAPPEARED_BEFORE_REPLY");
            ++releasedWithoutCompletion; slots[slot].reset();
        }
        if (f.completeValid) {
            const unsigned slot = oneSlot(f.completeSlots);
            require(slots[slot].has_value() && slots[slot]->token == f.completeToken,
                    "RETURN_FLOW_COMPLETE_FULL_OWNER");
            require(slots[slot]->forwarded || slots[slot]->replied, "RETURN_FLOW_COMPLETE_BEFORE_SLOT_REPLY");
            slots[slot].reset(); ++slotCompletions;
        } else require(!f.completeSlots, "RETURN_FLOW_UNOWNED_COMPLETE_MASK");
        if (f.startValid) {
            const unsigned slot = oneSlot(f.startSlots);
            require(!slots[slot], "RETURN_FLOW_LIVE_SLOT_OVERWRITE");
            require(f.startToken.index < 16, "RETURN_FLOW_START_INDEX");
            slots[slot] = SlotOwner{f.startToken, cycles, f.startForwarded, false}; ++slotStarts;
        } else require(!f.startSlots, "RETURN_FLOW_UNOWNED_START_MASK");
        for (unsigned slot = 0; slot < 4; ++slot) if (f.slotReplyAccepts & (1U << slot)) {
            require(slots[slot].has_value(), "RETURN_FLOW_SLOT_REPLY_WITHOUT_START");
            require(!slots[slot]->replied, "RETURN_FLOW_DUPLICATE_SLOT_REPLY");
            slots[slot]->replied = true;
            slotReplies.push_back({slots[slot]->token, slots[slot]->acceptedAt, cycles, slot,
                f.outputValid && f.outputReady, f.completeValid});
        }
        ++cycles;
        require(f.occupancy == queued.size(), "RETURN_FLOW_OCCUPANCY");
        require(f.inputReady == (queued.size() < 2), "RETURN_FLOW_OLD_OCCUPANCY_CREDIT");
        const bool valid = !queued.empty() || f.inputValid;
        require(f.outputValid == valid, "RETURN_FLOW_VALID_CONSERVATION");
        if (valid) require(f.output == (queued.empty() ? f.input : queued.front()), "RETURN_FLOW_FULL_PAYLOAD_ORDER");
        require(!(f.fpEpoch && f.integerBusy), "RETURN_FLOW_FP_EXCLUSIVE_OWNER");
        if (f.inputValid || !queued.empty())
            require(!(f.adapterIdle && f.backendIdle && f.occupancy == 0), "RETURN_FLOW_PREMATURE_AGGREGATE_IDLE");
        const bool in = f.inputValid && f.inputReady, out = f.outputValid && f.outputReady;
        const bool empty = queued.empty();
        if (out) {
            ++consumed; faults += f.output.error || f.output.pageFault; fp += f.fpEpoch;
            if (!empty) { fullPop += queued.size() == 2; queued.pop_front(); ++queuedPops; }
        }
        if (in) {
            ++accepted;
            if (empty && out) ++bypass;
            else { queued.push_back(f.input); ++captured; }
        }
        require(accepted == consumed + queued.size(), "RETURN_FLOW_BEAT_CONSERVATION");
        for (unsigned slot = 0; slot < 16; ++slot) {
            require(((f.viewIndices >> (slot * 4)) & 15) == slot, "RETURN_FLOW_RECONSTRUCTED_SLOT");
            if (written[slot]) require(((f.rawIndices >> (slot * 4)) & 15) == 0,
                                      "RETURN_FLOW_RAW_STORED_ZERO");
            if (((f.pending | f.memoryLive) >> slot) & 1) {
                ++liveChecks;
                require(written[slot], "RETURN_FLOW_LIVE_WITHOUT_ALLOCATION");
                require(f.rows[slot] == allocated[slot], "RETURN_FLOW_FULL_TAG_SOURCE_OWNER");
            }
        }
        // GSIM observed state precedes this cycle's accepted writes.  Update the
        // independent ledger only after checking all current valid row owners.
        require(!(f.allocations[0].valid && f.allocations[1].valid &&
            f.allocations[0].index == f.allocations[1].index), "RETURN_FLOW_DUAL_ALLOCATION_ALIAS");
        for (const auto &a : f.allocations) if (a.valid) {
            require(a.index < 16, "RETURN_FLOW_ALLOCATION_INDEX");
            allocated[a.index] = a.row; written[a.index] = true; ++allocations;
        }
    }
    template<class D> void observe(D &d) {
        Frame f;
        f.startValid = d.get_m3$$start$$valid(); f.completeValid = d.get_m3$$complete$$valid();
        f.startSlots = d.get_m3$$startSlots(); f.completeSlots = d.get_m3$$completeSlots();
        f.slotReplyAccepts = d.get_returnFlow$$resultCaptures();
        const unsigned states = d.get_supply$$states();
        for (unsigned slot = 0; slot < 4; ++slot) if ((states >> (2 * slot)) & 3) f.liveSlots |= 1U << slot;
        f.startToken = {unsigned(d.get_m3$$start$$bits$$token$$index()), uint64_t(d.get_m3$$start$$bits$$token$$tag())};
        f.completeToken = {unsigned(d.get_m3$$complete$$bits$$token$$index()), uint64_t(d.get_m3$$complete$$bits$$token$$tag())};
        f.startForwarded = d.get_m3$$start$$bits$$forward$$valid();
        f.rawIndices = d.get_returnFlow$$rawIndices(); f.viewIndices = d.get_returnFlow$$viewIndices();
        f.pending = d.get_bufferedProof$$pending(); f.memoryLive = d.get_bufferedProof$$memoryLive();
        for (unsigned i = 0; i < 16; ++i) {
            f.rows[i] = {d.tile$core$core$core$backend$queue$$renamed$$token$$tag[i],
                unsigned(d.tile$core$core$core$backend$queue$$renamed$$source1[i]),
                unsigned(d.tile$core$core$core$backend$queue$$renamed$$source2[i]),
                unsigned(d.tile$core$core$core$backend$queue$$renamed$$destination[i]),
                bool(d.tile$core$core$core$backend$queue$$renamed$$writesRd[i])};
        }
#define RETURN_ALLOC(N) f.allocations[N] = {bool(d.get_bufferedProof$$allocation##N##$$valid()), \
    unsigned(d.get_bufferedProof$$allocation##N##$$bits$$token$$index()), \
    {uint64_t(d.get_bufferedProof$$allocation##N##$$bits$$token$$tag()), \
    unsigned(d.get_bufferedProof$$allocation##N##$$bits$$source1()), \
    unsigned(d.get_bufferedProof$$allocation##N##$$bits$$source2()), \
    unsigned(d.get_bufferedProof$$allocation##N##$$bits$$destination()), \
    bool(d.get_bufferedProof$$allocation##N##$$bits$$writesRd())}};
        RETURN_ALLOC(0); RETURN_ALLOC(1);
#undef RETURN_ALLOC
        f.occupancy = d.get_returnFlow$$occupancy();
        f.inputValid = d.get_returnFlow$$inputValid(); f.inputReady = d.get_returnFlow$$inputReady();
        f.outputValid = d.get_returnFlow$$outputValid(); f.outputReady = d.get_returnFlow$$outputReady();
        f.input = {uint64_t(d.get_returnFlow$$inputBits$$data()), bool(d.get_returnFlow$$inputBits$$error()),
            bool(d.get_returnFlow$$inputBits$$pageFault())};
        f.output = {uint64_t(d.get_returnFlow$$outputBits$$data()), bool(d.get_returnFlow$$outputBits$$error()),
            bool(d.get_returnFlow$$outputBits$$pageFault())};
        f.adapterIdle = d.get_returnFlow$$adapterIdle(); f.backendIdle = d.get_returnFlow$$backendIdle();
        f.fpEpoch = d.get_returnFlow$$fpEpoch(); f.integerBusy = d.get_returnFlow$$integerBusy();
        observeFrame(f);
    }
    void report(std::ostream &out, const std::string &name) const {
        require(queued.empty() && accepted == consumed, "RETURN_FLOW_FINAL_DRAIN");
        for (const auto &owner : slots) require(!owner, "RETURN_FLOW_FINAL_EXECUTION_DRAIN");
        for (const auto &event : slotReplies) out << "BUFFERED_LSU_SLOT_REPLY name=" << name
            << " cycle=" << event.cycle << " slot=" << event.slot << " token_index=" << event.token.index
            << " token_tag=" << event.token.tag << " start_cycle=" << event.acceptedAt
            << " outer_reply_same_cycle=" << event.outerReplySameCycle
            << " any_complete_same_cycle=" << event.anyCompleteSameCycle << '\n';
        out << "BUFFERED_RETURN_FLOW name=" << name << " cycles=" << cycles
            << " allocations=" << allocations << " live_checks=" << liveChecks
            << " accepted=" << accepted << " consumed=" << consumed << " bypass=" << bypass
            << " captures=" << captured << " queued_pops=" << queuedPops << " full_pop=" << fullPop
            << " faults=" << faults << " fp=" << fp << " slot_starts=" << slotStarts
            << " slot_reply_accepts=" << slotReplies.size() << " slot_completions=" << slotCompletions
            << " slot_released_without_completion=" << releasedWithoutCompletion << '\n';
    }
};
}
