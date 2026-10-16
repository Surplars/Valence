#define main unused_board_boot_main
#include "board_boot.cpp"
#undef main
#include "permission_symbols.h"
#include <map>
static constexpr uint64_t TARGET=0x80400000, VALUE=0x1111222233334444ULL;
struct PermissionObserver {
    struct Reply{uint64_t value;bool write;};
    Test *test=nullptr;unsigned which=0,priorState=0,traps=0,probes=0,targetReads=0,writes=0,l2hits=0;
    uint64_t done=0,checked=0;std::string injection;
    std::map<uint64_t,uint64_t> expected;std::map<unsigned,Reply> replies;
    static void sample(SBoardSocGsim &d,void *p){static_cast<PermissionObserver*>(p)->sample(d);}
    void sample(SBoardSocGsim &d){
        if(d.get_io$$trap$$valid()){
            check(traps==0,"duplicate/unexpected trap");++traps;
            const uint64_t cause=(which==2?5:13)^(injection=="--inject-cause"?1:0);
            check(d.get_io$$trap$$bits$$cause()==cause && d.get_io$$trap$$bits$$pc()==PERM_FAULT[which] &&
                  d.get_io$$trap$$bits$$tval()==0x40000000,"wrong precise permission trap cause/PC/tval");
        }
        unsigned st=d.board$platform$physicalData_walkers_1$state;
        if(priorState==3&&st==2&&d.board$platform$physicalData_walkers_1$saved$$virtualAddress==0x40000000){
            check(d.board$platform$physicalData_walkers_1$saved$$rootPpn==0x80300 &&
                d.board$platform$physicalData_walkers_1$savedResponse$$physicalAddress==TARGET &&
                !d.board$platform$physicalData_walkers_1$savedResponse$$pageFault &&
                !d.board$platform$physicalData_walkers_1$savedResponse$$accessFault,"bad L2 target success");++l2hits;
        }
        priorState=st;
        auto raw=d.get_dataPathEvents();
        if(raw&(1ULL<<19)){
            uint64_t pa=d.get_dataPathRequest9Address(),meta=d.get_dataPathRequest9Meta();bool write=meta&1;
            check(!(meta&2)&&!(pa&7)&&((meta>>7)&3)==3&&((meta>>9)&255)==255,"physical access geometry changed");
            check(expected.contains(pa),"unseeded CPU data request");
            if(write){check(pa==0x80600000&&d.get_dataPathRequest9Data()==0x56414c5045524d00ULL+which&&traps==1,
                "unexpected permission-test side effect");expected[pa]=d.get_dataPathRequest9Data();++writes;}
            else if(pa==TARGET){++targetReads;check(targetReads<=2&&!traps,"denied target reached physical data path");}
            check(replies.emplace(d.get_cpuTagged$$physical$$handle(),Reply{expected.at(pa),write}).second,"duplicate physical owner");
        }
        if(raw&(1ULL<<21)){
            unsigned h=d.get_cpuTagged$$physicalReply$$handle();check(replies.contains(h),"unowned physical reply");
            auto r=replies.at(h);replies.erase(h);check(d.get_dataPathReply0Flags()==0,"physical fault response");
            if(!r.write)check(d.get_dataPathReply0Data()==(r.value^(injection=="--inject-data"?1ULL:0ULL)),"physical data mismatch");++checked;
        }
        for(unsigned lane=0;lane<2;++lane){
            bool v=lane?d.get_io$$commit1():d.get_io$$commit0();if(!v)continue;
            uint64_t pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();
            check(pc!=PERM_FAIL[which],"guest rejected permission trap/data");
            check(pc!=PERM_FAULT[which],"faulting load architecturally retired normally");
            if(pc==PERM_PROBE[which])++probes;
            if(pc==PERM_DONE[which]&&!done)done=test->cycles;
        }
    }
};
int main(int argc,char**argv){try{
    check(argc==3||argc==4,"permission.bin case0..2 [negative]");PermissionObserver o;o.which=std::stoul(argv[2]);check(o.which<3,"bad case");if(argc==4)o.injection=argv[3];
    auto code=readFile(argv[1]);Bytes rom;word(rom,0x00200297);word(rom,0x00028067);Test t(rom);t.running=false;o.test=&t;
    auto seed=[&](uint64_t pa,uint64_t x){t.ddr.memory[uint32_t(pa-ramBase)]=x;o.expected[pa]=x;};
    for(size_t off=0;off<code.size();off+=8){uint64_t v=0;for(unsigned b=0;b<8&&off+b<code.size();++b)v|=uint64_t(code[off+b])<<(8*b);seed(ramBase+off,v);}
    for(unsigned pg=0;pg<4;++pg)for(unsigned w=0;w<512;++w)seed(0x80300000+pg*4096+w*8,0);
    auto branch=[](uint64_t pa){return ((pa>>12)<<10)|1ULL;};seed(0x80300008,branch(0x80302000));seed(0x80302000,branch(0x80303000));
    for(unsigned pg=0;pg<32;++pg){uint64_t flags=pg?0xcf:(o.which==0?0xdf:o.which==1?0xc9:0xcf);seed(0x80303000+pg*8,(((TARGET+pg*4096)>>12)<<10)|flags);
        for(unsigned w=0;w<8;++w)seed(TARGET+pg*4096+w*8,w?0:pg?0x90000000ULL+pg:VALUE);}
    seed(0x80600000,0);t.observer=PermissionObserver::sample;t.observerContext=&o;
    while(!o.done&&t.cycles<1000000)t.tick();check(o.done&&o.probes==1&&o.traps==1&&o.targetReads==2&&o.writes==1,"permission execution incomplete");t.idle(128);
    check(o.replies.empty()&&t.ddr.pendingReads.empty()&&t.ddr.pendingWrites.empty()&&t.ddr.pendingB.empty(),"owners not drained");
    check(t.ddr.memory.at(0x80600000-ramBase)==0x56414c5045524d00ULL+o.which,"permission signature mismatch");t.fabric.finish();
    std::cout<<"NATIVE_PERMISSION_DATA_PASS case="<<o.which<<" cycles="<<t.cycles<<" trap=1 target_reads=2 writes=1 checked_replies="<<o.checked<<"\n";
    if(o.injection=="--inject-coverage")o.l2hits=0;check(o.l2hits>0,"missing actual target L2 permission coverage");
    std::cout<<"NATIVE_L2_PERMISSION_PASS case="<<o.which<<" target_l2_hits="<<o.l2hits<<"\n";return 0;
}catch(const std::exception&e){std::cerr<<"FAIL: "<<e.what()<<"\n";return 1;}}
