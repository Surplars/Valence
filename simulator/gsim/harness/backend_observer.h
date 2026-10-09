#pragma once
#include "backend_ownership_ledger.h"
#ifdef DATA_PATH_OWNERSHIP_PROBES
#include "data_path_ownership_ledger.h"
#endif
#include <map>
#include <iostream>
struct BackendObserver {
    BackendOwnershipLedger ledger;
#ifdef DATA_PATH_OWNERSHIP_PROBES
    DataPathOwnershipLedger dataLedger;
    std::map<std::string,uint64_t> dataCounts,serialKinds;
    uint64_t capacityCandidates=0,capacityBlocked=0,youngerLaunches=0;
#endif
    uint64_t startPc=0,endPc=0,cycles=0,zero=0,retired=0;
    bool active=false,finished=false;
    std::map<std::string,uint64_t> counts;
    std::array<uint64_t,BackendSample::ownerCount+1> freeSlots{};
    uint64_t ownerSelectedCauseDisagreement=0,ownerSelectedCauseSamples=0;
    template<class Board>
    static BackendSample read(Board &d){
        BackendSample s;s.events=d.get_backendEvents();s.reset=d.get_backendReset();
        s.head={d.get_backendHeadTag(),unsigned(d.get_backendHeadIndex())};
        s.queueHead={d.get_backendQueueHeadTag(),unsigned(d.get_backendQueueHeadIndex())};
        s.request={d.get_backendRequestTag(),unsigned(d.get_backendRequestIndex())};
        s.start={d.get_backendStartTag(),unsigned(d.get_backendStartIndex())};
        s.complete={d.get_backendCompleteTag(),unsigned(d.get_backendCompleteIndex())};
        if constexpr(requires(Board &b){b.get_backendSlotCount();})
            BackendOwnershipLedger::require(d.get_backendSlotCount()==BackendSample::ownerCount,"compiled owner count differs from probe schema");
        else static_assert(BackendSample::ownerCount==2 || sizeof(Board)==0,"four-owner observation requires backendSlotCount");
        auto pair=[&](unsigned first,uint64_t indices,uint64_t state,uint64_t tag0,uint64_t tag1) {
            s.slots[first]={tag0,unsigned(indices&255)};
            s.slots[first+1]={tag1,unsigned((indices>>8)&255)};
            for(unsigned i=0;i<2;++i){s.live[first+i]=(state>>i)&1;s.phase[first+i]=(state>>(2+2*i))&3;
                s.parallel[first+i]=(state>>(6+i))&1;s.cancelled[first+i]=(state>>(8+i))&1;}
        };
        pair(0,d.get_backendSlotIndices(),d.get_backendSlotState(),d.get_backendSlot0Tag(),d.get_backendSlot1Tag());
        if constexpr(BackendSample::ownerCount==4)
            pair(2,d.get_backendSlotIndicesHi(),d.get_backendSlotStateHi(),d.get_backendSlot2Tag(),d.get_backendSlot3Tag());
        else if constexpr(requires(Board &b){b.get_backendSlotStateHi();})
            BackendOwnershipLedger::require(d.get_backendSlotStateHi()==0,"two-owner probe exposes hidden upper owners");
        s.returnSlot=d.get_backendReturnSlot();s.fifoCount=d.get_backendFifoCount();s.storeCause=d.get_backendStoreCause();
        s.commits=d.get_io$$commit0()+d.get_io$$commit1();
        s.headValid=d.get_io$$headProfile$$valid();s.headDone=d.get_io$$headProfile$$done();
        s.headQueued=d.get_io$$headProfile$$queued();s.headMemory=d.get_io$$headProfile$$memory();
        s.recovery=(d.get_perfEvents()>>3)&1;return s;
    }
#ifdef DATA_PATH_OWNERSHIP_PROBES
    static DataPathSample readData(SBoardSocGsim &d){
        DataPathSample p;p.events=d.get_dataPathEvents();auto counts=d.get_dataPathCounts();
        for(unsigned i=0;i<9;++i)p.count[i]=(counts>>(4*i))&15;
        p.request[0]={d.get_dataPathRequest0Address(),d.get_dataPathRequest0Data(),d.get_dataPathRequest0Meta()};
        p.request[1]={d.get_dataPathRequest1Address(),d.get_dataPathRequest1Data(),d.get_dataPathRequest1Meta()};
        p.request[2]={d.get_dataPathRequest2Address(),d.get_dataPathRequest2Data(),d.get_dataPathRequest2Meta()};
        p.request[3]={d.get_dataPathRequest3Address(),d.get_dataPathRequest3Data(),d.get_dataPathRequest3Meta()};
        p.request[4]={d.get_dataPathRequest4Address(),d.get_dataPathRequest4Data(),d.get_dataPathRequest4Meta()};
        p.request[5]={d.get_dataPathRequest5Address(),d.get_dataPathRequest5Data(),d.get_dataPathRequest5Meta()};
        p.request[6]={d.get_dataPathRequest6Address(),d.get_dataPathRequest6Data(),d.get_dataPathRequest6Meta()};
        p.request[7]={d.get_dataPathRequest7Address(),d.get_dataPathRequest7Data(),d.get_dataPathRequest7Meta()};
        p.request[8]={d.get_dataPathRequest8Address(),d.get_dataPathRequest8Data(),d.get_dataPathRequest8Meta()};
        p.request[9]={d.get_dataPathRequest9Address(),d.get_dataPathRequest9Data(),d.get_dataPathRequest9Meta()};
        p.reply[0]={d.get_dataPathReply0Data(),d.get_dataPathReply0Flags()};
        p.reply[1]={d.get_dataPathReply1Data(),d.get_dataPathReply1Flags()};
        p.reply[2]={d.get_dataPathReply2Data(),d.get_dataPathReply2Flags()};
        p.reply[3]={d.get_dataPathReply3Data(),d.get_dataPathReply3Flags()};
        p.reply[4]={d.get_dataPathReply4Data(),d.get_dataPathReply4Flags()};
        return p;
    }
#endif
    static void sample(SBoardSocGsim &d,void *context){
        auto &o=*static_cast<BackendObserver*>(context);auto s=read(d);
#ifdef DATA_PATH_OWNERSHIP_PROBES
        auto p=readData(d);
        if(!s.reset)BackendOwnershipLedger::require(p.bit(DataPathSample::reserveGuardMatch),"test-only capacity guard differs from production");
#endif
        bool begin=(d.get_io$$commit0()&&d.get_io$$commit0Pc()==o.startPc)||(d.get_io$$commit1()&&d.get_io$$commit1Pc()==o.startPc);
        bool end=(d.get_io$$commit0()&&d.get_io$$commit0Pc()==o.endPc)||(d.get_io$$commit1()&&d.get_io$$commit1Pc()==o.endPc);
        if(begin&&!o.finished)o.active=true;
        if(o.active){
            ++o.cycles;o.zero+=!s.commits;o.retired+=s.commits;
            auto legacy=o.ledger.category(s);++o.counts[legacy];
#ifdef DATA_PATH_OWNERSHIP_PROBES
            auto refined=legacy;
            if(legacy=="issued_memory_downstream_unknown"){
                auto stage=o.dataLedger.category(s.head,s,p);if(!stage.empty())refined=stage;
            }
            ++o.dataCounts[refined];
            if(legacy=="queued_memory_serial_exclusion"){
                BackendOwnershipLedger::require(s.bit(2),"serial split needs actual selected head");
                std::string kind=p.bit(DataPathSample::selectedAtomic)?"atomic":
                    p.bit(DataPathSample::selectedOrdinaryRam)&&p.bit(DataPathSample::selectedStore)?"ordinary_ram_store":
                    !p.bit(DataPathSample::selectedOrdinaryRam)?"nonordinary_or_virtual":"other";
                ++o.serialKinds[kind];
            }
            o.capacityCandidates+=p.bit(DataPathSample::capacityCandidate);
            o.capacityBlocked+=p.bit(DataPathSample::capacityBlocked);
            o.youngerLaunches+=p.bit(DataPathSample::youngerLaunch);
#endif
            ++o.freeSlots[BackendSample::ownerCount-s.liveCount()];
            if(!s.commits&&s.headValid&&s.headMemory&&s.bit(41)&&s.request==s.head){
                ++o.ownerSelectedCauseSamples;
                o.ownerSelectedCauseDisagreement+=o.ledger.requests.empty()||!(o.ledger.requests.front()==s.head);
            }
        }
#ifdef DATA_PATH_OWNERSHIP_PROBES
        o.dataLedger.advance(s,p,o.ledger);
#endif
        o.ledger.advance(s);
        if(end&&o.active){o.active=false;o.finished=true;}
    }
    void report(){
#ifdef DATA_PATH_OWNERSHIP_PROBES
        uint64_t refinedSum=0;for(auto &[name,n]:dataCounts){refinedSum+=n;
            std::cout<<"DATA_PATH_BUCKET category="<<name<<" cycles="<<n<<"\n";}
        BackendOwnershipLedger::require(refinedSum==cycles,"refined partition conservation failed");
        for(auto &[name,n]:serialKinds)std::cout<<"DATA_PATH_SERIAL category="<<name<<" cycles="<<n<<"\n";
        std::cout<<"DATA_PATH_CAPACITY candidate_cycles="<<capacityCandidates<<" capacity_only_blocked_cycles="<<capacityBlocked
            <<" actual_younger_load_launches="<<youngerLaunches<<"\n";
        dataLedger.report();
#endif
        BackendOwnershipLedger::require(finished,"ROI did not finish");
        uint64_t sum=0,zeroSum=0;for(auto &[name,n]:counts){sum+=n;if(name.rfind("progress_",0)!=0)zeroSum+=n;
            std::cout<<"BACKEND_OWNER_BUCKET name=coremark_roi category="<<name<<" cycles="<<n<<"\n";}
        BackendOwnershipLedger::require(sum==cycles&&zeroSum==zero,"cycle partition conservation failed");
        std::cout<<"BACKEND_OWNER_TOTAL cycles="<<cycles<<" zero_commit="<<zero<<" retired="<<retired;
        for(unsigned i=0;i<freeSlots.size();++i)std::cout<<" free_slots_"<<i<<"="<<freeSlots[i];
        std::cout<<" unsafe_cause_samples="<<ownerSelectedCauseSamples<<" unrelated_fifo_owner="<<ownerSelectedCauseDisagreement<<"\n";
        std::cout<<"BACKEND_OWNER_LEDGER checks="<<ledger.checks<<" resets="<<ledger.resets
            <<" enqueues="<<ledger.enqueues<<" dequeues="<<ledger.dequeues<<" returns="<<ledger.returns
            <<" pending_fifo="<<ledger.requests.size()<<" pending_responses="<<ledger.responses.size()
            <<" local_accepts="<<ledger.localAccepts<<" direct_accepts="<<ledger.directAccepts
            <<" simultaneous_enqueue_dequeue="<<ledger.simultaneous<<" cancellations_outstanding="<<ledger.cancellationWhileOutstanding
            <<" fast_stores="<<ledger.fastStores<<" forwarded_starts="<<ledger.forwardedStarts<<"\n";
    }
};
