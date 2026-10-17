#pragma once
#include <fstream>
// Read-only observer: invoked after GSIM step, before the original ledger consumes replies.
// Raw members are hash-bound to the saved generated header. Never read $NEXT fields.
#define CB(x) d.board$platform$core$core$core$backend$##x
#define CT(x) d.get_cpuTagged$$##x()
struct CopyTrace {
    using Token=tagged_board::Token;
    struct Load {Token token;unsigned destination=0,ordinal=0;uint64_t pc=0,va=0,pa=0,value=0,start=0,physicalReply=0,reply=0,complete=0;};
    struct Pair {Token owner,producer;unsigned source2=0;uint64_t pc=0,seen=0,capturedAny=0,capturedReady=0,prepared=0,q=0,s=0,start=0,commit=0,qSaved=0,va=0,pa=0,value=0;};
    std::map<Token,Load> loads;
    std::map<Token,Pair> pairs;
    std::set<Token> allocations;
    std::map<Token,uint64_t> allocationPc;
    std::map<unsigned,Token> physicalProducer;
    std::map<Token,Token> sourceProducer;
    std::ofstream timeline{"waiting.csv"};
    unsigned ordinal=0;bool finished=false;
    CopyTrace(){timeline<<"cycle,ordinal,store_index,store_tag,head_index,head_tag,q_live,q_index,q_tag,s_live,s_index,s_tag,eligible_mask,start_valid,start_index,start_tag\n";}

    static bool copyLoadPc(uint64_t pc){return pc>=0x802000f8&&pc<=0x80200130&&((pc-0x802000f8)%8)==0;}
    static bool copyStorePc(uint64_t pc){return copyLoadPc(pc-4);}
    static void first(uint64_t &where,uint64_t cycle){if(!where)where=cycle;}
    static bool chosen(const Load &l){return l.ordinal>=65&&l.ordinal<=96;}
    uint64_t pcBank(SBoardSocGsim&d,unsigned i){return i&1?CB(payload_2$pcBank1)[i>>1]:CB(payload_2$pcBank0)[i>>1];}
    Token row(SBoardSocGsim&d,unsigned i){check(CB(queue$$renamed$$token$$index)[i]==i,"trace queue index/row mismatch");return {i,CB(queue$$renamed$$token$$tag)[i]};}
    uint64_t pc(SBoardSocGsim&d,unsigned i){auto t=row(d,i);return allocationPc.contains(t)?allocationPc.at(t):0;}
    bool live(SBoardSocGsim&d,Token t){return CB(memoryLive)[t.index]&&CB(pending)[t.index]&&!CB(killed)[t.index]&&row(d,t.index)==t;}
    void sample(SBoardSocGsim&d,uint64_t cycle,bool active,const tagged_board::Probe &probe){
        if(finished)return;
        // Immutable rename generations: process same-packet allocations in full-tag order.
        std::vector<Token> fresh;
        for(unsigned i=0;i<16;++i)if(CB(pending)[i]){auto t=row(d,i);if(!allocations.contains(t))fresh.push_back(t);}
        std::sort(fresh.begin(),fresh.end(),[](Token a,Token b){return a.tag<b.tag;});
        for(auto t:fresh){unsigned i=t.index;allocations.insert(t);allocationPc.emplace(t,pcBank(d,i));
            check(!CB(queue$$renamed$$moveAlias)[i],"trace alias-enabled model unsupported");
            if(copyStorePc(pc(d,i))){
                auto source=unsigned(CB(queue$$renamed$$source2)[i]);check(physicalProducer.contains(source),"trace missing rename producer generation");
                sourceProducer.emplace(t,physicalProducer.at(source));
            }
            if(CB(queue$$renamed$$writesRd)[i])physicalProducer[CB(queue$$renamed$$destination)[i]]=t;
        }
        if(!active)return;
        // Gather producers before consumers, including index wrap within one packet.
        for(unsigned i=0;i<16;++i)if(CB(memoryLive)[i]&&copyLoadPc(pc(d,i))){
            auto t=row(d,i);if(!loads.contains(t)){
                check(CB(queue$$request$$memory)[i]&&!CB(queue$$request$$store)[i]&&CB(queue$$renamed$$writesRd)[i],"trace producer class");
                loads.emplace(t,Load{t,unsigned(CB(queue$$renamed$$destination)[i]),0,pc(d,i)});
            }
        }
        for(unsigned i=0;i<16;++i)if(CB(memoryLive)[i]&&CB(pending)[i]&&copyStorePc(pc(d,i))){
            auto t=row(d,i);if(!pairs.contains(t)){
                // Adjacent ld/sd guest sequence supplies a candidate row only; full token,
                // PC, physical destination/source identity, and independent PA/data bind it.
                check(sourceProducer.contains(t),"trace missing immutable source binding");
                auto producer=sourceProducer.at(t);
                check(producer==row(d,(i+15)&15),"trace adjacent COPY producer generation changed before first observation");
                check(loads.contains(producer),"trace store lacks recorded full-token producer");
                auto &l=loads.at(producer);
                check(l.pc+4==pc(d,i)&&l.destination==CB(queue$$renamed$$source2)[i],"trace source producer/full-owner rename mismatch");
                check(CB(queue$$request$$store)[i]&&CB(queue$$request$$memory)[i],"trace consumer class");
                pairs.emplace(t,Pair{t,producer,unsigned(CB(queue$$renamed$$source2)[i]),pc(d,i),cycle});
            }
        }
        // Consume returns using the original ledger's OLD full owner, before same-edge reuse.
        if(CT(physicalReply$$valid)&&CT(physicalReply$$ready)){
            unsigned h=CT(physicalReply$$handle);check(probe.ledger.transport.contains(h),"trace unknown physical return owner");
            auto token=probe.ledger.transport.at(h).token;
            if(loads.contains(token)){auto&l=loads.at(token);first(l.physicalReply,cycle);check(CT(physicalReply$$data)==l.value,"trace load physical data oracle");}
        }
        if(CT(integerReply$$valid)&&CT(integerReply$$ready)){
            unsigned h=CT(integerReply$$handle);check(probe.ledger.handles.contains(h),"trace unknown integer return owner");
            auto token=probe.ledger.handles.at(h);
            if(loads.contains(token)){auto&l=loads.at(token);first(l.reply,cycle);check(CT(integerReply$$data)==l.value,"trace load integer data oracle");}
        }
#define COPY_COMPLETE(n) if(CT(slot##n##$$complete)){Token t{unsigned(CT(slot##n##$$completeIndex)),CT(slot##n##$$completeTag)};if(loads.contains(t))first(loads.at(t).complete,cycle);}
        COPY_COMPLETE(0);COPY_COMPLETE(1);COPY_COMPLETE(2);COPY_COMPLETE(3);
#undef COPY_COMPLETE
        if(CT(startValid)){
            Token t{unsigned(d.get_backendStartIndex()),d.get_backendStartTag()};
            if(loads.contains(t)){
                auto &l=loads.at(t);check(!l.start,"trace duplicate load start");l.start=cycle;l.ordinal=++ordinal;l.va=CT(startVa);l.pa=probe.physical(l.va);
                check(l.pa>=0x80400000&&l.pa<0x80410000,"trace source PA");l.value=0x10203040+(l.pa-0x80400000)/8;
            }
            if(pairs.contains(t)){
                auto&p=pairs.at(t);auto&l=loads.at(p.producer);check(l.start&&l.reply,"trace store start precedes matching load reply");
                p.start=cycle;p.va=CT(startVa);p.pa=probe.physical(p.va);p.value=CT(startData);
                check(p.pa==l.pa+0x1000000&&p.value==l.value,"trace COPY PA/data pair oracle");
            }
        }
#define COPY_CAPTURE(n) if(CB(capturedOwners_##n)){Token t{unsigned(CB(captured$$token$$index_##n)),CB(captured$$token$$tag_##n)}; \
            if(pairs.contains(t)&&live(d,t)){check(CB(capturedOwners_##n)==(1U<<t.index),"trace capture mask/token mismatch");auto&p=pairs.at(t);first(p.capturedAny,cycle); \
            if(CB(captured$$dataReady_##n)){first(p.capturedReady,cycle);auto&l=loads.at(p.producer);check(CB(captured$$data_##n)==l.value&&l.reply,"trace captured data/full-producer oracle");}}}
        COPY_CAPTURE(0);COPY_CAPTURE(1);
#undef COPY_CAPTURE
        for(auto &[t,p]:pairs)if(live(d,t)&&CB(storePrepared)[t.index]){
            first(p.prepared,cycle);auto&l=loads.at(p.producer);check(CB(storeData)[t.index]==l.value,"trace prepared store data oracle");
        }
        if(CB(preparationDescriptorValid)&&CB(descriptorLive)){
            Token t{unsigned(CB(preparationDescriptor$$token$$index)),CB(preparationDescriptor$$token$$tag)};if(pairs.contains(t)){auto&p=pairs.at(t);if(!p.q)p.qSaved=CB(preparationDescriptor$$saved);first(p.q,cycle);}
        }
        if(CB(stagedMemoryValid)&&CB(residentLive)){
            Token t{unsigned(CB(stagedMemoryToken$$index)),CB(stagedMemoryToken$$tag)};if(pairs.contains(t))first(pairs.at(t).s,cycle);
        }
        for(unsigned lane=0;lane<2;++lane)if(lane?d.get_io$$commit1():d.get_io$$commit0()){
            Token t{unsigned((d.get_backendHeadIndex()+lane)&15),lane?CB(ledger$io$$commit$$bits$$token$$tag_1):CB(ledger$io$$commit$$bits$$token$$tag_0)};
            const uint64_t committedPc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();
            if(pairs.contains(t)){check(committedPc==pairs.at(t).pc,"trace immutable PC/retirement mismatch");first(pairs.at(t).commit,cycle);}
            if(loads.contains(t))check(committedPc==loads.at(t).pc,"trace producer PC/retirement mismatch");
        }
        for(auto &[t,p]:pairs)if(chosen(loads.at(p.producer))&&p.prepared&&!p.q&&live(d,t)){
            timeline<<cycle<<','<<loads.at(p.producer).ordinal<<','<<t.index<<','<<t.tag<<','
                <<unsigned(d.get_backendHeadIndex())<<','<<d.get_backendHeadTag()<<','
                <<unsigned(CB(descriptorLive))<<','<<unsigned(CB(preparationDescriptor$$token$$index))<<','<<CB(preparationDescriptor$$token$$tag)<<','
                <<unsigned(CB(residentLive))<<','<<unsigned(CB(stagedMemoryToken$$index))<<','<<CB(stagedMemoryToken$$tag)<<','
                <<CB(preparationMask)<<','<<unsigned(CT(startValid))<<','
                <<unsigned(d.get_backendStartIndex())<<','<<d.get_backendStartTag()<<'\n';
        }
        if(ordinal>=96){unsigned count=0;for(auto &[t,p]:pairs)if(chosen(loads.at(p.producer))&&p.commit)++count;finished=count==32;}
    }
    void report(){
        check(finished,"trace fixed 32-pair window incomplete");
        std::ofstream f("copy-pairs.csv");check(bool(f),"trace CSV open");
        f<<"ordinal,load_index,load_tag,store_index,store_tag,source_physical,load_pc,store_pc,load_pa,store_pa,value,owner_seen,load_start,load_physical_reply,load_integer_reply,load_complete,captured_any,captured_ready,store_prepared,q_first,s_first,store_start,store_commit,q_saved\n";
        unsigned n=0;for(auto &[t,p]:pairs){auto&l=loads.at(p.producer);if(!chosen(l))continue;
            check(l.physicalReply&&l.reply&&l.complete&&p.q&&p.s&&p.start&&p.commit,"trace missing mandatory phase");
            f<<l.ordinal<<','<<l.token.index<<','<<l.token.tag<<','<<t.index<<','<<t.tag<<','<<p.source2<<','<<l.pc<<','<<p.pc<<','<<l.pa<<','<<p.pa<<','<<p.value<<','<<p.seen<<','<<l.start<<','<<l.physicalReply<<','<<l.reply<<','<<l.complete<<','<<p.capturedAny<<','<<p.capturedReady<<','<<p.prepared<<','<<p.q<<','<<p.s<<','<<p.start<<','<<p.commit<<','<<p.qSaved<<'\n';++n;
        }
        check(n==32,"trace pair count");f.close();std::cout<<"COPY_TRACE_PASS pairs="<<n<<" first_ordinal=65 last_ordinal=96 full_token_bits=68 producer_owner_rename_binding=1 pa_data_oracle=1 sampling=post_step_current_state\n";
    }
};
#undef CB
#undef CT
