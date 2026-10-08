#ifndef DDR_MULTI_ID_MODEL
#error "steady memory comparison requires the same multi-ID host model on both controls"
#endif
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
#include "performance_observer.h"
#include "mshr_occupancy.h"
#ifndef MODEL_MSHRS
#error "pin MODEL_MSHRS to the schema-validated generated model"
#endif
#ifndef STEADY_START_PC
#error "marker addresses must come from the exact shared guest ELF"
#endif
static unsigned occupiedMissOwners(const SBoardSocGsim &d) {
#if MODEL_MSHRS > 1
    return MshrOccupancy::nonblocking(d.board$platform$privateCache$phase);
#else
    return MshrOccupancy::legacy(d.board$platform$privateCache$state,d.board$platform$privateCache$probeResume,
        d.board$platform$privateCache$flushActive,d.board$platform$privateCache$pendingBypass);
#endif
}
static unsigned refillPhaseOwners(const SBoardSocGsim &d) {
#if MODEL_MSHRS > 1
    return MshrOccupancy::refilling(d.board$platform$privateCache$phase);
#else
    return MshrOccupancy::legacyRefilling(d.board$platform$privateCache$state,d.board$platform$privateCache$probeResume,
        d.board$platform$privateCache$flushActive,d.board$platform$privateCache$pendingBypass);
#endif
}
#ifdef MIXED_READ_STORE_KERNEL
#ifdef INDEPENDENT_LINE_KERNEL
#error "select only one alternative steady kernel"
#endif
#ifndef MIXED_STORE_LINE_PERIOD
#error "pin MIXED_STORE_LINE_PERIOD to the exact mixed guest build"
#endif
static_assert(MIXED_STORE_LINE_PERIOD==16||MIXED_STORE_LINE_PERIOD==64,"unsupported mixed store period");
struct MixedRequestWitness {
    struct Store { uint64_t address,data,meta,cycle; };
    std::vector<Store> stores;
    Bytes executable;
    uint64_t physicalSourceReads=0,retiredSourceLoads=0;
    static void verifyStores(const std::vector<Store> &records) {
        check(records.size()==3072/MIXED_STORE_LINE_PERIOD,"mixed accepted scratch store count mismatch");
        for(size_t ordinal=0;ordinal<records.size();++ordinal){const auto &s=records[ordinal];
            check(s.address==0x84000000ULL+(ordinal&7)*8,"mixed accepted scratch store address mismatch");
            check(s.data==0x5a170000ULL+ordinal,"mixed accepted scratch store value mismatch");
            // requestMeta: write[0], atomic[1], atomicOp[6:2], size[8:7], mask[16:9].
            check((s.meta&3)==1&&((s.meta>>7)&3)==3&&((s.meta>>9)&255)==255,
                "mixed accepted scratch store mask/size mismatch");
        }
    }
    void physical(uint64_t events,uint64_t address,uint64_t data,uint64_t meta,uint64_t cycle) {
        if(!(events&(1ULL<<19)))return; // adapter physical request fire
        if(address>=0x80400000ULL&&address<0x80410000ULL){
            check(!(meta&3)&&!(address&7)&&((meta>>7)&3)==3,"mixed source request is not an aligned LD");
            ++physicalSourceReads;
        }
        if((meta&1)&&address>=0x84000000ULL&&address<0x84000040ULL)
            stores.push_back({address,data,meta,cycle});
    }
    void retire(uint64_t pc) {
        if(pc<ramBase||pc+4>ramBase+executable.size())return;
        uint32_t instruction=0;for(unsigned b=0;b<4;++b)instruction|=uint32_t(executable[pc-ramBase+b])<<(8*b);
        // This fixed RV64IM guest's only non-stack LDs inside the markers are
        // the eight source loads. ABI save/restore LDs use x2 and are excluded.
        if((instruction&0x707f)==0x3003&&((instruction>>15)&31)!=2)++retiredSourceLoads;
    }
    void verifyAndReport() const {
        verifyStores(stores);
        check(retiredSourceLoads==24576,"mixed architectural source load count mismatch");
        check(physicalSourceReads!=0,"mixed physical request observation absent");
        // Corrupt an early store which is overwritten later in the real run.
        // Final backing contents cannot witness this error; the event log can.
        for(unsigned mutation=0;mutation<3;++mutation){auto changed=stores;
            const char *expected;
            if(mutation==0){changed[3].data^=1;expected="mixed accepted scratch store value mismatch";}
            else if(mutation==1){changed[3].address^=8;expected="mixed accepted scratch store address mismatch";}
            else{changed.erase(changed.begin()+3);expected="mixed accepted scratch store count mismatch";}
            bool rejected=false;try{verifyStores(changed);}catch(const std::runtime_error&e){rejected=std::string(e.what())==expected;}
            check(rejected,"mixed intermediate store oracle failed to reject mutation");
        }
        std::cout<<"MIXED_ACCEPTED_REQUESTS architectural_source_loads="<<retiredSourceLoads
            <<" physical_source_reads="<<physicalSourceReads<<" physical_minus_retired="
            <<(int64_t(physicalSourceReads)-int64_t(retiredSourceLoads))<<" scratch_stores="<<stores.size()
            <<" source_read_scope=physical_accepts_in_ROI_including_speculation\n";
        std::cout<<"MIXED_INTERMEDIATE_STORE_ORACLE ordinal_address_data_mask_checked="<<stores.size()
            <<" overwritten_store_value_address_omission_negatives=3 DUT_fault_injection=0\n";
    }
};
#endif
#if defined(INDEPENDENT_LINE_KERNEL) || defined(MIXED_READ_STORE_KERNEL)
static constexpr unsigned expectedRegions=1;
#else
static constexpr unsigned expectedRegions=6;
#endif
struct SteadyObserver {
    Test *test;
#ifdef MIXED_READ_STORE_KERNEL
    MixedRequestWitness mixed;
#endif
    std::array<PerfCounts,6> counts{};
    std::array<uint64_t,6> peaks{}, occupiedSum{}, occupiedCycles{}, multiOccupiedCycles{}, occupiedPeak{}, refillPhasePeak{}, multiRefillCycles{};
    struct Traffic {
        uint64_t candidates=0, allocated=0, useful=0, errors=0, busyCycles=0;
        uint64_t missOwnerCycles=0, releaseOwnerCycles=0;
        uint64_t reads=0, readBytes=0, writes=0, writeBytes=0, rBeats=0, wBeats=0;
        void sample(SBoardSocGsim &d, const Test &test) {
            const unsigned event=d.get_dataPrefetchEvents();
            candidates+=(event>>0)&1; allocated+=(event>>1)&1; useful+=(event>>2)&1;
            errors+=(event>>3)&1; busyCycles+=(event>>4)&1;
            missOwnerCycles+=(event>>5)&7; releaseOwnerCycles+=(event>>8)&7;
            if(d.get_io$$ddrAxi$$ar$$valid()&&test.ddr.arReady){++reads;
                readBytes+=(uint64_t(d.get_io$$ddrAxi$$ar$$bits$$len())+1)<<d.get_io$$ddrAxi$$ar$$bits$$size();}
            if(d.get_io$$ddrAxi$$aw$$valid()&&test.ddr.awReady){++writes;
                writeBytes+=(uint64_t(d.get_io$$ddrAxi$$aw$$bits$$len())+1)<<d.get_io$$ddrAxi$$aw$$bits$$size();}
            rBeats+=test.ddr.rValid&&d.get_io$$ddrAxi$$r$$ready();
            wBeats+=test.ddr.wReady&&d.get_io$$ddrAxi$$w$$valid();
        }
        void report(unsigned region) const {
            std::cout<<"STEADY_PREFETCH region="<<region<<" candidates="<<candidates<<" allocated="<<allocated
                <<" useful="<<useful<<" errors="<<errors<<" busy_cycles="<<busyCycles
                <<" miss_owner_cycles="<<missOwnerCycles<<" release_owner_cycles="<<releaseOwnerCycles<<"\n";
            std::cout<<"STEADY_TRAFFIC region="<<region<<" reads="<<reads<<" read_bytes="<<readBytes
                <<" writes="<<writes<<" write_bytes="<<writeBytes<<" r_beats="<<rBeats<<" w_beats="<<wBeats<<"\n";
        }
    };
    std::array<Traffic,6> traffic{};
    unsigned region=0;
    bool active=false;
    static void sample(SBoardSocGsim &d,void *context) {
        auto &o=*static_cast<SteadyObserver*>(context);
        bool start=false,stop=false;
        for(unsigned lane=0;lane<2;++lane) {
            const bool valid=lane?d.get_io$$commit1():d.get_io$$commit0();
            const uint64_t pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();
            start|=valid&&pc==STEADY_START_PC;stop|=valid&&pc==STEADY_STOP_PC;
        }
        if(start){check(!o.active&&o.region<expectedRegions,"unexpected steady start marker");o.active=true;}
#ifdef MIXED_READ_STORE_KERNEL
        if(o.active){
            o.mixed.physical(d.get_dataPathEvents(),d.get_dataPathRequest9Address(),d.get_dataPathRequest9Data(),
                d.get_dataPathRequest9Meta(),o.test->cycles);
            if(d.get_io$$commit0())o.mixed.retire(d.get_io$$commit0Pc());
            if(d.get_io$$commit1())o.mixed.retire(d.get_io$$commit1Pc());
        }
#endif
        if(o.active){o.traffic[o.region].sample(d,*o.test);const auto occupied=occupiedMissOwners(d);check(occupied<=MODEL_MSHRS,"board occupied-owner bound");
            const auto refilling=refillPhaseOwners(d);o.refillPhasePeak[o.region]=std::max(o.refillPhasePeak[o.region],uint64_t(refilling));
            o.multiRefillCycles[o.region]+=refilling>1;o.occupiedSum[o.region]+=occupied;o.occupiedCycles[o.region]+=occupied!=0;o.multiOccupiedCycles[o.region]+=occupied>1;
            o.occupiedPeak[o.region]=std::max(o.occupiedPeak[o.region],uint64_t(occupied));o.counts[o.region].sample(d);o.peaks[o.region]=std::max(o.peaks[o.region],uint64_t(o.test->ddr.pendingReads.size()));}
        if(stop){check(o.active,"orphan steady stop marker");o.active=false;++o.region;}
    }
};
int main(int argc,char **argv) {try {
    check(argc==2,"usage: run steady.bin");
    const auto image=readFile(argv[1]);check(!image.empty()&&image.size()<0x200000,"guest image bounds");
    Bytes rom;word(rom,0x00200297);word(rom,0x10000337);word(rom,0x00700393);word(rom,0x00730123);
    word(rom,0x000280e7);word(rom,0x0000006f);
    MshrOccupancy::selfTest();Test t(rom);check(occupiedMissOwners(*t.dut)==0,"reset cache owner not empty");SteadyObserver observer{&t};t.observer=SteadyObserver::sample;t.observerContext=&observer;
#ifdef MIXED_READ_STORE_KERNEL
    observer.mixed.executable=image;
#endif
    for(size_t off=0;off<image.size();off+=8){uint64_t value=0;for(unsigned lane=0;lane<8&&off+lane<image.size();++lane)value|=uint64_t(image[off+lane])<<(8*lane);t.ddr.memory[uint32_t(off)]=value;}
    const uint64_t deadline=t.cycles+8000000;
    while(t.cycles<deadline){t.tick();if(t.cycles%1000000==0)std::cout<<"STEADY_PROGRESS cycles="<<t.cycles<<"\n"<<std::flush;
        check(t.received.size()<4096,"steady UART output bound");
        std::string output(t.received.begin(),t.received.end());
        check(output.find("FAIL")==std::string::npos,"guest steady oracle failed");
        if(output.find("STEADY PASS\r\n")!=std::string::npos)break;}
    const std::string output(t.received.begin(),t.received.end());
    check(output.find("STEADY PASS\r\n")!=std::string::npos,"steady guest timeout");
    check(observer.region==expectedRegions&&!observer.active,"missing steady timing regions");
#ifdef MIXED_READ_STORE_KERNEL
    observer.mixed.verifyAndReport();
#endif
    auto verifyBacking=[&]() {
#if defined(INDEPENDENT_LINE_KERNEL) || defined(MIXED_READ_STORE_KERNEL)
    for(uint32_t base:{0x80400000U})
#else
    for(uint32_t base:{0x80400000U,0x81400040U})
#endif
    for(unsigned i=0;i<65536/8;++i){
        auto p=t.ddr.memory.find(base-ramBase+i*8);
        const uint64_t expected=0x10203040ULL+i;
        check(p!=t.ddr.memory.end()&&p->second==expected,"steady independent backing mismatch");}
#if !defined(INDEPENDENT_LINE_KERNEL) && !defined(MIXED_READ_STORE_KERNEL)
    for(unsigned i=0;i<1024;++i){auto p=t.ddr.memory.find(0x83000000U-ramBase+i*64);
        check(p!=t.ddr.memory.end()&&p->second==0x83000000ULL+((i+257)&1023)*64,"steady independent chain mismatch");}
#endif
#ifdef MIXED_READ_STORE_KERNEL
    // Independent closed-form expectation: the last eight ordinal stores land
    // in words 0..7 because both qualified store counts are multiples of eight.
    for(unsigned word=0;word<8;++word){auto p=t.ddr.memory.find(0x84000000U-ramBase+word*8);
        const uint64_t expected=0x5a170000ULL+(3072/MIXED_STORE_LINE_PERIOD)-8+word;
        check(p!=t.ddr.memory.end()&&p->second==expected,"mixed independent scratch mismatch");}
#endif
    };
    verifyBacking();
    const uint32_t mutationAddress=0x80400000U-ramBase;
    const uint64_t saved=t.ddr.memory.at(mutationAddress);
    t.ddr.memory.at(mutationAddress)=saved^1ULL;
    bool rejected=false;
    try { verifyBacking(); } catch(const std::runtime_error &e) { rejected=std::string(e.what())=="steady independent backing mismatch"; }
    t.ddr.memory.at(mutationAddress)=saved;
    check(rejected,"software backing oracle failed to reject mutation");
    verifyBacking();
    std::cout<<"STEADY_ORACLE_SENSITIVITY mutation_detected=1 restored_verified=1 DUT_fault_injection=0\n";
#ifdef MIXED_READ_STORE_KERNEL
    for(unsigned word=0;word<8;++word){
        const uint32_t address=0x84000000U-ramBase+word*8;
        const uint64_t original=t.ddr.memory.at(address);
        t.ddr.memory.at(address)=original^1ULL;
        bool scratchRejected=false;
        try{verifyBacking();}catch(const std::runtime_error &e){scratchRejected=std::string(e.what())=="mixed independent scratch mismatch";}
        t.ddr.memory.at(address)=original;
        check(scratchRejected,"software scratch oracle failed to reject mutation");
    }
    verifyBacking();
    check(output.find("store_line_period="+std::to_string(MIXED_STORE_LINE_PERIOD)+" scratch_stores="+
        std::to_string(3072/MIXED_STORE_LINE_PERIOD)+" ")!=std::string::npos,"mixed guest/host period mismatch");
    std::cout<<"MIXED_ORACLE_SENSITIVITY scratch_mutations_detected=8 restored_verified=1 DUT_fault_injection=0\n";
    std::cout<<"MIXED_WORKLOAD_CONTRACT expected_source_loads=24576 expected_scratch_stores="<<(3072/MIXED_STORE_LINE_PERIOD)
        <<" store_line_period="<<MIXED_STORE_LINE_PERIOD<<" scratch_base=0x84000000 scratch_words=8\n";
#endif
    std::cout<<output;
    std::cout<<"STEADY_INTERVALS host=rdtime-retirement-inclusive guest=rdtime-difference occupancy=generated-register-sample-including-completed-response-owners\n";
#ifdef MIXED_READ_STORE_KERNEL
    const char *names[]={"mixed_read_store_64KiB_3passes"};
#elif defined(INDEPENDENT_LINE_KERNEL)
    const char *names[]={"independent_line_64KiB_3passes"};
#else
    const char *names[]={"read_64KiB_3passes","write_kernel","write_flush_tail","copy_kernel","copy_flush_tail","dependent_chase_3072hops"};
#endif
    for(unsigned i=0;i<expectedRegions;++i){observer.counts[i].report(names[i]);std::cout<<"STEADY_AXI region="<<i<<" peak_read_ids="<<observer.peaks[i]<<" occupied_peak="<<observer.occupiedPeak[i]<<" occupied_entry_cycles="<<observer.occupiedSum[i]
            <<" any_occupied_cycles="<<observer.occupiedCycles[i]<<" multi_occupied_cycles="<<observer.multiOccupiedCycles[i]<<" acquire_fill_peak="<<observer.refillPhasePeak[i]<<" multi_acquire_fill_cycles="<<observer.multiRefillCycles[i]<<"\n";observer.traffic[i].report(i);}
    std::cout<<"BOARD_MEMORY_TRAFFIC reads="<<t.ddr.reads<<" writes="<<t.ddr.writes<<" r_beats="<<t.ddr.rBeats<<" w_beats="<<t.ddr.wBeats<<"\n";
    std::cout<<"BOARD_MEMORY_STEADY_PASS cycles="<<t.cycles<<" working_set=65536 repetitions=3 regions="<<expectedRegions<<"\n";
    return 0;
}catch(const std::exception &e){std::cerr<<"BOARD_MEMORY_STEADY_FAIL "<<e.what()<<"\n";return 1;}}
