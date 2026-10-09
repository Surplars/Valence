// Whole, unchanged archived diagnostic. Only the separately identified ROM is new.
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
#define DATA_PATH_OWNERSHIP_PROBES
#include "backend_observer.h"
#include "cpu_flow_bandwidth.h"
#include "performance_observer.h"
#include "memory_oracle.h"
#include "launcher_contract.h"
#include "stage_trace.h"
#include "stage_adapter.h"
#include "frontend_trace.h"
static_assert(BackendSample::ownerCount==4 && BackendOwnershipLedger::trackSlotLifetimes);
#include <array>
#include <map>
#include <optional>
#include <limits>
#include <regex>
#include <sstream>

namespace {
using P = DataPathSample;
using Key = std::pair<uint64_t, unsigned>;
Key key(BackendToken t) { return {t.tag, t.index}; }
using monitor_replay::MemoryOracle;
constexpr std::array<uint64_t,18> tickPcs{0xfff783d8,0xfff78404,0xfff787b0,0xfff787e4,
    0xfff784c4,0xfff784ec,0xfff78500,0xfff785dc,0xfff78618,0xfff7862c,
    0xfff783d8,0xfff78404,0xfff784c4,0xfff784ec,0xfff78500,0xfff785dc,0xfff78618,0xfff7862c};
struct Interval { const char *name; unsigned first, last; };
constexpr std::array<Interval,11> intervals{{
    {"read_cache_sized_cold",0,1},{"read_cache_hot",2,3},{"write_cache_sized",4,5},
    {"write_cache_sized_flush",5,6},{"copy_cache_sized",7,8},{"copy_cache_sized_flush",8,9},
    {"read_over_cache",10,11},{"write_over_cache",12,13},{"write_over_cache_flush",13,14},
    {"copy_over_cache",15,16},{"copy_over_cache_flush",16,17}}};
struct Distribution {
    uint64_t count=0,sum=0,minimum=~0ULL,maximum=0;
    std::map<uint64_t,uint64_t> histogram;
    void add(uint64_t n) { ++count;sum+=n;minimum=std::min(minimum,n);maximum=std::max(maximum,n);++histogram[n]; }
    void report(const std::string &name) const {
        std::cout<<"MONITOR_DISTRIBUTION name="<<name<<" count="<<count<<" sum="<<sum
            <<" min="<<(count?minimum:0)<<" max="<<maximum<<" histogram=";
        bool comma=false;for(auto [n,c]:histogram){if(comma)std::cout<<",";comma=true;std::cout<<n<<":"<<c;}std::cout<<"\n";
    }
};
struct Metrics {
    PerfCounts perf;
    uint64_t starts=0,physicalReads=0,physicalWrites=0,physicalReplies=0,lsuReplies=0;
    uint64_t axiReads=0,axiWrites=0,rBeats=0,wBeats=0,bResponses=0,lsuPeak=0,lsuOwnerCycles=0;
    uint64_t orderCheck=0,replayPending=0,doneHeadNoCommitOrderHold=0,frontendNoSupply=0;
    std::array<uint64_t,3> supply{};std::array<uint64_t,5> occupied{};
    std::array<uint64_t,16> instructionCacheEvents{};
    std::array<uint64_t,42> frontendEvents{};
    std::array<uint64_t,9> pathOccupancy{},pathPeak{};
    std::map<std::string,uint64_t> buckets;
    void sample(SBoardSocGsim &d,Test &t,const BackendSample &b,const P &p,
                const BackendOwnershipLedger &backend,const FlowDataPathOwnershipLedger &data) {
        perf.sample(d);starts+=b.bit(3);physicalReplies+=p.bit(P::physicalReply);lsuReplies+=b.reply();
        if(p.bit(P::physicalRequest)){physicalWrites+=p.request[P::physical].write();physicalReads+=!p.request[P::physical].write();}
        const unsigned live=b.liveCount();++occupied.at(live);lsuPeak=std::max<uint64_t>(lsuPeak,live);lsuOwnerCycles+=live;
        ++supply.at(d.get_perfSupply());
        const bool hold=d.board$platform$core$core$core$backend$orderCheckValid || d.board$platform$core$core$core$backend$replayPendingValid;
        orderCheck+=d.board$platform$core$core$core$backend$orderCheckValid;
        replayPending+=d.board$platform$core$core$core$backend$replayPendingValid;
        doneHeadNoCommitOrderHold+=!b.commits&&b.headValid&&b.headDone&&hold;
        const auto fe=d.get_perfEvents();const auto ice=d.get_perfCacheEvents();
        frontendNoSupply+=(fe>>39)&1;
        for(unsigned i=0;i<frontendEvents.size();++i)frontendEvents[i]+=(fe>>i)&1;
        for(unsigned i=0;i<instructionCacheEvents.size();++i)instructionCacheEvents[i]+=(ice>>i)&1;
        for(unsigned i=0;i<pathOccupancy.size();++i){pathOccupancy[i]+=p.count[i];pathPeak[i]=std::max<uint64_t>(pathPeak[i],p.count[i]);}
        axiReads+=d.get_io$$ddrAxi$$ar$$valid()&&t.ddr.arReady;axiWrites+=d.get_io$$ddrAxi$$aw$$valid()&&t.ddr.awReady;
        rBeats+=t.ddr.rValid&&d.get_io$$ddrAxi$$r$$ready();wBeats+=t.ddr.wReady&&d.get_io$$ddrAxi$$w$$valid();
        bResponses+=t.ddr.bValid&&d.get_io$$ddrAxi$$b$$ready();
        auto bucket=backend.category(b);
        if(bucket=="issued_memory_downstream_unknown"){auto refined=data.category(b.head,b,p);if(!refined.empty())bucket=refined;}
        ++buckets[bucket];
    }
    void report(const char *name) const {
        auto copy=perf;copy.report(name);
        std::cout<<"MONITOR_PIPELINE name="<<name<<" lsu_starts="<<starts<<" physical_reads="<<physicalReads
            <<" physical_writes="<<physicalWrites<<" physical_replies="<<physicalReplies<<" lsu_replies="<<lsuReplies
            <<" lsu_peak="<<lsuPeak<<" lsu_owner_cycles="<<lsuOwnerCycles<<" order_check_valid_cycles="<<orderCheck
            <<" replay_pending_cycles="<<replayPending<<" done_head_zero_commit_with_order_hold="<<doneHeadNoCommitOrderHold
            <<" frontend_no_supply_cycles="<<frontendNoSupply<<" axi_reads="<<axiReads<<" axi_writes="<<axiWrites
            <<" axi_r_beats="<<rBeats<<" axi_w_beats="<<wBeats<<" axi_b_responses="<<bResponses;
        for(unsigned i=0;i<3;++i)std::cout<<" supply_"<<i<<"="<<supply[i];
        for(unsigned i=0;i<5;++i)std::cout<<" lsu_occupied_"<<i<<"="<<occupied[i];
        for(unsigned i=0;i<9;++i)std::cout<<" path_"<<i<<"_sum="<<pathOccupancy[i]<<" path_"<<i<<"_peak="<<pathPeak[i];
        for(unsigned i=0;i<16;++i)std::cout<<" icache_event_"<<i<<"="<<instructionCacheEvents[i];
        for(unsigned i=0;i<42;++i)std::cout<<" frontend_event_"<<i<<"="<<frontendEvents[i];
        std::cout<<"\n";uint64_t sum=0;
        for(auto [bucket,n]:buckets){sum+=n;std::cout<<"MONITOR_BUCKET name="<<name<<" category="<<bucket<<" cycles="<<n<<"\n";}
        check(sum==perf.cycles,"monitor cycle bucket conservation");
    }
};
struct Stamp {
    uint64_t pc=0,start=0;
    std::optional<uint64_t> fifo,physical,reply,lsuReply,result,retire,cancel;
    unsigned region=0;
};
struct Pending { BackendToken token;uint64_t expected,address,meta;bool verify; };
struct TimerValue { uint64_t pc,value; };
struct Observer {
    Test *test=nullptr;
    Bytes image;
    BackendOwnershipLedger backend;
    FlowDataPathOwnershipLedger data;
    MemoryOracle physical,cpu;
    std::deque<Pending> pending,cpuPending;
    std::map<Key,Stamp> loads;
    std::map<Key,TimerValue> timerValues;
    std::array<uint64_t,18> ticks{},tickCycles{};
    std::array<std::optional<uint64_t>,3> previousLoadStart{};
    std::array<Distribution,3> loadStartGaps;
    unsigned tickCount=0,originalEntries=0,originalReturns=0,launcherReturns=0;
    bool done=false,negativeApplied=false;
    uint64_t cycle=0,ramReplies=0,cpuRamReplies=0,cpuForwardedReplies=0,rawRequests=0,rawReplies=0;
    uint64_t hotRetiredLoads=0,coldRetiredLoads=0,stackLow=monitor_replay::stackEnd;
    unsigned liveOwners=0;
    bool startLive=false;
    std::string mutation;
    std::ofstream traffic;
    monitor_stage::StageTrace stages;
    monitor_stage::FrontendTrace frontend;
    std::set<Key> guardOwners;
    bool rawRequestValid=false,rawReplyValid=false;
    Metrics all;
    std::array<Metrics,11> metrics;
    static void sample(SBoardSocGsim &d,void *context) {static_cast<Observer*>(context)->sample(d);}
    uint32_t instruction(uint64_t pc) const {
        if(pc<monitor_replay::base||pc+4>monitor_replay::base+image.size())return 0;
        return wordAt(image,pc-monitor_replay::base);
    }
    void initialize(Test &t) {
        test=&t;
        for(auto [address,value]:physical.words)if(address>=ramBase)t.ddr.memory[uint32_t(address-ramBase)]=value;
    }
    void sample(SBoardSocGsim &d) {
        auto b=BackendObserver::read(d);auto p=BackendObserver::readData(d);
        data.flowEvents=d.get_cpuFlowEvents();data.ingressAuth=d.get_cpuFlowIngressAuth();
        data.checkedAuth=d.get_cpuFlowCheckedAuth();data.checkedAddress=d.get_cpuFlowCheckedAddress();
        data.checkedData=d.get_cpuFlowCheckedData();data.checkedHeadAuth=d.get_cpuFlowCheckedHeadAuth();data.physicalAuth=d.get_cpuFlowPhysicalAuth();
        if(b.reset){stages.reset();data.advance(b,p,backend);backend.advance(b);++cycle;return;}
        check(!d.get_io$$trap$$valid(),"monitor unexpected CPU trap");
        check(p.bit(P::reserveGuardMatch),"monitor production capacity guard mismatch");
        liveOwners=b.liveCount();startLive=b.bit(3);rawRequestValid=b.bit(20);rawReplyValid=b.bit(24);
        auto snapshot=monitor_stage::read(d,b,p);
        if(!negativeApplied&&mutation=="--inject-stage-token"&&snapshot.start&&monitor_stage::pc(d,snapshot.start->second)==0xfff787d0){snapshot.start->first^=1ULL<<40;negativeApplied=true;}
        stages.sample(cycle,snapshot);frontend.sample(d,cycle,tickCount,!stages.records.empty());
        if(!negativeApplied&&mutation=="--inject-token"&&b.reply()){b.slots[b.returnSlot].tag^=1;negativeApplied=true;}
        for(unsigned i=0;i<BackendSample::ownerCount;++i)if(b.live[i]&&b.cancelled[i]){
            auto it=loads.find(key(b.slots[i]));if(it!=loads.end()&&!it->second.cancel)it->second.cancel=cycle;
        }
        // Capture the retained registered result with its complete token before retirement.
        // This is the actual rdtime value returned to guest code, not a host-cycle substitute.
        if(d.board$platform$core$core$core$backend$systemUnit$state==7) {
            const BackendToken token{d.board$platform$core$core$core$backend$systemUnit$result$$completion$$token$$tag,
                unsigned(d.board$platform$core$core$core$backend$systemUnit$result$$completion$$token$$index)};
            const uint64_t next=d.board$platform$core$core$core$backend$systemUnit$result$$completion$$nextPc;
            if((instruction(next-4)&0xfffff07fU)==0xc0102073U) {
                check(!d.board$platform$core$core$core$backend$systemUnit$result$$completion$$exception,"monitor rdtime exception");
                TimerValue value{next-4,d.board$platform$core$core$core$backend$systemUnit$result$$completion$$data};
                auto [it,fresh]=timerValues.emplace(key(token),value);
                check(fresh||(it->second.pc==value.pc&&it->second.value==value.value),"monitor held rdtime result changed");
            }
        }
        std::array<bool,11> active{};
        for(unsigned i=0;i<11;++i)active[i]=tickCount>intervals[i].first&&tickCount<=intervals[i].last;
        for(unsigned lane=0;lane<2;++lane) {
            if(!(lane?d.get_io$$commit1():d.get_io$$commit0()))continue;
            const uint64_t pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();
            const uint64_t tag=lane?d.board$platform$core$core$core$backend$ledger$io$$commit$$bits$$token$$tag_1:
                d.board$platform$core$core$core$backend$ledger$io$$commit$$bits$$token$$tag_0;
            const BackendToken token{tag,(b.head.index+lane)&15U};
            if(!lane)check(token==b.head,"monitor retirement token/head mismatch");
            stages.retire(key(token),pc,cycle);
            check((pc>=monitor_replay::base&&pc<monitor_replay::textEnd)||(pc>=0x80000000&&pc<LAUNCHER_FAIL+4),
                "monitor retired PC outside unchanged text/launcher");
            originalEntries+=pc==monitor_replay::base;originalReturns+=pc==0xfff78048;launcherReturns+=pc==LAUNCHER_RETURNED;
            check(pc!=LAUNCHER_FAIL,"monitor diagnostic returned failure");
            if(pc==LAUNCHER_DONE){check(originalReturns==1&&launcherReturns==1,"monitor launcher completed without original return");done=true;}
            auto found=loads.find(key(token));
            if(found!=loads.end()){
                check(found->second.pc==pc&&!found->second.retire&&!found->second.cancel,"monitor tracked load retirement mismatch");
                found->second.retire=cycle;
            }
            hotRetiredLoads+=pc==0xfff787d0;coldRetiredLoads+=pc==0xfff783f0;
            if((instruction(pc)&0xfffff07fU)==0xc0102073U) {
                uint64_t marker=pc;
                if(!negativeApplied&&mutation=="--inject-marker"&&pc==0xfff787b0){marker^=4;negativeApplied=true;}
                check(tickCount<tickPcs.size()&&marker==tickPcs[tickCount],"monitor rdtime marker sequence mismatch");
                auto value=timerValues.find(key(token));
                check(value!=timerValues.end()&&value->second.pc==pc,"monitor actual rdtime result lost full token");
                ticks[tickCount]=value->second.value;tickCycles[tickCount]=cycle;timerValues.erase(value);
                check(!tickCount||ticks[tickCount]>ticks[tickCount-1],"monitor rdtime did not advance monotonically");
                std::cout<<"MONITOR_RDTIME ordinal="<<tickCount<<" pc="<<pc<<" token_tag="<<tag
                    <<" token_index="<<token.index<<" actual_ticks="<<ticks[tickCount]<<" retirement_cycle="<<cycle<<"\n";
                for(unsigned i=0;i<11;++i)if(intervals[i].first==tickCount)active[i]=true;
                ++tickCount;
            }
        }
        if(b.bit(3)&&test) {
            // Selected bankedIssuePayload deliberately clears the unbanked
            // queue PC. Read the schema-bound payload bank for this full owner.
            const uint64_t pc=(b.start.index&1)?
                d.board$platform$core$core$core$backend$payload_1$pcBank1[b.start.index>>1]:
                d.board$platform$core$core$core$backend$payload_1$pcBank0[b.start.index>>1];
            if((instruction(pc)&0x707fU)==0x3003U){
                unsigned region=pc==0xfff787d0?1:pc==0xfff783f0?(tickCount<10?0:2):3;
                check(loads.emplace(key(b.start),Stamp{pc,cycle,{},{},{},{},{},{},{},region}).second,"monitor duplicate loop load full token");
                if(region<3){if(previousLoadStart[region])loadStartGaps[region].add(cycle-*previousLoadStart[region]);
                    previousLoadStart[region]=cycle;}
            }
        }
        auto stamp=[&](BackendToken token,auto member){auto it=loads.find(key(token));if(it!=loads.end()){
            check(!(it->second.*member),"monitor duplicate owner stage");it->second.*member=cycle;}};
        if(b.enq())stamp(b.request,&Stamp::fifo);
        if(b.reply())stamp(b.slots[b.returnSlot],&Stamp::lsuReply);
        if(b.bit(26)&&b.bit(27))stamp(b.complete,&Stamp::result);
        // CPU acceptance shadow includes local forwarded loads. It is separate
        // from the physical-cache shadow below; both start from known host bytes.
        if(p.bit(P::fastAccept)){
            const auto &r=p.request[P::fast];cpu.accept(r.address,r.data,r.meta,false);
        }
        if(b.deq()) {
            check(!data.fifo.empty(),"monitor CPU acceptance lost token");const auto &r=p.request[P::fifoDeq];
            const uint64_t expected=cpu.accept(r.address,r.data,r.meta,false);
            cpuPending.push_back({data.fifo.front().token,expected,r.address,r.meta,!MemoryOracle::uart(r.address)&&!r.write()});
        }
        if(b.reply()) {
            check(!cpuPending.empty(),"monitor CPU reply lacks independent owner");auto q=cpuPending.front();cpuPending.pop_front();
            check(q.token==b.slots[b.returnSlot],"monitor CPU reply full-token mismatch");
            check(p.reply[4].flags==0,"monitor CPU reply fault");
            if(q.verify){const uint64_t mask=monitor_replay::byteMask((q.meta>>9)&255);
                check((q.expected&mask)==(p.reply[4].data&mask),"monitor independent CPU RAM reply mismatch");++cpuRamReplies;
                cpuForwardedReplies+=p.bit(P::forwardedAccept)||p.bit(P::storeAckValid);
            }
        }
        if(p.bit(P::physicalReply)) {
            check(!pending.empty(),"monitor physical reply lacks independent owner");auto q=pending.front();pending.pop_front();
            stamp(q.token,&Stamp::reply);++rawReplies;
            if(mutation.empty())traffic<<"reply\t"<<cycle<<"\t"<<q.token.tag<<"\t"<<q.token.index<<"\t"<<q.address<<"\t"<<p.reply[0].data<<"\t"<<p.reply[0].flags<<"\n";
            check(p.reply[0].flags==0,"monitor physical reply fault");
            if(q.verify){
                if(!negativeApplied&&mutation=="--inject-data"&&q.address>=ramBase){q.expected^=1;negativeApplied=true;}
                check(q.expected==p.reply[0].data,"monitor independent physical RAM reply mismatch");++ramReplies;
            }
        }
        if(p.bit(P::physicalRequest)) {
            check(!data.checked.empty(),"monitor physical acceptance lost full token");const auto &r=p.request[P::physical];
            const BackendToken token=data.checked.front().token;stamp(token,&Stamp::physical);++rawRequests;
            const uint64_t expected=physical.accept(r.address,r.data,r.meta);
            stages.physical(key(token),r.address,cycle);
            if(r.address>=monitor_replay::bBase+monitor_replay::bufferBytes&&r.address<monitor_replay::bBase+monitor_replay::bufferBytes+32){
                check(!r.write()&&((r.meta>>7)&3)==3&&loads.contains(key(token)),"monitor guard request lacks full-token LD owner");
                check(loads.at(key(token)).pc==0xfff78650,"monitor guard load is outside final B verification loop");
                check(guardOwners.insert(key(token)).second,"monitor duplicate guard owner");
            }
            pending.push_back({token,expected,r.address,r.meta,!MemoryOracle::uart(r.address)&&!r.write()});
            if(mutation.empty())traffic<<"request\t"<<cycle<<"\t"<<token.tag<<"\t"<<token.index<<"\t"<<r.address<<"\t"<<r.data<<"\t"<<r.meta<<"\n";
            if(r.address>=monitor_replay::stackStart&&r.address<monitor_replay::stackEnd)stackLow=std::min(stackLow,r.address);
        }
        if(test){all.sample(d,*test,b,p,backend,data);for(unsigned i=0;i<11;++i)if(active[i])metrics[i].sample(d,*test,b,p,backend,data);}
        data.advance(b,p,backend);backend.advance(b);++cycle;
    }
    bool drained() const {
        return !liveOwners&&!startLive&&!rawRequestValid&&!rawReplyValid&&
            std::none_of(backend.slotOwners.begin(),backend.slotOwners.end(),[](const auto &o){return o.live;})&&
            !backend.stalledRequest&&!data.stalledRequest&&!data.stalledReply&&pending.empty()&&cpuPending.empty()&&backend.requests.empty()&&backend.responses.empty()&&
            data.fifo.empty()&&data.stores.empty()&&data.storeOwners.empty()&&data.ingress.empty()&&data.translated.empty()&&
            data.checked.empty()&&data.owners.empty()&&data.physicalPending.empty()&&data.returns.empty()&&!data.waiting&&!data.localReply&&
            test->ddr.pendingReads.empty()&&test->ddr.pendingWrites.empty()&&test->ddr.pendingB.empty()&&!test->ddr.heldRead&&!test->ddr.heldB;
    }
    void verify() {
        check(done&&originalEntries==1&&originalReturns==1&&launcherReturns==1,"monitor did not execute and return once");
        check(drained(),"monitor final CPU/AXI ownership did not fully drain");
        check(tickCount==tickPcs.size()&&timerValues.empty(),"monitor incomplete rdtime coverage");
        check(hotRetiredLoads==1024&&coldRetiredLoads==1024+16384,"monitor original loop retired load count mismatch");
        check(rawRequests==rawReplies&&ramReplies&&cpuRamReplies,"monitor request/reply conservation or coverage mismatch");
        for(const auto &id:guardOwners){const auto &s=loads.at(id);
            check(s.cancel&&!s.retire&&!s.result&&s.fifo&&s.physical&&s.reply&&s.lsuReply&&*s.cancel<=*s.lsuReply,
                "monitor speculative guard did not cancel and fully drain");}
        physical.verifyBuffers();
        check(physical.words==cpu.words,"monitor CPU/physical independent memory histories diverged");
        for(auto [address,value]:physical.words)if(address>=ramBase)
            check(test->ddr.memory[uint32_t(address-ramBase)]==value,"monitor final flushed DDR differs from independent memory");
        if(PHYSICAL_INGRESS_FLOW)check(data.counters.at("physical_ingress_pass")>0,"monitor ingress ON route unexercised");
        check(mutation.empty(),"monitor negative injection did not fail");
        const std::string output(test->received.begin(),test->received.end());
        check(output.find("CPU_BANDWIDTH_PASS verified=1 copy_bytes=payload_not_double_bus_traffic\r\n")!=std::string::npos,
            "monitor full guest PASS missing");
        check(output.find("FAIL")==std::string::npos&&output.find("SELFTEST")==std::string::npos,"monitor unexpected guest failure/quick mode");
        const std::regex line("BW ([a-z_]+) bytes=([0-9]+) ticks=([0-9]+) flush_tail=([0-9]+) clock_hz=([0-9]+) milli_MiB_s=([0-9]+)");
        const std::array<unsigned,7> first{0,2,4,7,10,12,15},last{1,3,5,8,11,13,16};
        const std::array<const char*,7> names{"read_cache_sized_cold","read_cache_hot","write_cache_sized","copy_cache_sized","read_over_cache","write_over_cache","copy_over_cache"};
        unsigned records=0;
        for(auto it=std::sregex_iterator(output.begin(),output.end(),line);it!=std::sregex_iterator();++it){
            check(records<7,"monitor excess UART bandwidth records");auto m=*it;const auto i=records++;
            const uint64_t bytes=i<4?8192:131072,elapsed=ticks[last[i]]-ticks[first[i]];
            check(elapsed>0,"monitor zero elapsed rdtime interval");
            const uint64_t tail=(i==2||i==3||i==5||i==6)?ticks[last[i]+1]-ticks[last[i]]:0;
            check(m[1]==names[i]&&std::stoull(m[2])==bytes&&std::stoull(m[3])==elapsed&&std::stoull(m[4])==tail&&
                  std::stoull(m[5])==100000000&&std::stoull(m[6])==(bytes*100000000ULL*1000/elapsed)/1048576,
                  "monitor UART report differs from actual rdtime values");
        }
        check(records==7,"monitor incomplete original read/write/copy UART reports");
    }
    void report(const char *stagePath,const char *frontendPath) {
        std::ofstream frontendFile(frontendPath);check(bool(frontendFile),"cannot open frontend trace");check(!stages.records.empty(),"hot scalar records missing");frontend.report(frontendFile,std::cout,std::min(tickCycles[2],stages.records.front()->allocated),tickCycles[3],stages);frontendFile.close();check(bool(frontendFile),"frontend trace write failed");
        std::ofstream stageFile(stagePath);check(bool(stageFile),"cannot open hot stage trace");stages.report(stageFile,std::cout);stageFile.close();check(bool(stageFile),"hot stage trace write failed");
        all.report("whole_run_includes_UART_and_launcher");
        for(unsigned i=0;i<11;++i){metrics[i].report(intervals[i].name);
            const auto begin=intervals[i].first,end=intervals[i].last;
            std::cout<<"MONITOR_INTERVAL name="<<intervals[i].name<<" actual_ticks="<<ticks[end]-ticks[begin]
                <<" retirement_cycles_inclusive="<<tickCycles[end]-tickCycles[begin]+1<<"\n";}
        std::array<std::map<std::string,Distribution>,3> distributions;
        std::array<uint64_t,3> retired{},cancelled{},started{};
        for(auto &[id,s]:loads){if(s.region>=3)continue;++started[s.region];retired[s.region]+=bool(s.retire);cancelled[s.region]+=bool(s.cancel);
            auto add=[&](const char *name,std::optional<uint64_t> a,std::optional<uint64_t> b){if(a&&b){check(*b>=*a,"monitor owner stage lifetime backwards");distributions[s.region][name].add(*b-*a);}};
            if(s.retire)check(s.fifo&&s.physical&&s.reply&&s.lsuReply&&s.result&&!s.cancel,"monitor retired loop owner missing stage");
            if(s.physical)check(s.reply&&s.lsuReply,"monitor accepted loop owner did not drain");
            add("start_to_fifo",s.start,s.fifo);add("fifo_to_physical",s.fifo,s.physical);add("physical_to_reply",s.physical,s.reply);
            add("reply_to_lsu_reply",s.reply,s.lsuReply);add("lsu_reply_to_result",s.lsuReply,s.result);
            add("start_to_result",s.start,s.result);add("start_to_retire",s.start,s.retire);add("result_to_retire",s.result,s.retire);
        }
        const std::array<std::string,3> names{"cold_8K_loop","hot_8K_loop","cold_128K_loop"};
        check(retired==std::array<uint64_t,3>{1024,1024,16384},"monitor PC-to-full-owner retirement join coverage missing");
        for(unsigned i=0;i<3;++i){for(auto &[stage,dist]:distributions[i])dist.report(names[i]+"_"+stage);
            loadStartGaps[i].report(names[i]+"_start_gap");
            std::cout<<"MONITOR_LOOP name="<<names[i]<<" started_owners="<<started[i]<<" retired_loads="<<retired[i]<<" cancelled_owners="<<cancelled[i]<<"\n";}
        data.report();traffic.close();check(bool(traffic),"raw traffic log write failed");
        std::cout<<"MONITOR_UART_BEGIN\n"<<std::string(test->received.begin(),test->received.end())<<"MONITOR_UART_END\n";
        std::cout<<"MONITOR_REPLAY_PASS total_cycles="<<cycle<<" owner_checks="<<backend.checks
            <<" physical_requests="<<rawRequests<<" physical_replies="<<rawReplies<<" known_memory_replies="<<ramReplies
            <<" cpu_known_memory_replies="<<cpuRamReplies<<" cpu_forwarded_replies="<<cpuForwardedReplies
            <<" a_stores="<<physical.aWrites<<" b_stores="<<physical.bWrites<<" stack_low="<<stackLow
            <<" terminal_raw_request_valid="<<rawRequestValid<<" terminal_raw_reply_valid="<<rawReplyValid<<" guard_owners="<<guardOwners.size()
            <<" full_return=1 full_drain=1 lsu_owners=4 actual_rdtime_records="<<tickCount<<" board_measurement=0 compiler=14.2.0\n";
    }
};
}
int main(int argc,char **argv) {try {
    check(argc==6||argc==7,"usage: replay archived.bin launcher.bin raw-traffic.tsv hot-stage.tsv frontend.tsv [--inject-data|--inject-token|--inject-marker|--inject-stage-token]");
    Observer observer;
    if(argc==7){observer.mutation=argv[6];check(observer.mutation=="--inject-data"||observer.mutation=="--inject-token"||observer.mutation=="--inject-marker"||observer.mutation=="--inject-stage-token","unknown monitor injection");}
    const auto image=readFile(argv[1]),rom=readFile(argv[2]);
    observer.image=image;observer.physical.initialize(image,rom);observer.cpu.initialize(image,rom);
    observer.traffic.open(argv[3]);check(bool(observer.traffic),"cannot open raw traffic log");
    observer.traffic<<"kind\tcycle\ttag\tindex\taddress\tdata\tmeta_or_flags\n";
    Test test(rom,Observer::sample,&observer);observer.initialize(test);
    size_t previousOutput=0;uint64_t quietSince=test.cycles;
    while(test.cycles<BOARD_CYCLE_LIMIT){
        test.running=true;test.tick();
        if(test.received.size()!=previousOutput){quietSince=test.cycles;previousOutput=test.received.size();}
        check(test.received.size()<8192,"monitor UART output bound");
        if(test.cycles%1000000==0)std::cout<<"MONITOR_PROGRESS cycles="<<test.cycles<<" rdtime_records="<<observer.tickCount<<" uart_bytes="<<test.received.size()<<"\n"<<std::flush;
        if(observer.done&&observer.drained()&&!test.phase&&test.cycles-quietSince>12*Test::period)break;
    }
    observer.verify();observer.report(argv[4],argv[5]);return 0;
}catch(const std::exception &e){std::cerr<<"MONITOR_REPLAY_FAIL "<<e.what()<<"\n";return 1;}}
