#include "ReadyStoreQuery77BackendGsim.h"
#include "ready_store_query77_reference.h"
#include <algorithm>
#include <array>
#include <cstring>
#include <deque>
#include <iostream>
#include <optional>
#include <set>
#include <tuple>
#include <type_traits>
#include <vector>
#ifndef PENDING_STORE_ENABLED
#define PENDING_STORE_ENABLED 1
#endif
#ifndef BOUND_HEAD_STORE_OVERLAP
#define BOUND_HEAD_STORE_OVERLAP 1
#endif
#ifndef PENDING_READY_STORE_BYPASS
#define PENDING_READY_STORE_BYPASS 1
#endif
#ifndef EARLY_LOAD_CREDITS
#define EARLY_LOAD_CREDITS 2
#endif
static_assert(PENDING_STORE_ENABLED == 1 && BOUND_HEAD_STORE_OVERLAP == 1 && PENDING_READY_STORE_BYPASS == 1 && EARLY_LOAD_CREDITS == 2);
using namespace pending_store_reference;
static uint64_t sext(uint64_t v,unsigned bits) { return uint64_t(int64_t(v << (64-bits)) >> (64-bits)); }
static uint32_t imm(unsigned rd,unsigned rs,int n) { return (uint32_t(n)&4095)<<20 | rs<<15 | rd<<7 | 0x13; }
static uint32_t shift(unsigned rd,unsigned n) { return n<<20 | rd<<15 | 1<<12 | rd<<7 | 0x13; }
static uint32_t ld(unsigned rd,unsigned rs,int off=0,unsigned size=3) { return (uint32_t(off)&4095)<<20 | rs<<15 | size<<12 | rd<<7 | 3; }
static uint32_t st(unsigned rs,unsigned data,int off=0,unsigned size=3) {
    const unsigned v=unsigned(off)&4095; return (v>>5)<<25 | data<<20 | rs<<15 | size<<12 | (v&31)<<7 | 0x23;
}
static uint32_t beq(unsigned rs,int offset=32) {
    const unsigned v=unsigned(offset)&8191;return ((v>>12)&1)<<31|((v>>5)&63)<<25|rs<<20|rs<<15|((v>>1)&15)<<8|((v>>11)&1)<<7|0x63;
}
static uint32_t divu(unsigned rd,unsigned a,unsigned b) { return 1u<<25 | b<<20 | a<<15 | 5<<12 | rd<<7 | 0x33; }
struct Instruction { uint32_t word=0x13; uint64_t pc=0; };
struct Entry {
    Token token{}; Instruction inst{}; unsigned rd=0, rs1=0, rs2=0, size=0;
    bool writes=false,memory=false,store=false,system=false,divide=false,branch=false,atomic=false,fault=false,killed=false;
    uint64_t expected=0,address=0,pa=0,data=0,allocated=0,start=0,physical=0,response=0,complete=0,retire=0,checked=0,released=0;
    bool started=false,requested=false,completed=false,retired=false,frozen=false,prechecked=false;
};
struct Reply { uint64_t due=0,data=0; Token token{}; bool error=false; unsigned handle=0; };
struct PteReply { uint64_t due=0,data=0; };
struct Bench {
    SReadyStoreQuery77BackendGsim dut;
    Tables tables; Bytes actual, expected;
    std::array<uint64_t,32> architectural{},predicted{};
    std::map<Token,Entry> entries;
    std::deque<Token> live,requests;
    std::deque<Reply> replies;
    std::deque<PteReply> ptes;
    std::set<Token> completionTokens,retiredTokens;
    uint64_t cycle=0,nextPc=0x1000,physicalHold=0,responseHold=0,latency=8;
    uint64_t oldDataReady=0,proofCycle=0,firstEarlyPhysical=0,earlyReadDrain=0,overlapCapture=0;
    unsigned accepted=0,retired=0,physicalCount=0,responseCount=0,queryReads=0,queryWrites=0,walks=0,traps=0;
    unsigned earlyStarts=0,peakCredit=0,creditReturns=0,holds=0,killCount=0,reuse=0;
    unsigned readyEarlyStarts=0,readyHeadCycles=0,activeCreditCycles=0;
    uint64_t readyRelease=0,firstReadyEarly=0,storeBecameHead=0;
    std::map<unsigned,uint64_t> generations;
    std::optional<Token> oldStore,youngLoad,secondLoad,previousCredit,expectedCredit;
    std::optional<Proof> boundProof;
    std::map<Token,Proof> currentProofs,proofHistory,protectedProofs;
    std::set<Token> expectedCredits,seenEarly;
    unsigned twoProofCycles=0,twoBoundCycles=0,twoCreditCycles=0,b2IdleStarts=0,maxNeededProofs=0,readyHeadSpareCycles=0;
    std::optional<Token> secondStore,thirdLoad;
    bool faultStore=false,faultLoad=false,commitEnable=true,injectData=false,injectRetire=false;
    bool injectFrozenPa=false,injectLocalAck=false,injectLoadError=false,injectStoreError=false;
    unsigned overlappedStarts=0,checkedStores=0,corruptions=0,recoveryEdges=0,recoveryWithLiveRead=0;
    bool trackingFresh=false,expectedQuery=false,denyStore=false,injectProofPa=false,injectEligibility=false;
    unsigned freshWindows=0,freshAdmissions=0,freshWrites=0,headVetoCycles=0;
    uint64_t freshStart=0;
    bool trackingHeadTransition=false;
    unsigned selectedReadyHeadWindows=0;
    std::map<unsigned,Token> physicalHandles;
    std::set<Token> previousLive;
    using Held=std::tuple<uint64_t,uint64_t,unsigned,unsigned,bool,bool,unsigned>;
    std::optional<Held> heldPhysical,heldUpstream;
    bool previousCreditActive=false;
    Bench() {
        static_assert(std::is_trivially_copyable_v<SReadyStoreQuery77BackendGsim>);
        std::memset(&dut,0,sizeof(dut));dut.LOG_START=1;dut.activateAll();
        tick({}, {}, true);tick({}, {}, true);tick();tick();
    }
    void check(bool ok,const std::string &why) const { require(ok,"cycle="+std::to_string(cycle)+" "+why); }
    Entry interpret(Instruction inst,Token token) {
        Entry e; e.token=token;e.inst=inst;e.allocated=cycle;
        const uint32_t w=inst.word;const unsigned op=w&127,f=(w>>12)&7;
        e.rd=(w>>7)&31;e.rs1=(w>>15)&31;e.rs2=(w>>20)&31;
        const uint64_t a=predicted[e.rs1],b=predicted[e.rs2];
        if(op==0x13) {e.writes=true;
            if(f==0)e.expected=a+sext(w>>20,12);else if(f==1)e.expected=a<<((w>>20)&63);
            else throw std::runtime_error("unimplemented independent immediate opcode");
        } else if(op==0x33 && (w>>25)==1 && f==5) {
            e.writes=true;e.divide=true;e.expected=b?a/b:UINT64_MAX;
        } else if(op==3 || op==0x23) {
            e.memory=true;e.store=op==0x23;e.writes=!e.store;e.size=f&3;
            const uint64_t offset=sext(e.store?((w>>25)<<5 | ((w>>7)&31)):(w>>20),12);
            e.address=a+offset;e.pa=tables.physical(e.address);e.data=b;e.fault=e.store?faultStore:faultLoad;
            if(e.store) { if(!e.fault) expected.write(e.pa,b,e.size); }
            else {e.expected=expected.read(e.pa,e.size);if(!(f&4)&&e.size<3)e.expected=sext(e.expected,8u<<e.size);}
        } else if(op==0x63) {
            check(f==0&&a==b,"independent branch fixture must be a taken BEQ");
            e.branch=true;e.expected=inst.pc+sext(((w>>31)<<12)|(((w>>7)&1)<<11)|(((w>>25)&63)<<5)|(((w>>8)&15)<<1),13);
        } else if(op==0x73) {e.system=true;e.writes=e.rd!=0;e.expected=0;}
        else throw std::runtime_error("unknown raw instruction in independent interpreter");
        if(e.writes && e.rd)predicted[e.rd]=e.expected;
        return e;
    }
    void observeRetirement(Token t,uint64_t pc,uint32_t word,uint64_t data) {
        check(entries.count(t),"retirement has no allocated full token");auto &e=entries.at(t);
        check(!e.killed&&!e.fault&&!retiredTokens.count(t),"fault/killed/duplicate retirement");
        check(!live.empty()&&live.front()==t,"retirement lost exact program order");live.pop_front();retiredTokens.insert(t);
        check(word==e.inst.word&&pc==e.inst.pc,"retirement provenance mismatch");
        if(e.writes&&e.rd){check(data==e.expected,"architectural retirement data mismatch");architectural[e.rd]=e.expected;}
        if(e.memory)check(e.response && e.complete && cycle>=e.response,"memory retirement before actual response and completion");
        e.retired=true;e.retire=cycle;++retired;
    }
    std::vector<Token> tick(std::array<std::optional<Instruction>,2> offered={},
            std::optional<Token> recover={},bool reset=false) {
        check(!recover,"registered redirect profile forbids external recovery input");
        dut.set_reset(reset);
#define INPUT(N) \
        dut.set_io$$instruction##N##$$valid(offered[N].has_value()); \
        dut.set_io$$instruction##N##$$bits(offered[N]?offered[N]->word:0xffffffffU); \
        dut.set_io$$pc##N(offered[N]?offered[N]->pc:UINT64_MAX)
        INPUT(0);INPUT(1);
#undef INPUT
        dut.set_io$$commitEnable(commitEnable);dut.set_io$$inspectRegister(cycle%32);
        dut.set_io$$probeIndex(oldStore?oldStore->index:15);
        dut.set_io$$recover$$valid(recover.has_value());dut.set_io$$recover$$bits$$inclusive(true);
        dut.set_io$$recover$$bits$$token$$index(recover?recover->index:15);
        dut.set_io$$recover$$bits$$token$$tag(recover?recover->tag:UINT64_MAX);
        const bool ready=cycle>=physicalHold && cycle%7!=3;
        const bool response=!replies.empty()&&replies.front().due<=cycle&&cycle>=responseHold;
        dut.set_io$$physical$$request$$ready(ready);dut.set_io$$physical$$response$$valid(response);
        dut.set_io$$physical$$response$$bits$$data(response?replies.front().data:UINT64_MAX);
        bool responseError=response&&replies.front().error;
        if(response && responseError && ((injectLoadError&&!entries.at(replies.front().token).store)||(injectStoreError&&entries.at(replies.front().token).store))) {responseError=false;++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';}
        dut.set_io$$physical$$response$$bits$$error(responseError);
        dut.set_io$$physical$$response$$bits$$pageFault(false);
        dut.set_io$$physical$$response$$bits$$returnHandle(response?replies.front().handle:0);
        const bool pte=!ptes.empty()&&ptes.front().due<=cycle;
        dut.set_io$$pte$$request$$ready(cycle%5!=2);dut.set_io$$pte$$response$$valid(pte);
        dut.set_io$$pte$$response$$bits$$data(pte?ptes.front().data:UINT64_MAX);
        dut.set_io$$pte$$response$$bits$$error(false);
        dut.step();
        if(reset){dut.resetAll();++cycle;return{};}
        check(dut.get_io$$committedValue()==architectural[cycle%32],"architectural register snapshot mismatch");
        // Rename, registered recovery and actual ordered retire outputs maintain
        // this independent full-token queue. Sample before this edge's commits.
        const std::optional<Token> preHead=live.empty()?std::nullopt:std::optional{live.front()};
        const bool readyOldHead=oldStore&&preHead&&*preHead==*oldStore&&dut.get_io$$probePending()&&dut.get_io$$probeDataReady();
        if(readyOldHead){++readyHeadCycles;if(expectedCredits.size()<EARLY_LOAD_CREDITS)++readyHeadSpareCycles;
            if(!storeBecameHead)storeBecameHead=cycle;}
        std::vector<Token> allocated;
        std::optional<Token> earlyThisCycle;
#define ACCEPT(N) \
        if(dut.get_io$$renamed##N##$$valid()) { \
            check(offered[N].has_value(),"rename without valid raw instruction"); \
            Token t{unsigned(dut.get_io$$renamed##N##$$bits$$token$$index()),uint64_t(dut.get_io$$renamed##N##$$bits$$token$$tag())}; \
            Entry e=interpret(*offered[N],t); \
            check(bool(dut.get_io$$decoded##N##$$memory())==e.memory && bool(dut.get_io$$decoded##N##$$store())==e.store && \
                bool(dut.get_io$$decoded##N##$$mulDiv())==e.divide && bool(dut.get_io$$decoded##N##$$system())==e.system, \
                "real decoder class differs from independent raw opcode"); \
            if(e.memory)check(dut.get_io$$decoded##N##$$rename$$rs1()==e.rs1 && \
                dut.get_io$$decoded##N##$$rename$$rs2()==(e.store?e.rs2:0) && \
                dut.get_io$$decoded##N##$$memorySize()==e.size,"real decoder memory operands/size mismatch"); \
            auto g=generations.find(t.index);if(g!=generations.end()&&g->second!=t.tag)++reuse;generations[t.index]=t.tag; \
            check(!entries.count(t),"full ROB generation reused");entries.emplace(t,e);live.push_back(t);allocated.push_back(t);++accepted; \
        }
        ACCEPT(0);ACCEPT(1);
#undef ACCEPT
        if(pte&&dut.get_io$$pte$$response$$ready())ptes.pop_front();
        if(dut.get_io$$pte$$request$$valid()&&cycle%5!=2)ptes.push_back({cycle+2,tables.pte(dut.get_io$$pte$$request$$bits())});
        walks+=dut.get_io$$translationWalk();
        if(dut.get_io$$queryValid()){dut.get_io$$queryWrite()?++queryWrites:++queryReads;}
        if(oldStore&&dut.get_io$$probePending()&&dut.get_io$$probeDataReady()&&!oldDataReady) {
            check(dut.get_io$$probeToken$$index()==oldStore->index&&dut.get_io$$probeToken$$tag()==oldStore->tag,
                "readiness probe mismatched full owner");oldDataReady=cycle;
        }
        currentProofs.clear();
#define PROOF(PORT,ROW) \
        if(dut.get_io$$##PORT##$$valid()) { \
            Proof p{{unsigned(dut.get_io$$##PORT##$$bits$$token$$index()),uint64_t(dut.get_io$$##PORT##$$bits$$token$$tag())}, \
                uint32_t(dut.get_io$$##PORT##$$bits$$epoch()),uint64_t(dut.get_io$$##PORT##$$bits$$payload$$address()), \
                uint64_t(dut.get_io$$##PORT##$$bits$$payload$$physicalAddress()),bool(dut.get_io$$##PORT##$$bits$$payload$$write()), \
                unsigned(dut.get_io$$##PORT##$$bits$$payload$$size()),unsigned(dut.get_io$$##PORT##$$bits$$payload$$mask())}; \
            check(entries.count(p.token),"proof has no allocated full token");const auto &e=entries.at(p.token); \
            check(e.memory&&e.store&&!e.killed&&p.write&&p.original==e.address&&p.physical==e.pa&&p.size==e.size&& \
                p.mask==lanes(e.pa,e.size)&&p.epoch==dut.get_io$$epoch(),"proof differs from host physical interval"); \
            check(currentProofs.emplace(p.token,p).second,"duplicate proof full token");proofHistory[p.token]=p; \
            if(oldStore&&p.token==*oldStore){if(!proofCycle)proofCycle=cycle;boundProof=p;} \
            if(protectedProofs.count(p.token))check(protectedProofs.at(p.token)==p&& \
                (dut.get_io$$proofBoundMask()&(1u<<ROW)),"bound proof changed or unbound before exact handoff/kill"); \
        }
        PROOF(proof,0);PROOF(proofSecond,1);
#undef PROOF
        if(trackingFresh && oldStore) {
            check(bool(dut.get_io$$actualQueryEnabled())==expectedQuery,"actual query option mismatch");
            check(!preHead || dut.get_io$$actualHead()==preHead->index,"actual head differs from independent retirement order");
            if(dut.get_io$$probePending()) check(dut.get_io$$probeAtHead()==(dut.get_io$$actualHead()==oldStore->index),"head-mask probe mismatch");
            const bool selected=youngLoad && dut.get_io$$selectedLoadValid() &&
                dut.get_io$$selectedToken$$index()==youngLoad->index && dut.get_io$$selectedToken$$tag()==youngLoad->tag;
            const bool readyOwner=dut.get_io$$probePending() && dut.get_io$$probeDataReady() &&
                dut.get_io$$probeOwnerValid() && dut.get_io$$probeAddressKnown();
            const bool absent=!(dut.get_io$$presentOwners()&(1u<<oldStore->index));
            const bool opportunity=selected&&readyOwner&&dut.get_io$$probeOlder()&&!dut.get_io$$probeAtHead()&&
                absent&&dut.get_io$$bankEmpty()&&dut.get_io$$creditAvailable()&&!dut.get_io$$queryPaused()&&dut.get_io$$queryStable();
            if(opportunity){
                ++freshWindows;
                bool eligible=dut.get_io$$queryEligibleMask()&(1u<<oldStore->index);
                if(injectEligibility){eligible=!eligible;++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';}
                check(eligible==expectedQuery,"ready nonhead query eligibility differs from selected option");
                check(bool(dut.get_io$$queryMask()&(1u<<oldStore->index))==expectedQuery,"ready nonhead actual query mask mismatch");
            }
            if(dut.get_io$$bankAdmission()&&dut.get_io$$bankAdmitIndex()==oldStore->index){
                check(expectedQuery&&readyOwner&&!dut.get_io$$probeAtHead()&&selected&&absent,"fresh admission lacks ready nonhead exact owner");
                ++freshAdmissions;
            }
            if(dut.get_io$$queryValid()&&dut.get_io$$queryWrite()&&dut.get_io$$queryAddress()==entries.at(*oldStore).address){
                check(freshAdmissions,"fresh store write query preceded observed admission");++freshWrites;
            }
            if(readyOwner&&dut.get_io$$probeAtHead()){
                ++headVetoCycles;
                check(!(dut.get_io$$queryEligibleMask()&(1u<<oldStore->index)),"ready head acquired query eligibility");
                check(!(dut.get_io$$bankAdmission()&&dut.get_io$$bankAdmitIndex()==oldStore->index),"ready head admitted new query");
                if(trackingHeadTransition&&selected&&dut.get_io$$probeOlder()&&absent&&
                    dut.get_io$$bankEmpty()&&dut.get_io$$creditAvailable()&&
                    !dut.get_io$$queryPaused()&&dut.get_io$$queryStable()) {
                    check(dut.get_io$$probeToken$$index()==oldStore->index&&dut.get_io$$probeToken$$tag()==oldStore->tag,
                        "selected ready-head transition lost exact store token");
                    check(preHead&&*preHead==*oldStore&&!entries.at(*oldStore).started,
                        "selected ready-head transition lacks unaccepted independent head owner");
                    check(!currentProofs.count(*oldStore)&&!proofHistory.count(*oldStore)&&!freshAdmissions&&!freshWrites,
                        "selected ready-head transition retained prior query/proof");
                    check(!(dut.get_io$$queryMask()&(1u<<oldStore->index)),"selected ready head entered actual query mask");
                    check(!dut.get_io$$lsuStart(),"commit-frozen selected ready-head transition admitted memory");
                    ++selectedReadyHeadWindows;
                }
            }
            if(injectProofPa&&currentProofs.count(*oldStore)){
                auto altered=currentProofs.at(*oldStore);altered.physical^=1ULL<<32;
                ++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';
                check(altered.physical==entries.at(*oldStore).pa,"injected proof full-PA mismatch");
            }
        }
        twoProofCycles+=currentProofs.size()==2;twoBoundCycles+=dut.get_io$$proofBoundMask()==3;
        for(const auto&[t,p]:protectedProofs)if(!entries.at(t).started&&!entries.at(t).killed)
            check(currentProofs.count(t)&&currentProofs.at(t)==p,"surviving unaccepted store lost protected certificate");
        if(dut.get_io$$lsuOffer())check(dut.get_io$$lsuReady(),"backend valid=>ready profile contract violated");
        if(dut.get_io$$lsuStart()) {
            check(!dut.get_io$$recovering()&&!dut.get_io$$recoveryAccepted(),"same-edge registered recovery admitted a memory start");
            Token t{unsigned(dut.get_io$$lsuToken$$index()),uint64_t(dut.get_io$$lsuToken$$tag())};
            check(entries.count(t),"LSU start has no full-token owner");auto &e=entries.at(t);
            check(!e.started&&!e.killed&&e.memory,"duplicate/cancelled/nonmemory LSU start");e.started=true;e.start=cycle;
            e.prechecked=dut.get_io$$lsuPrechecked();
            check(dut.get_io$$lsuVa()==e.address&&bool(dut.get_io$$lsuStore())==e.store,"LSU original VA/type mismatch");
            if(e.store) {
                check(!dut.get_io$$lsuParallel(),"pending proof made actual store parallel");
                if(oldStore&&t==*oldStore&&youngLoad&&previousLive.count(*youngLoad)&&!entries.at(*youngLoad).response) {
                    check(BOUND_HEAD_STORE_OVERLAP,"OLD admitted store beside live early owner");
                    check(protectedProofs.count(t)&&oldDataReady&&e.start>=oldDataReady,"overlap lost bound proof or data-ready authority");
                    check(dut.get_io$$b2Accepted()&&dut.get_io$$lsuIdleMask(),"B2 did not use an actual pre-edge idle slot");
                    ++b2IdleStarts;
                    ++overlappedStarts;overlapCapture=cycle;
                }
            }
            e.frozen=dut.get_io$$lsuFrozen$$valid();
            uint64_t observedFrozenPa=e.frozen?dut.get_io$$lsuFrozen$$bits$$physicalAddress():0;
            if(e.frozen&&injectFrozenPa){observedFrozenPa^=1ULL<<32;++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';}
            if(e.frozen)check(protectedProofs.count(t)&&observedFrozenPa==protectedProofs.at(t).physical&&observedFrozenPa==e.pa&&
                dut.get_io$$lsuFrozen$$bits$$address()==e.address&&dut.get_io$$lsuFrozen$$bits$$mask()==lanes(e.pa,e.size),
                "bound store failed frozen physical handoff");
            if(!e.store) {
                unsigned needed=0;
                for(auto older:live){
                    if(older==t)break;
                    const auto &store=entries.at(older);
                    if(!store.store||store.started||store.killed)continue;
                    ++needed;
                    // All directed stores share the observed DIVU rs2 producer. Head
                    // priority belongs to each still-unaccepted store, not a former
                    // pending owner that already transferred to its actual LSU slot.
                    if(oldDataReady)check(oldStore&&store.rs2==entries.at(*oldStore).rs2,
                        "directed readiness witness no longer shares the known producer");
                    if(oldDataReady&&preHead&&*preHead==older)
                        check(false,"ready unaccepted head store was bypassed");
                    check(PENDING_STORE_ENABLED&&currentProofs.count(older),"early load lacks every older unaccepted-store proof");
                    const auto proof=currentProofs.at(older);
                    check(disjoint(proof,{t,uint32_t(dut.get_io$$epoch()),e.address,e.pa,false,e.size,lanes(e.pa,e.size)}),
                        "overlapping physical byte interval bypassed old store");
                    protectedProofs[older]=proof;
                }
                if(needed){
                    check(e.prechecked&&!readyOldHead,"early start bypassed actual ready oldest store");
                    check(expectedCredits.size()<EARLY_LOAD_CREDITS,"third early load acquired occupied credit bank");
                    earlyThisCycle=t;seenEarly.insert(t);++earlyStarts;maxNeededProofs=std::max(maxNeededProofs,needed);
                    if(oldDataReady){check(PENDING_READY_STORE_BYPASS&&preHead,
                        "ready nonhead store bypass lacks enabled policy");++readyEarlyStarts;if(!firstReadyEarly)firstReadyEarly=cycle;}
                }
            }
        }
        if(dut.get_io$$canonicalChecked$$valid()) {
            Token t{unsigned(dut.get_io$$canonicalChecked$$bits$$origin$$token$$index()),uint64_t(dut.get_io$$canonicalChecked$$bits$$origin$$token$$tag())};
            check(entries.count(t)&&entries.at(t).store&&entries.at(t).started,"actual checked callback missing store owner");
            auto&e=entries.at(t);check(!e.checked&&dut.get_io$$canonicalChecked$$bits$$virtualAddress()==e.address&&
                dut.get_io$$canonicalChecked$$bits$$physicalAddress()==e.pa&&dut.get_io$$canonicalChecked$$bits$$mask()==lanes(e.pa,e.size),
                "actual checked callback tuple mismatch");e.checked=cycle;++checkedStores;
        }
        if(injectLocalAck&&oldStore&&entries.at(*oldStore).started&&!entries.at(*oldStore).response) {
            ++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';const auto&e=entries.at(*oldStore);observeRetirement(*oldStore,e.inst.pc,e.inst.word,e.expected);
        }
        if(dut.get_io$$lsuRequestFire()) {
            check(dut.get_io$$lsuRequestOwner$$valid(),"accepted LSU request missing exact owner");
            Token t{unsigned(dut.get_io$$lsuRequestOwner$$bits$$index()),uint64_t(dut.get_io$$lsuRequestOwner$$bits$$tag())};
            check(entries.count(t)&&entries.at(t).started,"LSU accepted request lacks prior start");requests.push_back(t);
        }
        if(response&&dut.get_io$$physical$$response$$ready()) {
            auto r=replies.front();replies.pop_front();
            check(physicalHandles.count(r.handle)&&physicalHandles.at(r.handle)==r.token,"response lost exact physical return handle");
            physicalHandles.erase(r.handle);
            auto &e=entries.at(r.token);e.response=cycle;++responseCount;
            if(e.store&&!r.error)actual.write(e.pa,e.data,e.size);
            if(youngLoad&&r.token==*youngLoad)earlyReadDrain=cycle;
        }
        const bool pv=dut.get_io$$physical$$request$$valid();
        if(pv) {
            Held now{uint64_t(dut.get_io$$physical$$request$$bits$$address()),uint64_t(dut.get_io$$physical$$request$$bits$$data()),
                unsigned(dut.get_io$$physical$$request$$bits$$size()),unsigned(dut.get_io$$physical$$request$$bits$$mask()),
                bool(dut.get_io$$physical$$request$$bits$$write()),bool(dut.get_io$$physical$$request$$bits$$uncached()),unsigned(dut.get_io$$physical$$request$$bits$$returnHandle())};
            if(heldPhysical)check(now==*heldPhysical,"held physical request changed");heldPhysical=ready?std::nullopt:std::optional{now};holds+=!ready;
            if(ready) {
                check(!requests.empty(),"physical acceptance has no accepted LSU owner");Token t=requests.front();requests.pop_front();auto &e=entries.at(t);
                check(!e.requested,"duplicate physical acceptance");e.requested=true;e.physical=cycle;
                check(std::get<0>(now)==e.pa&&std::get<2>(now)==e.size&&std::get<3>(now)==lanes(e.pa,e.size)&&std::get<4>(now)==e.store,
                    "physical request differs from independent owner/byte oracle");
                if(e.store)check(std::get<1>(now)==(e.data<<((e.pa&7)*8)),"aligned store data mismatch");
                check(!dut.get_io$$physical$$request$$bits$$virtualized()&&!dut.get_io$$physical$$request$$bits$$precheckedLoad(),"private authority leaked to physical boundary");
                const uint64_t data=e.store?0:actual.read(e.pa&~7ULL,3);
                if(injectData){++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';}
                const unsigned handle=std::get<6>(now);
                check(!physicalHandles.count(handle),"physical return handle reused before response");
                check(!(denyStore&&e.store),"PMP-denied store reached physical memory");
                physicalHandles.emplace(handle,t);
                replies.push_back({cycle+latency,data^uint64_t(injectData),t,e.fault,handle});++physicalCount;
                if(oldStore&&!e.store&&!entries.at(*oldStore).started){
                    check(!oldDataReady||e.start<oldDataReady||(PENDING_READY_STORE_BYPASS&&e.start>=readyRelease),
                        "early operation lacked qualified ready-store capture");
                    if(!firstEarlyPhysical)firstEarlyPhysical=cycle;
                }
            }
        } else {check(!heldPhysical,"held physical VALID withdrawn");}
        std::set<Token> actualLive;
#define LIVE(N) \
        if(dut.get_io$$lsuOwner##N##$$valid())actualLive.insert({unsigned(dut.get_io$$lsuOwner##N##$$bits$$index()),uint64_t(dut.get_io$$lsuOwner##N##$$bits$$tag())})
        LIVE(0);LIVE(1);LIVE(2);LIVE(3);
        for(auto t:previousLive)if(!actualLive.count(t)){
            auto&e=entries.at(t);e.released=cycle;
            check(e.response||!e.requested,"accepted response owner released before held response drain");
        }
        if(overlapCapture&&cycle==overlapCapture+1)check(oldStore&&youngLoad&&actualLive.count(*oldStore)&&actualLive.count(*youngLoad),
            "NEW overlap did not preserve two distinct captured owners");
        previousLive=actualLive;
#undef LIVE
        std::set<Token> observedCredits;
        const unsigned activeMask=dut.get_io$$creditActiveMask();
        check(!dut.get_io$$creditReservedMask(),"backend unexpectedly retains uncaptured reservation");
        if(activeMask&1)observedCredits.insert({unsigned(dut.get_io$$creditOwner$$index()),uint64_t(dut.get_io$$creditOwner$$tag())});
        if(activeMask&2)observedCredits.insert({unsigned(dut.get_io$$creditOwnerSecond$$index()),uint64_t(dut.get_io$$creditOwnerSecond$$tag())});
        check(observedCredits==expectedCredits,"credit lifetime differs from exact accepted LSU obligation set");
        check(observedCredits.size()<=EARLY_LOAD_CREDITS,"credit capacity exceeded");
        peakCredit=std::max(peakCredit,unsigned(observedCredits.size()));twoCreditCycles+=observedCredits.size()==2;
        activeCreditCycles+=observedCredits.size();
        for(auto t:observedCredits){
            check(entries.count(t)&&entries.at(t).started&&!entries.at(t).store,"credit lacks actual accepted load owner");
            if(!actualLive.count(t)){expectedCredits.erase(t);++creditReturns;}
        }
        if(earlyThisCycle){check(observedCredits.size()<EARLY_LOAD_CREDITS,"accepted start borrowed same-edge reclaimed credit");expectedCredits.insert(*earlyThisCycle);}
#define COMPLETE(N) \
        if(dut.get_io$$issued##N##$$valid()) { \
            Token t{unsigned(dut.get_io$$issued##N##$$bits$$token$$index()),uint64_t(dut.get_io$$issued##N##$$bits$$token$$tag())}; \
            check(entries.count(t)&&!entries.at(t).killed,"completion for nonexistent/killed full token"); \
            auto &e=entries.at(t);check(completionTokens.insert(t).second,"duplicate completion");e.completed=true;e.complete=cycle; \
            if(e.memory)check(bool(dut.get_io$$issued##N##$$bits$$exception())==e.fault && \
                (!e.fault || (dut.get_io$$issued##N##$$bits$$cause()==(e.store?7:5) && dut.get_io$$issued##N##$$bits$$tval()==e.address)), \
                "physical error lost exact completion cause/original VA"); \
            if(e.writes&&!e.fault)check(dut.get_io$$issued##N##$$bits$$data()==e.expected,"independent execution data mismatch"); \
        }
        COMPLETE(0);COMPLETE(1);
#undef COMPLETE
        if(denyStore&&oldStore&&entries.at(*oldStore).completed&&!entries.at(*oldStore).requested){
            auto at=std::find(requests.begin(),requests.end(),*oldStore);
            if(at!=requests.end()) requests.erase(at);
        }
        if(dut.get_io$$redirect$$valid() && !dut.get_io$$trap$$valid()) {
            ++recoveryEdges;
            if(youngLoad&&previousLive.count(*youngLoad)&&!entries.at(*youngLoad).response)++recoveryWithLiveRead;
            check(!dut.get_io$$lsuStart(),"same-edge decoded branch recovery admitted a memory start");
            Token t{unsigned(dut.get_io$$redirect$$bits$$token$$index()),uint64_t(dut.get_io$$redirect$$bits$$token$$tag())};
            check(entries.count(t),"redirect has no exact decoded owner");const auto&e=entries.at(t);
            if(e.branch) {
                check(dut.get_io$$redirect$$bits$$target()==e.expected,"real taken branch target differs from instruction oracle");
                auto at=std::find(live.begin(),live.end(),t);check(at!=live.end(),"branch redirect owner is not live");
                for(auto i=at+1;i!=live.end();++i){entries.at(*i).killed=true;++killCount;}live.erase(at+1,live.end());
                predicted=architectural;for(auto k:live){const auto&keep=entries.at(k);if(keep.writes&&keep.rd)predicted[keep.rd]=keep.expected;}
            }
        }
#define COMMIT(N) \
        if(dut.get_io$$commit##N##$$valid()) { \
            Token t{unsigned(dut.get_io$$commit##N##$$bits$$token$$index()),uint64_t(dut.get_io$$commit##N##$$bits$$token$$tag())}; \
            observeRetirement(t,dut.get_io$$commit##N##$$bits$$pc(),dut.get_io$$commit##N##$$bits$$instruction(),dut.get_io$$commit##N##$$bits$$data()); \
        }
        COMMIT(0);COMMIT(1);
#undef COMMIT
        if(dut.get_io$$recoveryAccepted() && recover) {
            check(recover.has_value(),"unexpected external recovery acceptance");auto at=std::find(live.begin(),live.end(),*recover);
            check(at!=live.end(),"recovery boundary not live");for(auto i=at;i!=live.end();++i){entries.at(*i).killed=true;++killCount;}live.erase(at,live.end());
            predicted=architectural;for(auto t:live){const auto&e=entries.at(t);if(e.writes&&e.rd)predicted[e.rd]=e.expected;}
        }
        if(dut.get_io$$trap$$valid()) {
            check(!live.empty(),"trap without owner");Token t{unsigned(dut.get_io$$trap$$bits$$token$$index()),uint64_t(dut.get_io$$trap$$bits$$token$$tag())};
            const auto&e=entries.at(live.front());check(t==live.front()&&e.fault&&dut.get_io$$trap$$bits$$cause()==(e.store?7:5)&&dut.get_io$$trap$$bits$$tval()==e.address,
                "late memory fault lost exact owner/cause/original VA");
            for(auto k:live){entries.at(k).killed=true;++killCount;}live.clear();predicted=architectural;++traps;
        }
        if(injectRetire&&youngLoad&&entries.at(*youngLoad).killed) {
            ++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';
            const auto&e=entries.at(*youngLoad);
            observeRetirement(*youngLoad,e.inst.pc,e.inst.word,e.expected);
        }
        ++cycle;return allocated;
    }
    std::vector<Token> submit(const std::vector<uint32_t>&words) {
        std::vector<Instruction> program;for(auto w:words){program.push_back({w,nextPc});nextPc+=4;}
        std::vector<Token> result;unsigned cursor=0;
        for(unsigned n=0;n<4096&&cursor<program.size();++n){std::array<std::optional<Instruction>,2> in{};in[0]=program[cursor];if(cursor+1<program.size())in[1]=program[cursor+1];
            auto got=tick(in);cursor+=got.size();result.insert(result.end(),got.begin(),got.end());}
        check(cursor==program.size(),"bounded instruction admission timeout");return result;
    }
    void wait(unsigned n){while(n--)tick();}
    void drain(){for(unsigned n=0;n<4096&&(!live.empty()||!requests.empty()||!replies.empty()||!ptes.empty());++n)tick();
        check(live.empty()&&requests.empty()&&replies.empty()&&ptes.empty(),"bounded pipeline drain timeout");wait(12);
        check(dut.get_io$$idle()&&physicalCount==responseCount,"idle/response accounting mismatch");
        for(const auto&[address,byte]:expected.changed){auto it=actual.changed.find(address);check(it!=actual.changed.end()&&it->second==byte,"final independent byte memory mismatch");}}
    void one(uint32_t w){submit({w});drain();}
    void constant(unsigned rd,uint64_t value){std::vector<uint32_t>w{imm(rd,0,int(value>>55))};for(int n=44;n>=0;n-=11){w.push_back(shift(rd,11));w.push_back(imm(rd,rd,int((value>>n)&2047)));}submit(w);drain();}
    void csr(unsigned n,uint64_t value){constant(31,value);one(n<<20|31<<15|1<<12|0x73);}
    void configure(){csr(0x3b0,allPmp);csr(0x3a0,0x1f);csr(0x180,satp);csr(0x300,(1ULL<<17)|(1ULL<<11));
        check(dut.get_io$$vm$$satp()==satp&&dut.get_io$$vm$$dataPrivilege()==1,"real CSR VM setup failed");
        constant(10,va);constant(11,va+4096);constant(12,va+8192);constant(25,0xfedcba987654321ULL);constant(26,7);constant(30,0x1122334455667788ULL);}
    void warm(){one(st(10,30));one(ld(5,11));one(ld(6,12));}
    void workload(unsigned loadBase=11,int loadOffset=0,unsigned storeSize=3,unsigned loadSize=3,bool twice=false,unsigned branchKind=0){
        oldDataReady=proofCycle=firstEarlyPhysical=earlyReadDrain=0;boundProof.reset();
        std::vector<uint32_t> words{divu(30,25,26)};
        if(branchKind==2)words.push_back(beq(30));
        words.push_back(st(10,30,0,storeSize));
        if(branchKind==1)words.push_back(beq(30));
        words.push_back(ld(20,loadBase,loadOffset,loadSize));
        auto t=submit(words);
        oldStore=t[branchKind==2?2:1];youngLoad=t.back();if(twice)secondLoad=submit({ld(21,11,16)})[0];}
    void dualWorkload(unsigned branchKind=0,bool includeThird=true) {
        oldDataReady=proofCycle=firstEarlyPhysical=earlyReadDrain=0;boundProof.reset();
        std::vector<uint32_t> words{divu(30,25,26)};
        if(branchKind==2)words.push_back(beq(30));
        const unsigned s0=words.size();words.push_back(st(10,30));
        const unsigned s1=words.size();words.push_back(st(10,30,8));
        if(branchKind==1)words.push_back(beq(30));
        const unsigned l0=words.size();words.push_back(ld(20,11));words.push_back(ld(21,11,16));
        if(includeThird)words.push_back(ld(22,11,32));
        auto tokens=submit(words);oldStore=tokens[s0];secondStore=tokens[s1];youngLoad=tokens[l0];secondLoad=tokens[l0+1];
        if(includeThird)thirdLoad=tokens[l0+2];
    }
    void readySpareWorkload() {
        commitEnable=false;auto tokens=submit({divu(30,25,26),st(10,30),ld(20,11),ld(21,11,16)});
        oldStore=tokens[1];youngLoad=tokens[2];secondLoad=tokens[3];
        for(unsigned n=0;n<300&&!(oldDataReady&&proofCycle);++n)tick();
        check(oldDataReady&&proofCycle&&!entries.at(*oldStore).started&&!entries.at(*youngLoad).started,
            "ready-spare setup lacked a retained proof and blocked real capture");
        readyRelease=cycle;commitEnable=true;
    }
    void freshReady(unsigned loadBase=11,int offset=0,unsigned storeSize=3,unsigned loadSize=3) {
        oldDataReady=proofCycle=firstEarlyPhysical=earlyReadDrain=0;boundProof.reset();
        // Store data is already committed x30; DIVU writes independent x29.
        auto t=submit({divu(29,25,26),st(10,30,0,storeSize)});
        oldStore=t[1];trackingFresh=true;freshStart=cycle;readyRelease=cycle;
        for(unsigned n=0;n<16&&!(dut.get_io$$probePending()&&dut.get_io$$probeDataReady()&&dut.get_io$$probeAddressKnown());++n)tick();
        check(dut.get_io$$probePending()&&dut.get_io$$probeDataReady()&&dut.get_io$$probeAddressKnown(),"fresh setup failed ready known-address store");
        check(dut.get_io$$actualHead()!=oldStore->index,"fresh setup missed nonhead window");
        check(!(dut.get_io$$presentOwners()&(1u<<oldStore->index))&&!currentProofs.count(*oldStore),"fresh setup already retained proof");
        youngLoad=submit({ld(20,loadBase,offset,loadSize)})[0];
    }
    void freshWitness(bool canBypass) {
        check(freshWindows>0,"fresh ready-nonhead absent-proof opportunity not exercised");
        check(oldStore&&youngLoad,"fresh case missing exact tokens");
        const auto&s=entries.at(*oldStore);const auto&l=entries.at(*youngLoad);
        if(expectedQuery){
            check(freshAdmissions&&freshWrites,"ON fresh query path not exercised");
            if(!denyStore)check(proofHistory.count(*oldStore),"ON fresh proof never captured");
        } else check(!freshAdmissions&&!freshWrites&&!proofHistory.count(*oldStore),"OFF acquired ready-only pending proof");
        if(expectedQuery&&canBypass){check(readyEarlyStarts&&seenEarly.count(*youngLoad)&&l.start<s.start,"ON fresh proof did not enable early accepted load");}
        else check(!seenEarly.count(*youngLoad),"veto case admitted early load");
        if(denyStore)check(traps==1&&!s.requested&&!s.retired&&!l.retired&&!proofHistory.count(*oldStore),"PMP deny lost precise no-physical/no-younger effect");
        else check(s.retired&&l.retired&&s.response&&l.response,"fresh owners did not finish actual responses and retirement");
        std::cout<<"READY_QUERY77_WITNESS enabled="<<expectedQuery<<" opportunities="<<freshWindows<<" admissions="<<freshAdmissions
            <<" write_queries="<<freshWrites<<" early="<<readyEarlyStarts<<" head_veto="<<headVetoCycles<<'\n';
    }
    void readyHead() {
        // A store placed at head cannot use the nonhead early-address preparation.
        // Prepare it legally behind an independent blocked-retirement DIVU first.
        commitEnable=false;
        const auto owners=submit({divu(29,25,26),st(10,30)});
        const Token blocker=owners[0];oldStore=owners[1];trackingFresh=true;
        for(unsigned n=0;n<200&&!(entries.at(blocker).completed&&dut.get_io$$probePending()&&
            dut.get_io$$probeDataReady()&&dut.get_io$$probeAddressKnown()&&dut.get_io$$probeOwnerValid());++n)tick();
        check(entries.at(blocker).completed&&!entries.at(blocker).retired,
            "ready-head setup failed completed unretired DIVU blocker");
        check(dut.get_io$$probePending()&&dut.get_io$$probeDataReady()&&dut.get_io$$probeAddressKnown()&&dut.get_io$$probeOwnerValid(),
            "ready-head setup failed nonhead ready known-address owner");
        // Settle existing completion/retirement registers before introducing any load.
        wait(4);
        check(dut.get_io$$actualHead()==blocker.index&&dut.get_io$$probeToken$$index()==oldStore->index&&
            dut.get_io$$probeToken$$tag()==oldStore->tag&&!dut.get_io$$probeAtHead()&&!entries.at(*oldStore).started,
            "ready-head setup lost exact nonhead unaccepted store");
        check(!(dut.get_io$$presentOwners()&(1u<<oldStore->index))&&dut.get_io$$bankEmpty()&&
            dut.get_io$$creditAvailable()&&!freshAdmissions&&!freshWrites&&!proofHistory.count(*oldStore),
            "ready-head setup lacked absent proof and free capacities");
        trackingHeadTransition=true;
        // submit returns on rename. No intervening tick: the one commit pulse is
        // intended to retire the blocker while the registered memory stage captures
        // this load. A missed alignment must fail, not relax the selected-load gate.
        youngLoad=submit({ld(20,11)})[0];
        check(!freshAdmissions&&!freshWrites&&!proofHistory.count(*oldStore),
            "ready-head setup queried store before head-transition pulse");
        commitEnable=true;tick();commitEnable=false;
        check(entries.at(blocker).retired&&!entries.at(*oldStore).started,
            "ready-head pulse failed exact blocker retirement or captured store");
        wait(4);
        check(selectedReadyHeadWindows>0&&headVetoCycles&&!freshAdmissions&&!freshWrites&&!proofHistory.count(*oldStore),
            "ready head selected-load missing-proof query veto not exercised");
        check(!entries.at(*youngLoad).started,"commit-disabled head case admitted load");
        trackingHeadTransition=false;commitEnable=true;drain();
        check(entries.at(*oldStore).retired&&entries.at(*youngLoad).retired&&!seenEarly.count(*youngLoad),"ready head failed progress or allowed bypass");
        std::cout<<"READY_QUERY77_HEAD_WITNESS selected_windows="<<selectedReadyHeadWindows
            <<" ready_head_cycles="<<headVetoCycles<<" admissions="<<freshAdmissions<<" write_queries="<<freshWrites<<'\n';
    }
    void dualWitness(bool fault=false,bool killedStores=false) {
        check(oldStore&&secondStore&&youngLoad&&secondLoad,"missing dual fixture owners");
        const auto&s=entries.at(*oldStore);const auto&s2=entries.at(*secondStore);
        const auto&l=entries.at(*youngLoad);const auto&l2=entries.at(*secondLoad);
        check(peakCredit==2&&twoCreditCycles&&twoProofCycles&&twoBoundCycles&&maxNeededProofs==2,
            "missing real two-owner/two-protected-proof witness");
        check(earlyStarts>=2&&seenEarly.count(*youngLoad)&&seenEarly.count(*secondLoad),"two legal early loads not observed");
        check(l.requested&&l2.requested&&((oldDataReady&&l.start<oldDataReady&&l2.start<oldDataReady)||killedStores),
            "both early owners did not precede store data-ready or older redirect");
        check(l.response&&l2.response&&creditReturns==earlyStarts&&expectedCredits.empty(),"two accepted reads did not drain exact response obligations");
        if(killedStores)check(s.killed&&s2.killed&&!s.started&&!s2.started,"older redirect failed to kill both unaccepted stores");
        else {
            check(s.frozen&&s.start<l.response&&s.start<l2.response&&b2IdleStarts,
                "actual oldest frozen B2 store did not capture idle slot beside two accepted loads");
            if(!fault)check(s.retired&&s2.retired&&s2.frozen&&s.retire<=s2.retire,"two protected stores lost precise ordered retirement");
        }
        if(thirdLoad){const auto&third=entries.at(*thirdLoad);
            check(third.started?third.start>std::min(l.released,l2.released):third.killed,
                "third load started before the conservative released-credit boundary");}
        std::cout<<"DUAL_BACKEND_WITNESS early="<<earlyStarts<<" peak_credit="<<peakCredit
            <<" two_proof_cycles="<<twoProofCycles<<" two_bound_cycles="<<twoBoundCycles<<" two_credit_cycles="<<twoCreditCycles
            <<" store_start="<<s.start<<" load0_start="<<l.start<<" load1_start="<<l2.start
            <<" load0_response="<<l.response<<" load1_response="<<l2.response
            <<" idle_b2="<<b2IdleStarts<<" credit_returns="<<creditReturns<<'\n';
    }
};
int main(int argc,char**argv){try{
    std::cout.setf(std::ios::unitbuf);
    require(argc>=2&&argc<=3,"usage: host on|off [--mutate-proof-pa|--mutate-eligibility|--mutate-data|--mutate-frozen-pa]");
    const std::string arm=argv[1],mode=argc==3?argv[2]:"";
    require(arm=="on"||arm=="off","invalid arm");
    require(mode.empty()||mode=="--mutate-proof-pa"||mode=="--mutate-eligibility"||mode=="--mutate-data"||mode=="--mutate-frozen-pa","invalid negative control");
    const bool on=arm=="on";
    {Bench b;b.expectedQuery=on;b.configure();b.warm();b.latency=100;
      b.injectProofPa=mode=="--mutate-proof-pa";b.injectEligibility=mode=="--mutate-eligibility";
      b.injectData=mode=="--mutate-data";b.injectFrozenPa=mode=="--mutate-frozen-pa";
      b.freshReady();b.drain();b.freshWitness(true);
      require(mode.empty(),"negative control failed to reach its expected failure");
      std::cout<<"READY_QUERY77_CASE fresh_ready_nonhead_missing_proof\n";}
    for(unsigned which=0;which<4;++which){Bench b;b.expectedQuery=on;b.configure();b.warm();
      if(which==0)b.freshReady(12); // distinct VA, exact same PA
      if(which==1)b.freshReady(10,4,2,2);
      if(which==2)b.freshReady(10,2,2,1);
      if(which==3)b.freshReady(10,1,0,0);
      b.drain();b.freshWitness(which==1||which==3);
      std::cout<<"READY_QUERY77_CASE byte_interval_"<<which<<'\n';}
    {Bench b;b.expectedQuery=on;b.configure();b.warm();b.readyHead();
      std::cout<<"READY_QUERY77_CASE ready_head_missing_proof_veto_progress\n";}
    {Bench b;b.expectedQuery=on;b.configure();b.warm();const auto oldEpoch=b.dut.get_io$$epoch();
      b.csr(0x3a0,0x1b);b.csr(0x3a0,0x1f);
      require(b.dut.get_io$$epoch()!=oldEpoch,"real published PMP change failed epoch advance");
      b.warm();b.freshReady();b.drain();b.freshWitness(true);
      require(b.proofHistory.empty()||b.proofHistory.at(*b.oldStore).epoch==b.dut.get_io$$epoch(),"post-context proof retained old epoch");
      std::cout<<"READY_QUERY77_CASE published_pmp_epoch_requery\n";}
    {Bench b;b.expectedQuery=on;b.configure();b.warm();b.csr(0x3a0,0x19);
      b.denyStore=true;b.faultStore=true;b.freshReady();b.drain();b.freshWitness(false);
      std::cout<<"READY_QUERY77_CASE write_pmp_deny_precise_fault\n";}
    std::cout<<"READY_QUERY77_PASS arm="<<arm<<" scope=actual_backend_component\n";return 0;
}catch(const std::exception&e){std::cerr<<"READY_QUERY77_FAIL "<<e.what()<<'\n';return 1;}}
