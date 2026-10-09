#pragma once
#include "backend_ownership_ledger.h"
#include <array>
// Request fingerprints retain every DataRequest field, never a lossy hash.
struct DataPathRequest {
    uint64_t address=0,data=0,meta=0;
    bool operator==(const DataPathRequest &) const = default;
    bool write() const { return meta&1; }
    bool atomic() const { return meta&2; }
    bool virtualized() const { return meta&(1ULL<<17); }
};
struct DataPathReply {
    uint64_t data=0,flags=0;
    bool operator==(const DataPathReply &) const = default;
};
struct DataPathSample {
    // Request ports: FIFO enqueue/dequeue, fast store, StoreBuffer physical,
    // translation virtual ingress/incoming/translated enqueue/dequeue/checked dequeue/physical.
    enum Port { fifoEnq, fifoDeq, fast, storePhysical, virtualIn, incoming, translatedEnq,
                translatedDeq, checkedDeq, physical, portCount };
    enum Event { storeRequest=0, storeResponse, drain, flowBuffered, flowFast, ownerValid,
        ownerBuffered, bufferedAccept, forwardedAccept, fastAccept, foreignRequest, foreignResponse,
        virtualRequest, incomingRequest, translationRequest, translationReply, translatedPush,
        translatedPop, checkedPop, physicalRequest, virtualReply, physicalReply,
        returnPush, returnPop, waiting, incomingVirtualized, checkedFault, ownerFault,
        storeAckValid, translatedFault, translatedPageFault, checkedPageFault,
        capacityCandidate, capacityBlocked, youngerLaunch, reserveGuardMatch, selectedOrdinaryRam,
        selectedStore, selectedAtomic, selectedYounger, foreignEpoch, translationEnqueuePageFault, translationEnqueueAccessFault };
    uint64_t events=0;
    std::array<DataPathRequest,portCount> request{};
    // Physical adapter reply, virtual adapter reply, return-buffer pop, StoreBuffer physical reply, LSU reply.
    std::array<DataPathReply,5> reply{};
    // Pre-edge counts: StoreBuffer allocated, issued, physical owners, direct outstanding;
    // translation ingress, translated, checked, owners; relocated response buffer.
    std::array<unsigned,9> count{};
    bool bit(Event n) const { return (events>>n)&1; }
};
