#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
#include "backend_observer.h"
#include "guest_symbols.h"
#include <deque>
#include <map>

namespace {
constexpr uint64_t data=0x80400000ULL, signature=0x80600000ULL;
constexpr uint64_t first=0x1122334455667788ULL, second=0x7766554433221100ULL;
std::string injection;
struct Observer {
    Test *test=nullptr;
    BackendOwnershipLedger ownership;
    std::map<uint64_t,uint64_t> memory;
    struct Owner {uint64_t address,value;bool write;};
    std::deque<Owner> physical;
    unsigned traps=0,deniedWordReads=0,neighborReads=0,stores=0,readReplies=0;
    bool done=false;uint64_t cycles=0,retired=0,trace=1469598103934665603ULL;
    static void sample(SBoardSocGsim &d,void *context){static_cast<Observer*>(context)->sample(d);}
    void sample(SBoardSocGsim &d){
        const auto b=BackendObserver::read(d);ownership.advance(b);
        if(b.reset){physical.clear();++cycles;return;}
        if(d.get_io$$trap$$valid()){
            const std::array<uint64_t,3> cause{5,9,5},pc{GUEST_DENIED_S,GUEST_SUPERVISOR_ECALL,GUEST_DENIED_MPRV};
            const std::array<uint64_t,3> tval{data,0,data};
            check(traps<3&&d.get_io$$trap$$bits$$cause()==cause[traps]&&
                d.get_io$$trap$$bits$$pc()==pc[traps]&&
                d.get_io$$trap$$bits$$tval()==(tval[traps]^(injection=="--inject-trap"?8:0)),
                "data PMP trap provenance mismatch");
            check(deniedWordReads==1,"denied physical data request crossed trap boundary");
            ++traps;
        }
        for(unsigned lane=0;lane<2;++lane){
            const bool valid=lane?d.get_io$$commit1():d.get_io$$commit0();
            const uint64_t pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();
            if(!valid)continue;
            check(pc!=GUEST_DENIED_S&&pc!=GUEST_DENIED_MPRV&&pc!=GUEST_FAIL,
                "faulting data PMP instruction retired");
            trace^=pc;trace*=1099511628211ULL;++retired;
            if(pc==GUEST_DONE)done=true;
        }
        const uint64_t events=d.get_dataPathEvents();
        if(events&(1ULL<<21)){
            check(!physical.empty(),"data PMP response without owner");
            const auto old=physical.front();physical.pop_front();
            check(!d.get_dataPathReply0Flags(),"data PMP physical reply fault");
            if(!old.write){
                const uint64_t expected=old.value^(injection=="--inject-data"?1:0);
                check(d.get_dataPathReply0Data()==expected,"data PMP independent read mismatch");++readReplies;
            }
        }
        if(events&(1ULL<<19)){
            const uint64_t address=d.get_dataPathRequest9Address(),value=d.get_dataPathRequest9Data(),meta=d.get_dataPathRequest9Meta();
            const bool write=meta&1;
            check((meta&((1ULL<<17)|(1ULL<<18)|2))==0&&((meta>>7)&3)==3&&((meta>>9)&255)==255,
                "data PMP unexpected physical request class");
            if(write){
                check(address==signature||address==signature+8,"data PMP unexpected store address");
                check(value==(address==signature?3:first),"data PMP independent store mismatch");++stores;
            }else if(address==data){
                check(traps==0||traps==3,"denied physical data request issued in protected interval");
                ++deniedWordReads;
            }else{check(address==data+8,"data PMP unexpected load address");++neighborReads;}
            check(memory.contains(address),"data PMP request outside independent memory");
            physical.push_back({address,memory.at(address),write});
            if(write)memory[address]=value;
        }
        ++cycles;
    }
};
}
int main(int argc,char **argv){try{
    check(argc==2||argc==3,"usage: data-pmp guest.bin [--inject-trap|--inject-data|--inject-count]");
    if(argc==3){injection=argv[2];check(injection=="--inject-trap"||injection=="--inject-data"||injection=="--inject-count","unknown mutation");}
    const auto image=readFile(argv[1]);check(!image.empty()&&image.size()<16384,"data PMP image bounds");
    Observer observer;Bytes rom;word(rom,0x00200297);word(rom,0x000280e7);word(rom,0x0000006f);
    Test test(rom,Observer::sample,&observer);observer.test=&test;
    for(size_t i=0;i<image.size();i+=8){uint64_t value=0;for(unsigned j=0;j<8&&i+j<image.size();++j)value|=uint64_t(image[i+j])<<(j*8);test.ddr.memory[uint32_t(i)]=value;}
    observer.memory={{data,first},{data+8,second},{signature,0},{signature+8,0}};
    for(auto [address,value]:observer.memory)test.ddr.memory[uint32_t(address-ramBase)]=value;
    test.running=false;
    while(!observer.done&&test.cycles<100000){test.tick();check(test.received.empty(),"unexpected data PMP UART");}
    check(observer.done&&observer.traps==3&&observer.deniedWordReads==(injection=="--inject-count"?3:2)&&
        observer.neighborReads==1&&observer.stores==2&&observer.readReplies==3,
        "data PMP final architectural/request count mismatch");
    check(observer.physical.empty()&&observer.ownership.requests.empty()&&observer.ownership.responses.empty(),"data PMP incomplete drain");
    for(auto [address,value]:observer.memory)check(test.ddr.memory.at(uint32_t(address-ramBase))==value,"data PMP final backing mismatch");
    std::cout<<"DATA_PMP_BOARD_PASS cycles="<<observer.cycles<<" traps=3 denied_s=1 denied_mprv=1 allowed_reads=3 forbidden_physical=0 retired="<<observer.retired<<" pc_trace="<<observer.trace<<"\n";
    return 0;
}catch(const std::exception &e){std::cerr<<"DATA_PMP_FAIL "<<e.what()<<"\n";return 1;}}
