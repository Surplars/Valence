#define main frozen_board_boot_main
#include "board_boot.cpp"
#undef main
#include "tagged_board_probe.h"
#include "guest_inputs.h"
#include <array>
#include <map>
#include <set>
#include <tuple>

// Fresh read-only pre-edge observer. Expected addresses/data come exclusively
// from the independently interpreted frozen raw guest, never from DUT payloads.
struct Directed {
    using Token=std::pair<unsigned,uint64_t>;
    using Context=std::array<uint64_t,7>; // owner slot/gen, root slot/gen, epoch, PA, MSHR
    Test *test=nullptr; Bytes code; std::ofstream out;
    tagged_board::Probe tagged; std::map<Token,uint64_t> bindings,retired,started,killed;
    std::map<uint64_t,Token> memoryTokens;
    std::set<Token> replies,completed; size_t nextRetire=0; uint64_t done=0;
    explicit Directed(const char *trace):out(trace){check(bool(out),"directed trace open");tagged.mode=0;}
    template<class...X> void row(const char *event,X...x){out<<event;((out<<'\t'<<uint64_t(x)),...);out<<'\n';}
    const directed_guest::Expected *expected(uint64_t pc)const {
        if(pc==directed_guest::killedPc)return &directed_guest::killed;
        for(const auto&e:directed_guest::trace)if(e.pc==pc)return &e;
        return nullptr;
    }
    uint64_t pc(Token t)const {check(bindings.contains(t),"unbound full ROB token");return bindings.at(t);}
    const directed_guest::Expected &memory(Token t)const {
        const auto *e=expected(pc(t));check(e&&e->memory,"actual memory token does not bind guest memory instruction");return *e;
    }
    void orderedY(Token t,uint64_t cycle){
        for(const auto &c:directed_guest::cases)if(pc(t)==c.y){
            check(memoryTokens.contains(c.u),"Y before U full-token allocation");const auto u=memoryTokens.at(c.u);
            check(retired.contains(u)&&retired.at(u)<cycle,"Y proof/start/member before prior U retirement edge");
        }
    }
    static void callback(SBoardSocGsim &d,void *p){static_cast<Directed*>(p)->sample(d);}
    template<class D> void sample(D &d){
#define DB(x) d.board$platform$core$core$core$backend$##x
#define DP(x) d.board$platform$privateCache$posted$##x
#define DC(x) d.board$platform$privateCache$##x
#define DA(x) d.board$platform$core$adapter$##x
#define DT(x) d.get_cpuTagged$$##x()
        const uint64_t cycle=test->cycles;
        check(!d.get_io$$trap$$valid(),"unexpected trap in finite directed guest");
        const unsigned head=DB(ledger$head),count=DB(ledger$count);check(head<16&&count<=16,"ROB geometry");
        for(unsigned age=0;age<count;++age){
            const unsigned i=(head+age)&15;Token t{i,DB(ledger$entries$$tag)[i]};
            check(DB(queue$$renamed$$token$$tag)[i]==t.second,"ledger/issue full-token disagreement");
            uint64_t p=(i&1)?DB(payload_2$pcBank1)[i>>1]:DB(payload_2$pcBank0)[i>>1];
            uint32_t raw=(i&1)?DB(payload_2$instructionBank1)[i>>1]:DB(payload_2$instructionBank0)[i>>1];
            const bool boot=p==0x80000000ULL||p==0x80000004ULL;
            check(boot||(p>=directed_guest::base&&p+4<=directed_guest::base+code.size()&&!(p&3)&&wordAt(code,p-directed_guest::base)==raw),"live full-token PC/raw instruction outside authored guest");
            if(bindings.contains(t))check(bindings.at(t)==p,"same full token rebound to a different PC");
            else {bindings[t]=p;row("BIND",cycle,i,t.second,p,raw,head,count,age);
                const auto *e=expected(p);if(e&&e->memory){
                    check(!memoryTokens.contains(p)||killed.contains(memoryTokens.at(p)),"live memory PC allocated twice");memoryTokens[p]=t;}}
            if(DB(killed)[i]&&!killed.contains(t)){
                check(!retired.contains(t),"recovery kills a retired full token");killed[t]=cycle;
                row("KILL",cycle,i,t.second,p,DB(pending)[i],DB(memoryLive)[i],DB(ledger$acceptRecovery),DB(postedBusy),d.board$platform$core$_io_posted_seal_T_1);
                if(p==directed_guest::killedPc)check(!started.contains(t),"designated killed younger load already issued");
            }
        }
        // Existing frozen observer sees original handles and validates native
        // LSU/FIFO/SB/physical/cache ownership. It is included without edits.
        tagged.sample(d,cycle);
        std::array<Token,4> slots{};std::array<bool,4> live{};
#define DS(n) live[n]=DT(slot##n##$$live);if(live[n])slots[n]={unsigned(DT(slot##n##$$index)),DT(slot##n##$$tag)};
        DS(0);DS(1);DS(2);DS(3);
#undef DS
        if(DT(startValid)){
            Token t{unsigned(d.get_backendStartIndex()),d.get_backendStartTag()};const auto &e=memory(t);
            check(e.pc!=directed_guest::killedPc&&!killed.contains(t),"killed/stale load acquired a real LSU start");
            check(started.emplace(t,cycle).second,"duplicate actual memory start");
            check(DT(startVa)==e.address&&DT(startSize)==e.size&&bool(DT(startFlags)&1)==e.store&&!(DT(startFlags)&6),"LSU start disagrees with raw ISA address/size/class");
            if(e.store){check(DT(startData)==e.data,"LSU store value differs from ISA oracle");check(t.first==head&&t.second==d.get_backendHeadTag(),"store starts before its actual full-token ROB head");orderedY(t,cycle);}
            else check(!DB(postedBusy),"ordinary load issued while posted responsibility remains");
            row("START",cycle,t.first,t.second,pc(t),DT(startSlot),DT(startVa),DT(startData),DT(startSize),DT(startFlags),head,d.get_backendHeadTag(),DB(postedBusy));
        }
        if(DB(postedEligible)){
            Token t{unsigned(DB(memoryIssueEntry$$renamed$$token$$index)),DB(memoryIssueEntry$$renamed$$token$$tag)};
            check(memory(t).store&&t.first==head&&t.second==d.get_backendHeadTag(),"posted proof does not belong actual guest store head");orderedY(t,cycle);
            row("PROOF",cycle,t.first,t.second,pc(t));
        }
        if(DT(sbLocal)&&DT(sbLocalWrite)){
            unsigned h=DT(sbOriginHandle);check(h<4&&live[h],"local response has no live slot");Token t=slots[h];
            check(memory(t).store&&started.contains(t),"local store detached from original start");row("LOCAL",cycle,t.first,t.second,pc(t),h);
        }
        if(DT(integerReply$$valid)&&DT(integerReply$$ready)){
            unsigned h=DT(integerReply$$handle);check(h<4&&live[h],"integer response has no live slot");Token t=slots[h];const auto&e=memory(t);
            check(started.contains(t)&&replies.insert(t).second&&!DT(integerReply$$flags),"duplicate/early/error integer response");
            if(!e.store)check(DT(integerReply$$data)==e.value,"actual load bytes differ from independent program-order oracle");
            row("REPLY",cycle,t.first,t.second,pc(t),DT(integerReply$$data),DT(integerReply$$flags));
        }
#define DE(n) if(DT(slot##n##$$complete)){Token t{unsigned(DT(slot##n##$$completeIndex)),DT(slot##n##$$completeTag)};check(replies.contains(t)&&completed.insert(t).second&&!DT(slot##n##$$exception),"completion lacks exact successful response");row("COMPLETE",cycle,t.first,t.second,pc(t));}check(!DT(slot##n##$$discard),"unexpected memory discard");
        DE(0);DE(1);DE(2);DE(3);
#undef DE
        auto ctx=[&](unsigned i){check(i<2&&DP(live)[i],"posted owner not live");return Context{DP(contexts$$owner$$slot)[i],DP(contexts$$owner$$generation)[i],DP(contexts$$cohortRoot$$slot)[i],DP(contexts$$cohortRoot$$generation)[i],DP(contexts$$epoch)[i],DP(contexts$$lineAddress)[i],DP(reservations$$mshr)[i]};};
        auto ownerRow=[&](const char *name,const Context &c){row(name,cycle,c[0],c[1],c[2],c[3],c[4],c[5],c[6]);};
        for(unsigned i=0;i<2;++i)if(DP(live)[i]){const auto c=ctx(i);
            row("OWNER",cycle,c[0],c[1],c[2],c[3],c[4],c[5],c[6],DP(sealedRun)[i],DP(refilled)[i],DP(installed)[i],DP(reservations$$set)[i],DP(reservations$$way)[i],DP(reservations$$victimValid)[i],DP(reservations$$victimDirty)[i],DP(reservations$$victimAddress)[i]);}
        if(DT(cache$$valid)&&DT(cachePostedIntent)){
            Token t{unsigned(DA(checked_checked$head$$postedProof$$bits$$token$$index)),DA(checked_checked$head$$postedProof$$bits$$token$$tag)};
            check(memory(t).store&&started.contains(t),"cache proof lacks original authored-store start");orderedY(t,cycle);
            row("OFFER",cycle,t.first,t.second,pc(t),DT(cache$$ready),DP(accepted),DT(cache$$address));
        }
        if(DP(accepted)){
            Token t{unsigned(DA(checked_checked$head$$postedProof$$bits$$token$$index)),DA(checked_checked$head$$postedProof$$bits$$token$$tag)};
            const auto&e=memory(t);check(e.store&&DT(cache$$valid)&&DT(cache$$ready)&&DT(cachePostedIntent),"posted member is not actual proof-bearing cache fire");orderedY(t,cycle);
            row("MEMBER",cycle,t.first,t.second,pc(t),DP(_io_admission_T$$owner$$slot),DP(_io_admission_T$$owner$$generation),DP(_io_admission_T$$cohortRoot$$slot),DP(_io_admission_T$$cohortRoot$$generation),DP(_io_admission_T$$epoch),DP(_io_admission_T$$lineAddress),DP(_io_accepted_bits_reservation_T$$mshr),DC(responseAllocation),DP(_io_accepted_bits_newLine_T));
        }
        if(DP(io$$acknowledged$$valid)){
            Token t{unsigned(DP(io$$acknowledged$$bits$$token$$index)),DP(io$$acknowledged$$bits$$token$$tag)};
            check(DT(cacheReply$$valid)&&DT(cacheReply$$ready),"posted ACK without actual cache response fire");
            row("ACK",cycle,t.first,t.second,pc(t),DP(io$$acknowledged$$bits$$context$$owner$$slot),DP(io$$acknowledged$$bits$$context$$owner$$generation),DP(io$$acknowledged$$bits$$context$$cohortRoot$$slot),DP(io$$acknowledged$$bits$$context$$cohortRoot$$generation),DP(io$$acknowledged$$bits$$context$$epoch),DP(io$$acknowledged$$bits$$context$$lineAddress),DP(io$$acknowledged$$bits$$responseTicket));
        }
        if(DP(_io_drained_valid_T_8)){
            const unsigned h=DP(head);check(h<16,"member FIFO index");Token t{unsigned(DP(members$$token$$index)[h]),DP(members$$token$$tag)[h]};
            row("DRAIN",cycle,t.first,t.second,pc(t),DP(members$$context$$owner$$slot)[h],DP(members$$context$$owner$$generation)[h],DP(members$$context$$cohortRoot$$slot)[h],DP(members$$context$$cohortRoot$$generation)[h],DP(members$$context$$epoch)[h],DP(members$$context$$lineAddress)[h],DP(members$$responseTicket)[h]);
        }
        if(DC(_posted_io_refill_valid_T)){
            const auto c=ctx(DP(io$$refill$$bits$$context$$owner$$slot));ownerRow("REFILL_OFFER",c);
            if(DP(_io_refill_ready_T_22))ownerRow("REFILL_FIRE",c);
        }
        if(DC(postedInstall))ownerRow("INSTALL",ctx(DP(installSlot)));
        if(DP(_io_released_valid_T_8))ownerRow("RELEASE",ctx(DP(oldest)));
        const bool choice=DB(_memoryChoice_valid_T_4);
        if(choice&&count){
            Token s{unsigned(DB(memoryIssueEntry$$renamed$$token$$index)),DB(memoryIssueEntry$$renamed$$token$$tag)};
            check(s.first<16&&unsigned((s.first-head)&15)<count&&DB(ledger$entries$$tag)[s.first]==s.second,"staged selection outside exact live ROB token/window");
            check(DB(stagedMemoryToken$$index)==s.first&&DB(stagedMemoryToken$$tag)==s.second&&DB(pending)[s.first],"staged selection detached from full token or pending bit");
            check(!killed.contains(s)||killed.at(s)==cycle,"killed full token reselected after recovery edge");
            Token h{head,DB(ledger$entries$$tag)[head]};const auto&e=memory(s);
            unsigned hard=unsigned(bool(DB(ledger$recovering)))|unsigned(bool(DB(_interruptDrain_T_1)))<<1|unsigned(bool(DB(_reserveSystem_T_11)))<<2|unsigned(bool(DB(contextMemoryEpoch)))<<3|unsigned(bool(DB(headRequest_headEntry$$request$$system)))<<4|unsigned(bool(DA(authorizationChanged)))<<5;
            bool selectedStart=DT(startValid)&&s==Token{unsigned(d.get_backendStartIndex()),d.get_backendStartTag()};
            if(!e.store&&DB(postedBusy))row("SELECT",cycle,s.first,s.second,pc(s),unsigned((s.first-head)&15),head,h.second,pc(h),DB(pending)[s.first],DB(memoryLive)[s.first],DB(postedBusy),d.board$platform$core$_io_posted_seal_T_1,hard,selectedStart,DB(stagedMemoryAddress),DB(ordinaryRam),DB(pmpCheck$_io_denied_T_3));
        }
        if(DB(postedBusy)){
            unsigned hard=unsigned(bool(DB(ledger$recovering)))|unsigned(bool(DB(_interruptDrain_T_1)))<<1|unsigned(bool(DB(_reserveSystem_T_11)))<<2|unsigned(bool(DB(contextMemoryEpoch)))<<3|unsigned(count&&bool(DB(headRequest_headEntry$$request$$system)))<<4|unsigned(bool(DA(authorizationChanged)))<<5;
            if(hard){check(d.board$platform$core$_io_posted_seal_T_1,"actual hard seal cause failed to seal posted owner");row("HARD",cycle,hard,d.board$platform$core$_io_posted_seal_T_1,head,count);}
        }
        // Ordered retirement is checked only after all pre-edge proof/start/member
        // observations, so a Y on the same edge as U retirement is rejected.
        for(unsigned lane=0;lane<2;++lane){
            bool valid=lane?d.get_io$$commit1():d.get_io$$commit0();if(!valid)continue;
            uint64_t p=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();
            Token t{(head+lane)&15,lane?DB(ledger$io$$commit$$bits$$token$$tag_1):DB(ledger$io$$commit$$bits$$token$$tag_0)};
            check(pc(t)==p,"retirement PC/full token mismatch");
            check(!killed.contains(t),"killed full token retired");
            if(p==0x80000000ULL||p==0x80000004ULL)continue;
            if(done&&p==directed_guest::donePc)continue;
            check(nextRetire<directed_guest::trace.size()&&directed_guest::trace[nextRetire].pc==p,"program-order retirement differs from independent ISA sequence");
            const auto&e=directed_guest::trace[nextRetire++];if(e.memory)check(completed.contains(t),"memory retires before exact-token completion");
            check(retired.emplace(t,cycle).second,"full token retired twice");row("RETIRE",cycle,t.first,t.second,p,lane);
            if(e.done)done=cycle;
        }
#undef DB
#undef DP
#undef DC
#undef DA
#undef DT
    }
    void finish(){
        check(done&&nextRetire==directed_guest::trace.size(),"finite guest did not retire fully");
        tagged.finish();tagged.report();
        for(const auto&b:directed_guest::finalBytes){uint64_t word=test->ddr.memory[uint32_t((b.address&~7ULL)-ramBase)];check(((word>>((b.address&7)*8))&255)==b.value,"final DDR byte mismatch including untouched guard bytes");}
        row("FINISH",test->cycles,bindings.size(),started.size(),replies.size(),completed.size(),retired.size());out.flush();check(bool(out),"directed trace write");
    }
};
int main(int argc,char**argv){try{
    check(argc==3,"usage: directed-host guest.bin trace.tsv");Directed o(argv[2]);o.code=readFile(argv[1]);
    check(o.code.size()==directed_guest::rawBytes,"frozen guest length");
    for(size_t n=0;n<directed_guest::rawWords.size();++n)check(wordAt(o.code,n*4)==directed_guest::rawWords[n],"frozen raw guest differs from independent oracle inputs");
    Bytes rom;word(rom,0x00200297);word(rom,0x00028067);Test t(rom);t.running=false;o.test=&t;
    // Constructor enables DDR but does not tick after enable. Preload actual DDR
    // before the first guest fetch; do not write any internal CPU/cache signal.
    for(size_t off=0;off<o.code.size();off+=8){uint64_t v=0;for(unsigned b=0;b<8&&off+b<o.code.size();++b)v|=uint64_t(o.code[off+b])<<(8*b);t.ddr.memory[uint32_t(off)]=v;}
    for(const auto&b:directed_guest::initial){auto&w=t.ddr.memory[uint32_t((b.address&~7ULL)-ramBase)];w=(w&~(255ULL<<((b.address&7)*8)))|(uint64_t(b.value)<<((b.address&7)*8));}
    t.observer=Directed::callback;t.observerContext=&o;
    const uint64_t deadline=t.cycles+30000;while(!o.done&&t.cycles<deadline)t.tick();check(o.done,"directed guest timeout");
    t.idle(128);check(t.ddr.pendingReads.empty()&&t.ddr.pendingWrites.empty()&&t.ddr.pendingB.empty(),"DDR work remains after final real FENCE.I");t.fabric.finish();o.finish();
    std::cout<<"DIRECTED_FUNCTIONAL_PASS cycles="<<t.cycles<<"; run analyze_trace.py for mandatory coverage\n";return 0;
}catch(const std::exception&e){std::cerr<<"DIRECTED_FAIL "<<e.what()<<'\n';return 1;}}
