#pragma once
#include "stage_trace.h"
namespace monitor_stage {
struct FrontendRow {
    uint64_t cycle=0,cursor=0,base=0;
    unsigned context=0,snapshotContext=0;
    bool notInvalidated=false,instruction0=false,instruction1=false;
    unsigned supply=0,rename=0,tail=0;uint64_t nextTag=0;
    std::array<bool,3> present{};
    std::array<uint64_t,3> keys{};
};
struct FrontendTrace {
    std::vector<FrontendRow> rows;std::optional<FrontendRow> previous;
    void sample(SBoardSocGsim &d,uint64_t cycle,unsigned tickCount,bool hotOwnerSeen){
        const uint64_t cursor=d.get_io$$fetchPc();
        if(tickCount>=4)return;
        FrontendRow r;r.cycle=cycle;r.cursor=cursor;r.base=d.board$platform$frontend$currentBase;
        require(r.base==(cursor&~7ULL),"frontend cursor/readBase binding changed");
        r.context=d.board$platform$frontend$context;r.snapshotContext=d.board$platform$frontend$suppliedPackets_window$context;
        r.notInvalidated=d.board$platform$frontend$suppliedPackets_window$_present_2_T;
        r.instruction0=d.board$platform$frontend$_io_instruction0_valid_T_2;
        r.instruction1=d.board$platform$frontend$_io_instruction1_valid_T_3;
        r.supply=d.get_perfSupply();r.rename=d.get_perfRename();
        r.tail=d.board$platform$core$core$core$backend$ledger$tail;r.nextTag=d.board$platform$core$core$core$backend$ledger$nextTag;
        require(r.supply==unsigned(r.instruction0)+unsigned(r.instruction1),"frontend instruction-valid/supply binding changed");
        r.present={bool(d.board$platform$frontend$suppliedPackets_window$present_0),bool(d.board$platform$frontend$suppliedPackets_window$present_1),bool(d.board$platform$frontend$suppliedPackets_window$present_2)};
        const std::array<uint64_t,3> regions{d.board$platform$frontend$suppliedPackets_window$regions_0,d.board$platform$frontend$suppliedPackets_window$regions_1,d.board$platform$frontend$suppliedPackets_window$regions_2};
        const std::array<unsigned,3> offsets{d.board$platform$frontend$suppliedPackets_window$offsets_2,d.board$platform$frontend$suppliedPackets_window$offsets_3,d.board$platform$frontend$suppliedPackets_window$offsets_4};
        const std::array<unsigned,3> regionIds{d.board$platform$frontend$suppliedPackets_window$regionIds_2,d.board$platform$frontend$suppliedPackets_window$regionIds_3,d.board$platform$frontend$suppliedPackets_window$regionIds_4};
        for(unsigned i=0;i<3;++i){require(regionIds[i]<3&&offsets[i]<8,"frontend registered key schema changed");r.keys[i]=(regions[regionIds[i]]<<6)|(uint64_t(offsets[i])<<3);}
        if(hotOwnerSeen||tickCount==3){
            if(rows.empty()){require(previous&&previous->cycle+1==cycle,"frontend first trigger lost preceding allocation/marker cycle");rows.push_back(*previous);}
            rows.push_back(r);
        }
        previous=r;
    }
    void report(std::ostream &out,std::ostream &summary,uint64_t first,uint64_t last,const StageTrace &stages)const{
        require(last>=first&&rows.size()==last-first+1,"frontend exact bounded interval length mismatch");
        for(size_t i=0;i<rows.size();++i)require(rows[i].cycle==first+i,"frontend exact bounded interval omission/duplicate/order");
        for(const auto &n:stages.records){require(n->allocated>=first&&n->allocated<=last,"hot owner allocation outside complete frontend interval");
            const auto &r=rows[n->allocated-first];require(n->identity.key.first>=r.nextTag&&n->identity.key.first-r.nextTag<r.rename&&
                n->identity.key.second==((r.tail+unsigned(n->identity.key.first-r.nextTag))&15),"hot allocation lost exact frontend accepted-prefix token");}
        out<<"cycle\tcursor\tread_base\tread_context\tsnapshot_context\tnot_invalidated\tinstruction0_valid\tinstruction1_valid\tsupply_count\trename_count\tnext_tag\ttail\tpresent0\tkey0\tpresent1\tkey1\tpresent2\tkey2\tcurrent_packet_present\tbackedge_d8_to_d0\n";
        uint64_t backedges=0,missedBackedges=0,invalidBackedges=0;
        for(size_t n=0;n<rows.size();++n){const auto &r=rows[n];bool present=false;
            for(unsigned i=0;i<3;++i)present|=r.present[i]&&r.keys[i]==r.base;
            present&=r.notInvalidated&&r.context==r.snapshotContext;
            const bool backedge=n&&rows[n-1].cycle+1==r.cycle&&rows[n-1].cursor==0xfff787d8&&r.cursor==0xfff787d0;
            backedges+=backedge;missedBackedges+=backedge&&!present;invalidBackedges+=backedge&&!r.instruction0;
            out<<r.cycle<<'\t'<<r.cursor<<'\t'<<r.base<<'\t'<<r.context<<'\t'<<r.snapshotContext<<'\t'<<r.notInvalidated<<'\t'<<r.instruction0<<'\t'<<r.instruction1<<'\t'<<r.supply<<'\t'<<r.rename<<'\t'<<r.nextTag<<'\t'<<r.tail;
            for(unsigned i=0;i<3;++i)out<<'\t'<<r.present[i]<<'\t'<<r.keys[i];out<<'\t'<<present<<'\t'<<backedge<<'\n';
        }
        require(!rows.empty(),"frontend hot timeline missing");
        summary<<"MONITOR_FRONTEND_PASS rows="<<rows.size()<<" first_cycle="<<first<<" last_cycle="<<last<<" joined_hot_owners="<<stages.records.size()<<" unjoined_hot_owners=0 cursor_backedges_d8_to_d0="<<backedges<<" backedges_without_current_packet="<<missedBackedges<<" backedges_instruction0_invalid="<<invalidBackedges<<" causal_claim=0\n";
    }
};
}
