#pragma once
#include <cstdint>
// Plain host probe fixture, not a compiled or simulated RTL model.
struct SBoardSocGsim {
    uint64_t backendCompleteIndex=0; uint64_t get_backendCompleteIndex() const {return backendCompleteIndex;}
    uint64_t backendCompleteTag=0; uint64_t get_backendCompleteTag() const {return backendCompleteTag;}
    uint64_t backendEvents=0; uint64_t get_backendEvents() const {return backendEvents;}
    uint64_t backendFifoCount=0; uint64_t get_backendFifoCount() const {return backendFifoCount;}
    uint64_t backendHeadIndex=0; uint64_t get_backendHeadIndex() const {return backendHeadIndex;}
    uint64_t backendHeadTag=0; uint64_t get_backendHeadTag() const {return backendHeadTag;}
    uint64_t backendQueueHeadIndex=0; uint64_t get_backendQueueHeadIndex() const {return backendQueueHeadIndex;}
    uint64_t backendQueueHeadTag=0; uint64_t get_backendQueueHeadTag() const {return backendQueueHeadTag;}
    uint64_t backendRequestIndex=0; uint64_t get_backendRequestIndex() const {return backendRequestIndex;}
    uint64_t backendRequestTag=0; uint64_t get_backendRequestTag() const {return backendRequestTag;}
    uint64_t backendReset=0; uint64_t get_backendReset() const {return backendReset;}
    uint64_t backendReturnSlot=0; uint64_t get_backendReturnSlot() const {return backendReturnSlot;}
    uint64_t backendSlot0Tag=0; uint64_t get_backendSlot0Tag() const {return backendSlot0Tag;}
    uint64_t backendSlot1Tag=0; uint64_t get_backendSlot1Tag() const {return backendSlot1Tag;}
#ifndef MOCK_LEGACY
    uint64_t backendSlot2Tag=0; uint64_t get_backendSlot2Tag() const {return backendSlot2Tag;}
#endif
#ifndef MOCK_LEGACY
    uint64_t backendSlot3Tag=0; uint64_t get_backendSlot3Tag() const {return backendSlot3Tag;}
#endif
#ifndef MOCK_LEGACY
    uint64_t backendSlotCount=0; uint64_t get_backendSlotCount() const {return backendSlotCount;}
#endif
    uint64_t backendSlotIndices=0; uint64_t get_backendSlotIndices() const {return backendSlotIndices;}
#ifndef MOCK_LEGACY
    uint64_t backendSlotIndicesHi=0; uint64_t get_backendSlotIndicesHi() const {return backendSlotIndicesHi;}
#endif
    uint64_t backendSlotState=0; uint64_t get_backendSlotState() const {return backendSlotState;}
#ifndef MOCK_LEGACY
    uint64_t backendSlotStateHi=0; uint64_t get_backendSlotStateHi() const {return backendSlotStateHi;}
#endif
    uint64_t backendStartIndex=0; uint64_t get_backendStartIndex() const {return backendStartIndex;}
    uint64_t backendStartTag=0; uint64_t get_backendStartTag() const {return backendStartTag;}
    uint64_t backendStoreCause=0; uint64_t get_backendStoreCause() const {return backendStoreCause;}
    uint64_t dataPathCounts=0; uint64_t get_dataPathCounts() const {return dataPathCounts;}
    uint64_t dataPathEvents=0; uint64_t get_dataPathEvents() const {return dataPathEvents;}
    uint64_t dataPathReply0Data=0; uint64_t get_dataPathReply0Data() const {return dataPathReply0Data;}
    uint64_t dataPathReply0Flags=0; uint64_t get_dataPathReply0Flags() const {return dataPathReply0Flags;}
    uint64_t dataPathReply1Data=0; uint64_t get_dataPathReply1Data() const {return dataPathReply1Data;}
    uint64_t dataPathReply1Flags=0; uint64_t get_dataPathReply1Flags() const {return dataPathReply1Flags;}
    uint64_t dataPathReply2Data=0; uint64_t get_dataPathReply2Data() const {return dataPathReply2Data;}
    uint64_t dataPathReply2Flags=0; uint64_t get_dataPathReply2Flags() const {return dataPathReply2Flags;}
    uint64_t dataPathReply3Data=0; uint64_t get_dataPathReply3Data() const {return dataPathReply3Data;}
    uint64_t dataPathReply3Flags=0; uint64_t get_dataPathReply3Flags() const {return dataPathReply3Flags;}
    uint64_t dataPathReply4Data=0; uint64_t get_dataPathReply4Data() const {return dataPathReply4Data;}
    uint64_t dataPathReply4Flags=0; uint64_t get_dataPathReply4Flags() const {return dataPathReply4Flags;}
    uint64_t dataPathRequest0Address=0; uint64_t get_dataPathRequest0Address() const {return dataPathRequest0Address;}
    uint64_t dataPathRequest0Data=0; uint64_t get_dataPathRequest0Data() const {return dataPathRequest0Data;}
    uint64_t dataPathRequest0Meta=0; uint64_t get_dataPathRequest0Meta() const {return dataPathRequest0Meta;}
    uint64_t dataPathRequest1Address=0; uint64_t get_dataPathRequest1Address() const {return dataPathRequest1Address;}
    uint64_t dataPathRequest1Data=0; uint64_t get_dataPathRequest1Data() const {return dataPathRequest1Data;}
    uint64_t dataPathRequest1Meta=0; uint64_t get_dataPathRequest1Meta() const {return dataPathRequest1Meta;}
    uint64_t dataPathRequest2Address=0; uint64_t get_dataPathRequest2Address() const {return dataPathRequest2Address;}
    uint64_t dataPathRequest2Data=0; uint64_t get_dataPathRequest2Data() const {return dataPathRequest2Data;}
    uint64_t dataPathRequest2Meta=0; uint64_t get_dataPathRequest2Meta() const {return dataPathRequest2Meta;}
    uint64_t dataPathRequest3Address=0; uint64_t get_dataPathRequest3Address() const {return dataPathRequest3Address;}
    uint64_t dataPathRequest3Data=0; uint64_t get_dataPathRequest3Data() const {return dataPathRequest3Data;}
    uint64_t dataPathRequest3Meta=0; uint64_t get_dataPathRequest3Meta() const {return dataPathRequest3Meta;}
    uint64_t dataPathRequest4Address=0; uint64_t get_dataPathRequest4Address() const {return dataPathRequest4Address;}
    uint64_t dataPathRequest4Data=0; uint64_t get_dataPathRequest4Data() const {return dataPathRequest4Data;}
    uint64_t dataPathRequest4Meta=0; uint64_t get_dataPathRequest4Meta() const {return dataPathRequest4Meta;}
    uint64_t dataPathRequest5Address=0; uint64_t get_dataPathRequest5Address() const {return dataPathRequest5Address;}
    uint64_t dataPathRequest5Data=0; uint64_t get_dataPathRequest5Data() const {return dataPathRequest5Data;}
    uint64_t dataPathRequest5Meta=0; uint64_t get_dataPathRequest5Meta() const {return dataPathRequest5Meta;}
    uint64_t dataPathRequest6Address=0; uint64_t get_dataPathRequest6Address() const {return dataPathRequest6Address;}
    uint64_t dataPathRequest6Data=0; uint64_t get_dataPathRequest6Data() const {return dataPathRequest6Data;}
    uint64_t dataPathRequest6Meta=0; uint64_t get_dataPathRequest6Meta() const {return dataPathRequest6Meta;}
    uint64_t dataPathRequest7Address=0; uint64_t get_dataPathRequest7Address() const {return dataPathRequest7Address;}
    uint64_t dataPathRequest7Data=0; uint64_t get_dataPathRequest7Data() const {return dataPathRequest7Data;}
    uint64_t dataPathRequest7Meta=0; uint64_t get_dataPathRequest7Meta() const {return dataPathRequest7Meta;}
    uint64_t dataPathRequest8Address=0; uint64_t get_dataPathRequest8Address() const {return dataPathRequest8Address;}
    uint64_t dataPathRequest8Data=0; uint64_t get_dataPathRequest8Data() const {return dataPathRequest8Data;}
    uint64_t dataPathRequest8Meta=0; uint64_t get_dataPathRequest8Meta() const {return dataPathRequest8Meta;}
    uint64_t dataPathRequest9Address=0; uint64_t get_dataPathRequest9Address() const {return dataPathRequest9Address;}
    uint64_t dataPathRequest9Data=0; uint64_t get_dataPathRequest9Data() const {return dataPathRequest9Data;}
    uint64_t dataPathRequest9Meta=0; uint64_t get_dataPathRequest9Meta() const {return dataPathRequest9Meta;}
    uint64_t io$$cacheProfile$$evictionCycle=0; uint64_t get_io$$cacheProfile$$evictionCycle() const {return io$$cacheProfile$$evictionCycle;}
    uint64_t io$$cacheProfile$$missBlocked=0; uint64_t get_io$$cacheProfile$$missBlocked() const {return io$$cacheProfile$$missBlocked;}
    uint64_t io$$cacheProfile$$readMiss=0; uint64_t get_io$$cacheProfile$$readMiss() const {return io$$cacheProfile$$readMiss;}
    uint64_t io$$cacheProfile$$refillCycle=0; uint64_t get_io$$cacheProfile$$refillCycle() const {return io$$cacheProfile$$refillCycle;}
    uint64_t io$$cacheProfile$$writeMiss=0; uint64_t get_io$$cacheProfile$$writeMiss() const {return io$$cacheProfile$$writeMiss;}
    uint64_t io$$commit0=0; uint64_t get_io$$commit0() const {return io$$commit0;}
    uint64_t io$$commit0Pc=0; uint64_t get_io$$commit0Pc() const {return io$$commit0Pc;}
    uint64_t io$$commit1=0; uint64_t get_io$$commit1() const {return io$$commit1;}
    uint64_t io$$commit1Pc=0; uint64_t get_io$$commit1Pc() const {return io$$commit1Pc;}
    uint64_t io$$headProfile$$candidateLoadBlockedByStore=0; uint64_t get_io$$headProfile$$candidateLoadBlockedByStore() const {return io$$headProfile$$candidateLoadBlockedByStore;}
    uint64_t io$$headProfile$$candidateLoadBlockedByUnknownStore=0; uint64_t get_io$$headProfile$$candidateLoadBlockedByUnknownStore() const {return io$$headProfile$$candidateLoadBlockedByUnknownStore;}
    uint64_t io$$headProfile$$done=0; uint64_t get_io$$headProfile$$done() const {return io$$headProfile$$done;}
    uint64_t io$$headProfile$$memory=0; uint64_t get_io$$headProfile$$memory() const {return io$$headProfile$$memory;}
    uint64_t io$$headProfile$$memoryCompletionBlocked=0; uint64_t get_io$$headProfile$$memoryCompletionBlocked() const {return io$$headProfile$$memoryCompletionBlocked;}
    uint64_t io$$headProfile$$memoryRequestStallCause=0; uint64_t get_io$$headProfile$$memoryRequestStallCause() const {return io$$headProfile$$memoryRequestStallCause;}
    uint64_t io$$headProfile$$operandsReady=0; uint64_t get_io$$headProfile$$operandsReady() const {return io$$headProfile$$operandsReady;}
    uint64_t io$$headProfile$$queued=0; uint64_t get_io$$headProfile$$queued() const {return io$$headProfile$$queued;}
    uint64_t io$$headProfile$$valid=0; uint64_t get_io$$headProfile$$valid() const {return io$$headProfile$$valid;}
    uint64_t perfEvents=0; uint64_t get_perfEvents() const {return perfEvents;}
};
