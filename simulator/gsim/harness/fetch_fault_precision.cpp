#include "FetchFaultPrecisionGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <map>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

static void require(bool ok, const std::string &why) { if (!ok) throw std::runtime_error(why); }
static std::string hex(uint64_t value) { std::ostringstream s; s << std::hex << value; return s.str(); }
struct Inputs {
    uint64_t pc=0x80000000, satp=0, addr0=0, addr1=0;
    unsigned privilege=3, cfg0=0, cfg1=0;
    bool enable=true, pause=false, invalidate=false, suppress=false, link=true;
    bool virtualized=false, sum=false, mxr=false, physicalReady=true, translationReady=true, flush=false, drain=false;
};
struct Owner {
    uint64_t address=0, satp=0, physical=0;
    unsigned mask=0, privilege=0, allowed=0;
    bool sum=false, mxr=false, translated=false, permissionCaptured=false;
};
struct Response { uint64_t address; unsigned mask, due; };
struct Result {
    std::map<std::string,std::vector<std::string>> events;
    std::map<std::string,uint64_t> metrics;
    void event(const std::string &kind,const std::string &value) { events[kind].push_back(value); }
    void print(const std::string &name) const {
        std::cout << "RESULT {\"name\":\"" << name << "\",\"events\":{";
        bool first=true;
        for (const auto &[kind,values]:events) {
            if(!first)std::cout<<',';first=false;std::cout<<'"'<<kind<<"\":[";
            for(size_t n=0;n<values.size();++n) { if(n)std::cout<<',';std::cout<<'"'<<values[n]<<'"'; }
            std::cout<<']';
        }
        std::cout << "},\"metrics\":{";first=true;
        for(const auto &[key,value]:metrics) {if(!first)std::cout<<',';first=false;std::cout<<'"'<<key<<"\":"<<value;}
        std::cout<<"}}\n";
    }
};
class Fixture {
public:
    SFetchFaultPrecisionGsim d;
    Inputs i;
    Result result;
    unsigned cycle=0, delay=2, translationDelay=1, busErrors=0, busPages=0;
    bool translationPage=false, translationAccess=false, wide=false;
    uint64_t instructionPc=0x80000002, probePc=0x80000000;
    uint32_t probeInstruction0=1, probeInstruction1=1;
    std::optional<uint64_t> translationFaultAt;
    uint64_t virtualBase=0x80000000, physicalBase=0x80000000;
    std::optional<Owner> owner;
    std::optional<Response> translation, physical;
    bool heldFetch=false, heldPhysical=false;
    uint64_t heldFetchAddress=0, heldPhysicalAddress=0;
    unsigned heldFetchMask=0, heldPhysicalMask=0;
    unsigned requests=0, replies=0, physicalRequests=0, translations=0, turnover=0;
    bool lastFetch=false, lastReply=false, lastPhysical=false;

    static unsigned pmpWord(uint64_t address,unsigned privilege,const Inputs &state) {
        // Independent NA4 PMP model. Lowest overlapping entry owns the access;
        // a match must cover every one of the four bytes, including locked M.
        const uint64_t addresses[2]={state.addr0<<2,state.addr1<<2};
        const unsigned cfg[2]={state.cfg0,state.cfg1};
        for(unsigned n=0;n<2;++n) {
            if(((cfg[n]>>3)&3)==0)continue;
            require(((cfg[n]>>3)&3)==2,"host fixture supports explicit NA4 or OFF only");
            const unsigned __int128 start=address,end=start+3,low=addresses[n],high=low+3;
            if(start<=high&&end>=low)
                return start>=low&&end<=high&&((privilege==3&&!(cfg[n]&128))||(cfg[n]&4));
        }
        return privilege==3;
    }
    static unsigned permitted(uint64_t address,unsigned privilege,const Inputs &state) {
        return unsigned(pmpWord(address,privilege,state)) | (unsigned(pmpWord(address+4,privilege,state))<<1);
    }
    uint64_t translated(uint64_t address) const { return physicalBase+(address-virtualBase); }
    uint64_t data(uint64_t address,unsigned mask) const {
        // Independent byte image: C.NOP everywhere, with an optional ADDI x1,x0,1.
        const uint32_t instruction=0x00100093;
        const uint64_t physicalPc=translated(instructionPc);
        uint64_t value=0;
        for(unsigned byte=0;byte<8;++byte)if(mask&(1U<<(byte/4))) {
            const uint64_t location=address+byte;
            uint8_t v=(location&1)?0:1;
            for(unsigned n=0;n<4;++n)if(wide&&location==physicalPc+n)v=instruction>>(8*n);
            value|=uint64_t(v)<<(8*byte);
        }
        return value;
    }
    bool pageAt(uint64_t address) const {
        return translationPage&&(!translationFaultAt||address==*translationFaultAt);
    }
    bool accessAt(uint64_t address) const {
        return translationAccess&&(!translationFaultAt||address==*translationFaultAt);
    }
    void drive(bool reset=false) {
        d.set_reset(reset); d.set_io$$pc(i.pc); d.set_io$$enable(i.enable); d.set_io$$pause(i.pause);
        d.set_io$$invalidate(i.invalidate); d.set_io$$suppress(i.suppress); d.set_io$$linkReady(i.link);
        d.set_io$$virtualized(i.virtualized); d.set_io$$privilege(i.privilege);d.set_io$$satp(i.satp);
        d.set_io$$sum(i.sum);d.set_io$$mxr(i.mxr);d.set_io$$pmpCfg0(i.cfg0);d.set_io$$pmpCfg1(i.cfg1);
        d.set_io$$pmpAddr0(i.addr0);d.set_io$$pmpAddr1(i.addr1);d.set_io$$flush(i.flush);
        d.set_io$$drain(i.drain);d.set_io$$probePc(probePc);
        d.set_io$$probeInstruction0(probeInstruction0 & 3);d.set_io$$probeInstruction1(probeInstruction1 & 3);
        d.set_io$$translation$$request$$ready(i.translationReady);
        const bool tr=translation&&cycle>=translation->due;
        d.set_io$$translation$$response$$valid(tr);
        d.set_io$$translation$$response$$bits$$physicalAddress(translation?translated(translation->address):0);
        d.set_io$$translation$$response$$bits$$pageFault(translation&&pageAt(translation->address));
        d.set_io$$translation$$response$$bits$$accessFault(translation&&accessAt(translation->address));
        d.set_io$$translation$$response$$bits$$level(0);d.set_io$$translation$$response$$bits$$napot(0);
        d.set_io$$translation$$response$$bits$$global(0);d.set_io$$translation$$response$$bits$$pbmt(0);
        d.set_io$$physical$$request$$ready(i.physicalReady);
        const bool pr=physical&&cycle>=physical->due;
        d.set_io$$physical$$response$$valid(pr);
        d.set_io$$physical$$response$$bits(physical?data(physical->address,physical->mask):0);
        d.set_io$$physical$$responseError(busErrors);d.set_io$$physical$$responsePageFault(busPages);
    }
    void reset() {
        i.enable=false;i.pause=true;drive(true);d.step();d.step();
        i.enable=true;i.pause=false;drive(false);cycle=0;
    }
    bool lane() { return d.get_io$$lane0$$valid(); }
    bool idle() { return !owner&&!translation&&!physical&&d.get_io$$quiescent()&&d.get_io$$adapterIdle(); }
    void tick() {
        drive();d.step();
        const bool fv=d.get_io$$fetchValid(),fr=d.get_io$$fetchReady();
        const uint64_t fa=d.get_io$$fetchAddress();const unsigned fm=d.get_io$$fetchMask();
        const bool pv=d.get_io$$physical$$request$$valid();
        const uint64_t pa=d.get_io$$physical$$request$$bits();const unsigned pm=d.get_io$$physical$$requestMask();
        lastFetch=fv&&fr;lastReply=d.get_io$$replyValid()&&d.get_io$$replyReady();
        lastPhysical=pv&&i.physicalReady;
        if(heldFetch)require(fv&&fa==heldFetchAddress&&fm==heldFetchMask,"held fetch owner/payload changed");
        if(heldPhysical)require(pv&&pa==heldPhysicalAddress&&pm==heldPhysicalMask,"held physical owner/payload changed");
        if(i.invalidate||!i.enable)require(!lane()&&!d.get_io$$lane1$$valid(),"invalidated/disabled instruction became visible");
        if(pv) {
            require(owner.has_value(),"physical request without virtual owner");
            if(!owner->permissionCaptured) {
                owner->allowed=owner->mask&permitted(owner->physical,owner->privilege,i);
                owner->permissionCaptured=true;
            }
            require(pm!=0&&pm==owner->allowed,"forbidden or missing physical word in request mask");
            require(pa==owner->physical,"physical request truncated or changed full address");
        }
        if(lastReply) {
            require(owner.has_value(),"reply without owner");
            const unsigned allowed=owner->permissionCaptured?owner->allowed:
                owner->mask&permitted(owner->physical,owner->privilege,i);
            const bool page=pageAt(owner->address),access=accessAt(owner->address);
            const bool faulted=owner->translated&&(page||access);
            const unsigned expectedErrors=faulted?(access&&!page?owner->mask:0):
                ((owner->mask&~allowed)|(busErrors&allowed));
            const unsigned expectedPages=faulted?(page?owner->mask:0):(busPages&allowed);
            require(d.get_io$$replyErrors()==expectedErrors,"independent reply access-fault mask mismatch");
            require(d.get_io$$replyPages()==expectedPages,"independent reply page-fault mask mismatch");
            require(d.get_io$$replyData()==(faulted?0:data(owner->physical,allowed)),"independent reply data mismatch");
            result.event("reply",hex(owner->address)+":"+hex(d.get_io$$replyData())+":"+
                std::to_string(expectedErrors)+":"+std::to_string(expectedPages));
            ++replies;turnover+=lastFetch;owner.reset();
        }
        if(translation&&cycle>=translation->due&&d.get_io$$translation$$response$$ready())translation.reset();
        if(physical&&cycle>=physical->due&&d.get_io$$physical$$response$$ready())physical.reset();
        if(lastFetch) {
            require(!owner,"two accepted fetch owners");require((fa&7)==0,"fetch address not packet aligned");
            const unsigned expected=heldFetch?heldFetchMask:(i.virtualized?3:permitted(fa,i.privilege,i));
            require(fm==expected,"frontend independent PMP mask mismatch");
            const bool vm=i.privilege!=3&&(i.satp>>60)!=0;
            owner=Owner{fa,i.satp,vm?translated(fa):fa,fm,i.privilege,0,i.sum,i.mxr,vm,false};
            result.event("fetch",hex(fa)+":"+std::to_string(fm));++requests;
            result.metrics.try_emplace("first_request",cycle);
        }
        if(d.get_io$$translation$$request$$valid()&&i.translationReady) {
            require(owner&&owner->translated&&!translation,"unexpected/overlapping translation request");
            require(d.get_io$$translation$$request$$bits$$virtualAddress()==owner->address,"translation lost virtual address bits");
            require(d.get_io$$translation$$request$$bits$$rootPpn()==(owner->satp&((1ULL<<44)-1))&&
                d.get_io$$translation$$request$$bits$$asid()==((owner->satp>>44)&65535)&&
                d.get_io$$translation$$request$$bits$$mode()==(owner->satp>>60)&&
                d.get_io$$translation$$request$$bits$$privilege()==owner->privilege&&
                d.get_io$$translation$$request$$bits$$sum()==owner->sum&&
                d.get_io$$translation$$request$$bits$$mxr()==owner->mxr&&
                d.get_io$$translation$$request$$bits$$access()==2,"translation context owner mismatch");
            translation=Response{owner->address,owner->mask,cycle+translationDelay};++translations;
            result.event("translation",hex(owner->address)+":"+hex(owner->satp)+":"+std::to_string(owner->privilege));
        }
        if(lastPhysical) {
            require(!physical,"two physical response owners");physical=Response{pa,pm,cycle+delay};++physicalRequests;
            result.event("physical",hex(pa)+":"+std::to_string(pm));
        }
        heldFetch=fv&&!fr;if(heldFetch){heldFetchAddress=fa;heldFetchMask=fm;}
        heldPhysical=pv&&!i.physicalReady;if(heldPhysical){heldPhysicalAddress=pa;heldPhysicalMask=pm;}
        if(lane())result.metrics.try_emplace("first_instruction",cycle);
        ++cycle;
    }
    template<class Predicate> void until(Predicate predicate,const std::string &why,unsigned limit=200) {
        for(unsigned n=0;n<limit;++n){tick();if(predicate())return;}throw std::runtime_error("timeout: "+why);
    }
    void start(uint64_t pc) {
        i.pc=pc;instructionPc=pc;
        reset();i.enable=false;i.flush=true;tick();i.flush=false;tick();i.enable=true;
    }
    void configureMask(unsigned mask,bool virtualized=false,bool locked=false,uint64_t word=0x80000000) {
        i.privilege=locked?3:1;i.virtualized=virtualized;
        i.satp=virtualized?0x8045600000001234ULL:0;i.sum=true;i.mxr=true;
        i.addr0=(word>>2)&((1ULL<<54)-1);i.addr1=((word+4)>>2)&((1ULL<<54)-1);
        i.cfg0=0x10|(locked?0x80:0)|((mask&1)?4:0);
        i.cfg1=0x10|(locked?0x80:0)|((mask&2)?4:0);
    }
    void drain() {
        // Stop new demand first. Every accepted owner must then reply; neither
        // reset nor fixture destruction is accepted as a completion witness.
        i.enable=false;i.pause=false;i.suppress=true;i.drain=true;
        until([&]{return idle()&&d.get_io$$occupancy()==0&&!d.get_io$$tokenValid();},
            "all accepted bus owners and captured tokens drain",400);
        require(requests==replies&&!heldFetch&&!heldPhysical,"accepted fetch owner lost during drain");
        result.metrics["all_accepted_owners_drained"]=1;
    }
    void finish(const std::string &name) {
        result.metrics["requests"]=requests;result.metrics["replies"]=replies;
        result.metrics["physical_requests"]=physicalRequests;result.metrics["translations"]=translations;
        result.metrics["reply_request_turnover"]=turnover;
        result.print(name);
    }
};


struct ArchitecturalResult { uint64_t pc,tval; uint32_t instruction; bool fault,page; };
static ArchitecturalResult result(Fixture &f) {
    f.until([&]{return bool(f.d.get_io$$arch0$$valid());},"architectural output");
    return {f.d.get_io$$arch0$$bits$$pc(),f.d.get_io$$arch0$$bits$$faultAddress(),
        uint32_t(f.d.get_io$$arch0$$bits$$instruction()),
        bool(f.d.get_io$$arch0$$bits$$accessFault()),bool(f.d.get_io$$arch0$$bits$$pageFault())};
}
static void verify(Fixture &f,const std::string &name,uint64_t pc,bool fault,bool page,uint64_t tval,
                   bool mutate=false) {
    const auto r=result(f);
    f.drain();
    require(r.pc==pc,"architectural PC mismatch in "+name);
    require(r.fault==fault&&r.page==page,"architectural exception mismatch in "+name);
    if(fault||page)require(r.tval==(tval^(mutate?2:0)),"precise fetch tval mismatch in "+name);
    else require(r.instruction==(f.wide?0x00100093U:1U),"instruction byte image mismatch in "+name);
    f.result.event("architecture",hex(r.pc)+":"+hex(r.tval)+":"+std::to_string(r.fault)+":"+std::to_string(r.page));
    f.finish(name);
}

static bool parcelDenied(uint64_t address,unsigned privilege,const Inputs &state) {
    // Independent byte-range model for one required 16-bit instruction parcel.
    // PMP region granularity is 4 bytes, matching the frontend's decomposed words.
    const uint64_t addresses[2]={state.addr0<<2,state.addr1<<2};
    const unsigned cfg[2]={state.cfg0,state.cfg1};
    for(unsigned n=0;n<2;++n) {
        if(((cfg[n]>>3)&3)==0)continue;
        require(((cfg[n]>>3)&3)==2,"parcel oracle requires NA4 or OFF");
        const unsigned __int128 first=address,last=first+1,low=addresses[n],end=low+3;
        if(first<=end&&last>=low)
            return first<low||last>end||!((privilege==3&&!(cfg[n]&128))||(cfg[n]&4));
    }
    return privilege!=3;
}
static void probes() {
    Fixture f;f.reset();f.i.enable=false;
    unsigned cases=0;
    for(uint64_t base:{0x80000000ULL,0x80000002ULL,0x80000006ULL,0x80000ffeULL,
                       0xfffffffffffffffeULL})
    for(unsigned mode=0;mode<4;++mode)for(unsigned mask=0;mask<4;++mask)
    for(unsigned lengths=0;lengths<4;++lengths) {
        f.configureMask(mask,mode==3,mode==2,base&~3ULL);
        if(mode==1)f.i.privilege=3; // Unlocked M-mode permissions are bypassed.
        f.probePc=base;f.probeInstruction0=(lengths&1)?0x00100093:1;
        f.probeInstruction1=(lengths&2)?0x00100093:1;f.tick();
        uint64_t pc=base;unsigned denied=0;uint64_t faults[2]={};
        for(unsigned lane=0;lane<2;++lane) {
            const bool first=parcelDenied(pc,f.i.privilege,f.i);
            const bool second=(lengths&(1U<<lane))&&parcelDenied(pc+2,f.i.privilege,f.i);
            if(!f.i.virtualized&&(first||second))denied|=1U<<lane;
            faults[lane]=first?pc:pc+2;
            pc+=(lengths&(1U<<lane))?4:2;
        }
        require(f.d.get_io$$probeDenied()==denied&&f.d.get_io$$probeGenericDenied()==denied,
                "independent parcel permission oracle mismatch");
        if(denied&1)require(f.d.get_io$$probeFault0()==faults[0]&&
            f.d.get_io$$probeGenericFault0()==faults[0],"first lane parcel fault address mismatch");
        if(denied&2)require(f.d.get_io$$probeFault1()==faults[1]&&
            f.d.get_io$$probeGenericFault1()==faults[1],"last lane parcel fault address mismatch");
        ++cases;
    }
    require(f.requests==0&&f.replies==0,"disabled probe fixture requested memory");
    f.drain();f.result.metrics["independent_permission_cases"]=cases;f.finish("parcel_oracle_matrix");
}
static void architectural(bool mutate) {
    for(uint64_t pc:{0x80000002ULL,0x80000006ULL,0x8000003eULL,0x80000ffeULL}) {
        for(bool wide:{false,true})for(unsigned mask:{1U,2U,3U}) {
            Fixture f;f.wide=wide;f.configureMask(mask,false,false,pc&~3ULL);f.start(pc);
            const bool fault=!(mask&1)||(wide&&!(mask&2));
            const uint64_t tval=!(mask&1)?pc:pc+2;
            verify(f,"bare_"+hex(pc)+"_"+std::to_string(wide)+"_"+std::to_string(mask),
                pc,fault,false,tval,mutate&&wide&&mask==1);
        }
    }
    {
        Fixture f;f.wide=true;f.configureMask(1,true,false,0x80000000);f.start(0x80000002);
        verify(f,"translated_second_permission",0x80000002,true,false,0x80000004);
    }
    for(bool page:{false,true}) {
        Fixture f;f.wide=true;f.virtualBase=0x40000000;f.physicalBase=0x80000000;
        f.configureMask(3,true,false,0x80000ffc);f.translationPage=page;f.translationAccess=!page;
        f.translationFaultAt=0x40001000;f.start(0x40000ffe);
        verify(f,page?"page_second_portion":"translated_access_second_portion",
            0x40000ffe,!page,page,0x40001000);
    }
    for(unsigned error:{1U,2U}) {
        Fixture f;f.wide=true;f.configureMask(3);f.busErrors=error;f.start(0x80000002);
        verify(f,"genuine_transport_"+std::to_string(error),0x80000002,true,false,
            error==1?0x80000002:0x80000004);
    }
    {
        Fixture f;f.wide=true;f.configureMask(1);f.busErrors=1;f.start(0x80000002);
        verify(f,"transport_before_second_permission",0x80000002,true,false,0x80000002);
    }
    {
        Fixture f;f.configureMask(3);f.busErrors=2;f.start(0x80000002);
        verify(f,"compressed_ignores_unused_word_error",0x80000002,false,false,0);
    }
    {
        Fixture f;f.configureMask(3);f.i.addr1=f.i.addr0;f.i.cfg0=0x10;f.start(0x80000002);
        verify(f,"lowest_entry_denial_wins",0x80000002,true,false,0x80000002);
    }
    for(bool locked:{false,true}) {
        Fixture f;f.wide=true;f.configureMask(1,false,locked);f.i.privilege=3;f.start(0x80000002);
        verify(f,locked?"locked_machine_second_denied":"unlocked_machine_bypass",
            0x80000002,locked,false,0x80000004);
    }
    {
        Fixture f;f.wide=true;f.start(0xfffffffffffffffeULL);
        verify(f,"instruction_wraps_xlen",0xfffffffffffffffeULL,false,false,0);
    }
    {
        Fixture f;f.configureMask(0);f.i.cfg0=0;f.i.cfg1=0;f.start(0x80000002);
        verify(f,"supervisor_unmatched_denied",0x80000002,true,false,0x80000002);
    }
}
static void cancellation() {
    for(bool held:{false,true}) {
        Fixture f;f.delay=9;f.configureMask(3,true);f.i.physicalReady=!held;f.start(0x80000002);
        f.until([&]{return held?f.heldPhysical:f.lastPhysical;},"accepted original context owner");
        f.i.enable=false;f.i.flush=true;f.i.invalidate=true;f.i.pc=0x80000402;f.tick();
        f.i.flush=false;f.i.invalidate=false;f.i.privilege=3;f.i.virtualized=false;f.i.satp=0;
        f.i.cfg0=0;f.i.cfg1=0;f.i.physicalReady=true;
        f.until([&]{return f.idle();},"cancelled accepted context drains");
        require(f.requests==f.replies&&!f.d.get_io$$arch0$$valid()&&!f.d.get_io$$tokenValid(),
            "cancelled context leaked architectural instruction or lost owner");
        f.i.enable=true;
        verify(f,held?"held_context_redirect":"accepted_context_redirect",0x80000402,false,false,0);
    }
    {
        Fixture f;f.start(0x80000002);
        f.until([&]{return f.d.get_io$$tokenValid()||f.d.get_io$$arch0$$valid();},"captured permission before revoke");
        f.i.enable=false;f.i.flush=true;f.i.invalidate=true;f.i.pc=0x80000802;f.tick();
        f.i.flush=false;f.i.invalidate=false;
        f.until([&]{return f.idle();},"old lookahead owner after token cancellation");
        require(!f.d.get_io$$arch0$$valid()&&!f.d.get_io$$tokenValid(),"old permission token survived redirect");
        f.configureMask(0,false,false,0x80000800);f.i.enable=true;
        verify(f,"captured_permission_context_revoke",0x80000802,true,false,0x80000802);
    }
}
int main(int argc,char **argv) {
    try {
        bool mutate=false;
        for(int n=1;n<argc;++n) {
            const std::string arg=argv[n];
            if(arg=="--inject-tval")mutate=true;
            else throw std::runtime_error("unknown host option");
        }
        probes();architectural(mutate);cancellation();
        std::cout<<"FETCH_FAULT_PRECISION_PASS\n";return 0;
    } catch(const std::exception &error) {
        std::cerr<<"FETCH_FAULT_PRECISION_FAIL "<<error.what()<<'\n';return 1;
    }
}
