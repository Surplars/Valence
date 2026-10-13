#include "FetchAddressStageGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <map>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

static bool requireDirectReady = false;
static void require(bool ok, const std::string &why) { if (!ok) throw std::runtime_error(why); }
static std::string hex(uint64_t value) { std::ostringstream s; s << std::hex << value; return s.str(); }
struct Inputs {
    uint64_t pc=0x80000000, satp=0, addr0=0, addr1=0;
    unsigned privilege=3, cfg0=0, cfg1=0;
    bool enable=true, pause=false, invalidate=false, suppress=false, link=true;
    bool virtualized=false, sum=false, mxr=false, physicalReady=true, translationReady=true, flush=false;
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
    SFetchAddressStageGsim d;
    Inputs i;
    Result result;
    unsigned cycle=0, delay=2, translationDelay=1, busErrors=0, busPages=0;
    bool translationPage=false, translationAccess=false, wideAtTwo=false, inject=false;
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
        uint64_t words=0;
        for(unsigned word=0;word<2;++word)if(mask&(1U<<word)) {
            uint32_t value=0x00010001; // Two independently known C.NOP instructions.
            if(wideAtTwo&&address+4*word==physicalBase)value=0x00930001;
            if(wideAtTwo&&address+4*word==physicalBase+4)value=0x00010010;
            words|=uint64_t(value)<<(32*word);
        }
        return words;
    }
    void drive(bool reset=false) {
        d.set_reset(reset); d.set_io$$pc(i.pc); d.set_io$$enable(i.enable); d.set_io$$pause(i.pause);
        d.set_io$$invalidate(i.invalidate); d.set_io$$suppress(i.suppress); d.set_io$$linkReady(i.link);
        d.set_io$$virtualized(i.virtualized); d.set_io$$privilege(i.privilege);d.set_io$$satp(i.satp);
        d.set_io$$sum(i.sum);d.set_io$$mxr(i.mxr);d.set_io$$pmpCfg0(i.cfg0);d.set_io$$pmpCfg1(i.cfg1);
        d.set_io$$pmpAddr0(i.addr0);d.set_io$$pmpAddr1(i.addr1);d.set_io$$flush(i.flush);
        d.set_io$$translation$$request$$ready(i.translationReady);
        const bool tr=translation&&cycle>=translation->due;
        d.set_io$$translation$$response$$valid(tr);
        d.set_io$$translation$$response$$bits$$physicalAddress(translation?translated(translation->address):0);
        d.set_io$$translation$$response$$bits$$pageFault(translationPage);
        d.set_io$$translation$$response$$bits$$accessFault(translationAccess);
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
        if(requireDirectReady&&i.link&&fv)require(fr,"supported direct adapter rejected staged offer");
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
            if(inject)require((pm^1)==owner->allowed,"negative physical-mask oracle mutation detected");
        }
        if(lastReply) {
            require(owner.has_value(),"reply without owner");
            const unsigned allowed=owner->permissionCaptured?owner->allowed:
                owner->mask&permitted(owner->physical,owner->privilege,i);
            const bool faulted=owner->translated&&(translationPage||translationAccess);
            const unsigned expectedErrors=faulted?(translationAccess&&!translationPage?owner->mask:0):
                ((owner->mask&~allowed)|(busErrors&allowed));
            const unsigned expectedPages=faulted?(translationPage?owner->mask:0):(busPages&allowed);
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
    void settle() {
        until([&]{return replies>=2&&idle();},"two cached packets and drained adapter");
        for(unsigned n=0;n<3;++n)tick();
    }
    void configureMask(unsigned mask,bool virtualized=true,bool locked=false) {
        i.privilege=locked?3:1;i.virtualized=virtualized;
        i.satp=virtualized?0x8045600000001234ULL:0;i.sum=true;i.mxr=true;
        i.addr0=physicalBase>>2;i.addr1=(physicalBase+4)>>2;
        i.cfg0=0x10|(locked?0x80:0)|((mask&1)?4:0);
        i.cfg1=0x10|(locked?0x80:0)|((mask&2)?4:0);
    }
    void finish(const std::string &name) {
        result.metrics["requests"]=requests;result.metrics["replies"]=replies;
        result.metrics["physical_requests"]=physicalRequests;result.metrics["translations"]=translations;
        result.metrics["reply_request_turnover"]=turnover;
        result.print(name);
    }
};

static void timing(bool staged,bool inject) {
    {
        Fixture f;f.inject=inject;f.reset();f.settle();
        require(f.requests==2&&f.physicalRequests==2,"cold fetch duplicated or lost packets");
        require(f.lane()&&f.d.get_io$$lane0$$bits()==1&&!f.d.get_io$$errors(),"cold C.NOP oracle mismatch");
        f.result.event("instruction",hex(f.i.pc)+":1:0:0");
        const unsigned start=f.cycle;f.i.pc+=0x400;f.until([&]{return f.lane();},"cold branch target");
        require(f.d.get_io$$lane0$$bits()==1,"branch C.NOP oracle mismatch");
        f.result.metrics["branch_latency"]=f.cycle-start;
        f.until([&]{return f.replies==4&&f.idle();},"branch target lookahead");
        for(unsigned n=0;n<3;++n)f.tick();
        f.i.pause=true;const unsigned before=f.requests;
        for(unsigned n=0;n<32;++n) {
            f.i.pc=0x80000400+2*(n%3);f.tick();
            require(f.lane()&&f.d.get_io$$lane1$$valid()&&f.d.get_io$$lane0$$bits()==1&&
                f.d.get_io$$lane1$$bits()==1,"hot cached instructions lost II=1");
        }
        require(f.requests==before,"hot paused cache unexpectedly requested memory");
        f.result.metrics["hot_cycles"]=32;f.result.metrics["hot_ii"]=1;f.finish("cold_branch_hot");
    }
    for(uint64_t address:{0x8000000080000000ULL,0xfffffffffffffff0ULL}) {
        Fixture f;f.i.pc=address;f.reset();f.settle();
        require(f.result.events["fetch"].front()==hex(address)+":3","full address lost at fetch boundary");
        f.finish("address_"+hex(address));
    }
    for(unsigned mode=0;mode<3;++mode)for(unsigned mask=0;mask<4;++mask) {
        Fixture f;f.configureMask(mask,mode==0,mode==2);f.reset();f.settle();
        require(f.result.events["fetch"].front()=="80000000:"+std::to_string(mode==0?3:mask),"PMP mask census mismatch");
        require(f.physicalRequests==unsigned(mask!=0)+(mode==2?1:0),"forbidden physical request escaped PMP");
        if(mode==0)require(bool(f.d.get_io$$errors()&1)==!(mask&1),"translated denied-word fault vanished");
        f.finish("mask_"+std::to_string(mode)+"_"+std::to_string(mask));
    }
    for(unsigned kind=0;kind<4;++kind) {
        Fixture f;f.configureMask(3);f.translationPage=kind==0;f.translationAccess=kind==1;
        f.busErrors=kind==2?1:0;f.busPages=kind==3?2:0;f.reset();f.settle();
        if(kind<2)require(f.physicalRequests==0,"translation fault issued physical read");
        require(f.lane(),"faulting raw instruction absent");
        require(bool(f.d.get_io$$errors()&1)==(kind==1||kind==2),"lane access-fault oracle mismatch");
        require(bool(f.d.get_io$$pages()&1)==(kind==0),"lane page-fault oracle mismatch");
        if(kind<3)require(f.d.get_io$$fault0()==f.i.pc,"fault address lost first parcel address");
        f.finish("fault_"+std::to_string(kind));
    }
    {
        Fixture f;f.configureMask(3);f.i.pc=0xffffffc080000000ULL;f.virtualBase=f.i.pc;f.reset();f.settle();
        require(f.translations==2,"high virtual address bypassed translation");f.finish("virtual_high_bits");
    }
    {
        Fixture f;f.i.link=false;f.reset();f.until([&]{return f.heldFetch;},"locked fetch offer");
        for(unsigned n=0;n<3;++n)f.tick();
        f.i.invalidate=true;f.i.enable=false;f.i.pause=true;f.i.pc=0x80000400;
        f.tick();f.i.invalidate=false;f.i.link=true;
        f.until([&]{return f.replies==1&&f.idle();},"stale held request drains");
        require(!f.lane(),"stale held owner produced instruction");
        f.i.enable=true;f.i.pause=false;
        f.until([&]{return f.lane();},"fresh trap context instruction");
        require(f.d.get_io$$lane0$$bits()==1,"stale fill poisoned fresh context");
        f.until([&]{return f.replies==3&&f.idle();},"drain both fresh context packets");
        f.result.metrics["locked_stale_drain"]=1;f.finish("locked_stale_cancel");
    }
    {
        Fixture f;f.configureMask(3);f.i.physicalReady=false;f.reset();
        f.until([&]{return f.heldPhysical;},"held physical offer");
        f.i.cfg0=0x10;f.i.cfg1=0x10;
        for(unsigned n=0;n<4;++n)f.tick();f.i.physicalReady=true;
        f.until([&]{return f.replies>=1;},"captured physical permission reply");
        require(f.result.events["physical"].front()=="80000000:3","held PMP permission changed");
        f.settle();
        f.result.metrics["physical_mask_hold"]=1;f.finish("physical_backpressure");
    }
    {
        Fixture f;f.configureMask(3);f.delay=5;f.reset();
        f.until([&]{return f.heldPhysical||f.lastPhysical;},"adapter captured original context");
        f.i.pause=true;f.i.enable=false;f.i.invalidate=true;
        f.i.privilege=3;f.i.virtualized=false;f.i.satp=0;f.i.sum=false;f.i.mxr=false;f.i.pc=0x80000400;
        f.tick();f.i.invalidate=false;
        f.until([&]{return f.replies==1&&f.idle();},"old translated owner drains after context change");
        require(f.translations==1&&f.requests==1,"accepted translation owner changed with live context");
        f.i.enable=true;f.i.pause=false;
        f.until([&]{return f.lane();},"fresh machine context after trap");
        require(f.d.get_io$$lane0$$bits()==1,"old translated owner poisoned new context");
        f.until([&]{return f.replies==3&&f.idle();},"drain fresh machine context packets");
        f.result.metrics["captured_context_drain"]=1;f.finish("accepted_context_change");
    }
    {
        Fixture f;f.configureMask(3);f.delay=5;f.reset();
        f.until([&]{return f.lastPhysical;},"original owner before non-invalidating context change");
        f.i.pause=true;f.i.enable=false;f.i.privilege=3;f.i.virtualized=false;f.i.satp=0;
        f.until([&]{return f.replies==1&&f.idle();},"context mismatch reply drain without invalidate");
        f.i.enable=true;f.i.pause=false;
        f.until([&]{return f.replies==3&&f.idle();},"same virtual address refetched for distinct context");
        require(f.requests==3&&f.translations==1,"old context cache entry reused as live context");
        f.result.metrics["context_mismatch_without_invalidate"]=1;f.finish("accepted_context_no_invalidate");
    }
    for(unsigned mask:{1U,2U}) {
        Fixture f;f.configureMask(mask);f.busErrors=3;f.busPages=3;f.reset();f.settle();
        require(f.physicalRequests==1,"partial permission physical response test escaped mask");
        f.finish("partial_bus_fault_"+std::to_string(mask));
    }
    {
        Fixture f;f.physicalBase=0x0012800080000000ULL;f.configureMask(3);f.reset();f.settle();
        require(f.result.events["physical"].front()=="12800080000000:3","physical PMP high bits truncated");
        f.finish("physical_pmp_high_bits");
    }
    // Prep-only cancellation has no OFF cycle equivalent: compare architectural
    // outcomes independently and record ON's explicit zero-offer witness.
    if(staged)for(unsigned kind=0;kind<6;++kind) {
        Fixture f;f.reset();f.tick();require(f.requests==0&&!f.heldFetch,"stage offered before preparation edge");
        if(kind==0)f.i.pause=true;
        if(kind==1)f.i.enable=false;
        if(kind==2)f.i.invalidate=true;
        if(kind==3)f.i.suppress=true;
        if(kind==4)f.i.privilege=1;
        if(kind==5){f.i.invalidate=true;f.i.privilege=1;f.i.virtualized=true;f.i.satp=0x8000000000012345ULL;}
        f.tick();require(f.requests==0&&!f.heldFetch,"cancelled preparation became an offered owner");
        f.i=Inputs{};f.i.pc=0x80000400;
        f.until([&]{return f.lane();},"restart after preparation cancellation");
        require(f.d.get_io$$lane0$$bits()==1,"preparation cancellation poisoned restart");
        require(f.result.events["fetch"].front()=="80000400:3","cancelled old preparation escaped");
        // End new demand, then honor every already accepted lookahead owner.
        // Reset or destroying an outstanding fixture is not a drain witness.
        f.i.enable=false;f.i.pause=true;
        f.until([&]{return f.idle();},"cancel-case accepted lookahead drains after input stops");
        require(f.requests==f.replies,"cancel-case lost an accepted fetch reply");
        f.result.metrics["all_accepted_owners_drained"]=1;
        f.result.metrics["cancelled_before_offer"]=1;f.finish("prep_cancel_"+std::to_string(kind));
    }
}

static int architecture(const std::string &which) {
    Fixture f;f.configureMask(1,false);f.wideAtTwo=which=="straddle32";f.i.pc=0x80000002;
    f.reset();f.i.enable=false;f.i.flush=true;f.tick();f.i.flush=false;f.tick();f.i.enable=true;
    f.until([&]{return bool(f.d.get_io$$arch0$$valid());},"real permission/reservoir architectural output");
    const uint64_t pc=f.d.get_io$$arch0$$bits$$pc(),tval=f.d.get_io$$arch0$$bits$$faultAddress();
    const bool fault=f.d.get_io$$arch0$$bits$$accessFault(),page=f.d.get_io$$arch0$$bits$$pageFault();
    const uint32_t instruction=f.d.get_io$$arch0$$bits$$instruction();
    require(pc==0x80000002&&!page,"architectural setup PC/page mismatch");
    const bool pass=which=="cnop16"?(!fault&&instruction==1):(fault&&tval==0x80000004);
    std::cout<<"ARCH {\"case\":\""<<which<<"\",\"pass\":"<<(pass?"true":"false")
        <<",\"actual_pc\":\""<<hex(pc)<<"\",\"actual_tval\":\""<<hex(tval)
        <<"\",\"actual_instruction\":\""<<hex(instruction)<<"\",\"actual_fault\":"<<(fault?"true":"false")
        <<",\"expected_pc\":\"80000002\",\"expected_fault\":"<<(which=="cnop16"?"false":"true")
        <<",\"expected_tval\":"<<(which=="cnop16"?"null":"\"80000004\"")<<"}\n";
    return pass?0:42; // Separate known-issue result; never folded into timing PASS.
}
int main(int argc,char **argv) {
    try {
        bool staged=false,inject=false;std::string arch;
        for(int n=1;n<argc;++n) {
            const std::string a=argv[n];
            if(a=="--staged")staged=true;
            else if(a=="--inject-mask")inject=true;
            else if(a=="--architecture"&&n+1<argc)arch=argv[++n];
            else throw std::runtime_error("unknown host option");
        }
        requireDirectReady=staged;
        if(!arch.empty()){require(arch=="cnop16"||arch=="straddle32","unknown architectural case");return architecture(arch);}
        timing(staged,inject);std::cout<<"FETCH_ADDRESS_STAGE_PASS\n";return 0;
    } catch(const std::exception &e) {std::cerr<<"FETCH_ADDRESS_STAGE_FAIL "<<e.what()<<'\n';return 1;}
}
