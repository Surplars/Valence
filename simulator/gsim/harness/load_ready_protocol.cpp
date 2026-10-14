#include "LoadReadyProtocolGsim.h"
#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <iostream>
#include <memory>
#include <new>
#include <optional>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>
#include <map>
namespace {
struct Token { unsigned index=0; uint64_t tag=0; bool operator==(const Token&) const=default; };
struct Op {
    Token token{}; unsigned dest=0,size=3,atomicOp=2,slot=9;
    uint64_t address=0x80010000ULL,data=0,beat=0x87fedcba98765480ULL,pc=0x80000000ULL;
    bool writes=true,store=false,atomic=false,unsign=false,denied=false,forward=false,parallel=true;
    bool fault()const{return (address & ((1U<<size)-1)) || denied || (atomic && (address<0x80010000ULL || address+(1U<<size)>0x80011000ULL));}
    bool ordinary()const{return !store && !atomic;}
};
using Ptr=std::shared_ptr<Op>;
struct Slot { Ptr op; unsigned phase=0; bool cancelled=false,exception=false; uint64_t result=0; };
struct Row { bool active=false,execution=true,ignored1=false,ignored2=false; unsigned s1=0,s2=0; bool r1=false,r2=false; };
struct Allocation { bool valid=false,execution=true; unsigned row=0; std::array<std::array<unsigned,2>,2> source{}; };
struct In {
    Ptr start; bool requestReady=true,sinkReady=false,response=false,error=false,page=false; uint64_t beat=0;
    unsigned cancel=0,faults=0; std::array<Allocation,2> alloc{};
    std::array<std::optional<unsigned>,2> reserve{};
    bool external=false; unsigned address=0; uint64_t data=0;
    std::array<unsigned,4> read{0,33,34,47};
};
struct Result { Token token; uint64_t data=0; bool exception=false; };
struct Out {
    bool startReady=false,requestValid=false,responseReady=false,completeValid=false,write=false,completeDestValid=false;
    unsigned slotStart=0,slotRequest=0,slotResponse=0,slotComplete=0,slotValid=0,capture=0,publish=0,held=0;
    unsigned ready1=0,ready2=0,direct1=0,direct2=0,ar1=0,ar2=0,writeAddress=0,completeDest=0;
    uint64_t physical=0,writeData=0,requestAddress=0; unsigned requestSize=0; bool requestStore=false,requestAtomic=false;
    Result complete; std::array<unsigned,4> phase{},pubDest{},heldDest{};
    std::array<Token,4> owner{}; std::array<Result,4> result{}; std::array<uint64_t,4> heldData{},read{};
};
uint64_t extract(uint64_t beat,const Op&op){unsigned n=8U<<op.size;uint64_t shifted=beat>>((op.address&7)*8);if(n==64)return shifted;uint64_t v=shifted&((1ULL<<n)-1);return !op.unsign && (v>>(n-1)) ? v|(~0ULL<<n) : v;}
void require(bool ok,const std::string&why){if(!ok)throw std::runtime_error(why);}
class Bench {
    alignas(SLoadReadyProtocolGsim) std::byte storage[sizeof(SLoadReadyProtocolGsim)]{};
    SLoadReadyProtocolGsim &d;
    std::array<Slot,4> slots{}; std::deque<unsigned> owed;
    std::array<Row,16> rows{}; uint64_t physical=1; std::array<uint64_t,48> prf{};
    unsigned next=1; bool injected=false; std::string mutation;
    void check(bool ok,const std::string&why){require(ok,"cycle="+std::to_string(cycle)+" "+why);}
    void inject(const std::string&name,bool reach,auto action){if(!injected && mutation==name && reach){injected=true;std::cout<<"REACHED_NEGATIVE "<<name<<" cycle="<<cycle<<std::endl;action();}}
public:
    const bool enabled; unsigned cycle=0; std::map<std::string,unsigned> count;
    Bench(bool on,std::string mut):d(*::new(static_cast<void*>(storage)) SLoadReadyProtocolGsim),mutation(mut),enabled(on){
        static_assert(std::is_trivially_copyable_v<SLoadReadyProtocolGsim>);
        d.LOG_START=1;d.activateAll();drive({});d.set_reset(1);d.step();d.resetAll();d.step();d.resetAll();d.activateAll();d.set_reset(0);
    }
    ~Bench(){d.~SLoadReadyProtocolGsim();}
    Ptr op(unsigned dest=33,unsigned size=3){auto p=std::make_shared<Op>();p->dest=dest;p->size=size;p->token={next%16,0xfedcba9800000000ULL+next};p->address+=((next*16)%4000)+(size==0?3:size==1?2:size==2?4:0);p->beat^=uint64_t(next)*0x0101010101010101ULL;++next;return p;}
    void clearRows(){for(auto&r:rows)r.active=false;}
    void inactive(unsigned r){rows[r].active=false;}
    void ignored(unsigned r,bool a,bool b){rows[r].ignored1=a;rows[r].ignored2=b;}
    void drive(const In &in){
        const Op z{};const auto&s=in.start?*in.start:z;
        d.set_io$$start$$valid(bool(in.start));d.set_io$$start$$bits$$forward$$valid(s.forward);d.set_io$$start$$bits$$forward$$bits(s.beat);
        d.set_io$$start$$bits$$token$$index(s.token.index);d.set_io$$start$$bits$$token$$tag(s.token.tag);d.set_io$$start$$bits$$pc(s.pc);
        d.set_io$$start$$bits$$address(s.address);d.set_io$$start$$bits$$data(s.data);d.set_io$$start$$bits$$atomic(s.atomic);d.set_io$$start$$bits$$atomicOp(s.atomicOp);
        d.set_io$$start$$bits$$store(s.store);d.set_io$$start$$bits$$size(s.size);d.set_io$$start$$bits$$unsigned(s.unsign);d.set_io$$start$$bits$$accessDenied(s.denied);
        d.set_io$$start$$bits$$virtualized(0);d.set_io$$start$$bits$$precheckedLoad(0);d.set_io$$start$$bits$$physicalAddress(s.address);d.set_io$$start$$bits$$translationEpoch(0);
        d.set_io$$destination$$valid(s.writes);d.set_io$$destination$$bits(s.dest);d.set_io$$parallel(s.parallel);
        d.set_io$$memory$$request$$ready(in.requestReady);d.set_io$$memory$$response$$valid(in.response);d.set_io$$memory$$response$$bits$$data(in.beat);
        d.set_io$$memory$$response$$bits$$error(in.error);d.set_io$$memory$$response$$bits$$pageFault(in.page);d.set_io$$sinkReady(in.sinkReady);d.set_io$$cancel(in.cancel);
        unsigned active=0,execution=0;for(unsigned i=0;i<16;++i){active|=unsigned(rows[i].active)<<i;execution|=unsigned(rows[i].execution)<<i;}
        d.set_io$$active(active);d.set_io$$execution(execution);d.set_io$$faults(in.faults);
        d.set_io$$incomingExecution(unsigned(in.alloc[0].execution)|(unsigned(in.alloc[1].execution)<<1));
#define ROW(N) d.set_io$$sources1##N(rows[N].s1);d.set_io$$sources2##N(rows[N].s2);
        ROW(0) ROW(1) ROW(2) ROW(3) ROW(4) ROW(5) ROW(6) ROW(7) ROW(8) ROW(9) ROW(10) ROW(11) ROW(12) ROW(13) ROW(14) ROW(15)
#undef ROW
#define ALLOC(N) d.set_io$$allocate##N##$$valid(in.alloc[N].valid);d.set_io$$allocate##N##$$bits(in.alloc[N].row); d.set_io$$reserve##N##$$valid(in.reserve[N].has_value());d.set_io$$reserve##N##$$bits(in.reserve[N].value_or(0));
        ALLOC(0) ALLOC(1)
#undef ALLOC
#define CAND(L,A) d.set_io$$candidate##L##A##$$source1(in.alloc[L].source[A][0]);d.set_io$$candidate##L##A##$$source2(in.alloc[L].source[A][1]);
        CAND(0,0) CAND(0,1) CAND(1,0) CAND(1,1)
#undef CAND
        d.set_io$$externalWrite$$valid(in.external);d.set_io$$externalWrite$$bits$$address(in.address);d.set_io$$externalWrite$$bits$$data(in.data);
#define READ(N) d.set_io$$readAddress##N(in.read[N]);
        READ(0) READ(1) READ(2) READ(3)
#undef READ
    }
    Out sample(){Out o;
        o.startReady=d.get_io$$start$$ready();o.requestValid=d.get_io$$memory$$request$$valid();o.responseReady=d.get_io$$memory$$response$$ready();
        o.requestAddress=d.get_io$$memory$$request$$bits$$address();o.requestSize=d.get_io$$memory$$request$$bits$$size();o.requestStore=d.get_io$$memory$$request$$bits$$write();o.requestAtomic=d.get_io$$memory$$request$$bits$$atomic();
        o.completeValid=d.get_io$$complete$$valid();o.complete={{unsigned(d.get_io$$complete$$bits$$token$$index()),d.get_io$$complete$$bits$$token$$tag()},d.get_io$$complete$$bits$$data(),bool(d.get_io$$complete$$bits$$exception())};
        o.completeDestValid=d.get_io$$completedDestination$$valid();o.completeDest=d.get_io$$completedDestination$$bits();
        o.slotStart=d.get_io$$slotStart();o.slotRequest=d.get_io$$slotRequest();o.slotResponse=d.get_io$$slotResponse();o.slotComplete=d.get_io$$slotComplete();o.slotValid=d.get_io$$slotValid();o.capture=d.get_io$$slotCapture();
        o.publish=d.get_io$$publish();o.held=d.get_io$$held();o.ready1=d.get_io$$ready1();o.ready2=d.get_io$$ready2();o.direct1=d.get_io$$directReady1();o.direct2=d.get_io$$directReady2();
        o.ar1=d.get_io$$allocationReady1();o.ar2=d.get_io$$allocationReady2();o.physical=d.get_io$$physical();o.write=d.get_io$$write$$valid();o.writeAddress=d.get_io$$write$$bits$$address();o.writeData=d.get_io$$write$$bits$$data();
#define SLOT(N) o.phase[N]=d.get_io$$phase##N();o.owner[N]={unsigned(d.get_io$$owner##N##$$index()),d.get_io$$owner##N##$$tag()};o.pubDest[N]=d.get_io$$publishDestination##N();o.heldDest[N]=d.get_io$$heldDestination##N();o.heldData[N]=d.get_io$$heldData##N();o.read[N]=d.get_io$$readData##N();o.result[N]={{unsigned(d.get_io$$slotResult##N##$$token$$index()),d.get_io$$slotResult##N##$$token$$tag()},d.get_io$$slotResult##N##$$data(),bool(d.get_io$$slotResult##N##$$exception())};
        SLOT(0) SLOT(1) SLOT(2) SLOT(3)
#undef SLOT
        return o;
    }
    Out tick(In in={}){
        drive(in);d.step();Out o=sample();
        if(in.start)check(o.startReady,"fixed directed start was not accepted");
        auto old=slots;auto nextSlots=slots;unsigned expectHeld=0,expectValid=0,pub=0,capture=0;
        for(unsigned i=0;i<4;++i){auto&s=old[i];check(o.phase[i]==s.phase,"actual phase != independent accepted-operation phase slot="+std::to_string(i));
            if(s.phase){check(s.op && o.owner[i]==s.op->token,"full64 owner token");}
            bool valid=s.phase==3&&!s.cancelled;expectValid|=unsigned(valid)<<i;
            if(s.phase==3){check(o.result[i].token==s.op->token,"actual next result token");check(o.result[i].exception==s.exception,"actual next result fault");check(o.result[i].data==s.result,"actual next result value");}
            bool h=valid&&!s.exception&&s.op->ordinary()&&s.op->writes&&s.op->dest;
            if(h)expectHeld|=1U<<i;
        }
        inject("holder-value",enabled&&expectHeld,[&]{o.heldData[__builtin_ctz(expectHeld)]^=1;});
        inject("holder-token",expectHeld,[&]{o.owner[__builtin_ctz(expectHeld)].tag^=1ULL<<63;});
        check(o.slotValid==expectValid,"actual completion-valid/cancel priority");check(o.held==(enabled?expectHeld:0),"stable holder validity");
        for(unsigned i=0;i<4;++i)if(expectHeld&(1U<<i)){
            check(o.owner[i]==old[i].op->token,"held full token changed");if(enabled){check(o.heldDest[i]==old[i].op->dest,"held destination");check(o.heldData[i]==old[i].result,"held value");}++count["holder_samples"];
        }
        auto heldMatch=[&](unsigned src){for(unsigned i=0;i<4;++i)if((expectHeld&(1U<<i))&&old[i].op->dest==src)return true;return false;};
        check(o.physical==physical,"physical ready bank");
        for(unsigned i=0;i<4;++i)check(o.read[i]==(in.read[i]<48?prf[in.read[i]]:0),"actual PRF bank data");
        inject("nonordinary-ready",mutation=="nonordinary-ready"&&enabled&&([&]{for(unsigned i=0;i<16;++i)if(rows[i].active&&!rows[i].execution&&!rows[i].r1&&heldMatch(rows[i].s1)){o.ready1|=1U<<i;return true;}return false;}()),[]{});
        for(unsigned i=0;i<16;++i){auto&r=rows[i];check(bool(o.ready1&(1U<<i))==r.r1 && bool(o.ready2&(1U<<i))==r.r2,"registered row-ready source pair");
            check(bool(o.direct1&(1U<<i))==r.r1 && bool(o.direct2&(1U<<i))==r.r2,"direct/precomputed ready source pair");
            if(r.active){check(r.r1==(bool(physical&(1ULL<<r.s1))||(enabled&&r.execution&&heldMatch(r.s1))),"independent exact mirror source1");check(r.r2==(bool(physical&(1ULL<<r.s2))||(enabled&&r.execution&&heldMatch(r.s2))),"independent exact mirror source2");++count["active_both_source_mirror"];count["ignored_source_mirror"]+=r.ignored1+r.ignored2;}
        }
        check(__builtin_popcount(o.slotStart)<=1 && bool(o.slotStart)==bool(in.start&&o.startReady),"accepted start ownership");
        check(__builtin_popcount(o.slotRequest)<=1 && bool(o.slotRequest)==bool(o.requestValid&&in.requestReady),"request ownership");
        check(__builtin_popcount(o.slotResponse)<=1 && bool(o.slotResponse)==bool(in.response&&o.responseReady),"response ownership");
        check(__builtin_popcount(o.slotComplete)<=1 && bool(o.slotComplete)==bool(o.completeValid&&in.sinkReady),"completion arbitration acceptance");
        bool sink=false;unsigned sinkDest=0;uint64_t sinkData=0;
        if(o.completeValid){unsigned s=0;while(s<4&&!(expectValid&(1U<<s)&&old[s].op->token==o.complete.token))++s;check(s<4,"selected complete full token");check(o.complete.data==old[s].result&&o.complete.exception==old[s].exception,"selected actual result");bool wr=!old[s].exception&&old[s].op->ordinary()&&old[s].op->writes&&old[s].op->dest;check(o.completeDestValid==wr,"completion sideband permission");if(wr)check(o.completeDest==old[s].op->dest,"old completion destination pairing");if(in.sinkReady&&wr){sink=true;sinkDest=old[s].op->dest;sinkData=old[s].result;}}
        inject("old-new-cross-pair",sink&&bool(o.slotStart),[&]{o.writeAddress=in.start->dest;o.writeData=in.start->beat;});
        inject("handoff-write",sink,[&]{o.write=false;});
        check(o.write==sink,"protocol sink write valid");if(sink)check(o.writeAddress==sinkDest&&o.writeData==sinkData,"protocol accepted write address/data");
        for(unsigned i=0;i<4;++i){auto&n=nextSlots[i];auto&s=old[i];if(in.cancel&(1U<<i)){if(s.phase){check(s.op->ordinary(),"host cannot cancel irrevocable owner");n.cancelled=true;++count["cancel"];}}
            if(o.slotComplete&(1U<<i)){check(o.complete.token==s.op->token,"selected completion slot");n.phase=0;++count["drain"];}
            if(s.phase==3&&(s.cancelled||bool(in.cancel&(1U<<i))))n.phase=0;
            if(o.slotStart&(1U<<i)){check(s.phase==0||(s.phase==3&&in.sinkReady&&!s.cancelled),"legal replacement");check(bool(in.start),"start without offered op");n.op=in.start;n.op->slot=i;n.cancelled=false;n.exception=n.op->fault();n.result=n.op->forward?extract(n.op->beat,*n.op):0;n.phase=(n.op->fault()||n.op->forward)?3:1;++count["start"];if(s.phase==3)++count["replace"];if(n.op->forward)++count["forwarded"];if(n.exception)++count["static_fault"];}
        }
        if(o.slotRequest){unsigned i=__builtin_ctz(o.slotRequest);auto&n=nextSlots[i];check(n.op&&n.phase==1,"request from accepted owner");check(o.requestAddress==n.op->address&&o.requestSize==n.op->size&&o.requestStore==n.op->store&&o.requestAtomic==n.op->atomic,"independent memory request tuple");n.phase=2;owed.push_back(i);++count["request"];}
        if(o.slotResponse){unsigned i=__builtin_ctz(o.slotResponse);check(!owed.empty()&&owed.front()==i,"ordered actual response owner");owed.pop_front();auto&n=nextSlots[i];check(n.phase==2,"response owes a request");n.phase=3;n.exception=in.error||in.page;n.result=n.op->atomic?in.beat:n.op->store?0:extract(in.beat,*n.op);++count["response"];if(old[i].phase==1)++count["owned_request_response"];if(o.slotStart&(1U<<i))++count["direct_start_response"];if(n.exception)++count["response_fault"];if(n.cancelled)++count["cancelled_response"];}
        for(unsigned i=0;i<4;++i){auto&n=nextSlots[i];bool resultWrite=bool(o.slotResponse&(1U<<i)) || (bool(o.slotStart&(1U<<i))&&n.phase==3);bool good=resultWrite&&n.phase==3&&!n.cancelled&&!n.exception&&n.op->ordinary();if(good)capture|=1U<<i;if(good&&n.op->writes&&n.op->dest)pub|=1U<<i;}
        inject("fault-publication",mutation=="fault-publication"&&enabled&&[&]{for(unsigned i=0;i<4;++i)if((o.slotResponse|o.slotStart)&(1U<<i))if(nextSlots[i].phase==3&&nextSlots[i].exception){o.publish|=1U<<i;return true;}return false;}(),[]{});
        inject("second-publication",enabled&&__builtin_popcount(pub)>=2,[&]{o.publish&=o.publish-1;});
        inject("publication-destination",enabled&&pub,[&]{o.pubDest[__builtin_ctz(pub)]^=1;});
        inject("cancelled-resurrection",mutation=="cancelled-resurrection"&&enabled&&[&]{for(unsigned i=0;i<4;++i)if((o.slotResponse&(1U<<i))&&nextSlots[i].cancelled){o.publish|=1U<<i;return true;}return false;}(),[]{});
        check(o.capture==(enabled?capture:0),"capture vs independent actual next result/phase/token");check(o.publish==(enabled?pub:0),"complete per-slot publication set");
        for(unsigned i=0;i<4;++i)if(pub&(1U<<i)){check(nextSlots[i].op->token==((o.slotStart&(1U<<i))?in.start->token:old[i].op->token),"next publish full owner");if(enabled)check(o.pubDest[i]==nextSlots[i].op->dest,"publication destination pair");++count["publication"];}if(__builtin_popcount(pub)>=2)++count["multi_publication"];
        unsigned heldCount=__builtin_popcount(expectHeld);count["held_occupancy_"+std::to_string(heldCount)]++;if(heldCount&&!in.sinkReady)++count["held_stall"];
        auto pubMatch=[&](unsigned src){for(unsigned i=0;i<4;++i)if((pub&(1U<<i))&&nextSlots[i].op->dest==src)return true;return false;};
        auto reserve=[&](unsigned src){return (in.reserve[0]&&*in.reserve[0]==src)||(in.reserve[1]&&*in.reserve[1]==src);};
        auto wake=[&](unsigned src){return (sink&&sinkDest==src)||(in.external&&in.address==src);};
        auto incoming=[&](unsigned src,bool ex){return (bool(physical&(1ULL<<src))||wake(src)||(enabled&&ex&&(heldMatch(src)||pubMatch(src))))&&!reserve(src);};
        unsigned ar1=0,ar2=0;for(unsigned l=0;l<2;++l){auto&a=in.alloc[l];unsigned alt=l==1&&bool(in.faults&1);unsigned s1=(in.faults&(1U<<l))?0:a.source[alt][0],s2=(in.faults&(1U<<l))?0:a.source[alt][1];bool r1=incoming(s1,a.execution),r2=incoming(s2,a.execution);ar1|=unsigned(r1)<<l;ar2|=unsigned(r2)<<l;
            if(!a.valid&&enabled&&a.execution&&((pubMatch(s1)&&reserve(s1))||(pubMatch(s2)&&reserve(s2))))++count["helper_only_publication_reserve"];
            if(!a.valid)++count["fault_mask_"+std::to_string(in.faults)];
            if(a.valid){if(enabled&&a.execution&&(pubMatch(s1)||pubMatch(s2)))++count["incoming_publication"];if(enabled&&a.execution&&(heldMatch(s1)||heldMatch(s2)))++count["incoming_holder"];if(reserve(s1)||reserve(s2))++count["incoming_reserved"];if(in.faults)++count["fault_alternative"];if(rows[a.row].active&&rows[a.row].execution!=a.execution)++count["class_reuse"];}
        }
        inject("incoming-publication",mutation=="incoming-publication"&&enabled&&pub&&[&]{for(unsigned l=0;l<2;++l)if(in.alloc[l].valid&&(ar1&(1U<<l))&&pubMatch(in.alloc[l].source[0][0])&&!(physical&(1ULL<<in.alloc[l].source[0][0]))){o.ar1&=~(1U<<l);return true;}return false;}(),[]{});
        inject("reserve-loses",mutation=="reserve-loses"&&[&]{for(unsigned l=0;l<2;++l)if(in.alloc[l].valid&&in.alloc[l].source[0][0]&&reserve(in.alloc[l].source[0][0])&&!(ar1&(1U<<l))&&(bool(physical&(1ULL<<in.alloc[l].source[0][0]))||wake(in.alloc[l].source[0][0])||(enabled&&in.alloc[l].execution&&(heldMatch(in.alloc[l].source[0][0])||pubMatch(in.alloc[l].source[0][0]))))){o.ar1|=1U<<l;return true;}return false;}(),[]{});
        check(o.ar1==ar1&&o.ar2==ar2,"fault-selected allocation next readiness");
        for(auto&r:rows)if(r.active){r.r1=(r.r1||wake(r.s1)||(enabled&&r.execution&&pubMatch(r.s1)))&&!reserve(r.s1);r.r2=(r.r2||wake(r.s2)||(enabled&&r.execution&&pubMatch(r.s2)))&&!reserve(r.s2);}
        for(unsigned l=0;l<2;++l){auto&a=in.alloc[l];if(a.valid){auto&r=rows[a.row];unsigned alt=l==1&&bool(in.faults&1);r.active=true;r.execution=a.execution;r.s1=(in.faults&(1U<<l))?0:a.source[alt][0];r.s2=(in.faults&(1U<<l))?0:a.source[alt][1];r.r1=ar1&(1U<<l);r.r2=ar2&(1U<<l);}}
        if(sink){physical|=1ULL<<sinkDest;prf[sinkDest]=sinkData;++count["write"];}
        if(in.external){physical|=1ULL<<in.address;if(in.address)prf[in.address]=in.data;}
        for(auto r:in.reserve)if(r)physical&=~(1ULL<<*r);
        slots=nextSlots;++cycle;d.resetAll();return o;
    }
    void wait(unsigned n){while(n--)tick();}
    void drain(){for(unsigned n=0;n<8;++n){In in;in.sinkReady=true;tick(in);}}
    void done(){tick();check(owed.empty(),"terminal response debt remains");for(const auto&s:slots)check(s.phase==0,"terminal slot remains live");for(const auto*k:{"start","replace","forwarded","static_fault","request","response","owned_request_response","direct_start_response","response_fault","cancelled_response","publication","multi_publication","held_occupancy_0","held_occupancy_1","held_occupancy_2","held_occupancy_3","held_occupancy_4","held_stall","active_both_source_mirror","ignored_source_mirror","incoming_reserved","fault_alternative","class_reuse","write"})check(count[k]>0,std::string("NOT_REACHED ")+k);if(enabled)for(const auto*k:{"incoming_holder","incoming_publication","helper_only_publication_reserve","fault_mask_0","fault_mask_1","fault_mask_2","fault_mask_3"})check(count[k]>0,std::string("NOT_REACHED ")+k);for(const auto&[k,v]:count)std::cout<<"COVER "<<k<<"="<<v<<"\n";check(!injected,"negative returned without oracle rejection");if(!mutation.empty())throw std::runtime_error("NOT_REACHED negative="+mutation);std::cout<<"PASS_LOAD_READY_PROTOCOL enabled="<<enabled<<" cycles="<<cycle<<"\n";}
};
Allocation alloc(unsigned row,unsigned s1,unsigned s2,bool execution=true){Allocation a;a.valid=true;a.row=row;a.execution=execution;a.source[0]={s1,s2};a.source[1]={s2,s1};return a;}
void cases(Bench&b){
    b.tick();
    // Same-edge accepted allocation and delayed publication; both ignored sources stay checked.
    auto a=b.op(33,1);In in;in.start=a;in.reserve[0]=33;in.alloc={alloc(0,33,0),alloc(1,33,33,false)};b.tick(in);b.ignored(0,false,true);b.wait(2);
    in={};in.response=true;in.beat=a->beat;in.alloc={alloc(2,33,33),alloc(3,33,0,false)};b.tick(in);b.ignored(2,true,true);b.wait(4);
    // All raw fault-selection alternatives are independent combinational probes, with no allocation.
    for(unsigned mask=0;mask<4;++mask){in={};in.faults=mask;in.alloc={alloc(0,33,47),alloc(0,47,33)};in.alloc[0].valid=false;in.alloc[1].valid=false;in.alloc[1].source[1]={33,0};b.tick(in);}
    in={};in.alloc={alloc(4,33,0),alloc(5,47,33)};in.faults=1;in.alloc[1].source[1]={33,0};b.tick(in);b.wait(2);
    in={};in.alloc={alloc(0,33,33,false),alloc(1,33,33,true)};b.tick(in);b.wait(2);
    // Drain handoff and old/new destination pairing; old consumers survive by the actual PRF sink.
    auto repl=b.op(34,0);repl->forward=true;in={};in.sinkReady=true;in.start=repl;in.alloc={alloc(6,33,34),alloc(7,34,33)};b.tick(in);b.wait(2);b.drain();b.clearRows();
    // Four accepted requests/owners, response+different-slot forwarded start create two publications.
    auto x=b.op(35),y=b.op(36,2),z=b.op(37,0),f=b.op(38,1);f->forward=true;
    for(auto p:{x,y,z}){in={};in.start=p;in.reserve[0]=p->dest;b.tick(in);}
    in={};in.start=f;in.response=true;in.beat=x->beat;in.alloc={alloc(8,35,38),alloc(9,35,38,false)};b.tick(in);
    in={};in.response=true;in.beat=y->beat;b.tick(in);in.beat=z->beat;b.tick(in);
    b.wait(8);in={};in.alloc={alloc(10,36,37),alloc(11,37,38)};b.tick(in);b.wait(3);b.drain();b.clearRows();
    // Owned request+ready+reply same edge, then direct new-start+request+reply.
    auto q=b.op(39);in={};in.start=q;in.requestReady=false;in.reserve[0]=39;b.tick(in);b.wait(0);
    in={};in.requestReady=true;in.response=true;in.beat=q->beat;b.tick(in);b.drain();
    auto imm=b.op(40,2);in={};in.start=imm;in.response=true;in.beat=imm->beat;in.reserve[0]=40;b.tick(in);b.drain();
    // Fault publication and exclusions, no fabricated external response for local faults.
    for(unsigned kind=0;kind<7;++kind){auto p=b.op(kind==6?0:41);p->address=0x80010100;in={};in.start=p;
        if(kind==0)p->address+=1;if(kind==1)p->denied=true;if(kind==2)p->atomic=true,p->address=0;if(kind==3)p->store=true;if(kind==4)p->writes=false;if(kind==5)p->atomic=true;
        b.tick(in);if(!p->fault()){in={};in.response=true;in.beat=p->beat;b.tick(in);}b.wait(1);b.drain();}
    for(unsigned fault=0;fault<2;++fault){auto p=b.op(42);in={};in.start=p;b.tick(in);in={};in.response=true;in.beat=p->beat;in.error=!fault;in.page=fault;b.tick(in);b.drain();}
    // Cancelled response debt remains with exact high-tag owner and never resurrects a holder.
    auto dead=b.op(43);in={};in.start=dead;in.reserve[0]=43;in.alloc={alloc(12,43,43),{}};b.tick(in);b.clearRows();in={};in.cancel=1U<<dead->slot;b.tick(in);b.wait(3);in={};in.response=true;in.beat=dead->beat;b.tick(in);b.wait(2);
    auto reuse=b.op(43);reuse->token.index=dead->token.index;reuse->forward=true;in={};in.start=reuse;in.reserve[0]=43;b.tick(in);b.wait(1);
    // Legal last-owner drain + name reservation: new consumer belongs to future writer, not old value.
    in={};in.sinkReady=true;in.reserve[0]=43;in.alloc={alloc(13,43,43),{}};b.tick(in);b.wait(2);
    auto future=b.op(43);in={};in.start=future;b.tick(in);in={};in.response=true;in.beat=future->beat;b.tick(in);b.wait(1);b.drain();b.clearRows();
    // Physical/wake reservation priority without any surviving holder.
    in={};in.external=true;in.address=47;in.data=0xfedcba9876543210ULL;in.reserve[0]=47;in.alloc={alloc(14,47,47,false),alloc(15,47,0)};b.tick(in);b.wait(2);
    in={};in.external=true;in.address=47;in.data=0x123456789abcdef0ULL;b.tick(in);b.wait(2);b.clearRows();
    // Current-edge cancel can clear an old done result while accepted replacement installs a new owner.
    auto old=b.op(44);old->forward=true;in={};in.start=old;b.tick(in);auto fresh=b.op(45);fresh->forward=true;in={};in.sinkReady=true;in.cancel=1U<<old->slot;in.start=fresh;b.tick(in);b.wait(1);b.drain();
    // Arbitrary module-interface priority probe, not a legal backend physical-name reallocation.
    // No active dependency or accepted allocation: only FaultAware's raw candidates observe the collision.
    b.clearRows();auto probe=b.op(46);probe->forward=true;in={};in.start=probe;in.reserve[0]=46;
    in.alloc={alloc(0,46,46),alloc(0,46,0)};in.alloc[0].valid=false;in.alloc[1].valid=false;b.tick(in);b.drain();
    b.done();
}
}
int main(int argc,char**argv){try{bool enabled=false,seen=false;std::string mutation;for(int i=1;i<argc;++i){std::string a=argv[i];if(a=="--enabled=1")enabled=true,seen=true;else if(a=="--enabled=0")enabled=false,seen=true;else if(a.rfind("--mutate=",0)==0)mutation=a.substr(9);else throw std::runtime_error("unknown argument");}require(seen,"--enabled required");Bench b(enabled,mutation);cases(b);return 0;}catch(const std::exception&e){std::cerr<<"FAIL_LOAD_READY_PROTOCOL "<<e.what()<<"\n";return 1;}}
