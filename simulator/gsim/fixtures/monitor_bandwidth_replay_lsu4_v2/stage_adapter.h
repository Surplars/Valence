#pragma once
#include "stage_trace.h"
namespace monitor_stage {
inline uint64_t pc(SBoardSocGsim &d,unsigned i){require(i<16,"hot stage PC index out of bounds");return (i&1)?d.board$platform$core$core$core$backend$payload_1$pcBank1[i>>1]:d.board$platform$core$core$core$backend$payload_1$pcBank0[i>>1];}
inline Snapshot read(SBoardSocGsim &d,const BackendSample &b,const DataPathSample &p){
    Snapshot s;
    const unsigned count=d.board$platform$core$core$core$backend$ledger$count,head=d.board$platform$core$core$core$backend$ledger$head;
    require(count<=16&&head<16,"hot stage ROB geometry drift");
    const std::array<uint8_t,16> ready1{d.board$platform$core$core$core$backend$ownerReady$ready1_0,d.board$platform$core$core$core$backend$ownerReady$ready1_1,d.board$platform$core$core$core$backend$ownerReady$ready1_2,d.board$platform$core$core$core$backend$ownerReady$ready1_3,d.board$platform$core$core$core$backend$ownerReady$ready1_4,d.board$platform$core$core$core$backend$ownerReady$ready1_5,d.board$platform$core$core$core$backend$ownerReady$ready1_6,d.board$platform$core$core$core$backend$ownerReady$ready1_7,d.board$platform$core$core$core$backend$ownerReady$ready1_8,d.board$platform$core$core$core$backend$ownerReady$ready1_9,d.board$platform$core$core$core$backend$ownerReady$ready1_10,d.board$platform$core$core$core$backend$ownerReady$ready1_11,d.board$platform$core$core$core$backend$ownerReady$ready1_12,d.board$platform$core$core$core$backend$ownerReady$ready1_13,d.board$platform$core$core$core$backend$ownerReady$ready1_14,d.board$platform$core$core$core$backend$ownerReady$ready1_15};
    const std::array<uint8_t,16> ready2{d.board$platform$core$core$core$backend$ownerReady$ready2_0,d.board$platform$core$core$core$backend$ownerReady$ready2_1,d.board$platform$core$core$core$backend$ownerReady$ready2_2,d.board$platform$core$core$core$backend$ownerReady$ready2_3,d.board$platform$core$core$core$backend$ownerReady$ready2_4,d.board$platform$core$core$core$backend$ownerReady$ready2_5,d.board$platform$core$core$core$backend$ownerReady$ready2_6,d.board$platform$core$core$core$backend$ownerReady$ready2_7,d.board$platform$core$core$core$backend$ownerReady$ready2_8,d.board$platform$core$core$core$backend$ownerReady$ready2_9,d.board$platform$core$core$core$backend$ownerReady$ready2_10,d.board$platform$core$core$core$backend$ownerReady$ready2_11,d.board$platform$core$core$core$backend$ownerReady$ready2_12,d.board$platform$core$core$core$backend$ownerReady$ready2_13,d.board$platform$core$core$core$backend$ownerReady$ready2_14,d.board$platform$core$core$core$backend$ownerReady$ready2_15};
    for(unsigned rank=0;rank<count;++rank){const unsigned i=(head+rank)&15;Entry e;
        e.key={d.board$platform$core$core$core$backend$queue$$renamed$$token$$tag[i],unsigned(d.board$platform$core$core$core$backend$queue$$renamed$$token$$index[i])};
        require(e.key.second==i&&e.key.first==d.board$platform$core$core$core$backend$ledger$entries$$tag[i],"hot stage queue/ROB full-token mismatch");
        e.pc=pc(d,i);e.ready1=ready1[i];e.ready2=ready2[i];
        e.source1=d.board$platform$core$core$core$backend$queue$$renamed$$source1[i];
        e.source2=d.board$platform$core$core$core$backend$queue$$renamed$$source2[i];
        e.destination=d.board$platform$core$core$core$backend$queue$$renamed$$destination[i];
        e.writes=d.board$platform$core$core$core$backend$queue$$renamed$$writesRd[i];
        e.alias=d.board$platform$core$core$core$backend$queue$$renamed$$moveAlias[i];
        e.pending=d.board$platform$core$core$core$backend$pending[i];
        e.done=d.board$platform$core$core$core$backend$ledger$entries$$done[i];
        s.entries.push_back(e);
    }
    const unsigned allocated=d.get_perfRename(),tail=d.board$platform$core$core$core$backend$ledger$tail;
    const uint64_t nextTag=d.board$platform$core$core$core$backend$ledger$nextTag;
    require(allocated<=2&&tail<16&&nextTag+allocated>=nextTag,"hot stage accepted rename schema drift");
    for(unsigned lane=0;lane<allocated;++lane)s.allocations.emplace_back(nextTag+lane,(tail+lane)&15);
    const unsigned index=d.board$platform$core$core$core$backend$stagedMemoryIndex;
    if(d.board$platform$core$core$core$backend$stagedMemoryValid&&index<16&&d.board$platform$core$core$core$backend$pending[index]){
        const Key token{d.board$platform$core$core$core$backend$stagedMemoryToken$$tag,unsigned(d.board$platform$core$core$core$backend$stagedMemoryToken$$index)};
        if(token.second==index&&token.first==d.board$platform$core$core$core$backend$queue$$renamed$$token$$tag[index]){s.prepared=token;s.address=d.board$platform$core$core$core$backend$stagedMemoryAddress;}
    }
    if(b.bit(3))s.start=Key{b.start.tag,b.start.index};
    s.available=b.bit(5);s.capacityBlocked=p.bit(DataPathSample::capacityBlocked);
    return s;
}
}
