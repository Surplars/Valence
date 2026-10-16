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
#include <set>
#include "tagged_board_probe.h"
#include "supply_ledger.h"

// Full CPU execution only: no DataPort injection, no forced memory holds.
// Fixed AXI service comes from board_ddr_benchmark.h on every compared run.
static constexpr uint64_t src=0x80400000, dst=0x81400000, control=0x80600000;
struct Observer {
    unsigned previousDTranslationState=0;
    uint64_t dWalkEntries=0,dL2Hits=0,roiDWalkEntries=0,roiDL2Hits=0;
    SupplyLedger supply;
    Test *test=nullptr;
    std::map<uint64_t,uint64_t> expected;
    std::map<uint64_t,uint64_t> allowedWrites;
    struct Reply { uint64_t value; bool write; };
#if TAGGED_STORE_RETURNS
    tagged_board::Probe tagged;
    std::map<tagged_board::Token,uint64_t> guardRequests;
    std::set<tagged_board::Token> committedTokens;
    std::map<unsigned,Reply> replies;
#else
    std::deque<Reply> replies;
#endif
    PerfCounts perf, coldPerf;
    uint64_t coldAr=0,coldR=0,coldWalk=0,coldL2=0;
    std::array<uint64_t,24> events{};
    uint64_t ar=0,aw=0,r=0,w=0,axiReadWriteFireCycles=0,lsuSum=0,lsuPeak=0,physicalPeak=0;
    uint64_t hitPass=0,pfCandidates=0,pfAllocated=0,pfUseful=0,pfMissSum=0;
    uint64_t handoffs=0,independentReadHits=0,independentMisses=0,independentStoreHits=0;
    uint64_t cacheOwnerPeak=0,cacheOwnerSum=0,twoCacheOwnerCycles=0,axiReadPeak=0;
    uint64_t roiLoads=0,roiStores=0,pcHash=1469598103934665603ULL;
    uint64_t totalLoads=0,totalStores=0,dataBytes=0;
    uint64_t checksum=0,trapCount=0,checkedReplies=0,begin=0,end=0,drain=0,done=0,lastB=0;
    Bytes code; bool active=false,ended=false; std::string injection;
    static void sample(SBoardSocGsim &d,void *ctx){static_cast<Observer*>(ctx)->sample(d);}
    void sample(SBoardSocGsim &d) {
        // Read-only source-bound state observation, sampled once per CPU tick.
        const unsigned ds=d.board$platform$physicalData_walkers_1$state;
        if(ds==1 && previousDTranslationState!=1){++dWalkEntries;if(active)++roiDWalkEntries;}
        if(ds==2 && previousDTranslationState==3){++dL2Hits;if(active)++roiDL2Hits;}
        previousDTranslationState=ds;

        if(!active&&!ended){coldPerf.sample(d);coldAr+=d.get_io$$ddrAxi$$ar$$valid()&&test->ddr.arReady;coldR+=test->ddr.rValid&&d.get_io$$ddrAxi$$r$$ready();}
        const bool awFire=d.get_io$$ddrAxi$$aw$$valid()&&test->ddr.awReady;
        const bool wFire=d.get_io$$ddrAxi$$w$$valid()&&test->ddr.wReady;
        const bool bFire=test->ddr.bValid&&d.get_io$$ddrAxi$$b$$ready();
        if(done)check(!awFire&&!wFire&&!bFire,"AXI write/B activity after BW_DONE");
        if(bFire)lastB=test->cycles;
        if(d.get_io$$trap$$valid()) {
            ++trapCount;
            check(d.get_io$$trap$$bits$$cause()==(injection=="--inject-trap"?8:9),
                "unexpected CPU trap cause");
            check(done!=0,"trap before measured program completed");
        }
#if TAGGED_STORE_RETURNS
        tagged.sample(d,test->cycles);
#endif
        const uint64_t raw=d.get_dataPathEvents();
        if(raw&(1ULL<<19)) {
            const uint64_t address=d.get_dataPathRequest9Address(), meta=d.get_dataPathRequest9Meta();
            check(!(meta&2)&&!(address&7)&&((meta>>7)&3)==3&&((meta>>9)&255)==255,
                "CPU physical request size/mask/class");
            const bool write=meta&1;
            if(!expected.contains(address))std::cerr << "UNSEEDED_REQUEST cycle=" << test->cycles
                << " address=0x" << std::hex << address << " meta=0x" << meta << std::dec
                << " roi=" << active << " ended=" << ended << "\n";
            check(expected.contains(address),"CPU physical request escaped independently initialized memory");
#if TAGGED_STORE_RETURNS
            const bool guard=(address>=src+dataBytes&&address<src+dataBytes+64)||
                (address>=dst+dataBytes&&address<dst+dataBytes+64);
            if(guard){
                check(!write&&tagged.requestHandle<4,"guard request was not an integer read");
                const auto &transport=tagged.ledger.transport.at(tagged.requestHandle);
                check(transport.pa==address&&!transport.write,"guard transport/address binding changed");
                check(guardRequests.emplace(transport.token,address).second,"duplicate guard full token");
            }
#endif
            if(write){
                check(allowedWrites.contains(address)&&allowedWrites.at(address)==d.get_dataPathRequest9Data(),
                    "CPU store address/data mismatch against guest workload");
                expected[address]=d.get_dataPathRequest9Data();
            }
#if TAGGED_STORE_RETURNS
            check(replies.emplace(tagged.requestHandle,Reply{expected[address],write}).second,"duplicate physical return handle");
#else
            replies.push_back({expected[address],write});
#endif
        }
        if(raw&(1ULL<<21)) {
            check(!replies.empty(),"CPU physical response lacks owner");
#if TAGGED_STORE_RETURNS
            check(replies.contains(tagged.replyHandle),"wrong/stale/duplicate physical return handle");
            const auto reply=replies.at(tagged.replyHandle);replies.erase(tagged.replyHandle);
#else
            const auto reply=replies.front(); replies.pop_front();
#endif
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
#if TAGGED_STORE_RETURNS
            // These two scalar tags are verified against the fresh generated
            // model. Index is the existing semantic head tap plus commit lane.
            check(lane==0||d.get_io$$commit0(),"commit1 without commit0");
            const uint64_t tag=lane?d.board$platform$core$core$core$backend$ledger$io$$commit$$bits$$token$$tag_1:
                d.board$platform$core$core$core$backend$ledger$io$$commit$$bits$$token$$tag_0;
            if(lane==0)check(tag==d.get_backendHeadTag(),"commit0/head full tag disagreement");
            tagged_board::Token retired{unsigned((d.get_backendHeadIndex()+lane)&15),tag};
            check(committedTokens.insert(retired).second,"duplicate architectural full-token commit");
#endif
            if(pc>=ramBase&&pc+4<=ramBase+code.size()){
                const uint32_t instruction=wordAt(code,pc-ramBase);
                totalLoads+=(instruction&0x7f)==0x03;
                totalStores+=(instruction&0x7f)==0x23;
            }
            if(pc==BW_BEGIN){check(!active&&!ended,"duplicate ROI begin");begin=test->cycles;coldWalk=dWalkEntries;coldL2=dL2Hits;active=true;starts=true;}
            if(pc==BW_END){check(active&&!ended,"orphan ROI end");end=test->cycles;stops=true;}
            if(pc==BW_DRAIN)drain=test->cycles;
            if(pc==BW_DONE){done=test->cycles;
                check(!awFire&&test->ddr.pendingWrites.empty()&&test->ddr.pendingB.empty(),
                    "BW_DONE retired before AXI write/B owners drained");
            }
            if(active&&pc>=ramBase&&pc+4<=ramBase+code.size()) {
                const uint32_t instruction=wordAt(code,pc-ramBase);
                roiLoads+=(instruction&0x7f)==0x03;
                roiStores+=(instruction&0x7f)==0x23;
                pcHash=(pcHash^pc)*1099511628211ULL;
            }
        }
        supply.sample(d,test->ddr,active,ended,done!=0&&done!=test->cycles,test->cycles);
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
    const unsigned mode=std::stoul(argv[2]),op=std::stoul(argv[3]),pages=std::stoul(argv[4]),reps=std::stoul(argv[5]);
    check(mode==1&&op==0&&(pages==16||pages==17||pages==32)&&reps==128,"page-sweep geometry");
    const unsigned bytes=pages*4096;
    Observer o;o.dataBytes=bytes;o.code=readFile(argv[1]);if(argc==7)o.injection=argv[6];
#if TAGGED_STORE_RETURNS
    o.tagged.mode=mode;o.tagged.bytes=bytes;
#endif
    Bytes rom;word(rom,0x00200297);word(rom,0x00028067);
    Test t(rom);t.running=false;o.test=&t;
    auto seed=[&](uint64_t pa,uint64_t value){t.ddr.memory[uint32_t(pa-ramBase)]=value;o.expected[pa]=value;};
    for(size_t off=0;off<o.code.size();off+=8){uint64_t value=0;for(unsigned b=0;b<8&&off+b<o.code.size();++b)value|=uint64_t(o.code[off+b])<<(8*b);seed(ramBase+off,value);}
    seed(control,mode);seed(control+8,op);seed(control+16,pages);seed(control+24,reps);
    const uint64_t words=pages;
    auto pattern=[](uint64_t word){return 0x729ad0513fe68bc4ULL^(word*0x102040810204081ULL);};
    uint64_t expectedChecksum=0;for(unsigned page=0;page<pages;++page)expectedChecksum+=pattern((page*4096ULL+page*64ULL)/8);expectedChecksum*=reps;
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
        seed(src+off,pattern(off/8));seed(dst+off,0);
        if(op)o.allowedWrites[dst+off]=op==1?0x5a170000ULL:0x10203040ULL+off/8;
    }
    // Bare mode can issue a squashed next-iteration load beyond the loop's
    // final cache line before its backward branch resolves. Explicit zero-valued
    // read-only guard lines preserve the DDR model's existing default-zero data.
    // No writes are allowed there; architectural counts/checksum/final bytes
    // remain independently checked against exactly bytes * reps.
    for(unsigned off=0;off<64;off+=8){seed(src+bytes+off,0);seed(dst+bytes+off,0);}
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
    check(o.totalLoads==4+(op==1?0:words*(reps+1))+(o.injection=="--inject-total-count"?1:0)&&
        o.totalStores==1+(op==0?0:words*(reps+1)),"whole-program architectural memory instruction count");
    for(unsigned off=0;off<64;off+=8){
        check(t.ddr.memory[uint32_t(src+bytes+off-ramBase)]==0&&
            t.ddr.memory[uint32_t(dst+bytes+off-ramBase)]==0,"read-only guard memory changed");
    }
    t.fabric.finish();
#if TAGGED_STORE_RETURNS
    o.tagged.finish();o.tagged.report();
    if(o.injection=="--inject-guard-commit"){
        check(!o.guardRequests.empty(),"guard negative control not exercised");
        o.committedTokens.insert(o.guardRequests.begin()->first);
    }
    for(const auto &[token,address]:o.guardRequests){
        const auto &life=o.tagged.ledger.lives.at(token);
        check(life.op.pa==address&&!life.op.write&&life.queued&&life.returned,
            "guard request lost exact accepted read owner");
        check(life.cancelled&&life.discarded&&!life.complete,"guard owner was not cancelled/discarded");
        check(!o.committedTokens.contains(token),"guard request token appeared in architectural commit stream");
    }
#endif
    o.supply.base.report(o.pfCandidates,o.pfAllocated);
    o.supply.finish(o.perf.cycles,o.done-o.end);
    o.perf.report("S_mode_page_sweep_ROI");
    o.coldPerf.report("cold_boot_plus_one_pass_warmup");
    std::cout<<"PAGE_SWEEP_COLD cycles="<<o.begin<<" d_walk_entries="<<o.coldWalk<<" d_l2_hits="<<o.coldL2<<" ar="<<o.coldAr<<" r_beats="<<o.coldR<<"\n";
    std::cout<<"MMU_SERVICE_OBSERVATION d_walk_entries="<<o.dWalkEntries<<" d_l2_hits="<<o.dL2Hits
        <<" roi_d_walk_entries="<<o.roiDWalkEntries<<" roi_d_l2_hits="<<o.roiDL2Hits<<"\n";

    std::cout<<"CPU_SV39_RESULT mode="<<mode<<" op="<<op<<" bytes="<<bytes<<" pages="<<pages<<" selected_stride=4160 useful_bytes="<<pages*8*reps<<" reps="<<reps
        <<" cycles="<<o.perf.cycles<<" drain="<<o.drain-o.end<<" clean_tail="<<o.done-o.end
        <<" done_cycle="<<o.done<<" last_b_cycle="<<o.lastB<<" done_write_owners=0"
        <<" payload_MiBps="<<std::setprecision(12)<<double(pages)*8*reps*100000000/o.perf.cycles/1048576
        <<" retired="<<o.perf.retired<<" pc_hash="<<o.pcHash<<" loads="<<o.roiLoads<<" stores="<<o.roiStores
        <<" total_loads="<<o.totalLoads<<" total_stores="<<o.totalStores<<" guard_requests="<<o.guardRequests.size()
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
