// Passive generated-net observation; every request originates in the executed guest.
#ifndef DDR_BENCHMARK_MODEL
#error "Requires unchanged independent credit-aware DDR benchmark model"
#endif
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
#define DATA_PATH_OWNERSHIP_PROBES
#include "backend_observer.h"
#include "cpu_flow_bandwidth.h"
#include "order_oracle.h"
#include <set>
#define B(name) d.board$platform$core$core$core$backend$##name
namespace {
using P=DataPathSample;using Key=std::pair<uint64_t,unsigned>;
Key key(BackendToken t){return {t.tag,t.index};}
order_oracle::Token token(BackendToken t){return {t.tag,t.index};}
struct Stamp {
    uint64_t pc=0,address=0;
    std::optional<uint64_t> start,fifo,physical,reply,lsuReply,result,cancel,observedCancel,retire;
};
struct Alloc {BackendToken token;uint64_t pc;};
struct Pending {BackendToken token;uint64_t expected;bool write;};
struct Observer {
    Test *test=nullptr;order_oracle::Architecture arch;
    BackendOwnershipLedger backend;FlowDataPathOwnershipLedger data;
    std::map<std::string,uint64_t> symbols;std::map<Key,Stamp> stamps;
    std::deque<Alloc> rob;std::deque<Pending> pending;
    std::set<Key> killed;std::vector<Key> branchKilled;
    order_oracle::Replay replay;
    uint64_t cycle=0,nextTag=0,retirements=0,readReplies=0,olderPrefix=0,replayOlderPrefix=0,pendingHolds=0;
    uint64_t replayOldStarts=0,replayNewStarts=0,branchRecoveries=0,signatureWrites=0,systemRecoveries=0;
    unsigned lastLive=0;bool lastStart=false,comparePending=false,finished=false,finalCompared=false,negativeFired=false;
    BackendToken selected{},checked{};std::string mutation;
    std::array<unsigned,9> lastCounts{};
    explicit Observer(Bytes bytes):arch(std::move(bytes)){}
    uint64_t sym(const char *name)const{return symbols.at(name);}
    bool inject(const char *name,bool when=true){if(!negativeFired&&when&&mutation==name){negativeFired=true;std::cerr<<"OBSERVATION_NEGATIVE fired=1 name="<<name<<'\n';return true;}return false;}
    static void sample(SBoardSocGsim &d,void *ctx){static_cast<Observer*>(ctx)->sample(d);}
    std::array<uint64_t,32> registers(SBoardSocGsim &d) {
        std::array<uint64_t,32> values{};
        for(unsigned r=0;r<32;++r){const unsigned p=B(ledger$committed)[r];check(p<48,"committed mapping outside PRF");
            if(!r)check(p==0,"zero register mapping changed");
            if(p&&B(physicalFile$initialized)[p]){const unsigned owner=B(physicalFile$owner)[p];check(owner<2,"PRF bank outside profile");
                values[r]=owner?B(physicalFile$banks_1)[p]:B(physicalFile$banks_0)[p];}}
        return values;
    }
    void allocations(SBoardSocGsim &d) {
        const uint64_t now=B(ledger$nextTag);check(now>=nextTag&&now-nextTag<=2,"allocation generation progression invalid");
        while(nextTag<now){unsigned hits=0;Alloc a{};
            for(unsigned i=0;i<16;++i)if(B(queue$$renamed$$token$$tag)[i]==nextTag&&B(queue$$renamed$$token$$index)[i]==i){
                ++hits;a={{nextTag,i},(i&1)?B(payload_1$pcBank1)[i>>1]:B(payload_1$pcBank0)[i>>1]};}
            check(hits==1,"new full generation lacks unique queue owner");
            check(a.pc>=order_oracle::rom&&a.pc+4<=order_oracle::rom+arch.image.size()&&!(a.pc&3),"allocated PC outside frozen guest");
            for(const auto &old:rob)check(old.token.index!=a.token.index,"allocation reused live ROB index cycle="+std::to_string(cycle)+" old_tag="+std::to_string(old.token.tag)+" new_tag="+std::to_string(a.token.tag)+" pc="+std::to_string(a.pc));
            check(!stamps.count(key(a.token)),"allocation reused full generation");
            stamps[key(a.token)].pc=a.pc;rob.push_back(a);++nextTag;
        }
    }
    void recover(BackendToken target,bool inclusive) {
        auto mark=std::find_if(rob.begin(),rob.end(),[&](const auto &a){return a.token==target;});
        check(mark!=rob.end(),"recovery target absent from independent allocation FIFO");
        if(!inclusive)++mark;
        for(auto i=mark;i!=rob.end();++i){killed.insert(key(i->token));stamps.at(key(i->token)).cancel=cycle;}
        rob.erase(mark,rob.end());
    }
    void sample(SBoardSocGsim &d) {
        ++cycle;auto b=BackendObserver::read(d);auto p=BackendObserver::readData(d);
        data.flowEvents=d.get_cpuFlowEvents();data.ingressAuth=d.get_cpuFlowIngressAuth();
        data.checkedAuth=d.get_cpuFlowCheckedAuth();data.checkedAddress=d.get_cpuFlowCheckedAddress();
        data.checkedData=d.get_cpuFlowCheckedData();data.checkedHeadAuth=d.get_cpuFlowCheckedHeadAuth();data.physicalAuth=d.get_cpuFlowPhysicalAuth();
        if(b.reset){data.advance(b,p,backend);backend.advance(b);return;}
        if(comparePending){auto actual=registers(d);if(inject("--inject-data",arch.loads>0)||inject("--inject-final-data",finished))actual[10]^=1;arch.compare(actual);comparePending=false;if(finished)finalCompared=true;}
        check(!d.get_io$$trap$$valid(),"unexpected executing CPU trap");
        check(!d.board$platform$dma$busy,"DMA must remain idle");check(p.bit(P::reserveGuardMatch),"capacity guard differs from production");
        if(finished&&finalCompared){
            // step() has applied the preceding observed retirement. Its newly
            // computed commit signals are offers for a future step, which this
            // bounded test never takes. Compare the last accepted GPR edge and
            // validate the CURRENT pre-edge memory state without admitting those
            // future offers into the architectural oracle. The terminal self-loop
            // need not produce an idle retirement cycle.
            backend.validate(b);data.validate(b,p,backend);
            lastLive=b.liveCount();lastStart=b.bit(3);lastCounts=p.count;
            check(!b.bit(3)&&!b.bit(20)&&!b.bit(22)&&!b.bit(24)&&!b.bit(26)&&!b.bit(41)&&
                !p.bit(P::physicalRequest)&&!p.bit(P::physicalReply),"terminal boundary has pending memory offer");
            std::cout<<"TERMINAL_REGISTER_EDGE compared=1 future_commit_offers="<<b.commits<<" future_edge_executed=0\n";
            return;
        }
        allocations(d);
        lastLive=b.liveCount();lastStart=b.bit(3);lastCounts=p.count;
        if(b.bit(3)){
            auto &s=stamps.at(key(b.start));check(!s.start,"duplicate full-token load start");s.start=cycle;
            if(s.pc==sym("replay_younger")){if(!replay.selected)++replayOldStarts;else ++replayNewStarts;}
        }
        if(b.enq()){auto &s=stamps.at(key(b.request));check(s.start.has_value(),"FIFO owner lacked executed start");s.fifo=cycle;
            s.address=p.request[P::fifoEnq].address;
            uint64_t expected=0;
            if(s.pc==sym("warmup_load")||s.pc==sym("replay_older")||s.pc==sym("replay_younger"))expected=order_oracle::overlap;
            for(unsigned i=0;i<4;++i)if(s.pc==sym(("wrong"+std::to_string(i)).c_str())||s.pc==sym(("survivor"+std::to_string(i)).c_str()))expected=order_oracle::cold+64*i;
            if(s.pc==sym("signature_store"))expected=order_oracle::signature;
            check(expected&&s.address==expected,"executed load/store PC/address binding mismatch");}
        if(b.reply())stamps.at(key(b.slots[b.returnSlot])).lsuReply=cycle;
        if(b.bit(26)&&b.bit(27)){auto &s=stamps.at(key(b.complete));check(!s.cancel,"canceled generation completed to ROB");s.result=cycle;}
        bool selector=B(replayPendingValid$NEXT),isPending=B(replayPendingValid),accepted=B(ordinaryLocalRedirectAccepted);
        BackendToken selectorToken{B(replayPending$$token$$tag$NEXT),B(replayPending$$token$$index$NEXT)};
        BackendToken pendingToken{B(replayPending$$token$$tag),B(replayPending$$token$$index)};
        BackendToken local{B(localCandidate$$bits$$token$$tag),B(localCandidate$$bits$$token$$index)};
        if(inject("--inject-selector",selector))selector=false;
        if(inject("--inject-pending",isPending))isPending=false;
        if(inject("--inject-generation",selector))selectorToken.tag^=1ULL<<63;
        if(inject("--inject-recovery",accepted&&isPending))accepted=false;
        if(selector){
            check(B(orderCheckValid),"selector lacked registered order check");
            const unsigned i=B(orderCheckIndex);checked={B(queue$$renamed$$token$$tag)[i],i};
            #if OLDER_PREFIX
            check(B(orderCheckTag)==checked.tag,"registered checked-load full generation mismatch");
#endif
            auto &old=stamps.at(key(checked));check(old.pc==sym("replay_older")&&old.start&&*old.start+1==cycle,"checked older load identity/timing mismatch");
            check(B(orderCheckBeat)==order_oracle::overlap/8&&B(orderCheckLanes)==255,"independent checked byte overlap mismatch");
            auto younger=std::find_if(rob.begin(),rob.end(),[&](const auto &a){return a.pc==sym("replay_younger");});
            check(younger!=rob.end(),"younger replay owner missing");selected=younger->token;auto &young=stamps.at(key(selected));
            std::cout<<"REPLAY_SELECTOR cycle="<<cycle<<" checked_index="<<checked.index<<" checked_tag="<<checked.tag
                <<" selected_index="<<selected.index<<" selected_tag="<<selected.tag<<" older_start="<<old.start.value_or(0)
                <<" younger_start="<<young.start.value_or(0)<<" physical="<<young.physical.value_or(0)
                <<" reply="<<young.reply.value_or(0)<<" result="<<young.result.value_or(0)<<'\n';
            check(young.start&&young.physical&&young.reply&&young.result&&*young.start<*old.start,"younger overlapping load did not execute before delayed older load");
            check(!young.retire&&!old.retire,"checked or younger load retired before overlap resolution");
            check(old.address<young.address+8&&young.address<old.address+8,"independent guest byte intervals did not overlap");
            replay.select(token(selected),token(selectorToken),cycle);
        }
        if(replay.selected&&cycle==replay.selectedCycle+1)check(isPending,"missing pending witness");
        if(isPending&&B(ordinaryLocalRedirectAccepted))check(accepted,"missing accepted replay recovery");
        if(isPending){replay.observePending(token(pendingToken),cycle);++pendingHolds;check(b.commits==0,"pending replay failed global retirement hold");}
        if(accepted){
            check(B(localCandidate$$valid),"accepted local recovery lacks valid candidate");
            const uint64_t pc=stamps.at(key(local)).pc;
            if(isPending){replay.accept(token(local));recover(local,true);
                std::cout<<"REPLAY_RECOVERY cycle="<<cycle<<" index="<<local.index<<" tag="<<local.tag<<" inclusive=1\n";}
            else if(pc==sym("branch_taken")){
                check(branchRecoveries++==0,"duplicate branch recovery");
                std::cout<<"BRANCH_RECOVERY cycle="<<cycle<<" index="<<local.index<<" tag="<<local.tag<<" live="<<b.liveCount()<<'\n';
                for(unsigned i=0;i<4;++i)if(b.live[i]){const auto &s=stamps.at(key(b.slots[i]));
                    std::cout<<"BRANCH_OWNER slot="<<i<<" index="<<b.slots[i].index<<" tag="<<b.slots[i].tag<<" pc="<<s.pc
                        <<" phase="<<b.phase[i]<<" start="<<s.start.value_or(0)<<" physical="<<s.physical.value_or(0)<<" reply="<<s.reply.value_or(0)<<'\n';}
                check(b.liveCount()==4,"delayed branch lacked four distinct live LSU owners");
                std::set<uint64_t> pcs;
                for(unsigned i=0;i<4;++i){const auto k=key(b.slots[i]);const auto &s=stamps.at(k);pcs.insert(s.pc);
                    check(s.start&&s.fifo&&!s.reply&&!s.result&&!s.retire,"branch canceled owner had already drained/completed");branchKilled.push_back(k);}
                for(unsigned i=0;i<4;++i)check(pcs.count(sym(("wrong"+std::to_string(i)).c_str())),"branch live-owner PC set mismatch");
                recover(local,false);
            }else if(pc==sym("replay_done"))recover(local,false);
            else throw std::runtime_error("unexpected local recovery outside replay/taken-branch/done");
        }
        if(B(ledger$acceptHeadSystem)){
            check(!accepted&&b.commits==0&&b.headValid&&!rob.empty()&&rob.front().token==b.head,
                "protected system recovery lacks independent current head");
            check(wordAt(arch.image,rob.front().pc-order_oracle::rom)==0x0000100f,
                "unexpected protected system recovery outside final FENCE.I");
            check(systemRecoveries++==0,"duplicate final FENCE.I recovery");
            recover(b.head,false);
            std::cout<<"FENCE_I_RECOVERY cycle="<<cycle<<" index="<<b.head.index<<" tag="<<b.head.tag<<" keep_head=1\n";
        }
        // The exported cancel bits are same-cycle kill pulses, not the
        // slot's sticky state. Check both at their actual clock boundaries.
        const std::array<bool,4> sticky{bool(B(lsu$slots_0$cancelled)),bool(B(lsu$slots_1$cancelled)),
            bool(B(lsu$slots_2$cancelled)),bool(B(lsu$slots_3$cancelled))};
        for(unsigned i=0;i<4;++i)if(b.live[i]){
            auto &s=stamps.at(key(b.slots[i]));
            if(inject("--inject-cancellation",s.cancel&&*s.cancel==cycle))b.cancelled[i]=false;
            if(s.cancel&&*s.cancel==cycle)check(b.cancelled[i],"accepted recovery omitted LSU cancellation");
            if(s.cancel&&*s.cancel<cycle)check(sticky[i],"canceled owner lost sticky cancellation");
            if(b.cancelled[i]){check(s.cancel.has_value(),"LSU canceled without accepted recovery");if(!s.observedCancel)s.observedCancel=cycle;}
            if(s.cancel)check(!s.result||*s.result<*s.cancel,"canceled generation completed to ROB");
        }
        for(unsigned lane=0;lane<2;++lane){const bool valid=lane?d.get_io$$commit1():d.get_io$$commit0();if(!valid)continue;
            const uint64_t pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();
            BackendToken t{lane?B(ledger$io$$commit$$bits$$token$$tag_1):B(ledger$io$$commit$$bits$$token$$tag_0),(b.head.index+lane)&15U};
            // Corrupt only the observed token of an actual valid retirement.
            // This exercises the ordinary commit admission path, not a separate assertion.
            if(inject("--inject-canceled-retirement",replay.accepted))t=selected;
            check(!killed.count(key(t)),"canceled full generation retired");check(!rob.empty()&&rob.front().token==t&&rob.front().pc==pc,"commit differs from independent allocation FIFO");
            if(B(orderCheckValid)){
                auto marker=std::find_if(rob.begin(),rob.end(),[&](const auto &a){return a.token.index==B(orderCheckIndex)&&a.token.tag==B(queue$$renamed$$token$$tag)[B(orderCheckIndex)];});
                check(marker!=rob.end()&&marker!=rob.begin(),"checked owner or younger suffix retired early");++olderPrefix;replayOlderPrefix+=marker->pc==sym("replay_older");
            }
            auto &s=stamps.at(key(t));check(!s.retire,"duplicate full-generation retirement");s.retire=cycle;
            if(inject("--inject-pc"))arch.retire(pc^4);else arch.retire(pc);
            rob.pop_front();++retirements;comparePending=true;finalCompared=false;if(pc==sym("replay_done"))finished=true;
        }
        if(p.bit(P::physicalReply)){
            check(!pending.empty()&&!data.physicalPending.empty(),"physical reply lacked independent owner");auto q=pending.front();pending.pop_front();
            check(q.token==data.physicalPending.front().token,"physical response full-token FIFO lineage mismatch");
            check(p.reply[0].flags==0,"unexpected physical memory fault");
            auto actual=p.reply[0].data;if(inject("--inject-read-data",!q.write))actual^=1;
            if(!q.write){check(actual==q.expected,"independent known-memory response mismatch");++readReplies;}
            stamps.at(key(q.token)).reply=cycle;
        }
        if(p.bit(P::physicalRequest)){
            check(!data.checked.empty(),"physical request lacks checked full-token owner");auto t=data.checked.front().token;
            const auto &r=p.request[P::physical];check(!(r.address&7)&&((r.meta>>7)&3)==3&&((r.meta>>9)&255)==255&&!r.atomic()&&!r.virtualized(),"unexpected RAM request shape");
            uint64_t expected=0;
            if(r.write()){check(r.address==order_oracle::signature&&r.data==order_oracle::value(order_oracle::overlap)&&signatureWrites++==0,"independent signature physical store mismatch");}
            else expected=order_oracle::value(r.address);
            stamps.at(key(t)).physical=cycle;pending.push_back({t,expected,r.write()});
        }
        data.advance(b,p,backend);backend.advance(b);
    }
    void initialize(Test &t){test=&t;t.ddr.memory[uint32_t(order_oracle::overlap-ramBase)]=order_oracle::value(order_oracle::overlap);
        for(unsigned i=0;i<4;++i)t.ddr.memory[uint32_t(order_oracle::cold+64*i-ramBase)]=order_oracle::value(order_oracle::cold+64*i);}
    void verify(){
        replay.verify();
        check(OLDER_PREFIX?replayOlderPrefix>0:olderPrefix==0,"older-prefix OFF/ON checking-window retirement witness missing");
        check(finished&&finalCompared&&!comparePending,"final PC/register edge not checked");check(replayOldStarts==1&&replayNewStarts==1,"replayed LD did not allocate a fresh full generation");
        check(branchRecoveries==1&&branchKilled.size()==4,"four-owner branch witness missing");
        unsigned before=0,after=0,reused=0;
        for(const auto &k:branchKilled){const auto &s=stamps.at(k);
            check(s.cancel&&s.observedCancel&&s.start&&s.fifo&&s.physical&&s.reply&&s.lsuReply&&!s.result&&!s.retire,"canceled owner did not drain without bad completion/retirement");
            check(*s.start<=*s.fifo&&*s.fifo<=*s.physical&&*s.physical<=*s.reply&&*s.reply<=*s.lsuReply,"canceled owner stage order invalid");
            before+=*s.cancel<*s.physical;after+=*s.physical<=*s.cancel;
            std::cout<<"CANCELED_DRAIN index="<<k.second<<" tag="<<k.first<<" cancel="<<*s.cancel<<" physical="<<*s.physical
                <<" reply="<<*s.reply<<" lsu_reply="<<*s.lsuReply<<" retired=0 completed=0\n";
            for(const auto &[other,n]:stamps)if(other.second==k.second&&other.first!=k.first&&n.retire&&*n.retire>*s.cancel){++reused;break;}}
        check(before&&after,"missing cancellation before/after physical acceptance");check(reused==4,"canceled ROB indices did not retire fresh generations");
        if(inject("--inject-drain"))pending.push_back({{},0,false});
        check(!lastLive&&!lastStart&&std::none_of(backend.slotOwners.begin(),backend.slotOwners.end(),[](const auto &s){return s.live;}),"terminal live LSU owner");
        check(std::all_of(lastCounts.begin(),lastCounts.end(),[](unsigned n){return !n;}),"terminal raw flow stage count");
        check(pending.empty()&&backend.requests.empty()&&backend.responses.empty(),"terminal pending owner/reply drain failure");
        check(!backend.stalledRequest&&!data.stalledRequest&&!data.stalledReply,"terminal held handshake");
        check(data.fifo.empty()&&data.stores.empty()&&data.storeOwners.empty()&&data.ingress.empty()&&data.translated.empty()&&data.checked.empty()&&data.owners.empty()&&data.physicalPending.empty()&&data.returns.empty()&&!data.waiting&&!data.localReply,"terminal full flow stage drain failure");
        check(test->ddr.pendingReads.empty()&&test->ddr.pendingWrites.empty()&&test->ddr.pendingB.empty()&&!test->ddr.heldRead&&!test->ddr.heldB,"terminal external AXI/held drain failure");
        check(systemRecoveries==1,"final FENCE.I protected-head recovery missing");
        check(arch.loads==7&&arch.stores==1&&signatureWrites==1,"architectural load/store conservation failed");
        check(test->ddr.memory[uint32_t(order_oracle::signature-ramBase)]==order_oracle::value(order_oracle::overlap),"final flushed signature mismatch");
        check(mutation.empty()||negativeFired,"observation negative did not fire");
        std::cout<<"EXECUTED_CPU_ORDER_PASS selector=1 pending=1 accepted=1 branch_live=4 cancellation_before_physical="<<before<<" cancellation_after_physical="<<after<<" reused_indices="<<reused<<" terminal_drain=1 pending_holds="<<pendingHolds<<" older_prefix_commits="<<olderPrefix<<" replay_older_prefix_commits="<<replayOlderPrefix<<" read_replies="<<readReplies<<" cycles="<<cycle<<" retired="<<retirements<<'\n';data.report();
    }
};
}
int main(int argc,char **argv){try{
    check(argc==3||argc==4,"usage: run guest.bin symbols.txt [observation-negative]");Observer o(readFile(argv[1]));if(argc==4)o.mutation=argv[3];
    std::ifstream f(argv[2]);check(bool(f),"missing guest symbols");std::string name;uint64_t value;while(f>>name>>std::hex>>value)check(o.symbols.emplace(name,value).second,"duplicate guest symbol");
    check(o.symbols.size()==18&&o.sym("_start")==order_oracle::rom,"guest symbol inventory mismatch");
    Test t(o.arch.image,Observer::sample,&o);o.initialize(t);
    while(!o.finished||!o.finalCompared){check(t.cycles<20000,"bounded executing replay guest timed out");t.tick();}
    o.verify();return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
