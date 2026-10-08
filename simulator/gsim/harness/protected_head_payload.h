#pragma once
#include <cstdlib>
// Independent passive full-token invariant, including held/error completions.
// The mutation changes only the oracle's observed tag and must be rejected.
static void protectedStep(SFloatingPointCpuGsim &d) {
    d.step();
    if(d.get_protectedReset())return;
    const bool active=d.get_protectedActive(), complete=d.get_protectedCompleteValid();
    uint64_t owner=d.get_protectedOwnerTag();
    if(std::getenv("PROTECTED_OWNER_NEGATIVE"))owner^=1ULL<<63;
    if(active&&(!d.get_protectedHeadValid()||owner!=d.get_protectedHeadTag()||
            d.get_protectedOwnerIndex()!=d.get_protectedHeadIndex()))
        throw std::runtime_error("protected head oracle: full-token owner diverged");
    if(complete&&(!active||owner!=d.get_protectedCompleteTag()||
            d.get_protectedOwnerIndex()!=d.get_protectedCompleteIndex()))
        throw std::runtime_error("protected head oracle: completion lost full-token ownership");
}

// Instruction-device cursor only, never an architectural correctness oracle.
// These retained next-state fields implement RegisteredFetchPacket.nextFetchPc
// for the source-locked split-cursor profile. Every next cycle checks fetchPc,
// and all retired PC/raw instruction/value/FP state checks remain independent.
static uint64_t protectedNextFetch(const SFloatingPointCpuGsim &d) {
    return d.core$core$fetchPacket$correctionPending$NEXT ?
        d.core$core$fetchPacket$correctionPc$NEXT : d.core$core$fetchPacket$rawCursor$NEXT;
}
static uint64_t protectedRenamePc(const SFloatingPointCpuGsim &d,unsigned lane) {
    return lane ? d.core$core$fetchPacket$slots$$pc_1 : d.core$core$fetchPacket$slots$$pc_0;
}
