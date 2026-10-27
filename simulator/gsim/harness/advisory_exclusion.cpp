// Independent ticket/byte-permission oracle; DUT events never select stimuli or expected state.
#include <algorithm>
#include "AdvisoryExclusionGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <map>
#include <optional>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
namespace {
constexpr uint64_t Ram=0x80000000ULL, RamBytes=0x400000ULL, Va=0x40000000ULL;
struct Token { unsigned index=0; uint64_t tag=0; bool operator==(const Token&)const=default; bool operator<(const Token&b)const{return std::pair(index,tag)<std::pair(b.index,b.tag);} };
struct Key { Token token; uint64_t address=0; unsigned size=0,epoch=7; bool operator==(const Key&)const=default; };
struct Row { bool valid=false; Key key; uint64_t physical=0; bool normal=false,allowed=false; };
struct Ticket { Token token; unsigned size=0; bool pending=true,ordinary=true; };
struct Response { bool valid=true; uint64_t physical=Ram; unsigned pbmt=0,epoch=7; };
struct Inputs { std::optional<Key> current,lookahead0,lookahead1; std::optional<Token> issued; unsigned epoch=7,privilege=1; bool stable=true,flush=false; std::optional<Response> response; };
struct Plan { std::array<bool,5> live{},fresh{}; std::array<bool,5> currentIn{}; int dEmpty=-1,rEmpty=-1,qRow=-1,captureLane=-1; bool advance=false,tSpace=false,offer=false,accept=false,victim=false; std::optional<Key> query,capture; Response response{.valid=false}; std::set<Token> bad,conflict; };
struct Write { bool valid=false; unsigned address=0; uint64_t data=0; };
struct Event { bool valid=false; unsigned address=0; };
struct Phase { std::array<Write,2> writes{}; std::array<Event,3> wakes{}; std::array<Event,2> reserves{}; unsigned address=0; };
class Oracle {
    SAdvisoryExclusionGsim dut;
    std::array<Row,5> rows{}; // D0,D1,T,R0,R1
    std::array<std::optional<Ticket>,16> tickets{};
    std::map<uint64_t,Response> translations;
    std::array<unsigned,16> cfg{}; std::array<uint64_t,16> addr{};
    unsigned dTurn=0,rTurn=0; uint64_t cycle=0,sequence=1;
    std::string scenario="reset",injection; bool injected=false;
    std::map<std::string,uint64_t> cov;
    unsigned maskExpected=0, maskRaw=0, maskQuery=0, maskCapture=0, maskPrior=0, maskNextValid=0;
    Phase phase; std::array<uint64_t,48> phaseValue{}; uint64_t phaseReady=(UINT64_C(1)<<32)-1;
    void require(bool ok,const std::string&m)const {if(!ok)throw std::runtime_error("case="+scenario+" cycle="+std::to_string(cycle)+" "+m);}
    static bool samePayload(const Key&a,const Key&b){return a.address==b.address&&a.size==b.size;}
    static bool conflicts(const Key&a,const Key&b){return a.token==b.token&&!samePayload(a,b);}
    bool live(const Row&r)const {if(!r.valid)return false;auto&t=tickets.at(r.key.token.index);return t&&t->pending&&t->ordinary&&t->token==r.key.token&&t->size==r.key.size;}
    static Key atEpoch(Key k,unsigned epoch){k.epoch=epoch;return k;}
    std::vector<Key> sources(const Inputs&in)const {std::vector<Key>s;for(auto k:{in.current,in.lookahead0,in.lookahead1})if(k)s.push_back(atEpoch(*k,in.epoch));return s;}
    bool readPermission(uint64_t pa,unsigned size,unsigned privilege)const {
        using W=unsigned __int128;W begin=pa,end=begin+(W(1)<<size);
        for(unsigned i=0;i<16;++i){unsigned mode=(cfg[i]>>3)&3;if(!mode)continue;W low=0,high=0;
            if(mode==1){low=i?W(addr[i-1])*4:0;high=W(addr[i])*4;}
            if(mode==2){low=W(addr[i])*4;high=low+4;}
            if(mode==3){unsigned ones=0;while(ones<54&&((addr[i]>>ones)&1))++ones;W n=W(1)<<(ones+3>56?56:ones+3);low=(W(addr[i])*4)&~(n-1);high=low+n;}
            bool touch=false,all=true;for(W b=begin;b<end;++b){bool inside=b>=low&&b<high;touch|=inside;all&=inside;}
            if(touch)return all&&((privilege==3&&!(cfg[i]&0x80))||(cfg[i]&1));
        }return privilege==3;
    }
    bool permission(const Row&r,unsigned privilege)const {
        uint64_t bytes=UINT64_C(1)<<r.key.size;bool ram=true;
        for(unsigned b=0;b<bytes;++b){unsigned __int128 a=static_cast<unsigned __int128>(r.physical)+b;ram&=a>=Ram&&a<static_cast<unsigned __int128>(Ram)+RamBytes;}
        return r.normal&&r.key.address%bytes==0&&ram&&r.key.address%4096==r.physical%4096&&readPermission(r.physical,r.key.size,privilege);
    }
    Plan plan(const Inputs&in)const {
        Plan p; const bool enabled=in.stable&&!in.flush; const auto ss=sources(in);
        for(unsigned i=0;i<5;++i){p.live[i]=live(rows[i]);p.fresh[i]=p.live[i]&&rows[i].key.epoch==in.epoch;p.currentIn[i]=in.current&&p.fresh[i]&&rows[i].key==atEpoch(*in.current,in.epoch);}
        for(auto&s:ss){for(auto&t:ss)if(conflicts(s,t))p.conflict.insert(s.token);for(auto&r:rows)if(r.valid&&conflicts(s,r.key))p.conflict.insert(s.token);}
        for(unsigned i=0;i<5;++i)if(rows[i].valid&&(!p.fresh[i]||p.conflict.contains(rows[i].key.token)))p.bad.insert(rows[i].key.token);
        for(int i=0;i<2;++i){if(p.dEmpty<0&&!rows[i].valid)p.dEmpty=i;if(p.rEmpty<0&&!rows[i+3].valid)p.rEmpty=i+3;}
        p.advance=enabled&&p.fresh[2]&&p.rEmpty>=0;p.tSpace=!rows[2].valid||p.advance;
        bool reserved=false,oldConflict=false;for(bool v:p.currentIn)reserved|=v;
        if(in.current)for(auto&r:rows)oldConflict|=r.valid&&conflicts(*in.current,r.key);
        if(p.currentIn[0])p.qRow=0;else if(p.currentIn[1])p.qRow=1;
        else if(!in.current||reserved){for(unsigned j:{dTurn,1-dTurn})if(p.qRow<0&&p.fresh[j])p.qRow=int(j);}
        if(p.qRow>=0)p.query=rows[p.qRow].key;
        else if(in.current&&!reserved&&!oldConflict)p.query=atEpoch(*in.current,in.epoch);
        p.offer=enabled&&p.tSpace&&p.query.has_value();
        if(in.response)p.response=*in.response;else if(p.query&&translations.contains(p.query->address))p.response=translations.at(p.query->address);else p.response={.valid=false,.epoch=in.epoch};
        p.accept=p.offer&&(!p.response.valid||p.response.epoch==in.epoch);
        std::array<std::optional<Key>,2> ahead{in.lookahead0,in.lookahead1};
        for(unsigned j=0;j<2;++j)if(ahead[j]){bool duplicate=false;for(auto&r:rows)duplicate|=r.valid&&r.key.token==ahead[j]->token;duplicate|=p.accept&&p.query->token==ahead[j]->token;
            if(!duplicate&&p.captureLane<0){p.captureLane=j;p.capture=atEpoch(*ahead[j],in.epoch);}}
        if(!enabled||p.dEmpty<0){p.capture.reset();p.captureLane=-1;}
        p.victim=enabled&&in.current&&!p.currentIn[3]&&!p.currentIn[4]&&p.rEmpty<0;
        return p;
    }
    void drive(const Inputs&in,const Plan&p){
#define CAND(N,K) {auto k=(K).value_or(Key{});dut.set_io$$##N##$$valid((K).has_value());dut.set_io$$##N##$$bits$$token$$index(k.token.index);dut.set_io$$##N##$$bits$$token$$tag(k.token.tag);dut.set_io$$##N##$$bits$$address(k.address);dut.set_io$$##N##$$bits$$size(k.size);}
        CAND(current,in.current);CAND(lookahead0,in.lookahead0);CAND(lookahead1,in.lookahead1);
#undef CAND
        auto issued=in.issued.value_or(Token{});dut.set_io$$issued$$valid(in.issued.has_value());dut.set_io$$issued$$bits$$index(issued.index);dut.set_io$$issued$$bits$$tag(issued.tag);
        dut.set_io$$descriptorLive0(p.live[0]);dut.set_io$$descriptorLive1(p.live[1]);dut.set_io$$translatedLive(p.live[2]);dut.set_io$$preparedLive0(p.live[3]);dut.set_io$$preparedLive1(p.live[4]);
        dut.set_io$$precheck$$response$$valid(p.response.valid);dut.set_io$$precheck$$response$$bits$$physicalAddress(p.response.physical);dut.set_io$$precheck$$response$$bits$$pbmt(p.response.pbmt);dut.set_io$$precheck$$response$$bits$$epoch(p.response.epoch);
        dut.set_io$$precheck$$epoch(in.epoch);dut.set_io$$precheck$$stable(in.stable);dut.set_io$$flush(in.flush);dut.set_io$$privilege(in.privilege);
#define PMP(N) dut.set_io$$cfg##N(cfg[N]);dut.set_io$$addr##N(addr[N]);
        PMP(0);PMP(1);PMP(2);PMP(3);PMP(4);PMP(5);PMP(6);PMP(7);PMP(8);PMP(9);PMP(10);PMP(11);PMP(12);PMP(13);PMP(14);PMP(15);
#undef PMP
#define PW(N) dut.set_io$$phaseWrite##N##$$valid(phase.writes[N].valid);dut.set_io$$phaseWrite##N##$$bits$$address(phase.writes[N].address);dut.set_io$$phaseWrite##N##$$bits$$data(phase.writes[N].data);
        PW(0);PW(1);
#undef PW
#define PE(N,K,F) dut.set_io$$phase##K##N##$$valid(phase.F[N].valid);dut.set_io$$phase##K##N##$$bits(phase.F[N].address);
        PE(0,Wake,wakes);PE(1,Wake,wakes);PE(2,Wake,wakes);PE(0,Reserve,reserves);PE(1,Reserve,reserves);
#undef PE
        dut.set_io$$phaseAddress(phase.address);
    }
    void observe(const Inputs&in,const Plan&p){
#define OWNER(N) Row{bool(dut.get_io$$##N##$$valid()),{{unsigned(dut.get_io$$##N##$$bits$$token$$index()),uint64_t(dut.get_io$$##N##$$bits$$token$$tag())},uint64_t(dut.get_io$$##N##$$bits$$address()),unsigned(dut.get_io$$##N##$$bits$$size()),unsigned(dut.get_io$$##N##$$bits$$epoch())}}
        std::array<Row,5>a{OWNER(descriptor0),OWNER(descriptor1),OWNER(translatedOwner),OWNER(prepared0),OWNER(prepared1)};
#undef OWNER
        a[2].physical=dut.get_io$$translatedPayload$$physicalAddress();a[2].normal=dut.get_io$$translatedNormal();a[2].allowed=dut.get_io$$translatedPayload$$allowed();
        a[3].physical=dut.get_io$$preparedPayload0$$physicalAddress();a[3].allowed=dut.get_io$$preparedPayload0$$allowed();
        a[4].physical=dut.get_io$$preparedPayload1$$physicalAddress();a[4].allowed=dut.get_io$$preparedPayload1$$allowed();
        bool rSpace=dut.get_io$$resultSpace(),published=dut.get_io$$prepared$$valid();
        auto inject=[&](const std::string&kind,const std::string&detail){injected=true;std::cerr<<"ADVISORY_EXCLUSION_INJECTION_REACHED kind="<<kind<<" mutation="<<detail<<"\n";};
        if(!injected&&injection=="owner"&&a[2].valid){a[2].key.token.tag^=UINT64_C(1)<<48;inject("owner","sampled_high_tag");}
        if(!injected&&injection=="permission"&&(a[3].valid||a[4].valid)){auto j=a[3].valid?3:4;a[j].allowed=!a[j].allowed;inject("permission","sampled_allowed");}
        if(!injected&&injection=="credit"&&p.rEmpty<0&&in.issued){rSpace=true;inject("credit","borrow_same_edge_issue");}
        if(!injected&&injection=="row"&&scenario=="old-T-issued-new-T-survives"&&rows[2].valid&&rows[2].key.token.tag==cov["newTtag"]){a[2].valid=false;inject("row","old_destination_cancel");}
        if(!injected&&injection=="bypass"&&p.accept&&!rows[3].valid&&!rows[4].valid){published=true;inject("bypass","unregistered_publication");}
        if(!injected&&injection=="va"&&scenario=="wrong-current-VA"&&in.current&&((rows[3].valid&&conflicts(*in.current,rows[3].key))||(rows[4].valid&&conflicts(*in.current,rows[4].key)))){published=true;inject("va","saved_VA_self_comparison");}
        unsigned sampledMask=dut.get_io$$exclusionMask();
        auto maskMutation=[&](const std::string&kind,unsigned mutated){
            if(!injected&&injection==kind&&mutated!=sampledMask){sampledMask=mutated;inject(kind,"sampled_exclusion_mask");}
        };
        maskMutation("mask-missing-query", maskExpected & ~(maskQuery & ~(maskRaw|maskCapture)));
        maskMutation("mask-missing-capture", maskExpected & ~(maskCapture & ~(maskRaw|maskQuery)));
        maskMutation("mask-missing-raw", maskExpected & ~(maskRaw & ~(maskQuery|maskCapture)));
        maskMutation("mask-phantom", maskExpected | ((~maskExpected & 65535U) & -(~maskExpected & 65535U)));
        maskMutation("mask-self-hold", maskExpected|maskPrior);
        maskMutation("mask-final-valid", maskNextValid);
        require(sampledMask==maskExpected,"independent exact temporal exclusion mask mismatch");
        unsigned actualOwners=0;for(auto&r:a)if(r.valid)actualOwners|=1U<<r.key.token.index;
        require(!(actualOwners&~sampledMask),"raw owners missing from exclusion superset");
        cov["mask_checks"]++;cov["mask_zero"]+=sampledMask==0;
        cov["mask_stale_only"]+=(sampledMask&~actualOwners)!=0;
        for(unsigned i=0;i<5;++i){require(a[i].valid==rows[i].valid,"independent raw validity mismatch slot="+std::to_string(i));if(rows[i].valid){require(a[i].key==rows[i].key,"independent full owner key mismatch slot="+std::to_string(i));if(i>=2)require(a[i].physical==rows[i].physical,"independent physical payload mismatch");if(i==2)require(a[i].normal==rows[i].normal&&!a[i].allowed,"independent T response mismatch");if(i>=3)require(a[i].allowed==rows[i].allowed,"independent byte permission mismatch");}}
        require(rSpace==(p.rEmpty>=0),"independent raw pre-edge R credit mismatch");
#define B(N,E) require(bool(dut.get_io$$##N())==bool(E),"independent " #N " mismatch")
        B(translatedAdvance,p.advance);B(translatedSpace,p.tSpace);B(queryOffer,p.offer);B(queryAccept,p.accept);B(queryFromDescriptor,p.qRow>=0);B(descriptorTransfer,p.accept&&p.qRow>=0);B(descriptorCapture,p.capture.has_value());B(preparedPreempt,p.victim);B(negativeExpire,(rows[3].valid&&!rows[3].allowed)||(rows[4].valid&&!rows[4].allowed));B(hit,p.offer&&p.response.valid&&in.stable);
#undef B
        require(bool(dut.get_io$$precheck$$request$$valid())==p.offer,"independent query validity mismatch");
        if(p.offer)require(dut.get_io$$precheck$$request$$bits$$address()==p.query->address&&dut.get_io$$precheck$$request$$bits$$size()==p.query->size&&!dut.get_io$$precheck$$request$$bits$$write(),"independent query provenance mismatch");
        if(p.qRow>=0)require(dut.get_io$$queryDescriptorIndex()==unsigned(p.qRow),"independent D round-robin/current priority mismatch");
        if(p.capture)require(dut.get_io$$descriptorCaptureIndex()==unsigned(p.dEmpty)&&dut.get_io$$captureLookaheadIndex()==unsigned(p.captureLane),"independent capture row/rank mismatch");
        if(p.advance)require(dut.get_io$$preparedInsertIndex()==unsigned(p.rEmpty-3),"independent R insertion row mismatch");
        if(p.victim)require(dut.get_io$$preparedVictimIndex()==rTurn,"independent R victim turn mismatch");
        const int selected=p.currentIn[3]?3:(p.currentIn[4]?4:-1);
        const bool publication=in.stable&&!in.flush&&selected>=0;
        // Legacy current authority: contradictory lookahead cancels at edge, not via AGU->launch veto.
        require(published==publication,"independent current-key publication mismatch");
        if(publication){auto&r=rows[selected];require(dut.get_io$$selectedPreparedIndex()==unsigned(selected-3)&&dut.get_io$$prepared$$bits$$token$$index()==r.key.token.index&&dut.get_io$$prepared$$bits$$token$$tag()==r.key.token.tag&&dut.get_io$$prepared$$bits$$address()==r.key.address&&dut.get_io$$prepared$$bits$$size()==r.key.size&&dut.get_io$$prepared$$bits$$epoch()==r.key.epoch&&dut.get_io$$prepared$$bits$$physicalAddress()==r.physical&&bool(dut.get_io$$prepared$$bits$$allowed())==r.allowed,"independent current certificate payload mismatch");}
        require(dut.get_io$$phaseData()==(phase.address&&phase.address<48?phaseValue[phase.address]:0),"independent PRF pre-edge/lane/zero phase mismatch");
        require(dut.get_io$$phaseReady()==phaseReady,"independent reserve-over-wake phase mismatch");
    }
    void advance(const Inputs&in,const Plan&p){
        auto old=rows;
        maskPrior=maskExpected;maskRaw=maskQuery=maskCapture=0;
        for(auto&r:old)if(r.valid)maskRaw|=1U<<r.key.token.index;
        if(p.accept)maskQuery=1U<<p.query->token.index;
        if(p.capture)maskCapture=1U<<p.capture->token.index;
        maskExpected=maskRaw|maskQuery|maskCapture;
        cov["nominal_query_unique"]+=(maskQuery&~(maskRaw|maskCapture))!=0;
        cov["nominal_capture_unique"]+=(maskCapture&~(maskRaw|maskQuery))!=0;

        if(p.advance){rows[p.rEmpty]=old[2];rows[p.rEmpty].allowed=permission(old[2],in.privilege);rows[2].valid=false;}
        if(p.accept){rows[2]={.valid=true,.key=*p.query,.physical=p.response.valid?p.response.physical:0,.normal=p.response.valid&&p.response.pbmt==0};if(p.qRow>=0){rows[p.qRow].valid=false;dTurn=1-p.qRow;}}
        if(p.capture)rows[p.dEmpty]={.valid=true,.key=*p.capture};
        const auto victim=p.victim?std::optional<Token>(old[3+rTurn].key.token):std::nullopt;
        if(p.victim)rTurn^=1;
        for(auto&r:rows)if(r.valid){bool drop=!in.stable||in.flush||r.key.epoch!=in.epoch||p.bad.contains(r.key.token)||p.conflict.contains(r.key.token)||(in.issued&&r.key.token==*in.issued)||(victim&&r.key.token==*victim);
            for(int j=3;j<5;++j)drop|=old[j].valid&&!old[j].allowed&&old[j].key==r.key;
            if(drop)r.valid=false;
        }
        maskNextValid=0;for(auto&r:rows)if(r.valid)maskNextValid|=1U<<r.key.token.index;
        std::set<Token> unique;for(auto&r:rows)if(r.valid)require(unique.insert(r.key.token).second,"oracle duplicate owner bug");
        cov["query"]+=p.accept;cov["capture"]+=p.capture.has_value();cov["advance"]+=p.advance;cov["victim"]+=p.victim;cov["turnover"]+=p.advance&&p.accept;cov["issue"]+=in.issued.has_value();
        cov["raw_full_R"]+=p.rEmpty<0;cov["raw_full_D"]+=p.dEmpty<0;cov["stale_response"]+=p.offer&&p.response.valid&&p.response.epoch!=in.epoch;cov["negative"]+=(old[3].valid&&!old[3].allowed)+(old[4].valid&&!old[4].allowed);cov["conflict"]+=!p.conflict.empty();cov["flush"]+=in.flush;cov["unstable"]+=!in.stable;
        cov["distinct_D_turnover"]+=p.capture&&p.accept&&p.qRow>=0&&p.dEmpty!=p.qRow;
        cov["distinct_R_turnover"]+=p.advance&&in.issued&&old[3+(p.rEmpty==3?1:0)].valid&&old[3+(p.rEmpty==3?1:0)].key.token==*in.issued;
        for(unsigned i=0;i<5;++i){cov["dead"]+=old[i].valid&&!p.live[i];cov["epoch"]+=old[i].valid&&old[i].key.epoch!=in.epoch;}
        for(auto&w:phase.writes)if(w.valid&&w.address&&w.address<48)phaseValue[w.address]=w.data;
        for(auto&w:phase.wakes)if(w.valid&&w.address<48)phaseReady|=UINT64_C(1)<<w.address;
        for(auto&r:phase.reserves)if(r.valid&&r.address<48)phaseReady&=~(UINT64_C(1)<<r.address);
        ++cycle;
    }
public:
    explicit Oracle(std::string kind):injection(std::move(kind)){allowAll();Inputs in;auto p=plan(in);dut.LOG_START=1;dut.activateAll();drive(in,p);dut.set_reset(true);dut.step();dut.step();dut.set_reset(false);}
    Plan tick(Inputs in={}){auto p=plan(in);drive(in,p);dut.step();observe(in,p);advance(in,p);return p;}
    void allowAll(){cfg.fill(0);addr.fill(0);cfg[0]=0x1f;addr[0]=(UINT64_C(1)<<54)-1;}
    void clean(const std::string&name){scenario=name;phase={};tick({.flush=true});tick();tick();require(maskExpected==0,"no-contribution exclusion failed to clear");for(auto&r:rows)require(!r.valid,"flush did not clear raw owner");tickets.fill({});translations.clear();allowAll();}
    Key make(unsigned size=3,std::optional<uint64_t>va={},std::optional<unsigned>index={}){uint64_t n=sequence++;Key k{{index.value_or(unsigned(n&15)),UINT64_C(0x8fed000000000000)+n},va.value_or(Va+(n*16)%0x100000),size,7};tickets[k.token.index]=Ticket{k.token,size};translations[k.address]={.physical=Ram+(k.address-Va),.epoch=7};return k;}
    bool positive(const Key&k)const{for(int i=3;i<5;++i)if(rows[i].valid&&rows[i].key==k&&rows[i].allowed)return true;return false;}
    void waitProof(const Key&k,bool allow=true,Inputs in={}){in.current=k;for(unsigned n=0;n<8;++n){bool found=false;for(int i=3;i<5;++i)found|=rows[i].valid&&rows[i].key==atEpoch(k,in.epoch);if(found){for(int i=3;i<5;++i)if(rows[i].valid&&rows[i].key==atEpoch(k,in.epoch))require(rows[i].allowed==allow,"independent expected permission scenario mismatch");tick(in);return;}tick(in);}require(false,"bounded proof progress failure");}
    void phaseTests(){clean("PRF-ready-phase");phase.address=35;tick();phase.writes[0]={true,35,0x1234};phase.wakes[0]={true,35};tick();phase={.address=35};tick();require(phaseValue[35]==0x1234&&(phaseReady&(UINT64_C(1)<<35)),"phase test setup");phase.writes[0]={true,35,0x1111};phase.writes[1]={true,35,0x2222};phase.wakes[1]={true,35};phase.reserves[0]={true,35};tick();phase={.address=35};tick();require(phaseValue[35]==0x2222&&!(phaseReady&(UINT64_C(1)<<35)),"lane/reserve priority setup");phase.writes[1]={true,0,0xffff};phase.address=0;tick();phase={.address=63};tick();phase={.address=36};tick();phase={};cov["phase_cases"]=7;std::cout<<"ADVISORY_EXCLUSION_PHASE_PASS cases=7 phase=post_step_pre_edge_observe_then_apply_events\n";}
    void warm(unsigned ranks,unsigned slots=0){clean("warm-ranks-"+std::to_string(ranks)+"-slots-"+std::to_string(slots));std::map<unsigned,Key>keys;unsigned head=0;std::vector<uint64_t>active,starts;const uint64_t start=cycle;for(unsigned n=0;n<1600;++n){for(unsigned j=head;j<head+ranks;++j)if(!keys.contains(j))keys[j]=make();active.erase(std::remove_if(active.begin(),active.end(),[&](uint64_t c){return c<=cycle;}),active.end());Inputs in{.current=keys[head],.lookahead0=keys[head+1]};if(ranks==3)in.lookahead1=keys[head+2];bool issue=positive(keys[head])&&(!slots||active.size()<slots);if(issue)in.issued=keys[head].token;tick(in);if(issue){starts.push_back(cycle-1-start);active.push_back(cycle-1+6);++head;}}
        unsigned tail=0;for(auto n:starts)tail+=n>=200;double rate=double(tail)/1400;require(rate>(ranks==2?.49:(slots?.65:.74))&&rate<(ranks==2?.51:(slots?.68:.76)),"independent warm supply rate outside contract");cov["warm_cases"]++;std::cout<<"ADVISORY_EXCLUSION_IDEAL ranks="<<ranks<<" slots="<<slots<<" issues="<<head<<" steady_rate="<<rate<<" cpu_performance=UNVERIFIED\n";}
    void saturate(){clean("saturate");std::vector<Key>keys;for(unsigned n=0;n<5;++n)keys.push_back(make());for(unsigned n=0;n<20;++n){Inputs in;unsigned j=0;for(auto&k:keys){bool resident=false;for(auto&r:rows)resident|=r.valid&&r.key.token==k.token;if(!resident){if(j++==0)in.lookahead0=k;else if(j==2)in.lookahead1=k;}}tick(in);bool full=true;for(auto&r:rows)full&=r.valid;if(full)return;}require(false,"failed independent full-row setup");}
    void directed(){
        saturate();scenario="full-R-consume-no-credit";auto issued=rows[3].key;auto p=tick({.issued=issued.token});require(!p.advance&&p.rEmpty<0,"raw full R admitted same-edge issue credit");
        saturate();scenario="current-D-blocked-T-full-R";auto target=rows[1].key;unsigned waited=0;while(!positive(target)&&waited<5){tick({.current=target});++waited;}require(positive(target)&&waited<=4,"positive full-state progress exceeded four edges");cov["progress4"]++;
        clean("old-T-issued-new-T-survives");auto a=make(),b=make();tick({.current=a});cov["newTtag"]=b.token.tag;tick({.current=b,.issued=a.token});tick({.current=b});require(positive(b),"old T issue destroyed incoming unrelated T");
        clean("wrong-current-VA");a=make();waitProof(a);b=a;b.address+=8;tick({.current=b});for(auto&r:rows)require(!r.valid,"wrong current VA retained conflicting proof");
        clean("lookahead-conflict-current-publication");a=make();waitProof(a);b=a;b.address+=8;p=tick({.current=a,.lookahead0=b});require(p.currentIn[3]||p.currentIn[4],"expected current-key pre-edge proof");for(auto&r:rows)require(!r.valid,"lookahead conflict did not cancel after publication");cov["publication_refinement"]++;
        clean("source-source-conflict-new-T");a=make();b=a;b.address+=8;p=tick({.current=a,.lookahead0=b});require(p.accept&&!rows[2].valid,"new conflicting source query survived edge");
        clean("same-index-new-generation");a=make(3,{},6);tick({.lookahead0=a});b=make(3,{},6);p=tick({.current=b});require(p.accept&&rows[2].valid&&rows[2].key==b&&!rows[0].valid,"index-only coverage or stale owner cancellation");
        clean("negative-reservation-expiry");a=make();translations.erase(a.address);tick({.current=a});tick({.current=a});require(rows[3].valid&&!rows[3].allowed,"miss did not create negative R");p=tick({.current=a});require(!p.offer&&!rows[3].valid,"negative exact current failed full-cycle reservation");translations[a.address]={.physical=Ram+(a.address-Va)};tick({.current=a});tick({.current=a});require(positive(a),"negative expiry did not retry");
        clean("stale-response-keeps-D");a=make();tick({.lookahead0=a});p=tick({.response=Response{.epoch=6}});require(p.offer&&!p.accept&&rows[0].valid,"stale valid response consumed descriptor");tick();tick();
        clean("miss-ignores-unobserved-epoch");a=make();p=tick({.current=a,.response=Response{.valid=false,.epoch=6}});require(p.accept&&rows[2].valid,"miss treated invalid epoch as authority");tick();
        for(unsigned mode=0;mode<3;++mode){clean("context-cut");a=make();waitProof(a);Inputs in{.current=a};if(mode==0)in.flush=true;if(mode==1)in.stable=false;if(mode==2)in.epoch=8;tick(in);for(auto&r:rows)require(!r.valid,"context change retained old owner");}
        clean("issued-incoming-cancellation");a=make();b=make();tick({.current=a,.lookahead0=b,.issued=a.token});require(!rows[2].valid&&rows[0].valid,"issued current killed unrelated capture");tick({.current=b,.issued=b.token});for(auto&r:rows)require(!r.valid,"issued D transfer resurrected");
        clean("same-index-wrong-tag-issue");a=make();waitProof(a);auto wrong=a.token;wrong.tag^=UINT64_C(1)<<47;tick({.current=a,.issued=wrong});require(positive(a),"index-only issue removed owner");tick({.current=a,.issued=a.token});
        for(unsigned i=0;i<5;++i){saturate();scenario="dead-owner-row-"+std::to_string(i);a=rows[i].key;tickets[a.token.index]->pending=false;tick();for(auto&r:rows)require(!r.valid||r.key.token!=a.token,"dead owner persisted/propagated");}
        cov["directed_done"]++;
    }
    void permissions() {
        auto run = [&](const std::string &name, unsigned size, uint64_t va, Response response,
                       bool expected, unsigned privilege = 1) {
            scenario = name; Key a = make(size, va); translations[a.address] = response;
            waitProof(a, expected, {.privilege = privilege}); ++cov["pmp_cases"];
        };
        for (unsigned size = 0; size < 4; ++size) {
            clean("alignment"); run("aligned-size-" + std::to_string(size), size, Va + 32,
                {.physical = Ram + 32}, true);
            if (size) { clean("VA-misaligned"); run("VA-misaligned", size, Va + 33, {.physical = Ram + 33}, false); }
        }
        for (unsigned pbmt : {1U, 2U, 3U}) { clean("PBMT-denial");
            run("PBMT-denial", 3, Va + 32, {.physical = Ram + 32, .pbmt = pbmt}, false); }
        for (uint64_t pa : {Ram - 8, Ram + RamBytes, UINT64_MAX - 7, Ram + 33, Ram + 40}) {
            clean("range-offset-denial"); run("range-offset-denial", 3, Va + 32, {.physical = pa}, false);
        }
        clean("last-RAM-byte"); run("last-RAM-byte", 0, Va + 4095, {.physical = Ram + RamBytes - 1}, true);
        clean("last-RAM-doubleword"); run("last-RAM-doubleword", 3, Va + 4088,
            {.physical = Ram + RamBytes - 8}, true);
        // Every raw PMP entry gets an independent positive/negative test. Empty
        // lower entries cannot silently mask cfg15/addr15 wiring mistakes.
        for (unsigned entry = 0; entry < 16; ++entry) for (bool allow : {false, true}) {
            clean("PMP-entry-" + std::to_string(entry)); cfg.fill(0); addr.fill(0);
            cfg[entry] = allow ? 0x19 : 0x18; addr[entry] = (Ram + 32) >> 2;
            run("PMP-NAPOT-entry-" + std::to_string(entry), 3, Va + 32, {.physical = Ram + 32}, allow);
        }
        clean("PMP-first-overlap-wins"); cfg[0] = 0x18; addr[0] = (Ram + 32) >> 2;
        cfg[15] = 0x1f; addr[15] = (UINT64_C(1) << 54) - 1;
        run("PMP-first-overlap-wins", 3, Va + 32, {.physical = Ram + 32}, false);
        clean("PMP-NA4-partial-overlap"); cfg.fill(0); addr.fill(0); cfg[3] = 0x11; addr[3] = (Ram + 36) >> 2;
        cfg[15] = 0x1f; addr[15] = (UINT64_C(1) << 54) - 1;
        run("PMP-NA4-partial-overlap", 3, Va + 32, {.physical = Ram + 32}, false);
        clean("PMP-TOR-cover"); cfg.fill(0); addr.fill(0); addr[6] = (Ram + 32) >> 2;
        addr[7] = (Ram + 40) >> 2; cfg[7] = 0x09;
        run("PMP-TOR-cover", 3, Va + 32, {.physical = Ram + 32}, true);
        clean("PMP-reversed-TOR"); cfg.fill(0); addr.fill(0); addr[6] = (Ram + 40) >> 2;
        addr[7] = (Ram + 32) >> 2; cfg[7] = 0x09;
        run("PMP-reversed-TOR", 3, Va + 32, {.physical = Ram + 32}, false);
        for (unsigned privilege : {1U, 3U}) for (bool locked : {false, true}) {
            clean("PMP-lock-and-privilege"); cfg[0] = locked ? 0x98 : 0x18;
            run("PMP-lock-and-privilege", 3, Va + 32, {.physical = Ram + 32}, privilege == 3 && !locked, privilege);
        }
        for (unsigned privilege : {1U, 3U}) {
            clean("PMP-unmatched"); cfg.fill(0); addr.fill(0);
            run("PMP-unmatched", 3, Va + 32, {.physical = Ram + 32}, privilege == 3, privilege);
        }
    }
    void randomCases(){clean("random-adversarial");std::mt19937_64 rng(20261025);std::vector<Key>pool;for(unsigned i=0;i<8;++i)pool.push_back(make());unsigned epoch=7;
        for(unsigned n=0;n<5000;++n){if(rng()%17==0){auto k=make(unsigned(rng()%4),{},unsigned(rng()%16));pool.push_back(k);}if(rng()%31==0&&!pool.empty()){auto k=pool[rng()%pool.size()];if(tickets[k.token.index]&&tickets[k.token.index]->token==k.token)tickets[k.token.index]->pending=false;}
            pool.erase(std::remove_if(pool.begin(),pool.end(),[&](const Key&k){auto&t=tickets[k.token.index];return !t||!t->pending||t->token!=k.token;}),pool.end());while(pool.size()<3)pool.push_back(make());
            if(rng()%73==0){++epoch;for(auto&kv:translations)kv.second.epoch=epoch;}
            Inputs in{.epoch=epoch};if(rng()%9)in.current=pool[rng()%pool.size()];if(rng()%4)in.lookahead0=pool[rng()%pool.size()];if(rng()%4)in.lookahead1=pool[rng()%pool.size()];
            if(in.current&&rng()%23==0){auto bad=*in.current;bad.address^=8;in.lookahead1=bad;}
            if(rng()%5==0)in.issued=pool[rng()%pool.size()].token;
            if(rng()%67==0)in.flush=true;if(rng()%53==0)in.stable=false;
            if(rng()%13==0)in.response=Response{.valid=false,.epoch=epoch+1};else if(rng()%19==0)in.response=Response{.physical=Ram,.epoch=epoch+1};
            cfg[0]=(rng()%11==0)?0x18:0x1f;tick(in);
        }cov["random_cycles"]=5000;
    }
    void finish(){clean("final-drain");require(cov["mask_checks"]&&cov["mask_zero"]&&cov["mask_stale_only"]&&cov["nominal_query_unique"]&&cov["nominal_capture_unique"]&&cov["query"]&&cov["capture"]&&cov["advance"]&&cov["victim"]&&cov["turnover"]&&cov["raw_full_R"]&&cov["raw_full_D"]&&cov["stale_response"]&&cov["negative"]&&cov["conflict"]&&cov["flush"]&&cov["unstable"]&&cov["dead"]&&cov["epoch"]&&cov["distinct_D_turnover"]&&cov["distinct_R_turnover"]&&cov["publication_refinement"]&&cov["progress4"]&&cov["pmp_cases"]>=50&&cov["warm_cases"]==4&&cov["phase_cases"]==7&&cov["random_cycles"]==5000,"required independent hardware hazard coverage missing");require(injection.empty()||injected,"requested sampled mutation not reached");std::cout<<"ADVISORY_EXCLUSION_PASS cycles="<<cycle;for(auto&kv:cov)std::cout<<' '<<kv.first<<'='<<kv.second;std::cout<<" raw_PMP_entries=16 authority=current_full_key latency=current_query_2_descriptor_3 cpu_performance=UNVERIFIED timing=UNVERIFIED\n";}
};
}
int main(int argc,char**argv){try{std::string mode;if(argc==2){std::string flag=argv[1];if(flag.rfind("--inject-",0)!=0)throw std::runtime_error("unknown argument");mode=flag.substr(9);if(mode!="owner"&&mode!="permission"&&mode!="credit"&&mode!="row"&&mode!="bypass"&&mode!="va"&&mode!="mask-missing-query"&&mode!="mask-missing-capture"&&mode!="mask-missing-raw"&&mode!="mask-phantom"&&mode!="mask-self-hold"&&mode!="mask-final-valid")throw std::runtime_error("unknown sampled mutation");}else if(argc!=1)throw std::runtime_error("expected zero or one injection argument");Oracle o(mode);o.phaseTests();o.warm(2);o.warm(3);o.warm(2,4);o.warm(3,4);o.directed();o.permissions();o.randomCases();o.finish();return 0;}catch(const std::exception&e){std::cerr<<"ADVISORY_EXCLUSION_FAIL "<<e.what()<<'\n';return 1;}}
