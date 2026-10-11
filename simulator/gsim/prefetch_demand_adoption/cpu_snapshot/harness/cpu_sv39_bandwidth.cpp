#define main unused_board_boot_main
#include "board_boot.cpp"
#undef main
#include "performance_observer.h"
#include "mshr_occupancy.h"
#include "cpu_lsu_occupancy.h"
#ifndef BOARD_EXPECTED_LSU_ENTRIES
#define BOARD_EXPECTED_LSU_ENTRIES 2
#endif
#include "cpu_sv39_symbols.h"
#include <array>
#include <deque>
#include <map>

// Full CPU execution only: no DataPort injection, no forced memory holds.
// Fixed AXI service comes from board_ddr_benchmark.h on every compared run.
static constexpr uint64_t src=0x80400000, dst=0x81400000, control=0x80600000;
struct Observer {
    Test *test=nullptr;
    std::map<uint64_t,uint64_t> expected;
    std::map<uint64_t,uint64_t> allowedWrites;
    struct Reply { uint64_t value; bool write; };
    std::deque<Reply> replies;
    PerfCounts perf;
    std::array<uint64_t,24> events{};
    uint64_t ar=0,aw=0,r=0,w=0,axiReadWriteFireCycles=0,lsuSum=0,lsuPeak=0,physicalPeak=0;
    uint64_t hitPass=0,pfCandidates=0,pfAllocated=0,pfUseful=0,pfMissSum=0;
    uint64_t handoffs=0,independentReadHits=0,independentMisses=0,independentStoreHits=0;
    uint64_t cacheOwnerPeak=0,cacheOwnerSum=0,twoCacheOwnerCycles=0,axiReadPeak=0;
    uint64_t roiLoads=0,roiStores=0,pcHash=1469598103934665603ULL;
    uint64_t checksum=0,trapCount=0,checkedReplies=0,begin=0,end=0,drain=0,done=0;
    Bytes code; bool active=false,ended=false; std::string injection;
    static void sample(SBoardSocGsim &d,void *ctx){static_cast<Observer*>(ctx)->sample(d);}
    void sample(SBoardSocGsim &d) {
        if(d.get_io$$trap$$valid()) {
            ++trapCount;
            check(d.get_io$$trap$$bits$$cause()==(injection=="--inject-trap"?8:9),
                "unexpected CPU trap cause");
            check(done!=0,"trap before measured program completed");
        }
        const uint64_t raw=d.get_dataPathEvents();
        if(raw&(1ULL<<19)) {
            const uint64_t address=d.get_dataPathRequest9Address(), meta=d.get_dataPathRequest9Meta();
            check(!(meta&2)&&!(address&7)&&((meta>>7)&3)==3&&((meta>>9)&255)==255,
                "CPU physical request size/mask/class");
            const bool write=meta&1;
            check(expected.contains(address),"CPU physical request escaped independently initialized memory");
            if(write){
                check(allowedWrites.contains(address)&&allowedWrites.at(address)==d.get_dataPathRequest9Data(),
                    "CPU store address/data mismatch against guest workload");
                expected[address]=d.get_dataPathRequest9Data();
            }
            replies.push_back({expected[address],write});
        }
        if(raw&(1ULL<<21)) {
            check(!replies.empty(),"CPU physical response lacks owner");
            const auto reply=replies.front(); replies.pop_front();
            check(d.get_dataPathReply0Flags()==0,"CPU physical response error");
            if(!reply.write)check(d.get_dataPathReply0Data()==
                (reply.value^(injection=="--inject-read"?1:0)),"CPU read data mismatch");
            ++checkedReplies;
        }
        bool starts=false,stops=false;
        for(unsigned lane=0;lane<2;++lane){
            const bool valid=lane?d.get_io$$commit1():d.get_io$$commit0();
            const uint64_t pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();
            if(!valid)continue;
            if(pc==BW_BEGIN){check(!active&&!ended,"duplicate ROI begin");begin=test->cycles;active=true;starts=true;}
            if(pc==BW_END){check(active&&!ended,"orphan ROI end");end=test->cycles;stops=true;}
            if(pc==BW_DRAIN)drain=test->cycles;
            if(pc==BW_DONE)done=test->cycles;
            if(active&&pc>=ramBase&&pc+4<=ramBase+code.size()) {
                const uint32_t instruction=wordAt(code,pc-ramBase);
                roiLoads+=(instruction&0x7f)==0x03;
                roiStores+=(instruction&0x7f)==0x23;
                pcHash=(pcHash^pc)*1099511628211ULL;
            }
        }
        if(active){
            perf.sample(d);
            hitPass+=d.get_cpuTranslationHitPass();
            handoffs+=d.get_cpuAuthorizedHandoff();
            const unsigned admission=d.get_cpuIndependentAdmission();
            independentReadHits+=admission&1;independentMisses+=(admission>>1)&1;
            independentStoreHits+=(admission>>2)&1;
            const unsigned pf=d.get_dataPrefetchEvents();pfCandidates+=pf&1;pfAllocated+=(pf>>1)&1;
            pfUseful+=(pf>>2)&1;pfMissSum+=(pf>>5)&7;
            const unsigned missOwners=MshrOccupancy::nonblocking(d.board$platform$privateCache$phase);
            cacheOwnerPeak=std::max<uint64_t>(cacheOwnerPeak,missOwners);cacheOwnerSum+=missOwners;
            twoCacheOwnerCycles+=missOwners>1;axiReadPeak=std::max<uint64_t>(axiReadPeak,test->ddr.pendingReads.size());
            uint64_t e=d.get_cpuBandwidthEvents();for(unsigned i=0;i<24;++i)events[i]+=(e>>i)&1;
            ar+=d.get_io$$ddrAxi$$ar$$valid()&&test->ddr.arReady;
            aw+=d.get_io$$ddrAxi$$aw$$valid()&&test->ddr.awReady;
            r+=test->ddr.rValid&&d.get_io$$ddrAxi$$r$$ready();
            w+=test->ddr.wReady&&d.get_io$$ddrAxi$$w$$valid();
            axiReadWriteFireCycles+=(test->ddr.rValid&&d.get_io$$ddrAxi$$r$$ready())&&
                (test->ddr.wReady&&d.get_io$$ddrAxi$$w$$valid());
            const unsigned live=CpuLsuOccupancy::sample(d,BOARD_EXPECTED_LSU_ENTRIES);
            lsuSum+=live;lsuPeak=std::max<uint64_t>(lsuPeak,live);
            physicalPeak=std::max<uint64_t>(physicalPeak,replies.size());
        }
        if(stops){active=false;ended=true;}
        (void)starts;
    }
};
int main(int argc,char **argv){try{
    check(argc==6||argc==7,"image mode op bytes repetitions [negative]");
    const unsigned mode=std::stoul(argv[2]),op=std::stoul(argv[3]),bytes=std::stoul(argv[4]),reps=std::stoul(argv[5]);
    check(mode<=1&&op<=2&&(bytes==4096||bytes==65536)&&reps<=4&&reps>0,"workload geometry");
    Observer o;o.code=readFile(argv[1]);if(argc==7)o.injection=argv[6];
    Bytes rom;word(rom,0x00200297);word(rom,0x00028067);
    Test t(rom);t.running=false;o.test=&t;
    auto seed=[&](uint64_t pa,uint64_t value){t.ddr.memory[uint32_t(pa-ramBase)]=value;o.expected[pa]=value;};
    for(size_t off=0;off<o.code.size();off+=8){uint64_t value=0;for(unsigned b=0;b<8&&off+b<o.code.size();++b)value|=uint64_t(o.code[off+b])<<(8*b);seed(ramBase+off,value);}
    seed(control,mode);seed(control+8,op);seed(control+16,bytes);seed(control+24,reps);
    const uint64_t words=bytes/8,expectedChecksum=op==0?reps*(words*0x10203040ULL+words*(words-1)/2):0;
    seed(control+32,0);o.allowedWrites[control+32]=expectedChecksum;
    // Independent three-level Sv39 page tables. Code/control use 2MiB identity
    // leaves; the two buffers use ordinary 4KiB leaves, same A/D permissions.
    auto branch=[](uint64_t pa){return ((pa>>12)<<10)|1ULL;};
    auto leaf=[](uint64_t pa){return ((pa>>12)<<10)|0xcfULL;};
    seed(0x80300000+2*8,branch(0x80301000));
    seed(0x80301000+1*8,leaf(0x80200000));
    seed(0x80301000+3*8,leaf(0x80600000));
    seed(0x80300000+1*8,branch(0x80302000));
    seed(0x80302000,branch(0x80303000));seed(0x80302000+8*8,branch(0x80304000));
    for(unsigned page=0;page<bytes/4096;++page){seed(0x80303000+8*page,leaf(src+4096*page));seed(0x80304000+8*page,leaf(dst+4096*page));}
    for(unsigned off=0;off<bytes;off+=8){
        seed(src+off,0x10203040ULL+off/8);seed(dst+off,0);
        if(op)o.allowedWrites[dst+off]=op==1?0x5a170000ULL:0x10203040ULL+off/8;
    }
    t.observer=Observer::sample;t.observerContext=&o;
    const uint64_t deadline=t.cycles+2500000;
    while(t.cycles<deadline&&o.trapCount==0)t.tick();
    check(o.trapCount==1&&o.ended&&o.done,"executing CPU workload timed out");
    t.idle(128);
    check(o.replies.empty()&&t.ddr.pendingReads.empty()&&t.ddr.pendingWrites.empty()&&t.ddr.pendingB.empty(),"CPU/AXI owners not drained");
    check(t.ddr.memory[uint32_t(control+32-ramBase)]==expectedChecksum,"read checksum mismatch");
    if(op!=0)for(unsigned off=0;off<bytes;off+=8)check(t.ddr.memory[uint32_t(dst+off-ramBase)]==
        ((op==1?0x5a170000ULL:0x10203040ULL+off/8)^(o.injection=="--inject-memory"?1:0)),"final copied/stored memory mismatch");
    check(o.roiLoads==(op==1?0:words*reps)&&o.roiStores==(op==0?0:words*reps),"architectural memory instruction count");
    t.fabric.finish();
    o.perf.report("S_mode_kernel");
    std::cout<<"CPU_SV39_RESULT mode="<<mode<<" op="<<op<<" bytes="<<bytes<<" reps="<<reps
        <<" cycles="<<o.perf.cycles<<" drain="<<o.drain-o.end<<" clean_tail="<<o.done-o.end
        <<" payload_MiBps="<<std::setprecision(12)<<double(bytes)*reps*100000000/o.perf.cycles/1048576
        <<" retired="<<o.perf.retired<<" pc_hash="<<o.pcHash<<" loads="<<o.roiLoads<<" stores="<<o.roiStores
        <<" ar="<<o.ar<<" aw="<<o.aw<<" r_beats="<<o.r<<" w_beats="<<o.w
        <<" lsu_capacity="<<BOARD_EXPECTED_LSU_ENTRIES<<" axi_rw_fire_cycles="<<o.axiReadWriteFireCycles
        <<" lsu_peak="<<o.lsuPeak<<" lsu_sum="<<o.lsuSum<<" physical_peak="<<o.physicalPeak
        <<" hit_pass="<<o.hitPass<<" pf_candidates="<<o.pfCandidates<<" pf_allocated="<<o.pfAllocated
        <<" pf_useful="<<o.pfUseful<<" pf_miss_sum="<<o.pfMissSum;
    std::cout<<" cache_owner_peak="<<o.cacheOwnerPeak<<" cache_owner_sum="<<o.cacheOwnerSum
        <<" two_cache_owner_cycles="<<o.twoCacheOwnerCycles<<" axi_read_peak="<<o.axiReadPeak;
    std::cout<<" handoffs="<<o.handoffs<<" independent_read_hits="<<o.independentReadHits
        <<" independent_misses="<<o.independentMisses<<" independent_store_hits="<<o.independentStoreHits;
    for(unsigned i=0;i<24;++i)std::cout<<" event"<<i<<"="<<o.events[i];
    std::cout<<"\nCPU_SV39_PASS checked_replies="<<o.checkedReplies<<" checksum="<<expectedChecksum<<"\n";
    return 0;
}catch(const std::exception&e){std::cerr<<"CPU_SV39_FAIL "<<e.what()<<"\n";return 1;}}
