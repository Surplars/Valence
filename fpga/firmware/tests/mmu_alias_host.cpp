// Passive, source-bound existing model probes; no DUT state is modified.
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
#include "backend_observer.h"
#include "alias_symbols.h"
#include <deque>
#include <optional>
#include <array>
namespace {
constexpr uint64_t base=ALIAS_ENTRY,pa=base+0x20000,va=0x40000000ULL+(pa&0x1fffff),table=base+0x60000,sig=base+0x7f000;
constexpr std::array<unsigned,8> sizes{4,7,8,9,15,16,17,32};
uint64_t pattern(uint64_t n){return 0x729ad0513fe68bc4ULL^(n*0x0102040810204081ULL);}
struct Origin {BackendToken token;uint64_t pc=0,address=0,physical=0;unsigned size=0,row=0,phase=0;bool virt=false,pre=false,write=false,atomic=false;};
struct Counts {uint64_t issued=0,certified=0,ingress=0,demand=0,hit=0,miss=0,walk=0,translated=0,physical=0,replies=0,retired=0;};
struct Observer {
    Test* test=nullptr;BackendOwnershipLedger ledger;std::array<std::array<Counts,2>,16> counts{};
    std::deque<Origin> ingressOwners,physicalOrigins,translationOrigins;std::optional<Origin> translationOwner;
    struct Physical {std::optional<Origin> origin;};std::deque<Physical> replies;
    struct Capture {BackendToken token;uint64_t pc,address,meta,cycle;unsigned row;};std::optional<Capture> capture;
    uint64_t cycles=0,originals=0,sameStart=0;unsigned begun=0,ended=0,traps=0;bool active=false,terminal=false,poisoned=false;std::string injection;
    unsigned live=0,fifo=0;uint64_t dataCounts=0;bool starting=false;
    static void sample(SBoardSocGsim&d,void*c){static_cast<Observer*>(c)->sample(d);}
    static bool aliasVa(uint64_t a){return a>=va&&a<va+32*4096ULL&&((a-va)%4096)==0;}
    static uint64_t map(const Origin&o){check(o.address==(o.virt?va+((o.address-va)/4096)*4096:pa),"original alias address shape");if(o.virt)check(aliasVa(o.address),"independent alias VA range");return pa;}
    template<class D> static Origin original(D&d,const BackendSample&b,BackendToken token){
        unsigned slot=b.ownerCount;for(unsigned i=0;i<b.ownerCount;i++)if(b.live[i]&&b.slots[i]==token){check(slot==b.ownerCount,"duplicate original owner");slot=i;}
        check(slot<b.ownerCount,"deferred original missing registered owner");Origin o;
#define ORIGINAL(N) if(slot==N){ \
        o.token={d.board$platform$core$core$core$backend$lsu$slots_##N##$operation$$token$$tag,unsigned(d.board$platform$core$core$core$backend$lsu$slots_##N##$operation$$token$$index)}; \
        o.address=d.board$platform$core$core$core$backend$lsu$slots_##N##$operation$$address; \
        o.virt=d.board$platform$core$core$core$backend$lsu$slots_##N##$operation$$virtualized; \
        o.write=d.board$platform$core$core$core$backend$lsu$slots_##N##$operation$$store; \
        o.atomic=d.board$platform$core$core$core$backend$lsu$slots_##N##$operation$$atomic; \
        o.size=d.board$platform$core$core$core$backend$lsu$slots_##N##$operation$$size; \
        if constexpr(requires{d.board$platform$core$core$core$backend$lsu$slots_##N##$operation$$precheckedLoad;}){ \
            o.pre=d.board$platform$core$core$core$backend$lsu$slots_##N##$operation$$precheckedLoad; \
            o.physical=d.board$platform$core$core$core$backend$lsu$slots_##N##$operation$$physicalAddress;}}
        ORIGINAL(0) ORIGINAL(1) ORIGINAL(2) ORIGINAL(3)
#undef ORIGINAL
        check(o.token==token,"deferred full-token mismatch");return o;
    }
    Counts& of(const Origin&o){return counts[o.row][o.phase];}
    void sample(SBoardSocGsim&d){
        auto b=BackendObserver::read(d);
        if(injection=="--inject-token"&&!poisoned)for(unsigned i=0;i<b.ownerCount;i++)if(b.live[i]){b.slots[i].tag^=1;poisoned=true;break;}
        ledger.advance(b);++cycles;if(b.reset||!test)return;
        live=b.liveCount();fifo=b.fifoCount;starting=b.bit(3);dataCounts=d.get_dataPathCounts();
        // Snapshot the accepted packet before the edge, resolve operation one
        // callback later, including start.fire == FIFO-enqueue.fire.
        if(capture){auto c=*capture;check(c.cycle+1==cycles,"deferred capture crossed edge");auto o=original(d,b,c.token);++originals;
            o.pc=c.pc;o.row=c.row;o.phase=o.pc==ALIAS_TIMED_LOAD;
            if(o.pc==ALIAS_TIMED_LOAD||o.pc==ALIAS_WARM_LOAD){
                check(active&&o.row<16&&!o.write&&!o.atomic&&o.size==3,"alias original operation shape");
                check(o.virt==(o.row>=8)&&(!o.pre||o.virt),"alias original privilege class");
                const auto mapped=map(o);check(!o.pre||o.physical==mapped,"independent certificate PA");
                check(c.address==(o.pre?mapped:o.address)&&!(c.meta&3)&&((c.meta>>7)&3)==3&&((c.meta>>9)&255)==255&&
                      !(c.meta&(1ULL<<18))&&bool(c.meta&(1ULL<<17))==(o.virt&&!o.pre),"accepted alias FIFO shape/address");
                auto& n=of(o);++n.issued;n.certified+=o.pre;ingressOwners.push_back(o);
            }
            capture.reset();
        }
        const auto events=d.get_dataPathEvents();auto fire=[&](unsigned n){return bool(events&(1ULL<<n));};
        if(b.enq()){
            check(!capture&&b.request.index<16,"pending capture capacity/index");const auto i=b.request.index;
            check(d.board$platform$core$core$core$backend$queue$$renamed$$token$$tag[i]==b.request.tag,"PC lookup full tag mismatch");
            // Selected bankedIssuePayload zeros the queue PC. Actual immutable PC
            // lives in parity banks, authorized by the same checked full token.
            const auto pc=(i&1)?d.board$platform$core$core$core$backend$payload_1$pcBank1[i>>1]:d.board$platform$core$core$core$backend$payload_1$pcBank0[i>>1];
            check(pc>=base&&pc<base+32768,"accepted load/store PC outside guest code");
            if(pc>=ALIAS_ROI_BEGIN&&pc<=ALIAS_ROI_END)check(pc==ALIAS_TIMED_LOAD,"ROI performed stack/metadata data access");
            capture=Capture{b.request,pc,d.get_dataPathRequest0Address(),d.get_dataPathRequest0Meta(),cycles,begun?begun-1:0};
            sameStart+=b.bit(3)&&b.request==b.start;
        }
        if(fire(12)){
            uint64_t a=d.get_dataPathRequest4Address(),m=d.get_dataPathRequest4Meta(),auth=d.get_cpuFlowIngressAuth();
            bool candidate=aliasVa(a)||(!ingressOwners.empty()&&a==pa&&!(m&3));
            if(candidate){check(!ingressOwners.empty(),"alias ingress lacks original owner");auto o=ingressOwners.front();ingressOwners.pop_front();
                check((auth&((1ULL<<19)-1))==m&&bool(auth&(1ULL<<19))==o.pre&&bool(auth&(1ULL<<17))==(o.virt&&!o.pre),"alias ingress certificate provenance");
                check(a==(o.pre?map(o):o.address)&&!(m&3),"alias ingress independent address");++of(o).ingress;physicalOrigins.push_back(o);if(o.virt&&!o.pre)translationOrigins.push_back(o);
            }
        }
        // Source-proved demand classification: active VM fast hit is the only
        // request accepted with same-cycle response; replying never accepts a new request.
        if(fire(14)&&aliasVa(d.get_dataPathRequest5Address())){
            check(!translationOwner,"multiple alias translation owners");const auto a=d.get_dataPathRequest5Address();
            check(!translationOrigins.empty()&&translationOrigins.front().address==a,"translation lacks original VA/full-token owner");
            const auto o=translationOrigins.front();translationOrigins.pop_front();
            check(o.pc==ALIAS_TIMED_LOAD||o.pc==ALIAS_WARM_LOAD,"translation PC provenance");
            check(d.board$platform$core$core$core$backend$systemUnit$satp==((8ULL<<60)|(table>>12))&&d.board$platform$core$core$core$backend$systemUnit$privilege==1,"counted translation not S/Sv39");
            check(!(d.get_dataPathRequest5Meta()&3),"counted translation not read");translationOwner=o;
            auto& n=of(o);++n.demand;if(fire(15))++n.hit;else ++n.miss;
        }
        if(d.board$platform$physicalData_walkers_1$state==1&&d.board$platform$physicalData_walkers_1$walker$state==0&&
           aliasVa(d.board$platform$physicalData_walkers_1$saved$$virtualAddress)){
            check(translationOwner&&translationOwner->address==d.board$platform$physicalData_walkers_1$saved$$virtualAddress,"walk start lacks same VA/full-token owner");++of(*translationOwner).walk;
        }
        if(fire(15)&&translationOwner){++of(*translationOwner).translated;translationOwner.reset();}
        if(fire(21)){check(!replies.empty(),"physical reply without ordered owner");auto q=replies.front();replies.pop_front();
            check(d.get_dataPathReply0Flags()==0,"unexpected physical data fault");if(q.origin){check(d.get_dataPathReply0Data()==pattern(0),"independent same-PA read value");++of(*q.origin).replies;}}
        if(fire(19)){uint64_t a=d.get_dataPathRequest9Address(),m=d.get_dataPathRequest9Meta();Physical q;
            if(a==pa&&!(m&3)&&!physicalOrigins.empty()){
                q.origin=physicalOrigins.front();physicalOrigins.pop_front();check(a==map(*q.origin)&&!(m&(1ULL<<17))&&((m>>7)&3)==3,"physical alias conversion mismatch");++of(*q.origin).physical;
            }replies.push_back(q);
        }
        if(d.get_io$$trap$$valid()){check(active&&traps<16&&d.get_io$$trap$$bits$$cause()==9&&d.get_io$$trap$$bits$$pc()==ALIAS_RETURN_ECALL,"alias unexpected trap");++traps;}
        for(unsigned lane=0;lane<2;lane++)if(lane?d.get_io$$commit1():d.get_io$$commit0()){
            const auto pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();
            if(pc==ALIAS_CASE_BEGIN){check(!active&&begun==ended&&begun<16,"alias case begin order");active=true;++begun;}
            if(pc==ALIAS_WARM_LOAD||pc==ALIAS_TIMED_LOAD){check(active,"alias load retired outside case");++counts[begun-1][pc==ALIAS_TIMED_LOAD].retired;}
            if(pc==ALIAS_CASE_END){check(active&&traps==begun&&ingressOwners.empty()&&physicalOrigins.empty()&&translationOrigins.empty()&&!translationOwner,"alias case accepted owners not drained");for(unsigned phase=0;phase<2;phase++){const auto c=counts[begun-1][phase];
                    check(c.retired==sizes[(begun-1)%8]*(phase?64:4)&&c.issued>=c.retired&&c.issued==c.ingress&&c.issued==c.physical&&c.physical==c.replies,"per-case alias PC/owner conservation");
                    check(c.demand==c.hit+c.miss&&c.demand==c.translated&&c.miss==c.walk,"per-case alias demand/walk conservation");}
                active=false;++ended;const auto c=counts[ended-1][1];
                std::cout<<"ALIAS_PROGRESS row="<<ended-1<<" cycles="<<test->cycles<<" retired="<<c.retired<<" issued="<<c.issued<<" certified="<<c.certified<<" demand="<<c.demand<<" hit="<<c.hit<<" miss="<<c.miss<<" walk="<<c.walk<<std::endl;}
            if(pc==ALIAS_DONE)terminal=true;
        }
    }
    void oracle(unsigned poison=0)const{
        auto at=[&](uint64_t a){return test->ddr.memory.at(uint32_t(a-ramBase));};
        check(at(sig)==0x414c494153434150ULL&&at(sig+8)==0&&at(sig+16)==16,"alias final signature");
        for(unsigned n=0;n<512;n++)check((at(pa+n*8)^(poison==1&&n==17))==pattern(n),"independent alias physical page bytes");
        // Independent expected root/nonleaf/leaf PTEs. Every alias leaf shares
        // the same PPN but a distinct VA, with read-only A-set permissions.
        check(at(table+(base>>30)*8)==(((base&~0x3fffffffULL)>>2)|0xcf)&&at(table+8)==(((table+4096)>>2)|1)&&at(table+4096)==(((table+8192)>>2)|1),"independent alias page-table path");
        for(unsigned p=0;p<32;p++)check((at(table+8192+(((pa>>12)&511)+p)*8)^(poison==2&&p==19?1024ULL:0))==((pa>>2)|0x43ULL),"independent alias PPN/permissions");
        for(unsigned row=0;row<16;row++){
            uint64_t r[8];for(unsigned k=0;k<8;k++)r[k]=at(base+0x65000+row*64+k*8);
            auto n=sizes[row%8];check(r[0]==row/8&&r[1]==n&&r[2]==64&&r[3]>0&&r[4]==pattern(0)*n*64&&r[5]==(row<8?pa:va)&&r[6]==(row<8?0:4096)&&r[7]==4,"independent alias row/results");
            for(unsigned phase=0;phase<2;phase++){auto c=counts[row][phase];if(poison==3&&row==10&&phase==1)++c.retired;if(poison==4&&row==11&&phase==1)++c.miss;
                check(c.retired==n*(phase?64:4)&&c.issued>=c.retired&&c.issued==c.ingress&&c.issued==c.physical&&c.physical==c.replies,"alias load/physical count conservation");
                check(c.demand==c.hit+c.miss&&c.demand==c.translated&&c.miss==c.walk,"alias demand/walk conservation");
                check(row<8?(!c.demand&&!c.certified):(c.issued==c.certified+c.demand),"alias certified/legacy conservation");
                if(!ALIAS_PRECHECK)check(!c.certified,"OFF model unexpectedly certified a load");
            }
        }
    }
    void verify(){
        check(terminal&&!active&&begun==16&&ended==16&&traps==16,"alias terminal coverage");
        check(!capture&&ingressOwners.empty()&&physicalOrigins.empty()&&translationOrigins.empty()&&!translationOwner&&replies.empty()&&ledger.requests.empty()&&ledger.responses.empty()&&!ledger.stalledRequest,"alias terminal accepted owner drain");
        check(!live&&!fifo&&!starting&&!dataCounts,"alias terminal hardware owner drain");oracle();
        for(unsigned p=1;p<=4;p++){bool rejected=false;try{oracle(p);}catch(const std::runtime_error&){rejected=true;}check(rejected,"alias offline poison escaped");}
        uint64_t certified=0;for(unsigned r=0;r<16;r++)for(unsigned p=0;p<2;p++){auto c=counts[r][p];certified+=c.certified;
            std::cout<<"ALIAS_COUNT row="<<r<<" mode="<<(r/8)<<" pages="<<sizes[r%8]<<" phase="<<(p?"timed":"warm")<<" issued="<<c.issued<<" retired="<<c.retired<<" certified="<<c.certified<<" ingress="<<c.ingress<<" demand="<<c.demand<<" hit="<<c.hit<<" miss="<<c.miss<<" walk="<<c.walk<<" translated="<<c.translated<<" physical="<<c.physical<<" replies="<<c.replies<<"\n";
        }
        check(!ALIAS_PRECHECK||certified>0,"ON model certificate path not exercised");
        for(unsigned r=0;r<16;r++)std::cout<<"ALIAS_TICKS row="<<r<<" mode="<<r/8<<" pages="<<sizes[r%8]<<" ticks="<<test->ddr.memory.at(uint32_t(base+0x65000+r*64+24-ramBase))<<" loads="<<sizes[r%8]*64<<"\n";
        std::cout<<"ALIAS_CAPACITY_PASS cycles="<<test->cycles<<" cases=16 faults=0 S_ecalls=16 offline_poison_rejected=4 full_token_checks="<<ledger.checks<<" same_start_captures="<<sameStart<<" precheck="<<ALIAS_PRECHECK<<"\n";
    }
};
}
int main(int argc,char**argv){try{
    check(argc==2||argc==3,"usage alias image.bin [--inject-token]");Observer o;if(argc==3){o.injection=argv[2];check(o.injection=="--inject-token","unknown alias poison");}
    auto image=readFile(argv[1]);check(image.size()<32768,"alias guest capacity");Bytes rom;word(rom,uint32_t(base&0xfffff000ULL)|0x2b7);word(rom,0x02029293);word(rom,0x0202d293);word(rom,0x000280e7);word(rom,0x0000006f);
    Test t(rom);t.running=false;o.test=&t;t.observer=Observer::sample;t.observerContext=&o;
    for(size_t off=0;off<image.size();off+=8){uint64_t v=0;for(unsigned k=0;k<8&&off+k<image.size();k++)v|=uint64_t(image[off+k])<<(8*k);t.ddr.memory[uint32_t(base-ramBase+off)]=v;}
    bool done=false;while(t.cycles<4000000){t.tick();if(o.terminal&&!o.live&&!o.fifo&&!o.starting&&!o.dataCounts&&t.ddr.pendingReads.empty()&&!t.ddr.heldRead&&!t.ddr.writing&&!t.ddr.responding&&!t.ddr.writeWaiting){done=true;break;}}
    check(done,"alias bounded terminal");o.verify();
}catch(const std::exception&e){std::cerr<<"ALIAS_CAPACITY_FAIL "<<e.what()<<"\n";return 1;}}
