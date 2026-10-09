// Reuse-only observer: no generated model edits and no testbench request injection.
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
#define DATA_PATH_OWNERSHIP_PROBES
#include "backend_observer.h"
#include "performance_observer.h"
#include "cpu_hot_bandwidth.h"
#include "cpu_hot_bandwidth_symbols.h"
#include <map>
#include <optional>
#include <limits>

namespace {
using P = DataPathSample;
using Key = std::pair<uint64_t,unsigned>;
Key key(BackendToken t) { return {t.tag,t.index}; }
constexpr uint64_t sourceBase=0x80400000, destinationBase=0x80402000, signatureBase=0x80600000;
constexpr uint64_t readSeed=0x10203040, writeSeed=0x5a170000;
struct Distribution {
    uint64_t count=0,sum=0,minimum=std::numeric_limits<uint64_t>::max(),maximum=0;
    std::map<uint64_t,uint64_t> histogram;
    void add(uint64_t n) { ++count;sum+=n;minimum=std::min(minimum,n);maximum=std::max(maximum,n);++histogram[n]; }
    void report(const std::string &name) const {
        std::cout<<"HOT_DISTRIBUTION name="<<name<<" count="<<count<<" sum="<<sum<<" min="<<(count?minimum:0)
            <<" max="<<maximum<<" mean="<<(count?double(sum)/count:0)<<" histogram=";
        bool comma=false;for(auto [n,c]:histogram){if(comma)std::cout<<",";comma=true;std::cout<<n<<":"<<c;}std::cout<<"\n";
    }
};
struct Stamp {
    std::optional<uint64_t> start,fifo,fast,physical,reply,lsuReply,result;
    bool measured=false,write=false;
};
struct Witness { uint64_t address,data,meta; };
struct ReplyWitness { uint64_t expected,actual; };
struct Metrics {
    PerfCounts perf;
    uint64_t cpuStarts=0,fifoEnqueues=0,fifoDequeues=0,fastStores=0,lsuReplies=0,results=0;
    uint64_t physicalRequests=0,physicalReplies=0,reads=0,writes=0,lsuPeak=0,physicalPeak=0,sbPeak=0;
    uint64_t startResultSameCycle=0,fullSlotReplacement=0,fullSlots=0,fullSlotsResult=0,fullSlotsStart=0;
    uint64_t sbFull=0,fifoBackpressure=0,capacityBlocked=0,physicalMultiple=0,axiReads=0,axiWrites=0;
    std::array<uint64_t,8> storeCause{};
    std::array<uint64_t,9> peak{},occupancy{};
    std::map<std::string,uint64_t> buckets;
    std::map<std::string,Distribution> gaps;
    std::map<std::string,uint64_t> previous;
    void event(const std::string &name,bool fire,uint64_t cycle) {
        if(!fire)return;
        auto it=previous.find(name);if(it!=previous.end())gaps[name].add(cycle-it->second);previous[name]=cycle;
    }
    void sample(SBoardSocGsim &d,Test &t,const BackendSample &b,const P &p,const BackendOwnershipLedger &ledger,
                const HotDataPathOwnershipLedger &data,uint64_t cycle) {
        perf.sample(d);cpuStarts+=b.bit(3);fifoEnqueues+=b.enq();fifoDequeues+=b.deq();fastStores+=p.bit(P::fastAccept);
        lsuReplies+=b.reply();results+=b.bit(26)&&b.bit(27);
        physicalRequests+=p.bit(P::physicalRequest);physicalReplies+=p.bit(P::physicalReply);
        if(p.bit(P::physicalRequest)){if(p.request[P::physical].write())++writes;else ++reads;}
        lsuPeak=std::max<uint64_t>(lsuPeak,b.live[0]+b.live[1]);
        const bool full=b.live[0]&&b.live[1],result=b.bit(26)&&b.bit(27);
        startResultSameCycle+=b.bit(3)&&result;fullSlotReplacement+=full&&b.bit(3)&&result;
        fullSlots+=full;fullSlotsResult+=full&&result;fullSlotsStart+=full&&b.bit(3);
        physicalPeak=std::max<uint64_t>(physicalPeak,data.physicalPending.size());physicalMultiple+=data.physicalPending.size()>1;
        sbPeak=std::max<uint64_t>(sbPeak,p.count[0]);check(p.count[0]<=HOT_SB_ENTRIES,"selected StoreBuffer capacity exceeded");sbFull+=p.count[0]==HOT_SB_ENTRIES;
        fifoBackpressure+=b.bit(20)&&!b.bit(21);capacityBlocked+=p.bit(P::capacityBlocked);++storeCause[b.storeCause];
        for(unsigned i=0;i<9;++i){peak[i]=std::max<uint64_t>(peak[i],p.count[i]);occupancy[i]+=p.count[i];}
        axiReads+=d.get_io$$ddrAxi$$ar$$valid()&&t.ddr.arReady;axiWrites+=d.get_io$$ddrAxi$$aw$$valid()&&t.ddr.awReady;
        auto bucket=ledger.category(b);
        if(bucket=="issued_memory_downstream_unknown"){auto refined=data.category(b.head,b,p);if(!refined.empty())bucket=refined;}
        ++buckets[bucket];
        event("cpu_start",b.bit(3),cycle);event("fifo_enqueue",b.enq(),cycle);
        event("fast_store",p.bit(P::fastAccept),cycle);event("physical_request",p.bit(P::physicalRequest),cycle);
        event("physical_reply",p.bit(P::physicalReply),cycle);event("lsu_reply",b.reply(),cycle);
        event("result",b.bit(26)&&b.bit(27),cycle);
    }
    void report(const std::string &name) {
        perf.report(name.c_str());
        std::cout<<"HOT_PIPELINE name="<<name<<" cpu_starts="<<cpuStarts<<" fifo_enqueues="<<fifoEnqueues
            <<" fifo_dequeues="<<fifoDequeues<<" fast_stores="<<fastStores<<" lsu_replies="<<lsuReplies<<" results="<<results
            <<" physical_requests="<<physicalRequests<<" physical_replies="<<physicalReplies<<" reads="<<reads<<" writes="<<writes
            <<" lsu_peak="<<lsuPeak<<" physical_peak="<<physicalPeak<<" sb_peak="<<sbPeak<<" sb_full_cycles="<<sbFull
            <<" sb_entries="<<HOT_SB_ENTRIES<<" same_cycle_start_result="<<startResultSameCycle
            <<" full_slot_replacement="<<fullSlotReplacement<<" full_slots_cycles="<<fullSlots
            <<" full_slots_result_cycles="<<fullSlotsResult<<" full_slots_start_cycles="<<fullSlotsStart
            <<" fifo_backpressure_cycles="<<fifoBackpressure<<" capacity_blocked_cycles="<<capacityBlocked
            <<" multiple_physical_cycles="<<physicalMultiple<<" axi_read_bursts="<<axiReads<<" axi_write_bursts="<<axiWrites;
        for(unsigned i=0;i<8;++i)std::cout<<" store_cause_"<<i<<"="<<storeCause[i];
        for(unsigned i=0;i<9;++i)std::cout<<" count_"<<i<<"_peak="<<peak[i]<<" count_"<<i<<"_sum="<<occupancy[i];
        std::cout<<"\n";
        uint64_t total=0;for(auto [bucket,n]:buckets){total+=n;std::cout<<"HOT_BUCKET name="<<name<<" category="<<bucket<<" cycles="<<n<<"\n";}
        check(total==perf.cycles,"cycle bucket conservation");
        for(auto &[stage,dist]:gaps)dist.report(name+"_"+stage+"_gap");
    }
};
struct Observer {
    Test *test=nullptr; Bytes image;
    BackendOwnershipLedger backend; HotDataPathOwnershipLedger data;
    std::map<Key,Stamp> stamps;
    std::map<uint64_t,uint64_t> memory;
    struct Pending { uint64_t expected,address;bool write; };
    std::deque<Pending> pending;
    std::vector<Witness> writes,reads;
    std::vector<ReplyWitness> readReplies;
    std::array<Metrics,3> metrics{};
    int phase=-1;bool finished=false;uint64_t cycle=0,begin=0,kernelEnd=0,drainEnd=0,completeEnd=0;
    uint64_t architecturalLoads=0,architecturalStores=0,physicalSourceReads=0,physicalDestinationWrites=0;
    uint64_t negativeChecks=0;
    static void sample(SBoardSocGsim &d,void *context) { static_cast<Observer*>(context)->sample(d); }
    bool buffer(uint64_t address) const {return (address>=sourceBase&&address<sourceBase+HOT_BYTES)||
        (address>=destinationBase&&address<destinationBase+HOT_BYTES);}
    static void verifyWrites(const std::vector<Witness> &v) {
        const uint64_t expectedCount=HOT_OP==0?0:HOT_BYTES/8*HOT_REPS;
        check(v.size()==expectedCount,"hot write count mismatch");
        for(size_t i=0;i<v.size();++i){const auto &w=v[i];const uint64_t word=i%(HOT_BYTES/8);
            check(w.address==destinationBase+8*word,"hot write address mismatch");
            check(w.data==(HOT_OP==1?writeSeed:readSeed)+word,"hot write data mismatch");
            check((w.meta&3)==1&&((w.meta>>7)&3)==3&&((w.meta>>9)&255)==255&&!(w.meta&(3ULL<<17)),"hot write mask/class mismatch");}
    }
    static void verifyReads(const std::vector<Witness> &v) {
        check(v.size()==(HOT_OP==1?0:HOT_BYTES/8*HOT_REPS),"hot read count mismatch");
        for(size_t i=0;i<v.size();++i){const auto &r=v[i];
            check(r.address==sourceBase+8*(i%(HOT_BYTES/8)),"hot read address mismatch");
            check((r.meta&3)==0&&((r.meta>>7)&3)==3&&((r.meta>>9)&255)==255&&!(r.meta&(3ULL<<17)),"hot read mask/class mismatch");}
    }
    static void verifyReplies(const std::vector<ReplyWitness> &v) {
        for(auto w:v)check(w.actual==w.expected,"hot read data mismatch");
    }
    void sample(SBoardSocGsim &d) {
        auto b=BackendObserver::read(d);auto p=BackendObserver::readData(d);
        if(b.reset){data.advance(b,p,backend);backend.advance(b);++cycle;return;}
        check(!d.get_io$$trap$$valid(),"unexpected guest trap");
        bool endKernel=false,endDrain=false,endComplete=false;
        unsigned included=0;
        for(unsigned lane=0;lane<2;++lane){bool valid=lane?d.get_io$$commit1():d.get_io$$commit0();
            uint64_t pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();if(!valid)continue;
            if(pc==HOT_BEGIN){check(phase==-1,"duplicate begin marker");phase=0;begin=cycle;}
            if(phase>=0&&phase<3)++included;
            if(phase==0){
                check(pc>=ramBase&&pc+4<=ramBase+image.size(),"retired PC outside guest");
                const uint32_t insn=wordAt(image,pc-ramBase);
                architecturalLoads+=(insn&0x707f)==0x3003;architecturalStores+=(insn&0x707f)==0x3023;}
            if(pc==HOT_KERNEL_END){check(phase==0,"kernel marker order");kernelEnd=cycle;endKernel=true;}
            if(pc==HOT_DRAIN_END){check(phase==1,"drain marker order");drainEnd=cycle;endDrain=true;}
            if(pc==HOT_COMPLETE_END){check(phase==2,"completion marker order");completeEnd=cycle;endComplete=true;}
            if(pc==HOT_DONE){check(phase==3,"done before completion");finished=true;}
        }
        if(b.bit(3))stamps[key(b.start)].start=cycle;
        if(b.enq())stamps[key(b.request)].fifo=cycle;
        if(p.bit(P::fastAccept))stamps[key(b.head)].fast=cycle;
        if(b.reply())stamps[key(b.slots[b.returnSlot])].lsuReply=cycle;
        if(b.bit(26)&&b.bit(27))stamps[key(b.complete)].result=cycle;
        if(p.bit(P::physicalReply)){
            check(!pending.empty()&&!data.physicalPending.empty(),"physical reply without owner");
            auto owner=pending.front();pending.pop_front();
            auto &stamp=stamps[key(data.physicalPending.front().token)];stamp.reply=cycle;
            check(p.reply[0].flags==0,"physical reply fault");
            if(!owner.write&&buffer(owner.address)){
                readReplies.push_back({owner.expected,p.reply[0].data});check(owner.expected==p.reply[0].data,"hot read data mismatch");}
        }
        if(p.bit(P::physicalRequest)){
            check(!data.checked.empty(),"physical request without checked token");
            auto r=p.request[P::physical];auto &stamp=stamps[key(data.checked.front().token)];
            stamp.physical=cycle;stamp.write=r.write();stamp.measured=phase==0||phase==1;
            check(!r.virtualized()&&!r.atomic(),"guest unexpectedly used VM/atomic data");
            const uint64_t aligned=r.address&~7ULL,expected=memory.count(aligned)?memory.at(aligned):0;
            if(buffer(r.address)){
                check(!(r.address&7)&&((r.meta>>7)&3)==3&&((r.meta>>9)&255)==255,"hot aligned LD/SD mask mismatch");
                if(stamp.measured){
                    if(r.write()){check(r.address>=destinationBase,"source buffer was written");writes.push_back({r.address,r.data,r.meta});++physicalDestinationWrites;}
                    else {check(HOT_OP!=1&&r.address>=sourceBase&&r.address<sourceBase+HOT_BYTES,"unexpected timed source load address");reads.push_back({r.address,r.data,r.meta});++physicalSourceReads;}}
            } else if(stamp.measured)check(false,"nonbuffer physical request in timed kernel/drain");
            pending.push_back({expected,r.address,r.write()});
            if(r.write()){uint64_t value=expected;for(unsigned byte=0;byte<8;++byte)if((r.meta>>(9+byte))&1){const uint64_t mask=255ULL<<(8*byte);value=(value&~mask)|(r.data&mask);}memory[aligned]=value;}
        }
        if(phase>=0&&phase<3){auto &m=metrics[phase];const uint64_t retired=m.perf.retired;m.sample(d,*test,b,p,backend,data,cycle);
            // Marker-cycle instruction count is lane-exact; cycle windows remain inclusive.
            m.perf.retired=retired+included;--m.perf.commits[b.commits];++m.perf.commits[included];}
        data.advance(b,p,backend);backend.advance(b);
        if(endKernel)phase=1;if(endDrain)phase=2;if(endComplete)phase=3;
        ++cycle;
    }
    void initialize(Test &t,const Bytes &bytes) {
        test=&t;image=bytes;
        auto put=[&](uint64_t address,uint64_t value){memory[address]=value;t.ddr.memory[uint32_t(address-ramBase)]=value;};
        for(size_t off=0;off<image.size();off+=8){uint64_t value=0;for(unsigned byte=0;byte<8&&off+byte<image.size();++byte)value|=uint64_t(image[off+byte])<<(8*byte);put(ramBase+off,value);}
        for(unsigned i=0;i<HOT_BYTES/8;++i){put(sourceBase+8*i,readSeed+i);put(destinationBase+8*i,~(readSeed+i));}
        for(unsigned i=0;i<4;++i)put(signatureBase+8*i,0xdeadbeef);
    }
    void verifyBacking() const {
        for(unsigned i=0;i<HOT_BYTES/8;++i){
            check(test->ddr.memory.at(uint32_t(sourceBase-ramBase+8*i))==readSeed+i,"hot source backing mismatch");
            const uint64_t value=HOT_OP==0?~(readSeed+i):(HOT_OP==1?writeSeed:readSeed)+i;
            check(test->ddr.memory.at(uint32_t(destinationBase-ramBase+8*i))==value,"hot destination backing mismatch");}
        const uint64_t words=HOT_BYTES/8;
        const uint64_t sum=HOT_OP==0?(words*readSeed+words*(words-1)/2)*HOT_REPS:0;
        const std::array<uint64_t,4> expected{sum,HOT_BYTES,HOT_OP,HOT_REPS};
        for(unsigned i=0;i<expected.size();++i)check(test->ddr.memory.at(uint32_t(signatureBase-ramBase+8*i))==expected[i],"hot architectural signature mismatch");
    }
    template<class F> void rejects(F f,const std::string &expected) {
        bool rejected=false;try{f();}catch(const std::runtime_error &e){rejected=e.what()==expected;}
        check(rejected,"hot negative oracle did not reject expected corruption");++negativeChecks;
    }
    void verify() {
        check(finished&&phase==3,"hot bounded guest did not complete");
        check(pending.empty()&&data.physicalPending.empty()&&data.storeOwners.empty()&&data.stores.empty()&&backend.requests.empty()&&backend.responses.empty(),"done before data-path drain");
        const uint64_t count=HOT_BYTES/8*HOT_REPS;
        check(architecturalLoads==(HOT_OP==1?0:count),"architectural load count mismatch");
        check(architecturalStores==(HOT_OP==0?0:count),"architectural store count mismatch");
        check(physicalSourceReads>=architecturalLoads,"missing accepted source reads");
        for(unsigned i=0;i<2;++i)check(metrics[i].perf.readMiss==0&&metrics[i].perf.writeMiss==0,"timed workload is not all-hit");
        verifyWrites(writes);verifyReads(reads);verifyReplies(readReplies);verifyBacking();
        if(!reads.empty())for(unsigned mutation=0;mutation<3;++mutation){auto altered=reads;const char *error;
            if(mutation==0){altered[3].address^=8;error="hot read address mismatch";}
            else if(mutation==1){altered[3].meta^=1ULL<<9;error="hot read mask/class mismatch";}
            else{altered.erase(altered.begin()+3);error="hot read count mismatch";}
            rejects([&]{verifyReads(altered);},error);}
        if(!writes.empty())for(unsigned mutation=0;mutation<4;++mutation){auto altered=writes;const char *error;
            if(mutation==0){altered[3].address^=8;error="hot write address mismatch";}
            else if(mutation==1){altered[3].data^=1;error="hot write data mismatch";}
            else if(mutation==2){altered[3].meta^=1ULL<<9;error="hot write mask/class mismatch";}
            else{altered.erase(altered.begin()+3);error="hot write count mismatch";}
            rejects([&]{verifyWrites(altered);},error);}
        auto altered=readReplies;check(!altered.empty(),"no independent read reply witnesses");altered[0].actual^=1;
        rejects([&]{verifyReplies(altered);},"hot read data mismatch");
        for(auto [address,error]:{std::pair{sourceBase,"hot source backing mismatch"},std::pair{destinationBase,"hot destination backing mismatch"},std::pair{signatureBase,"hot architectural signature mismatch"}}){
            auto &word=test->ddr.memory.at(uint32_t(address-ramBase));word^=1;rejects([&]{verifyBacking();},error);word^=1;}
        verifyBacking();
    }
    void report() {
        for(unsigned i=0;i<3;++i)metrics[i].report(i==0?"kernel":i==1?"drain_tail":"flush_tail");
        std::map<std::string,Distribution> lifetimes;
        for(auto &[id,s]:stamps)if(s.measured){
            auto add=[&](const char *name,const std::optional<uint64_t> &a,const std::optional<uint64_t> &b){if(a&&b){check(*b>=*a,"stage lifetime ran backward");lifetimes[name].add(*b-*a);}};
            if(s.fast){add("fast_accept_to_physical",s.fast,s.physical);add("fast_accept_to_physical_reply",s.fast,s.reply);}
            else if(s.write){add("store_cpu_start_to_fifo",s.start,s.fifo);add("store_fifo_to_physical",s.fifo,s.physical);add("store_fifo_to_physical_reply",s.fifo,s.reply);add("store_cpu_start_to_result",s.start,s.result);add("store_fifo_to_lsu_ack",s.fifo,s.lsuReply);}
            else{add("cpu_start_to_fifo",s.start,s.fifo);add("fifo_to_physical",s.fifo,s.physical);
                add("cpu_start_to_result",s.start,s.result);add("physical_reply_to_lsu_reply",s.reply,s.lsuReply);add("lsu_reply_to_result",s.lsuReply,s.result);}
            add("physical_to_reply",s.physical,s.reply);
        }
        for(auto &[name,dist]:lifetimes)dist.report(name);
        const uint64_t payload=uint64_t(HOT_BYTES)*HOT_REPS,kernelCycles=kernelEnd-begin+1,drainCycles=drainEnd-kernelEnd,flushCycles=completeEnd-drainEnd;
        std::cout<<"HOT_RESULT op="<<(HOT_OP==0?"read":HOT_OP==1?"write":"copy")<<" buffer_bytes="<<HOT_BYTES<<" footprint_bytes="<<(HOT_OP==2?2*HOT_BYTES:HOT_BYTES)
            <<" warmup_footprint_bytes="<<2*HOT_BYTES<<" reps="<<HOT_REPS<<" payload_bytes="<<payload<<" kernel_cycles="<<kernelCycles<<" drain_tail_cycles="<<drainCycles
            <<" flush_tail_cycles="<<flushCycles<<" complete_cycles="<<kernelCycles+drainCycles+flushCycles
            <<" payload_MiB_s_100MHz="<<double(payload)*100000000/kernelCycles/1048576
            <<" complete_payload_MiB_s_100MHz="<<double(payload)*100000000/(kernelCycles+drainCycles+flushCycles)/1048576
            <<" logical_rw_MiB_s_100MHz="<<double(payload)*(HOT_OP==2?2:1)*100000000/kernelCycles/1048576
            <<" architectural_loads="<<architecturalLoads<<" architectural_stores="<<architecturalStores
            <<" physical_source_reads="<<physicalSourceReads<<" physical_destination_writes="<<physicalDestinationWrites
            <<" read_physical_minus_architectural="<<int64_t(physicalSourceReads)-int64_t(architecturalLoads)
            <<" negative_oracle_checks="<<negativeChecks<<" board_measurement=0\n";
        data.report();std::cout<<"HOT_PASS total_cycles="<<cycle<<" owner_checks="<<backend.checks<<" physical_read_data_checks="<<readReplies.size()<<"\n";
    }
};
}
int main(int argc,char **argv) {try{
    check(argc==2,"usage: cpu_hot_bandwidth guest.bin");Observer observer;const auto image=readFile(argv[1]);
    check(!image.empty()&&image.size()<0x10000,"guest image bounds");
    Bytes rom;word(rom,0x00200297);word(rom,0x10000337);word(rom,0x00700393);word(rom,0x00730123);word(rom,0x000280e7);word(rom,0x0000006f);
    Test test(rom,Observer::sample,&observer);observer.initialize(test,image);
    while(!observer.finished&&test.cycles<300000){test.running=true;test.tick();check(test.received.empty(),"unexpected UART output");}
    observer.verify();observer.report();return 0;
}catch(const std::exception &e){std::cerr<<"HOT_FAIL "<<e.what()<<"\n";return 1;}}
