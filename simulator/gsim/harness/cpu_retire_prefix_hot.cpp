// Older-prefix-only fork of frozen CPU hot oracle SHA256 9308ca677c8d9e1fc19a24b1da6fb2f24a4912d63dd2f6cbdd853f0f0d06b8b4.
// Adds bounded four-word guard admission and cancel-before-LSU-return proof.
// Reuse-only observer: no generated model edits and no testbench request injection.
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
#define DATA_PATH_OWNERSHIP_PROBES
#include "backend_observer.h"
#include "performance_observer.h"
#include "cpu_flow_bandwidth.h"
#include "cpu_hot_bandwidth_symbols.h"
#include <map>
#include <optional>
#include <limits>

namespace {
std::string injection;
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
    std::optional<uint64_t> start,fifo,fast,physical,reply,lsuReply,result,cancel;
    bool retired=false;
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
                const FlowDataPathOwnershipLedger &data,uint64_t cycle) {
        perf.sample(d);cpuStarts+=b.bit(3);fifoEnqueues+=b.enq();fifoDequeues+=b.deq();fastStores+=p.bit(P::fastAccept);
        lsuReplies+=b.reply();results+=b.bit(26)&&b.bit(27);
        physicalRequests+=p.bit(P::physicalRequest);physicalReplies+=p.bit(P::physicalReply);
        if(p.bit(P::physicalRequest)){if(p.request[P::physical].write())++writes;else ++reads;}
        lsuPeak=std::max<uint64_t>(lsuPeak,b.liveCount());
        const bool full=b.liveCount()==BackendSample::ownerCount,result=b.bit(26)&&b.bit(27);
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
            <<" lsu_entries="<<BackendSample::ownerCount<<" sb_entries="<<HOT_SB_ENTRIES<<" same_cycle_start_result="<<startResultSameCycle
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
    BackendOwnershipLedger backend; FlowDataPathOwnershipLedger data;
    std::map<Key,Stamp> stamps;
    std::map<uint64_t,uint64_t> memory;
    struct Pending { uint64_t expected,address;bool write; };
    std::deque<Pending> pending;
    std::vector<Witness> writes,reads;
    std::vector<ReplyWitness> readReplies;
    std::map<Key,Witness> guardReads;
    uint64_t physicalGuardReads=0;
    std::array<Metrics,3> metrics{};
    unsigned observedLiveOwners=0;bool observedStart=false;
    int phase=-1;bool finished=false;uint64_t cycle=0,begin=0,kernelEnd=0,drainEnd=0,completeEnd=0;
    uint64_t architecturalLoads=0,architecturalStores=0,physicalSourceReads=0,physicalDestinationWrites=0;
    uint64_t negativeChecks=0, kernelPcTrace=1469598103934665603ULL, kernelRetired=0;
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
    static void verifyGuardTraffic(uint64_t accepted) {
        check(accepted<=HOT_REPS*BackendSample::ownerCount,
              "speculative guard traffic exceeds four-owner loop bound");
    }
    static void verifyGuardRequest(const DataPathRequest &r) {
        // This fork is only qualified for the four-owner older-prefix pair.
        // The first four unrolled LDs may enter before the loop-exit recovery.
        // No other address, class, width, mask or privileged access is admitted.
        static_assert(BackendSample::ownerCount==4);
        check(HOT_OP!=1&&!r.write()&&!r.atomic()&&!r.virtualized()&&!(r.meta&(1ULL<<18))&&
              !(r.address&7)&&((r.meta>>7)&3)==3&&((r.meta>>9)&255)==255&&
              r.address>=sourceBase+HOT_BYTES&&r.address<sourceBase+HOT_BYTES+32,
              "nonbuffer physical request outside speculative RAM guard");
    }
    static void verifyGuardOwner(const Stamp &s) {
        check(s.cancel.has_value(),"speculative guard read lacks cancellation");
        check(!s.retired,"speculative guard read retired");
        check(!s.result,"speculative guard read produced completion");
        check(s.start&&s.fifo&&s.physical&&s.reply&&s.lsuReply,
              "speculative guard read did not fully drain");
        check(*s.start<=*s.fifo&&*s.fifo<=*s.physical&&*s.physical<=*s.reply&&
              *s.reply<=*s.lsuReply&&*s.start<=*s.cancel&&*s.cancel<=*s.lsuReply,
              "speculative guard read stage order mismatch");
    }
    static void verifyReplies(const std::vector<ReplyWitness> &v) {
        for(auto w:v)check(w.actual==w.expected,"hot read data mismatch");
    }
    void sample(SBoardSocGsim &d) {
        auto b=BackendObserver::read(d);auto p=BackendObserver::readData(d);
        observedLiveOwners=b.liveCount();observedStart=b.bit(3);
        if(injection=="--inject-reserve-guard")p.events^=1ULL<<P::reserveGuardMatch;
        data.flowEvents=d.get_cpuFlowEvents();data.ingressAuth=d.get_cpuFlowIngressAuth();
        data.checkedAuth=d.get_cpuFlowCheckedAuth();data.checkedAddress=d.get_cpuFlowCheckedAddress();
        data.checkedData=d.get_cpuFlowCheckedData();data.checkedHeadAuth=d.get_cpuFlowCheckedHeadAuth();
        data.physicalAuth=d.get_cpuFlowPhysicalAuth();
        if(injection=="--inject-physical-fingerprint"&&p.bit(P::physicalRequest))p.request[P::physical].address^=8;
        if(injection=="--inject-route"&&p.bit(P::virtualRequest))data.flowEvents^=1ULL<<1;
        if(injection=="--inject-virtual-enqueue"&&p.bit(P::virtualRequest))data.flowEvents^=1ULL<<0;
        if(injection=="--inject-checked-enqueue"&&data.flow(3))data.flowEvents^=1ULL<<3;
        if(injection=="--inject-authorization"&&data.flow(3))data.checkedAuth^=1ULL<<52;
        if(injection=="--inject-private-metadata"&&p.bit(P::physicalRequest))data.physicalAuth^=1ULL<<19;
        if(injection=="--inject-return-token"&&b.reply())b.slots[b.returnSlot].tag^=1;
        if constexpr(BackendSample::ownerCount==4) {
            if(injection=="--inject-upper-live"&&b.live[2])b.live[2]=false;
            if(injection=="--inject-upper-token"&&b.live[3])b.slots[3].tag^=1ULL<<40;
        }
        if(b.reset){data.advance(b,p,backend);backend.advance(b);++cycle;return;}
        check(p.bit(P::reserveGuardMatch),"test-only capacity guard differs from production");
        check(!d.get_io$$trap$$valid(),"unexpected guest trap");
        for(unsigned i=0;i<BackendSample::ownerCount;++i)if(b.live[i]&&b.cancelled[i]) {
            auto &stamp=stamps[key(b.slots[i])];
            if(!stamp.cancel)stamp.cancel=cycle;
            check(!stamp.retired,"cancellation of retired full token");
        }
        bool endKernel=false,endDrain=false,endComplete=false;
        unsigned included=0;
        for(unsigned lane=0;lane<2;++lane){bool valid=lane?d.get_io$$commit1():d.get_io$$commit0();
            uint64_t pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();if(!valid)continue;
            // Passive, hash-bound generated observation. The wrapper exports the
            // first ROB token; the unchanged 16-entry ROB retires a prefix.
            const uint64_t commitTag=lane?
                d.board$platform$core$core$core$backend$ledger$io$$commit$$bits$$token$$tag_1:
                d.board$platform$core$core$core$backend$ledger$io$$commit$$bits$$token$$tag_0;
            const BackendToken commitToken{commitTag,(b.head.index+lane)&15U};
            if(!lane)check(commitToken==b.head,"retirement full-token probe/head mismatch");
            auto &committed=stamps[key(commitToken)];
            check(!committed.retired&&!committed.cancel,"duplicate or canceled full-token retirement");
            committed.retired=true;
            if(pc==HOT_BEGIN){check(phase==-1,"duplicate begin marker");phase=0;begin=cycle;}
            if(phase>=0&&phase<3)++included;
            if(phase==0&&!endKernel){
                kernelPcTrace^=pc;kernelPcTrace*=1099511628211ULL;++kernelRetired;
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
            if(!owner.write){
                readReplies.push_back({owner.expected,p.reply[0].data});check(owner.expected==p.reply[0].data,"hot read data mismatch");}
        }
        if(p.bit(P::physicalRequest)){
            check(!data.checked.empty(),"physical request without checked token");
            auto r=p.request[P::physical];auto &stamp=stamps[key(data.checked.front().token)];
            stamp.physical=cycle;stamp.write=r.write();stamp.measured=phase==0||phase==1;
            check(!r.virtualized()&&!r.atomic(),"guest unexpectedly used VM/atomic data");
            const uint64_t aligned=r.address&~7ULL,expected=memory.count(aligned)?memory.at(aligned):0;
            if(stamp.measured) {
                check(!(r.address&7)&&((r.meta>>7)&3)==3&&((r.meta>>9)&255)==255,
                      "hot aligned LD/SD mask mismatch");
                if(r.write()) {
                    check(HOT_OP!=0&&r.address>=destinationBase&&r.address<destinationBase+HOT_BYTES,
                          "unexpected timed destination store address");
                    writes.push_back({r.address,r.data,r.meta});++physicalDestinationWrites;
                } else if(r.address>=sourceBase&&r.address<sourceBase+HOT_BYTES) {
                    check(HOT_OP!=1,"unexpected timed source read");
                    reads.push_back({r.address,r.data,r.meta});++physicalSourceReads;
                } else {
                    // The faster pipeline can issue beyond the predicted loop
                    // edge. Admit only a read in the immediate RAM guard line;
                    // its exact token must later prove canceled, drained and
                    // absent from architectural retirement. Never count it as
                    // useful payload or remove its elapsed/miss cycles.
                    verifyGuardRequest(r);
                    verifyGuardTraffic(physicalGuardReads+1);
                    const auto id=key(data.checked.front().token);
                    check(guardReads.emplace(id,Witness{r.address,r.data,r.meta}).second,
                          "duplicate speculative guard full token");
                    ++physicalGuardReads;
                }
            }
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
    void verifyTerminalDrain() const {
        check(!observedLiveOwners&&!observedStart,"done before observed LSU owner drain");
        check(std::none_of(backend.slotOwners.begin(),backend.slotOwners.end(),
            [](const auto &owner){return owner.live;}),"done before shadow LSU owner drain");
        check(pending.empty()&&backend.requests.empty()&&backend.responses.empty()&&
            data.fifo.empty()&&data.storeOwners.empty()&&data.ingress.empty()&&data.translated.empty()&&
            data.checked.empty()&&data.owners.empty()&&data.physicalPending.empty()&&
            data.stores.empty()&&data.returns.empty()&&!data.waiting&&!data.localReply,
            "done before complete data-path drain");
        check(!backend.stalledRequest&&!data.stalledRequest&&!data.stalledReply,
            "done before held backend handshake drain");
    }
    void terminalDrainNegatives() {
        observedLiveOwners=1;rejects([&]{verifyTerminalDrain();},"done before observed LSU owner drain");observedLiveOwners=0;
        observedStart=true;rejects([&]{verifyTerminalDrain();},"done before observed LSU owner drain");observedStart=false;
        backend.slotOwners.back().live=true;rejects([&]{verifyTerminalDrain();},"done before shadow LSU owner drain");backend.slotOwners.back().live=false;
        auto queued=[&](auto &queue) {
            queue.emplace_back();rejects([&]{verifyTerminalDrain();},"done before complete data-path drain");queue.pop_back();
        };
        queued(pending);queued(backend.requests);queued(backend.responses);queued(data.fifo);queued(data.storeOwners);
        queued(data.ingress);queued(data.translated);queued(data.checked);queued(data.owners);
        queued(data.physicalPending);queued(data.stores);queued(data.returns);
        data.waiting=FlowDataPathOwnershipLedger::Transaction{{},{},{},false,false,false,0};rejects([&]{verifyTerminalDrain();},"done before complete data-path drain");data.waiting.reset();
        data.localReply=FlowDataPathOwnershipLedger::Returned{FlowDataPathOwnershipLedger::Transaction{{},{},{},false,false,false,0},{}};rejects([&]{verifyTerminalDrain();},"done before complete data-path drain");data.localReply.reset();
        backend.stalledRequest.emplace();rejects([&]{verifyTerminalDrain();},"done before held backend handshake drain");backend.stalledRequest.reset();
        data.stalledRequest.emplace();rejects([&]{verifyTerminalDrain();},"done before held backend handshake drain");data.stalledRequest.reset();
        data.stalledReply.emplace();rejects([&]{verifyTerminalDrain();},"done before held backend handshake drain");data.stalledReply.reset();
        verifyTerminalDrain();
    }
    void verify() {
        check(finished&&phase==3,"hot bounded guest did not complete");
        verifyTerminalDrain();terminalDrainNegatives();
        const uint64_t count=HOT_BYTES/8*HOT_REPS;
        check(architecturalLoads==(HOT_OP==1?0:count),"architectural load count mismatch");
        check(architecturalStores==(HOT_OP==0?0:count),"architectural store count mismatch");
        check(physicalSourceReads>=architecturalLoads,"missing accepted source reads");
        for(unsigned i=0;i<2;++i)check(metrics[i].perf.readMiss==0&&metrics[i].perf.writeMiss==0,"timed workload is not all-hit");
        verifyWrites(writes);verifyReads(reads);verifyReplies(readReplies);verifyBacking();
        for(const auto &[id,witness]:guardReads) {
            const auto &stamp=stamps.at(id);verifyGuardOwner(stamp);
            std::cout<<"HOT_SPECULATIVE_GUARD token_tag="<<id.first<<" token_index="<<id.second
                <<" address="<<witness.address<<" start="<<*stamp.start<<" accepted="<<*stamp.physical
                <<" canceled="<<*stamp.cancel<<" replied="<<*stamp.reply<<" lsu_reply="<<*stamp.lsuReply
                <<" retired="<<stamp.retired<<"\n";
        }
        check(metrics[0].reads+metrics[1].reads==physicalSourceReads+physicalGuardReads,
              "timed physical read traffic accounting mismatch");
        if(!guardReads.empty()) {
            const auto &stamp=stamps.at(guardReads.begin()->first);
            auto missingCancel=stamp;missingCancel.cancel.reset();
            rejects([&]{verifyGuardOwner(missingCancel);},"speculative guard read lacks cancellation");
            auto retiredGuard=stamp;retiredGuard.retired=true;
            rejects([&]{verifyGuardOwner(retiredGuard);},"speculative guard read retired");
            auto completedGuard=stamp;completedGuard.result=*stamp.lsuReply+1;
            rejects([&]{verifyGuardOwner(completedGuard);},"speculative guard read produced completion");
            auto missingReply=stamp;missingReply.reply.reset();
            rejects([&]{verifyGuardOwner(missingReply);},"speculative guard read did not fully drain");
            auto earlyCancel=stamp;earlyCancel.cancel=*stamp.start-1;
            rejects([&]{verifyGuardOwner(earlyCancel);},"speculative guard read stage order mismatch");
            auto lateCancel=stamp;lateCancel.cancel=*stamp.lsuReply+1;
            rejects([&]{verifyGuardOwner(lateCancel);},"speculative guard read stage order mismatch");
            auto earlyReply=stamp;earlyReply.reply=*stamp.physical-1;
            rejects([&]{verifyGuardOwner(earlyReply);},"speculative guard read stage order mismatch");
            auto earlyReturn=stamp;earlyReturn.lsuReply=*stamp.reply-1;
            rejects([&]{verifyGuardOwner(earlyReturn);},"speculative guard read stage order mismatch");
            const auto &w=guardReads.begin()->second;
            const DataPathRequest valid{w.address,w.data,w.meta};verifyGuardRequest(valid);
            for(unsigned mutation=0;mutation<9;++mutation){auto bad=valid;
                if(mutation==0)bad.address=sourceBase+HOT_BYTES-8;
                if(mutation==1)bad.address=sourceBase+HOT_BYTES+32;
                if(mutation==2)bad.address|=1;
                if(mutation==3)bad.meta|=1;
                if(mutation==4)bad.meta|=1ULL<<17;
                if(mutation==5)bad.meta|=1ULL<<18;
                if(mutation==6)bad.meta^=1ULL<<7;
                if(mutation==7)bad.meta^=1ULL<<9;
                if(mutation==8)bad.meta|=2;
                rejects([&]{verifyGuardRequest(bad);},"nonbuffer physical request outside speculative RAM guard");
            }
        }
        verifyGuardTraffic(physicalGuardReads);
        rejects([&]{verifyGuardTraffic(HOT_REPS*BackendSample::ownerCount+1);},
                "speculative guard traffic exceeds four-owner loop bound");
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
            <<" speculative_guard_reads="<<physicalGuardReads
            <<" timed_physical_reads="<<physicalSourceReads+physicalGuardReads
            <<" timed_physical_read_bytes="<<8*(physicalSourceReads+physicalGuardReads)
            <<" speculative_guard_bytes="<<8*physicalGuardReads
            <<" total_physical_reads_minus_architectural="<<int64_t(physicalSourceReads+physicalGuardReads)-int64_t(architecturalLoads)
            <<" physical_source_reads_minus_architectural="<<int64_t(physicalSourceReads)-int64_t(architecturalLoads)
            <<" kernel_pc_trace="<<kernelPcTrace<<" kernel_retired="<<kernelRetired
            <<" negative_oracle_checks="<<negativeChecks<<" board_measurement=0\n";
        data.report();std::cout<<"HOT_PASS total_cycles="<<cycle<<" owner_checks="<<backend.checks<<" physical_read_data_checks="<<readReplies.size()<<" terminal_live_owners="<<observedLiveOwners
            <<" terminal_start="<<observedStart<<" complete_owner_drain=1\n";
    }
};
}
int main(int argc,char **argv) {try{
    check(argc==2||argc==3,"usage: cpu_flow_bandwidth guest.bin [--inject-physical-fingerprint]");
    if(argc==3) {
        injection=argv[2];
        const std::array<std::string,10> modes{"--inject-physical-fingerprint","--inject-route",
            "--inject-virtual-enqueue","--inject-checked-enqueue","--inject-authorization",
            "--inject-private-metadata","--inject-return-token",
            "--inject-upper-live","--inject-upper-token","--inject-reserve-guard"};
        check(std::find(modes.begin(),modes.end(),injection)!=modes.end(),"unknown injection mode");
    }
    Observer observer;const auto image=readFile(argv[1]);
    check(!image.empty()&&image.size()<0x10000,"guest image bounds");
    Bytes rom;word(rom,0x00200297);word(rom,0x10000337);word(rom,0x00700393);word(rom,0x00730123);word(rom,0x000280e7);word(rom,0x0000006f);
    Test test(rom,Observer::sample,&observer);observer.initialize(test,image);
    while(!observer.finished&&test.cycles<300000){test.running=true;test.tick();check(test.received.empty(),"unexpected UART output");}
    observer.verify();observer.report();return 0;
}catch(const std::exception &e){std::cerr<<"HOT_FAIL "<<e.what()<<"\n";return 1;}}
