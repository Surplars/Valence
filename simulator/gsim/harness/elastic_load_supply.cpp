// Private host-only experiment. Reuses the immutable saved CommonA1 model.
// No generated state is changed except through the public fixture inputs/reset.
// This is a whole-line (512-bit Grant) cache fixture, NOT DDR or D-beat timing.
#ifndef A1_LOAD_ORACLE_ONLY
#include "CommonA1VmPipelineGsim.h"
#include "gsim_model_storage.h"
#endif
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
namespace {
constexpr uint64_t romBase=0x80000000ULL, ramBase=0x80200000ULL;
constexpr uint64_t vmVa=0x40000000ULL, vmPa=0x80210000ULL;
constexpr uint64_t rootPa=0x80300000ULL, l1Pa=rootPa+4096, l0Pa=rootPa+8192;
constexpr uint64_t satpValue=(8ULL<<60)|(rootPa>>12), mstatusValue=0x20800;
constexpr unsigned serviceLatency=3, maxTransactions=16, maxCycles=30000;
constexpr uint32_t nop=0x13, ebreak=0x00100073, fence=0x0330000f;
constexpr uint64_t dataBase=vmPa;
using Memory=std::array<uint8_t,4096>;
#include "isa_model.h"
void require(bool ok,const std::string &s) { if(!ok) throw std::runtime_error(s); }
std::string hex(uint64_t x) {std::ostringstream s;s<<"0x"<<std::hex<<x;return s.str();}
uint32_t imm(unsigned d,unsigned a,int v,unsigned f=0) {return (uint32_t(v)&4095)<<20|a<<15|f<<12|d<<7|0x13;}
uint32_t branch(unsigned a,unsigned b,int off,unsigned f) {const uint32_t x=uint32_t(off)&8191;return ((x>>12)&1)<<31|((x>>5)&63)<<25|b<<20|a<<15|f<<12|((x>>1)&15)<<8|((x>>11)&1)<<7|0x63;}
uint32_t jump(int off) {const uint32_t x=uint32_t(off)&0x1fffff;return ((x>>20)&1)<<31|((x>>1)&1023)<<21|((x>>11)&1)<<20|((x>>12)&255)<<12|0x6f;}
uint32_t ld(unsigned d,unsigned a,unsigned off) {require(off<2048,"LD immediate out of range");return off<<20|a<<15|3<<12|d<<7|3;}
uint32_t csr(unsigned n,unsigned a) {return n<<20|a<<15|1<<12|0x73;}
void constant(std::vector<uint32_t>&c,unsigned d,uint64_t v) {int s=56;while(s&&!(v>>s))s-=8;c.push_back(imm(d,0,int((v>>s)&255)));for(s-=8;s>=0;s-=8){c.push_back(imm(d,d,8,1));if((v>>s)&255)c.push_back(imm(d,d,int((v>>s)&255)));}}
struct Program {
 std::string name; bool cold=false; std::vector<uint32_t> code;
 const std::array<uint32_t,2> boot{0x00200f97,0x000f8067};
 uint64_t bodyEntry=0, body=0, bodyEnd=0, loopEnd=0, done=0; unsigned measuredIterations=0,bodyLoads=0;
 bool mapped(uint64_t a,uint64_t n)const {return n&&((a>=romBase&&a-romBase<=128*1024-n)||(a>=ramBase&&a-ramBase<=128*1024-n));}
 bool architectural(uint64_t pc)const{return !(pc&3)&&((pc>=romBase&&(pc-romBase)/4<boot.size())||(pc>=ramBase&&(pc-ramBase)/4<code.size()));}
 uint32_t word(uint64_t pc)const{require(!(pc&3)&&mapped(pc,4),"instruction aperture "+hex(pc));if(pc>=ramBase&&(pc-ramBase)/4<code.size())return code[(pc-ramBase)/4];if(pc>=romBase&&(pc-romBase)/4<boot.size())return boot[(pc-romBase)/4];return nop;}
 uint64_t beat(uint64_t a)const{require(!(a&7),"instruction alignment");return uint64_t(word(a))|uint64_t(word(a+4))<<32;}
 unsigned dataLatency()const{return cold?32:3;}
};
Program makeProgram(bool cold) {
 Program p;p.name=cold?"delayed_cold_loads":"hot_loads";p.cold=cold;p.measuredIterations=1;p.bodyLoads=cold?16:256;auto &c=p.code;
 constant(c,10,0x40000000);c.push_back(csr(0x3b0,10));constant(c,10,15);c.push_back(csr(0x3a0,10));
 constant(c,10,satpValue);c.push_back(csr(0x180,10));c.push_back(0x12000073);constant(c,10,mstatusValue);c.push_back(csr(0x300,10));
 constant(c,11,vmVa);c.push_back(imm(20,0,1));c.push_back(imm(21,0,0));
 p.bodyEntry=ramBase+c.size()*4;c.push_back(fence);p.body=ramBase+c.size()*4;
 constexpr std::array<unsigned,16> dest{1,2,3,4,5,6,7,8,9,12,13,14,15,16,17,18};
 for(unsigned i=0;i<p.bodyLoads;++i)c.push_back(ld(dest[i%16],11,cold?i*128:(i%8)*8));
 p.bodyEnd=ramBase+c.size()*4;c.push_back(imm(20,20,-1));
 c.push_back(branch(20,0,int(p.bodyEntry-(ramBase+c.size()*4)),1));
 const size_t phaseBranch=c.size();c.push_back(0);p.loopEnd=ramBase+c.size()*4;
 c.push_back(fence);c.push_back(imm(21,0,1));
 if(cold){c.push_back(imm(11,11,1024));c.push_back(imm(11,11,1024));}
 c.push_back(imm(20,0,p.measuredIterations));c.push_back(jump(int(p.bodyEntry-(ramBase+c.size()*4))));
 p.done=ramBase+c.size()*4;c[phaseBranch]=branch(21,0,int(p.done-(ramBase+phaseBranch*4)),1);
 c.push_back(fence);c.push_back(ebreak);return p;
}
// Low sixteen bits preserve the entire 9-bit word index. The remaining
// fields carry nonzero, address-dependent sentinels; no 2 KiB alias exists.
uint64_t managerData(uint64_t a) {
 require(a>=vmPa&&a<vmPa+4096&&!(a&7),"data service aperture "+hex(a));
 const uint64_t index=(a-vmPa)/8;
 return 0x6d3a000000000000ULL | index |
        (((index*0x101+0x2345)&0xffffULL)<<16) |
        (((index*0x21+0x4567)&0xffffULL)<<32);
}
// The oracle constructs byte memory directly, independently of managerData.
uint8_t oracleByte(uint64_t offset) {
 require(offset<4096,"oracle byte aperture");const uint64_t word=offset/8;const unsigned byte=offset%8;
 if(byte<2)return uint8_t(word>>(8*byte));
 if(byte<4)return uint8_t((257*word+9029)>>(8*(byte-2)));
 if(byte<6)return uint8_t((33*word+17767)>>(8*(byte-4)));
 return byte==6?0x3a:0x6d;
}
void dataOracleSelfTest() {
 std::set<uint64_t>unique;std::array<uint64_t,512>words{};
 for(unsigned i=0;i<512;++i){for(unsigned b=0;b<8;++b)words[i]|=uint64_t(oracleByte(i*8+b))<<(8*b);require(words[i]==managerData(vmPa+8*i),"manager/independent byte image disagreement");require(unique.insert(words[i]).second,"data image word alias");}
 for(unsigned i=0;i<256;++i)require(words[i]!=words[i+256],"warm/cold half-page data alias");
 std::cout<<"LOAD_SUPPLY_DATA_ORACLE {\"unique_words\":512,\"distinct_half_page_pairs\":256}\n";
}
uint64_t managerPte(uint64_t a) {if(a==rootPa+8)return(l1Pa>>12)<<10|1;if(a==l1Pa)return(l0Pa>>12)<<10|1;if(a==l0Pa)return(vmPa>>12)<<10|0xc7;throw std::runtime_error("scalar PTE aperture "+hex(a));}
uint64_t oracleWalk(uint64_t va,uint64_t satp,uint64_t status,uint64_t cfg,uint64_t limit) {
 require(satp==satpValue&&status==mstatusValue&&cfg==15&&limit==0x40000000,"oracle CSR/PMP context");
 require(va>=vmVa&&va<vmVa+4096&&!(va&7),"oracle aligned virtual page");
 const std::map<uint64_t,uint64_t> image{{rootPa+8,((l1Pa>>12)<<10)|1},{l1Pa,((l0Pa>>12)<<10)|1},{l0Pa,((vmPa>>12)<<10)|0xc7}};
 uint64_t table=(satp&((1ULL<<44)-1))<<12;
 for(int level=2;level>=0;--level){const uint64_t a=table+8*((va>>(12+9*level))&511);require(a+8<=(limit<<2),"oracle PTE PMP");const auto f=image.find(a);require(f!=image.end(),"oracle absent PTE");const uint64_t pte=f->second;require((pte&1)&&!((pte&4)&&!(pte&2)),"oracle invalid PTE");if(pte&14){require(level==0&&(pte&0x53)==0x43,"oracle readable supervisor leaf");const uint64_t pa=((pte>>10)<<12)|(va&4095);require(pa+8<=(limit<<2),"oracle data PMP");return pa;}table=(pte>>10)<<12;}throw std::runtime_error("oracle no leaf");
}
struct Retire {uint64_t pc=0,data=0,nextPc=0;uint32_t instruction=0;unsigned rd=0;bool writes=false;};
struct Event {Retire r;bool load=false,roi=false,warm=false,loop=false,roiBoundary=false;uint64_t va=0,pa=0;unsigned occurrence=0;};
struct Oracle {
 std::array<uint64_t,32> registers{};std::vector<Event> events;std::map<uint64_t,std::vector<size_t>> loadsByPc;
 uint64_t trapPc=0;unsigned warmLoads=0,roiLoads=0,roiInstructions=0,roiLoop=0;
 explicit Oracle(const Program&p) {
  Memory bytes{};for(size_t b=0;b<bytes.size();++b)bytes[b]=oracleByte(b);
  uint64_t pc=romBase,satp=0,status=0,cfg=0,limit=0;std::map<uint64_t,unsigned> occurrence;
  for(unsigned n=0;n<4000;++n){require(p.architectural(pc),"oracle escaped image "+hex(pc));const uint32_t ins=p.word(pc);if(ins==ebreak){trapPc=pc;require(warmLoads==p.bodyLoads&&roiLoads==p.bodyLoads*p.measuredIterations,"oracle independent body count");return;}
   Event e;e.roiBoundary=pc==p.bodyEntry&&registers[21]==1;e.r={pc,0,pc+4,ins,0,false};const unsigned op=ins&127,rs=(ins>>15)&31;
   if(ins==0x12000073||ins==fence){}else if(op==0x73){require(((ins>>12)&7)==1&&((ins>>7)&31)==0,"oracle CSR subset");switch(ins>>20){case 0x3b0:limit=registers[rs];break;case 0x3a0:cfg=registers[rs];break;case 0x180:satp=registers[rs];break;case 0x300:status=registers[rs];break;default:require(false,"oracle unknown CSR");}}
   else if(op==3){require(((ins>>12)&7)==3&&pc>=p.body&&pc<p.bodyEnd,"oracle LD subset");e.load=true;e.occurrence=++occurrence[pc];e.warm=e.occurrence==1;e.roi=!e.warm;e.va=registers[rs]+(int(ins>>20)^2048)-2048;e.pa=oracleWalk(e.va,satp,status,cfg,limit);e.r.rd=(ins>>7)&31;e.r.writes=e.r.rd!=0;for(unsigned b=0;b<8;++b)e.r.data|=uint64_t(bytes.at(e.pa-vmPa+b))<<(8*b);loadsByPc[pc].push_back(events.size());warmLoads+=e.warm;roiLoads+=e.roi;}
   else {const Encoding*enc=decode(ins);require(enc&&!enc->memory&&!enc->mulDiv,"oracle unsupported integer");const Expected x=interpret(*enc,ins,pc,registers,bytes);require(!x.fault,"oracle integer fault");e.r.data=x.result;e.r.nextPc=x.nextPc;e.r.rd=x.rd;e.r.writes=x.rd!=0;}
   e.loop=pc>=p.bodyEnd&&pc<p.loopEnd;e.roi=e.roi||(e.loop&&registers[21]==1);roiInstructions+=e.roi;roiLoop+=e.roi&&e.loop;
   if(e.r.writes)registers[e.r.rd]=e.r.data;registers[0]=0;events.push_back(e);pc=e.r.nextPc;
  }throw std::runtime_error("oracle dynamic bound");
 }
};
void checkRetire(const Retire&a,const Retire&e) {require(a.pc==e.pc,"retirement PC expected "+hex(e.pc)+" got "+hex(a.pc));require(a.instruction==e.instruction,"retirement raw instruction");require(a.rd==e.rd&&a.writes==e.writes,"retirement destination");require(!e.writes||a.data==e.data,"retirement data "+hex(a.pc));require(a.nextPc==e.nextPc,"retirement nextPC");}

// Unchanged fixed-latency instruction service and independent protocol checker.
struct Request {
    uint64_t address = 0, data = 0;
    unsigned opcode = 0, param = 0, size = 0, source = 0, mask = 0;
    bool corrupt = false;
    auto tuple() const { return std::tie(address, data, opcode, param, size, source, mask, corrupt); }
    bool operator==(const Request &other) const { return tuple() == other.tuple(); }
};
struct Reply {
    uint64_t data = 0;
    unsigned source = 0, size = 0, opcode = 1, param = 0, sink = 0;
    bool denied = false, corrupt = false;
    auto tuple() const { return std::tie(data, source, size, opcode, param, sink, denied, corrupt); }
    bool operator==(const Reply &other) const { return tuple() == other.tuple(); }
};
struct Transaction { Request request; uint64_t due; unsigned beat = 0; };
unsigned beats(unsigned size) { return size <= 3 ? 1 : 1u << (size - 3); }

// Service production and checking have separate ownership state. The checker
// learns only accepted A requests, independently recomputes byte/beat contents,
// and rejects source reuse, unowned/wrong D, early replies and held changes.
class ManagerOracle {
    const Program &program;
    struct Owner { Request request; uint64_t due; unsigned beat = 0; };
    std::map<unsigned, Owner> owners;
    std::optional<Request> heldA;
    std::optional<Reply> heldD;
public:
    uint64_t accepted = 0, returned = 0, completed = 0;
    explicit ManagerOracle(const Program &p) : program(p) {}
    void a(bool valid, bool ready, const Request &request, uint64_t cycle) {
        if (heldA) require(valid && request == *heldA, "manager oracle A changed while stalled");
        if (!valid) { heldA.reset(); return; }
        require(request.opcode == 4 && request.param == 0 && !request.corrupt,
            "manager oracle requires legal uncorrupted Get");
        require((request.size == 2 || request.size == 3 || request.size == 6) &&
            request.source < maxTransactions, "manager oracle illegal size/source");
        const uint64_t bytes = UINT64_C(1) << request.size;
        require(!(request.address & (bytes - 1)) && program.mapped(request.address, bytes),
            "manager oracle request outside aligned ROM/RAM windows");
        const unsigned mask = request.size >= 3 ? 255 : 15u << (request.address & 7);
        require(request.mask == mask, "manager oracle incorrect byte mask");
        if (ready) {
            require(owners.count(request.source) == 0, "manager oracle source reused before last D beat");
            owners.emplace(request.source, Owner{request, cycle + serviceLatency, 0});
            ++accepted; heldA.reset();
        } else heldA = request;
    }
    void d(bool valid, bool ready, const Reply &reply, uint64_t cycle, bool negative = false) {
        const std::string prefix = negative ? "A1_MANAGER_NEGATIVE_REACHED " : "manager oracle ";
        if (heldD) require(valid && reply == *heldD, prefix + "D changed while stalled");
        if (!valid) { heldD.reset(); return; }
        const auto found = owners.find(reply.source);
        require(found != owners.end(), prefix + "D source has no accepted Get");
        Owner &owner = found->second;
        require(cycle >= owner.due, prefix + "reply earlier than fixed service latency");
        require(reply.opcode == 1 && reply.param == 0 && reply.sink == 0 &&
            !reply.denied && !reply.corrupt && reply.size == owner.request.size,
            prefix + "AccessAckData metadata");
        const uint64_t address = (owner.request.address & ~UINT64_C(7)) + 8 * owner.beat;
        require(reply.data == program.beat(address), prefix + "byte/beat mismatch");
        if (ready) {
            ++returned;
            if (++owner.beat == beats(owner.request.size)) { owners.erase(found); ++completed; }
            heldD.reset();
        } else heldD = reply;
    }
    bool idle() const { return owners.empty() && !heldA && !heldD; }
};
class InstructionManager {
    const Program &program;
    std::deque<Transaction> pending;
    std::set<unsigned> sources;
public:
    explicit InstructionManager(const Program &p) : program(p) {}
    bool ready() const { return pending.size() < maxTransactions; }
    std::optional<Reply> offer(uint64_t cycle) const {
        if (pending.empty() || cycle < pending.front().due) return {};
        const auto &entry = pending.front();
        return Reply{program.beat((entry.request.address & ~UINT64_C(7)) + 8 * entry.beat),
            entry.request.source, entry.request.size};
    }
    void accept(const Request &request, uint64_t cycle) {
        require(sources.insert(request.source).second, "service duplicated a live source");
        pending.push_back({request, cycle + serviceLatency, 0});
    }
    void consume() {
        require(!pending.empty(), "service consumed empty D queue");
        auto &entry = pending.front();
        if (++entry.beat == beats(entry.request.size)) {
            sources.erase(entry.request.source); pending.pop_front();
        }
    }
    bool idle() const { return pending.empty() && sources.empty(); }
};
struct Grant {unsigned source=0,sink=0,cap=0;bool denied=false,corrupt=false;std::array<uint64_t,8> data{};auto tuple()const{return std::tie(source,sink,cap,denied,corrupt,data);}bool operator==(const Grant&o)const{return tuple()==o.tuple();}};
struct DataOwner {Request request;uint64_t accepted=0,due=0;bool prefetch=false;unsigned mshr=0;};
// Service state is deliberately separate from the protocol audit's state.
class DataManager {
 unsigned latency;std::map<unsigned,DataOwner> owners;std::deque<unsigned> order;std::set<unsigned>sinks;std::optional<Grant>active;
public:
 explicit DataManager(unsigned n):latency(n){}
 bool ready()const{return owners.size()<16;}
 void prepare(uint64_t cycle){if(active||order.empty()||owners.at(order.front()).due>cycle)return;unsigned sink=0;while(sinks.count(sink))++sink;if(sink==2)return;const auto&o=owners.at(order.front());Grant g;g.source=order.front();g.sink=sink;g.cap=o.request.param==0?1:0;for(unsigned i=0;i<8;++i)g.data[i]=managerData(o.request.address+i*8);sinks.insert(sink);active=g;}
 std::optional<Grant> offer()const{return active;}
 void accept(const Request&r,uint64_t c,bool pf,unsigned m){require(!owners.count(r.source),"data service source reuse");owners.emplace(r.source,DataOwner{r,c,c+latency,pf,m});order.push_back(r.source);}
 void consume(){require(active&&order.front()==active->source,"data service Grant ordering");require(owners.erase(active->source)==1,"data service absent source");order.pop_front();active.reset();}
 void ack(unsigned sink){require(sinks.erase(sink)==1,"data service unowned E");}
 bool idle()const{return owners.empty()&&order.empty()&&sinks.empty()&&!active;}
};
class DataAudit {
 unsigned latency;std::map<unsigned,DataOwner>owners;std::deque<unsigned>order;std::set<unsigned>sinks;std::optional<Request>heldA;std::optional<Grant>heldGrant;
 static uint64_t expectedWord(uint64_t a){require(a>=vmPa&&a+8<=vmPa+4096&&!(a&7),"data audit aperture");uint64_t x=0;for(unsigned byte=0;byte<8;++byte){const uint64_t pos=a-vmPa+byte;const uint8_t b=oracleByte(pos);x+=uint64_t(b)<<(8*byte);}return x;}
public:
 uint64_t accepted=0,returned=0,acks=0,prefetchA=0,demandA=0;std::map<uint64_t,uint64_t>latencies;
 explicit DataAudit(unsigned n):latency(n){}
 const std::map<unsigned,DataOwner>& pending()const{return owners;}
 void a(bool valid,bool ready,const Request&r,uint64_t c,bool pf,unsigned m){if(heldA)require(valid&&r==*heldA,"data held A changed");if(!valid){heldA.reset();return;}
  require(r.opcode==6&&r.param<=1&&r.size==6&&r.source<2&&r.mask==255&&!r.corrupt&&!(r.address&63)&&r.address>=vmPa&&r.address+64<=vmPa+4096,"illegal data AcquireBlock "+hex(r.address));
  if(ready){require(!owners.count(r.source),"data audit source reused before actual Grant");require(owners.size()<16,"data audit capacity");owners.emplace(r.source,DataOwner{r,c,c+latency,pf,m});order.push_back(r.source);++accepted;prefetchA+=pf;demandA+=!pf;heldA.reset();}else heldA=r;
 }
 void grant(const std::optional<Grant>&g,bool ready,uint64_t c){if(heldGrant)require(g&&*g==*heldGrant,"data held Grant changed");if(!g){heldGrant.reset();return;}auto f=owners.find(g->source);require(f!=owners.end()&&!order.empty()&&order.front()==g->source,"data Grant lacks ordered source");const auto&o=f->second;require(c>=o.due,"data Grant earlier than declared whole-line latency");require(g->sink<2&&!sinks.count(g->sink)&&g->cap==(o.request.param==0?1u:0u)&&!g->denied&&!g->corrupt,"data Grant metadata/sink reuse");for(unsigned i=0;i<8;++i)require(g->data[i]==expectedWord(o.request.address+8*i),"data Grant independent bytes");if(ready){++latencies[c-o.accepted];++returned;sinks.insert(g->sink);owners.erase(f);order.pop_front();heldGrant.reset();}else heldGrant=g;}
 void e(bool valid,unsigned sink){if(valid){require(sinks.erase(sink)==1,"data audit unowned E");++acks;}}
 bool idle()const{return owners.empty()&&order.empty()&&sinks.empty()&&!heldA&&!heldGrant;}
};
using Token=std::pair<unsigned,uint64_t>;
struct LoadOwner {
 Token token;uint64_t pc=0,va=0,pa=0,expectedData=0,epoch=0,start=0;
 unsigned observedOccurrence=0;std::optional<size_t>event;bool prechecked=false,requested=false,completed=false,retired=false,cancelled=false;
 std::optional<uint64_t>upstream,checked,physical,reply,complete,retire;
 bool hit=false,miss=false;
};
struct ScalarReply {unsigned owner;uint64_t due;bool clear;uint64_t data;};
struct Sample {
 uint64_t cycle=0;bool work=false,offer=false,ready=false,start=false,complete=false,physical=false,response=false,hit=false,miss=false;
 unsigned live=0,credits=0,creditComplete=0,demandMshr=0,prefetchMshr=0,engines=0,hostOwners=0;
 bool qualified=false,choice=false,staged=false;unsigned lsuStateCode=0,accepted=0,present=0,consume=0;bool packetFlush=false,fetch=false,physicalFetch=false;
 bool aValid=false,aReady=false,aFire=false,grantValid=false,grantReady=false,grantFire=false,eFire=false;
};
using Histogram=std::map<uint64_t,uint64_t>;
std::string histJson(const Histogram&h){std::ostringstream s;s<<'{';bool first=true;for(auto [k,v]:h){if(!first)s<<',';first=false;s<<'"'<<k<<"\":"<<v;}s<<'}';return s.str();}
struct Window {
 uint64_t cycles=0,offer=0,ready=0,start=0,complete=0,physical=0,response=0,hit=0,miss=0,accepted=0,present=0,consume=0,flush=0,fetch=0,physicalFetch=0;
 uint64_t aValid=0,aReady=0,aFire=0,grantValid=0,grantReady=0,grantFire=0,eFire=0,qualified=0,qualRun=0,qualMaxRun=0;
 uint64_t choice=0,staged=0; unsigned maxDemand=0,maxPrefetch=0,maxEngine=0,maxHost=0;Histogram lsuStates,live,credits,completedCredits,mshrDemand,mshrPrefetch,engines,packetPresent,packetConsume,startGaps;std::optional<uint64_t>lastStart;
 void add(const Sample&s){++cycles;choice+=s.choice;staged+=s.staged;++lsuStates[s.lsuStateCode];offer+=s.offer;ready+=s.ready;start+=s.start;complete+=s.complete;physical+=s.physical;response+=s.response;hit+=s.hit;miss+=s.miss;accepted+=s.accepted;present+=s.present;consume+=s.consume;flush+=s.packetFlush;fetch+=s.fetch;physicalFetch+=s.physicalFetch;aValid+=s.aValid;aReady+=s.aReady;aFire+=s.aFire;grantValid+=s.grantValid;grantReady+=s.grantReady;grantFire+=s.grantFire;eFire+=s.eFire;qualified+=s.qualified;qualRun=s.qualified?qualRun+1:0;qualMaxRun=std::max(qualMaxRun,qualRun);maxDemand=std::max(maxDemand,s.demandMshr);maxPrefetch=std::max(maxPrefetch,s.prefetchMshr);maxEngine=std::max(maxEngine,s.engines);maxHost=std::max(maxHost,s.hostOwners);++live[s.live];++credits[s.credits];++completedCredits[s.creditComplete];++mshrDemand[s.demandMshr];++mshrPrefetch[s.prefetchMshr];++engines[s.engines];++packetPresent[s.present];++packetConsume[s.consume];if(s.start){if(lastStart)++startGaps[s.cycle-*lastStart];lastStart=s.cycle;}}
 std::string json()const{std::ostringstream o;o<<"{\"cycles\":"<<cycles<<",\"memory_choice_valid\":"<<choice<<",\"staged_memory_valid\":"<<staged<<",\"lsu_state_code_hist\":"<<histJson(lsuStates)<<",\"lsu_offer\":"<<offer<<",\"lsu_ready\":"<<ready<<",\"lsu_fire\":"<<start<<",\"lsu_complete\":"<<complete<<",\"physical_fire\":"<<physical<<",\"physical_reply\":"<<response<<",\"cache_hit\":"<<hit<<",\"cache_miss\":"<<miss<<",\"accepted_instructions\":"<<accepted<<",\"packet_present_sum\":"<<present<<",\"packet_consume_sum\":"<<consume<<",\"packet_flush\":"<<flush<<",\"virtual_fetch\":"<<fetch<<",\"physical_fetch\":"<<physicalFetch<<",\"a_valid\":"<<aValid<<",\"a_ready\":"<<aReady<<",\"a_fire\":"<<aFire<<",\"grant_valid\":"<<grantValid<<",\"grant_ready\":"<<grantReady<<",\"grant_fire\":"<<grantFire<<",\"e_fire\":"<<eFire<<",\"a_acceptance_duty\":"<<(cycles?double(aFire)/cycles:0)<<",\"whole_line_grant_duty\":"<<(cycles?double(grantFire)/cycles:0)<<",\"max_demand_mshr\":"<<maxDemand<<",\"max_prefetch_mshr\":"<<maxPrefetch<<",\"max_engine\":"<<maxEngine<<",\"max_host_pending_not_mshr_evidence\":"<<maxHost<<",\"qualified_two_pending_demand_cycles\":"<<qualified<<",\"qualified_max_contiguous_cycles\":"<<qualMaxRun<<",\"lsu_live_hist\":"<<histJson(live)<<",\"response_credit_hist\":"<<histJson(credits)<<",\"response_complete_hist\":"<<histJson(completedCredits)<<",\"demand_mshr_hist\":"<<histJson(mshrDemand)<<",\"prefetch_mshr_hist\":"<<histJson(mshrPrefetch)<<",\"engine_hist\":"<<histJson(engines)<<",\"packet_present_hist\":"<<histJson(packetPresent)<<",\"packet_consume_hist\":"<<histJson(packetConsume)<<",\"start_gap_hist\":"<<histJson(startGaps)<<'}';return o.str();}
};
#ifndef A1_LOAD_ORACLE_ONLY
class Run {
 const Program&program;const Oracle oracle;std::unique_ptr<GsimModelStorage<SCommonA1VmPipelineGsim>>storage;SCommonA1VmPipelineGsim&dut;
 InstructionManager instruction;ManagerOracle instructionAudit;DataManager data;DataAudit dataAudit;
 std::array<std::deque<ScalarReply>,2>scalar;std::array<std::set<unsigned>,2>scalarOwners;
 std::array<std::optional<Token>,4>slots;std::map<Token,LoadOwner>loads;std::deque<Token>lsuQ,ingressQ,checkedQ,physicalQ;
 std::map<uint64_t,unsigned>startedOccurrences,retiredOccurrences;std::set<Token>retiredTokens;std::vector<Sample>samples;
 uint64_t cycle=0,workCycles=0,drainCycles=0,inspectionCycles=0,clearRequests=0,clearReplies=0,pteRequests=0,pteReplies=0;
 std::optional<uint64_t>roiFenceRetire,trapCycle;size_t roiFenceEvent=0;std::vector<uint64_t>retirementCycles;
 uint64_t dtlbHits=0,translationRequests=0,translationReplies=0,prechecked=0;size_t retired=0;bool terminal=false,trace=false;
 static unsigned slot(unsigned mask){require(mask&&!(mask&(mask-1))&&mask<16,"LSU slot not one hot");unsigned n=0;while(!(mask&(1u<<n)))++n;return n;}
 static Token pop(std::deque<Token>&q,const char*why){require(!q.empty(),why);const Token t=q.front();q.pop_front();return t;}
 LoadOwner&owner(Token t){auto f=loads.find(t);require(f!=loads.end(),"missing full-token load owner");return f->second;}
 uint64_t valueFor(uint64_t pa)const{require(pa>=vmPa&&pa+8<=vmPa+4096&&!(pa&7),"load owner outside data page");uint64_t v=0;for(unsigned j=0;j<8;++j){const size_t b=pa-vmPa+j;const uint8_t byte=oracleByte(b);v|=uint64_t(byte)<<(8*j);}return v;}
 void flow(Sample&s){
  require(dut.get_m3$$enabled()&&dut.get_flow$$enabled(),"saved actual M3/flow profile disabled");
  // Old completion releases its exact owner before a same-edge new start.
  if(dut.get_m3$$complete$$valid()){const unsigned n=slot(dut.get_m3$$completeSlots());const Token t{dut.get_m3$$complete$$bits$$token$$index(),dut.get_m3$$complete$$bits$$token$$tag()};require(slots[n]&&*slots[n]==t,"LSU completion slot/full-token");auto&o=owner(t);require(!o.completed&&!dut.get_m3$$complete$$bits$$exception()&&dut.get_m3$$complete$$bits$$data()==o.expectedData,"LSU completion independent result");o.completed=true;o.complete=cycle;slots[n].reset();s.complete=true;}
  if(dut.get_m3$$start$$valid()){const unsigned n=slot(dut.get_m3$$startSlots());require(!slots[n],"LSU live slot overwritten");LoadOwner o;o.token={dut.get_m3$$start$$bits$$token$$index(),dut.get_m3$$start$$bits$$token$$tag()};o.pc=dut.get_m3$$start$$bits$$pc();o.va=dut.get_m3$$start$$bits$$address();o.pa=oracleWalk(o.va,satpValue,mstatusValue,15,0x40000000);o.expectedData=valueFor(o.pa);o.epoch=dut.get_m3$$start$$bits$$translationEpoch();o.prechecked=dut.get_m3$$start$$bits$$precheckedLoad();o.start=cycle;o.observedOccurrence=++startedOccurrences[o.pc];require(oracle.loadsByPc.count(o.pc)&&!dut.get_m3$$start$$bits$$store()&&!dut.get_m3$$start$$bits$$atomic()&&!dut.get_m3$$start$$bits$$forward$$valid()&&dut.get_m3$$start$$bits$$size()==3&&!dut.get_m3$$start$$bits$$accessDenied(),"unexpected LSU load start shape/PC");if(o.prechecked)require(dut.get_m3$$start$$bits$$physicalAddress()==o.pa,"prechecked load physical owner");require(loads.emplace(o.token,o).second,"duplicate full-token load start");slots[n]=o.token;s.start=true;prechecked+=o.prechecked;}
  const unsigned mask=dut.get_flow$$requestSlots();if(mask){const unsigned n=slot(mask);require(slots[n].has_value(),"LSU request without live slot");auto&o=owner(*slots[n]);require(!o.requested,"load submitted twice");o.requested=true;lsuQ.push_back(o.token);}
  if(dut.get_io$$upstream$$valid()){const Token t=pop(lsuQ,"DTA ingress without LSU request");auto&o=owner(t);o.upstream=cycle;require(!dut.get_io$$upstream$$bits$$write()&&!dut.get_io$$upstream$$bits$$atomic()&&dut.get_io$$upstream$$bits$$size()==3&&dut.get_io$$upstream$$bits$$mask()==255&&bool(dut.get_io$$upstream$$bits$$precheckedLoad())==o.prechecked&&dut.get_io$$upstream$$bits$$address()==(o.prechecked?o.pa:o.va),"DTA ingress ordered payload");ingressQ.push_back(t);}
  if(dut.get_io$$checked$$valid()){const Token t=pop(ingressQ,"checked without ordered ingress");auto&o=owner(t);o.checked=cycle;require(!dut.get_io$$checkedFault()&&!dut.get_io$$checkedPageFault()&&!dut.get_io$$checked$$bits$$write()&&!dut.get_io$$checked$$bits$$virtualized()&&dut.get_io$$checked$$bits$$address()==o.pa&&dut.get_io$$checked$$bits$$size()==3&&dut.get_io$$checked$$bits$$mask()==255,"checked load permission/PA");checkedQ.push_back(t);}
  if(dut.get_io$$physical$$valid()){const Token t=pop(checkedQ,"physical without checked owner");auto&o=owner(t);require(o.checked&&cycle>*o.checked,"physical bypassed checked register");o.physical=cycle;require(!dut.get_io$$physical$$bits$$write()&&dut.get_io$$physical$$bits$$address()==o.pa&&dut.tile$cache$cpuFire,"physical/cache acceptance owner");o.hit=dut.tile$cache$ordinary&&dut.tile$cache$readHit;o.miss=dut.tile$cache$ordinary&&!dut.tile$cache$found;require(o.hit||o.miss,"read physical accepted without hit/miss classification");physicalQ.push_back(t);s.physical=true;s.hit=o.hit;s.miss=o.miss;}
  else require(!dut.tile$cache$cpuFire,"cache CPU fire without physical owner");
  if(dut.get_io$$physicalResponse()){const Token t=pop(physicalQ,"physical reply without ordered request");auto&o=owner(t);require(o.physical&&!o.reply,"duplicate physical reply");o.reply=cycle;s.response=true;}
  dtlbHits+=dut.get_io$$dtlbHit();translationRequests+=dut.get_io$$translationRequest$$valid();translationReplies+=dut.get_io$$translationResponse$$valid();
  if(dut.get_io$$translationResponse$$valid())require(!dut.get_io$$translationResponse$$bits$$pageFault()&&!dut.get_io$$translationResponse$$bits$$accessFault(),"unexpected translation exception");
 }
 // Passive elastic evidence. The tiny-module independent FSM oracle owns adversarial
 // lifecycle coverage; this CPU checks actual query -> authorized proof -> LSU issue.
 struct ProofQuery {uint64_t cycle,va,epoch;unsigned size;bool descriptor;};
 std::map<Token,ProofQuery>proofQueries;
 struct ProofSample {uint64_t cycle;unsigned occupied;bool query,descriptor,capture,advance,hit,negative,preempt;};
 std::vector<ProofSample>proofSamples;std::map<Token,uint64_t>proofIssueLatency;
 void proofObserve(){
  const bool q=dut.get_proof$$queryAccept(),from=dut.get_proof$$queryFromDescriptor();
  const uint64_t epoch=dut.get_proof$$epoch();
  if(q){
   require(dut.get_proof$$queryOffer()&&dut.get_proof$$stable()&&!dut.get_proof$$flush(),"elastic query accepted outside stable context");
   Token t;uint64_t va;unsigned size;
   if(from){require(dut.get_proof$$descriptorOwner$$valid(),"elastic descriptor query lacks owner");t={dut.get_proof$$descriptorOwner$$bits$$token$$index(),dut.get_proof$$descriptorOwner$$bits$$token$$tag()};va=dut.get_proof$$descriptorOwner$$bits$$address();size=dut.get_proof$$descriptorOwner$$bits$$size();require(dut.get_proof$$descriptorOwner$$bits$$epoch()==epoch&&(dut.get_proof$$live()&1),"elastic descriptor query stale/dead owner");}
   else {require(dut.get_proof$$current$$valid(),"elastic current query lacks owner");t={dut.get_proof$$current$$bits$$token$$index(),dut.get_proof$$current$$bits$$token$$tag()};va=dut.get_proof$$current$$bits$$address();size=dut.get_proof$$current$$bits$$size();}
   proofQueries[t]={cycle,va,epoch,size,from};
  }
  if(dut.get_proof$$prepared$$valid()&&dut.get_proof$$prepared$$bits$$allowed()){
   require(dut.get_proof$$stable()&&!dut.get_proof$$flush()&&dut.get_proof$$prepared$$bits$$epoch()==epoch,"elastic positive certificate outside current context");
   const uint64_t va=dut.get_proof$$prepared$$bits$$address();
   require(dut.get_proof$$prepared$$bits$$size()==3&&dut.get_proof$$prepared$$bits$$physicalAddress()==oracleWalk(va,satpValue,mstatusValue,15,0x40000000),"elastic positive certificate independent Sv39/PMP PA");
  }
  if(dut.get_m3$$start$$valid()&&dut.get_m3$$start$$bits$$precheckedLoad()){
   const Token t{dut.get_m3$$start$$bits$$token$$index(),dut.get_m3$$start$$bits$$token$$tag()};
   const auto f=proofQueries.find(t);require(f!=proofQueries.end(),"elastic prechecked issue without observed query owner");const auto&qv=f->second;
   require(dut.get_proof$$prepared$$valid()&&dut.get_proof$$prepared$$bits$$allowed()&&dut.get_proof$$prepared$$bits$$token$$index()==t.first&&dut.get_proof$$prepared$$bits$$token$$tag()==t.second&&dut.get_proof$$prepared$$bits$$address()==dut.get_m3$$start$$bits$$address()&&dut.get_proof$$prepared$$bits$$physicalAddress()==dut.get_m3$$start$$bits$$physicalAddress()&&dut.get_proof$$prepared$$bits$$size()==dut.get_m3$$start$$bits$$size()&&dut.get_proof$$prepared$$bits$$epoch()==dut.get_m3$$start$$bits$$translationEpoch(),"elastic actual LSU issue lost exact authorized proof owner");
   require(qv.va==dut.get_m3$$start$$bits$$address()&&qv.size==3&&qv.epoch==epoch&&cycle>=qv.cycle+2,"elastic query/permission registers or full owner violated");
   require(proofIssueLatency.emplace(t,cycle-qv.cycle).second,"elastic owner issued twice");
  }
  proofSamples.push_back({cycle,unsigned(bool(dut.get_proof$$descriptorOwner$$valid()))+unsigned(bool(dut.get_proof$$translatedOwner$$valid()))+unsigned(bool(dut.get_proof$$preparedOwner$$valid())),q,q&&from,bool(dut.get_proof$$descriptorCapture()),bool(dut.get_proof$$translatedAdvance()),bool(dut.get_proof$$hit()),bool(dut.get_proof$$negativeExpire()),bool(dut.get_proof$$descriptorPreempt()||dut.get_proof$$translatedPreempt()||dut.get_proof$$preparedPreempt())});
 }
 void proofReport(){
  uint64_t queries=0,descriptor=0,captures=0,advance=0,hits=0,negative=0,preempt=0;Histogram occupancy,gaps,latencies;std::optional<uint64_t>last;
  for(const auto&s:proofSamples)if(s.cycle>*roiFenceRetire&&s.cycle<=*trapCycle){queries+=s.query;descriptor+=s.descriptor;captures+=s.capture;advance+=s.advance;hits+=s.hit;negative+=s.negative;preempt+=s.preempt;++occupancy[s.occupied];if(s.query){if(last)++gaps[s.cycle-*last];last=s.cycle;}}
  for(const auto&[t,o]:loads)if(o.retired&&oracle.events[*o.event].roi&&o.prechecked){require(proofIssueLatency.count(t),"ROI prechecked issue lacks elastic latency");++latencies[proofIssueLatency.at(t)];}
  std::cout<<"ELASTIC_PROOF_METRIC {\"name\":\""<<program.name<<"\",\"roi_queries\":"<<queries<<",\"roi_descriptor_queries\":"<<descriptor<<",\"roi_descriptor_captures\":"<<captures<<",\"roi_translated_advances\":"<<advance<<",\"roi_hits\":"<<hits<<",\"roi_negative_expiry\":"<<negative<<",\"roi_preempt_cycles\":"<<preempt<<",\"roi_raw_occupancy_hist\":"<<histJson(occupancy)<<",\"roi_query_gap_hist\":"<<histJson(gaps)<<",\"retired_roi_query_to_issue_hist\":"<<histJson(latencies)<<"}\n";
 }
 void retireOne(const Retire&r,Token t){require(!terminal&&retired<oracle.events.size()&&retiredTokens.insert(t).second,"extra/duplicate retirement");const Event&e=oracle.events[retired];checkRetire(r,e.r);retirementCycles.push_back(cycle);if(e.roiBoundary){require(!roiFenceRetire,"duplicate measured entry FENCE retirement");roiFenceRetire=cycle;roiFenceEvent=retired;}if(e.load){auto&o=owner(t);const unsigned occurrence=++retiredOccurrences[r.pc];const auto&ids=oracle.loadsByPc.at(r.pc);require(occurrence<=ids.size()&&ids[occurrence-1]==retired&&e.occurrence==occurrence,"precomputed per-PC dynamic retirement occurrence");require(o.completed&&!o.cancelled&&o.pc==e.r.pc&&o.va==e.va&&o.pa==e.pa&&o.expectedData==e.r.data&&!o.retired,"full-token architectural load owner/result");o.event=retired;o.retired=true;o.retire=cycle;}++retired;}
 void drive(bool stopped,unsigned inspect){
  dut.set_io$$hold(stopped);dut.set_io$$inspectRegister(inspect);dut.set_io$$instructionA$$ready(instruction.ready());const auto ir=instruction.offer(cycle);const Reply b=ir.value_or(Reply{});dut.set_io$$instructionD$$valid(bool(ir));
#define ID(F) dut.set_io$$instructionD$$bits$$##F(b.F)
  ID(opcode);ID(param);ID(size);ID(source);ID(sink);ID(denied);ID(data);ID(corrupt);
#undef ID
#define SCALAR(N) \
 dut.set_io$$scalar##N##$$request$$ready(true); \
 dut.set_io$$scalar##N##$$response$$valid(!scalar[N].empty()&&scalar[N].front().due<=cycle); \
 dut.set_io$$scalar##N##$$response$$bits$$owner(scalar[N].empty()?0:scalar[N].front().owner); \
 dut.set_io$$scalar##N##$$response$$bits$$clearReservation(scalar[N].empty()?false:scalar[N].front().clear); \
 dut.set_io$$scalar##N##$$response$$bits$$memory$$data(scalar[N].empty()?0:scalar[N].front().data); \
 dut.set_io$$scalar##N##$$response$$bits$$memory$$error(false); \
 dut.set_io$$scalar##N##$$response$$bits$$memory$$pageFault(false)
  SCALAR(0);SCALAR(1);
#undef SCALAR
  data.prepare(cycle);const auto g=data.offer();const Grant v=g.value_or(Grant{});dut.set_io$$dataA$$ready(data.ready());dut.set_io$$dataC$$ready(true);dut.set_io$$dataE$$ready(true);dut.set_io$$dataGrant$$valid(bool(g));dut.set_io$$dataGrant$$bits$$source(v.source);dut.set_io$$dataGrant$$bits$$sink(v.sink);dut.set_io$$dataGrant$$bits$$cap(v.cap);dut.set_io$$dataGrant$$bits$$denied(v.denied);dut.set_io$$dataGrant$$bits$$corrupt(v.corrupt);
#define DW(N) dut.set_io$$dataGrant$$bits$$data##N(v.data[N])
  DW(0);DW(1);DW(2);DW(3);DW(4);DW(5);DW(6);DW(7);
#undef DW
 }
 void occupancy(Sample&s,const std::optional<Grant>&grant){
  const std::array<unsigned,4>state{unsigned(dut.get_supply$$states())&3u,(unsigned(dut.get_supply$$states())>>2)&3u,(unsigned(dut.get_supply$$states())>>4)&3u,(unsigned(dut.get_supply$$states())>>6)&3u};
  const std::array<bool,4>cancel{bool(dut.get_supply$$cancelled()&1),bool(dut.get_supply$$cancelled()&2),bool(dut.get_supply$$cancelled()&4),bool(dut.get_supply$$cancelled()&8)};
  // An idle operation payload is never interpreted. Cancellation is attached
  // only to an already valid, independently captured full-token slot owner.
  for(unsigned n=0;n<4;++n){require(state[n]<4,"invalid LSU state");s.lsuStateCode|=state[n]<<(2*n);s.live+=state[n]!=0;if(slots[n]){auto&o=owner(*slots[n]);if(state[n]&&cancel[n])o.cancelled=true;if(!state[n]){require(o.cancelled&&!o.retired,"LSU owner vanished without complete/cancellation");require(!o.requested||o.reply,"cancelled LSU released before physical response drain");slots[n].reset();}}else require(state[n]==0,"busy LSU slot without start owner");}
#define VALID_SLOT_TOKEN(N) if(state[N]) { require(slots[N].has_value(),"valid LSU operation has no captured owner"); const Token raw{dut.get_supply$$owner##N##$$index(),dut.get_supply$$owner##N##$$tag()}; require(raw==*slots[N],"valid LSU registered operation changed full token"); }
  VALID_SLOT_TOKEN(0);VALID_SLOT_TOKEN(1);VALID_SLOT_TOKEN(2);VALID_SLOT_TOKEN(3);
#undef VALID_SLOT_TOKEN
  for(unsigned i=0;i<2;++i){s.credits+=bool(dut.tile$cache$responseOwned[i]);s.creditComplete+=bool(dut.tile$cache$responseOwned[i]&&dut.tile$cache$responseComplete[i]);const unsigned phase=dut.tile$cache$phase[i];require(phase<=4,"invalid cache phase");if(phase){require(!dut.tile$cache$pending$$write[i],"load-only cache owns a write");if(dut.tile$cache$prefetchOwner[i])++s.prefetchMshr;else ++s.demandMshr;}const unsigned ep=dut.tile$cache$engine$phase[i];require(ep<=4,"invalid fill engine phase");s.engines+=ep!=0;}
  s.hostOwners=dataAudit.pending().size();
  // Qualified witness: BOTH genuine read MSHRs await fill for different lines,
  // BOTH mapped engine sources are in receive, BOTH accepted A owners still
  // lack an accepted Grant. Host queue depth alone never qualifies a witness.
  bool good=s.demandMshr==2;std::array<uint64_t,2>lines{};std::set<unsigned>sources;
  for(unsigned m=0;m<2&&good;++m){good=dut.tile$cache$phase[m]==3&&!dut.tile$cache$prefetchOwner[m]&&!dut.tile$cache$pending$$write[m];if(!good)break;lines[m]=dut.tile$cache$pending$$address[m]&~63ULL;bool found=false;for(unsigned src=0;src<2;++src){if(dut.tile$cache$engine$phase[src]!=2||dut.tile$cache$engine$tag[src]!=m)continue;const auto f=dataAudit.pending().find(src);if(f==dataAudit.pending().end())continue;const bool retiringGrant=grant&&grant->source==src&&dut.get_io$$dataGrant$$ready();if(!retiringGrant&&!f->second.prefetch&&f->second.mshr==m&&(dut.tile$cache$engine$address[src]&~63ULL)==lines[m]&&f->second.request.address==lines[m]){found=true;sources.insert(src);}}good=good&&found;}
  s.qualified=good&&sources.size()==2&&lines[0]!=lines[1];
  if(s.qualified&&(!firstQualified||(roiFenceRetire&&cycle>*roiFenceRetire&&!terminal&&!firstRoiQualified))){std::ostringstream o;o<<"{\"cycle\":"<<cycle<<",\"owners\":[";bool first=true;for(unsigned src:sources){if(!first)o<<',';first=false;const unsigned m=dut.tile$cache$engine$tag[src];o<<"{\"source\":"<<src<<",\"mshr\":"<<m<<",\"line\":"<<lines[m]<<",\"cache_phase\":3,\"engine_phase\":2,\"prefetch\":false,\"pending_index\":"<<dut.tile$cache$pendingIndex[m]<<",\"response_ticket\":"<<unsigned(dut.tile$cache$pendingTicket[m])<<",\"accepted_cycle\":"<<dataAudit.pending().at(src).accepted<<'}';}o<<"]}";if(!firstQualified)firstQualified=o.str();if(roiFenceRetire&&cycle>*roiFenceRetire&&!terminal&&!firstRoiQualified)firstRoiQualified=o.str();}
 }
 bool observersIdle()const{return lsuQ.empty()&&ingressQ.empty()&&checkedQ.empty()&&physicalQ.empty()&&std::all_of(slots.begin(),slots.end(),[](const auto&s){return !s;});}
 bool tick(bool inspect=false,unsigned reg=0){const bool stopped=terminal;const auto ir=instruction.offer(cycle);const bool iaReady=instruction.ready(),daReady=data.ready();drive(stopped,reg);const auto grant=data.offer();dut.step();Sample s;s.cycle=cycle;s.work=!stopped;
  s.offer=dut.get_supply$$offer();s.ready=dut.get_supply$$ready();s.choice=dut.get_supply$$choice();s.staged=dut.get_supply$$staged();
  occupancy(s,grant);flow(s);proofObserve();require(s.start==bool(s.offer&&s.ready),"actual LSU fire differs from final-qualified offer and ready");require(dut.get_io$$robOccupancy()<=16,"ROB capacity");
  s.accepted=dut.get_io$$acceptedInstructions();s.present=dut.get_io$$packetPresent();s.consume=dut.get_io$$packetConsume();s.packetFlush=dut.get_io$$packetFlush();s.fetch=dut.get_io$$virtualFetchFire();s.physicalFetch=dut.get_io$$physicalFetchFire();
  if(!stopped)++workCycles;else if(inspect)++inspectionCycles;else ++drainCycles;
  require(!dut.get_io$$commit1$$valid()||dut.get_io$$commit0$$valid(),"non-prefix retirement");
#define RET(N) if(dut.get_io$$commit##N##$$valid())retireOne({dut.get_io$$commit##N##$$bits$$pc(),dut.get_io$$commit##N##$$bits$$data(),dut.get_io$$commit##N##$$bits$$nextPc(),uint32_t(dut.get_io$$commit##N##$$bits$$instruction()),unsigned(dut.get_io$$commit##N##$$bits$$rd()),bool(dut.get_io$$commit##N##$$bits$$writesRd())},{dut.get_io$$commit##N##$$bits$$token$$index(),dut.get_io$$commit##N##$$bits$$token$$tag()})
  RET(0);RET(1);
#undef RET
  if(dut.get_io$$trap$$valid()){require(!terminal&&retired==oracle.events.size(),"early or repeated trap");require(dut.get_io$$trap$$bits$$pc()==oracle.trapPc&&dut.get_io$$trap$$bits$$cause()==3&&dut.get_io$$trap$$bits$$tval()==oracle.trapPc,"precise EBREAK PC/cause/tval");terminal=true;trapCycle=cycle;}
  instructionAudit.d(bool(ir),dut.get_io$$instructionD$$ready(),ir.value_or(Reply{}),cycle);if(ir&&dut.get_io$$instructionD$$ready())instruction.consume();
  const Request ia{dut.get_io$$instructionA$$bits$$address(),dut.get_io$$instructionA$$bits$$data(),unsigned(dut.get_io$$instructionA$$bits$$opcode()),unsigned(dut.get_io$$instructionA$$bits$$param()),unsigned(dut.get_io$$instructionA$$bits$$size()),unsigned(dut.get_io$$instructionA$$bits$$source()),unsigned(dut.get_io$$instructionA$$bits$$mask()),bool(dut.get_io$$instructionA$$bits$$corrupt())};instructionAudit.a(dut.get_io$$instructionA$$valid(),iaReady,ia,cycle);if(dut.get_io$$instructionA$$valid()&&iaReady)instruction.accept(ia,cycle);
#define SCALAR_OBSERVE(N) \
 if(!scalar[N].empty()&&scalar[N].front().due<=cycle&&dut.get_io$$scalar##N##$$response$$ready()){require(scalarOwners[N].erase(scalar[N].front().owner)==1,"scalar response ownership");if(scalar[N].front().clear)++clearReplies;else ++pteReplies;scalar[N].pop_front();} \
 if(dut.get_io$$scalar##N##$$request$$valid()){require(N==1,"unexpected scalar0 request");const unsigned id=dut.get_io$$scalar##N##$$request$$bits$$owner();require(scalarOwners[N].insert(id).second,"scalar source reuse");const bool clear=dut.get_io$$scalar##N##$$request$$bits$$clearReservation();uint64_t v=0;if(clear){require(terminal,"reservation clear before final trap");++clearRequests;}else{require(!dut.get_io$$scalar##N##$$request$$bits$$memory$$write()&&!dut.get_io$$scalar##N##$$request$$bits$$memory$$atomic()&&!dut.get_io$$scalar##N##$$request$$bits$$memory$$virtualized()&&!dut.get_io$$scalar##N##$$request$$bits$$memory$$precheckedLoad()&&dut.get_io$$scalar##N##$$request$$bits$$memory$$size()==3&&dut.get_io$$scalar##N##$$request$$bits$$memory$$mask()==255,"illegal scalar PTE request");v=managerPte(dut.get_io$$scalar##N##$$request$$bits$$memory$$address());++pteRequests;}scalar[N].push_back({id,cycle+3,clear,v});}
  SCALAR_OBSERVE(0);SCALAR_OBSERVE(1);
#undef SCALAR_OBSERVE
  require(!dut.get_io$$dataC$$valid(),"load-only bounded working set emitted C/eviction");
  s.eFire=dut.get_io$$dataE$$valid();if(s.eFire){const unsigned sink=dut.get_io$$dataE$$bits$$sink();dataAudit.e(true,sink);data.ack(sink);}
  s.grantValid=bool(grant);s.grantReady=dut.get_io$$dataGrant$$ready();s.grantFire=s.grantValid&&s.grantReady;dataAudit.grant(grant,s.grantReady,cycle);if(s.grantFire)data.consume();
  s.aValid=dut.get_io$$dataA$$valid();s.aReady=daReady;s.aFire=s.aValid&&s.aReady;
  const Request a{dut.get_io$$dataA$$bits$$address(),dut.get_io$$dataA$$bits$$data(),unsigned(dut.get_io$$dataA$$bits$$opcode()),unsigned(dut.get_io$$dataA$$bits$$param()),unsigned(dut.get_io$$dataA$$bits$$size()),unsigned(dut.get_io$$dataA$$bits$$source()),unsigned(dut.get_io$$dataA$$bits$$mask()),bool(dut.get_io$$dataA$$bits$$corrupt())};bool pf=false;unsigned m=0;
  if(s.aValid){require(a.source<2,"A source outside actual engine");m=dut.tile$cache$engine$tag[a.source];require(m<2&&dut.tile$cache$phase[m]!=0,"A has no valid MSHR owner");pf=dut.tile$cache$prefetchOwner[m];require(!dut.tile$cache$pending$$write[m]&&(dut.tile$cache$pending$$address[m]&~63ULL)==a.address,"A MSHR read/line mismatch");}
  dataAudit.a(s.aValid,daReady,a,cycle,pf,m);if(s.aFire)data.accept(a,cycle,pf,m);
  if(!inspect)samples.push_back(s);++cycle;
  return terminal&&instruction.idle()&&instructionAudit.idle()&&scalar[0].empty()&&scalar[1].empty()&&scalarOwners[0].empty()&&scalarOwners[1].empty()&&data.idle()&&dataAudit.idle()&&observersIdle()&&dut.get_io$$fetchIdle()&&dut.get_io$$privateIdle()&&dut.get_io$$ownersIdle()&&!dut.get_io$$memoryBusy()&&dut.get_io$$robOccupancy()==0;
 }
 std::optional<std::string>firstQualified,firstRoiQualified;
 void report(){
  uint64_t issueFirst=UINT64_MAX,issueLast=0,retireFirst=UINT64_MAX,retireLast=0,warmLastRetire=0;
  unsigned warm=0,roi=0,speculative=0,cancelled=0,unretiredCompleted=0,roiHits=0,roiMisses=0,roiPhysical=0,roiEarly=0,roiEarlyFence=0;
  Histogram startPhysical,physicalReply,startComplete,startRetire,roiStartGaps;std::vector<uint64_t>roiStarts;
  for(const auto&[token,o]:loads){cancelled+=o.cancelled;if(!o.retired){++speculative;unretiredCompleted+=o.completed;require(o.cancelled||o.completed,"unretired LSU start has no cancellation or completed drain");continue;}require(o.event&&o.physical&&o.reply&&o.complete&&o.retire,"retired load missing full flow");const auto&e=oracle.events[*o.event];if(e.warm){++warm;warmLastRetire=std::max(warmLastRetire,*o.retire);}if(e.roi){++roi;roiHits+=o.hit;roiMisses+=o.miss;roiPhysical+=bool(o.physical);issueFirst=std::min(issueFirst,o.start);issueLast=std::max(issueLast,o.start);retireFirst=std::min(retireFirst,*o.retire);retireLast=std::max(retireLast,*o.retire);++startPhysical[*o.physical-o.start];++physicalReply[*o.reply-*o.physical];++startComplete[*o.complete-o.start];++startRetire[*o.retire-o.start];roiStarts.push_back(o.start);}}
  for(const auto&[token,o]:loads)if(o.retired&&oracle.events[*o.event].roi&&o.start<=warmLastRetire)++roiEarly;
  require(roiFenceRetire&&trapCycle&&*trapCycle>*roiFenceRetire,"missing measured entry FENCE/trap work boundary");for(const auto&[token,o]:loads)if(o.retired&&oracle.events[*o.event].roi&&o.start<=*roiFenceRetire)++roiEarlyFence;
  std::sort(roiStarts.begin(),roiStarts.end());for(size_t i=1;i<roiStarts.size();++i)++roiStartGaps[roiStarts[i]-roiStarts[i-1]];
  require(warm==oracle.warmLoads&&roi==oracle.roiLoads,"committed warm/ROI owner conservation");Window whole,issue,retireWindow,roiWork;uint64_t roiRetired=0;for(uint64_t c:retirementCycles)roiRetired+=c>*roiFenceRetire&&c<=*trapCycle;for(const auto&s:samples){if(s.work)whole.add(s);if(s.cycle>*roiFenceRetire&&s.cycle<=*trapCycle)roiWork.add(s);if(s.cycle>=issueFirst&&s.cycle<=issueLast)issue.add(s);if(s.cycle>=retireFirst&&s.cycle<=retireLast)retireWindow.add(s);}
  std::cout<<"LOAD_SUPPLY_METRIC {\"name\":\""<<program.name<<"\",\"model\":\"new_full_r1_m3_checked_flow_store_row_elastic_proof\",\"fixture\":\"whole_line_512_bit_Grant_not_DDR\",\"service\":{\"instruction_latency\":3,\"pte_latency\":3,\"data_grant_latency\":"<<program.dataLatency()<<",\"data_A_owner_capacity\":16,\"grant_II\":1,\"sink_count\":2,\"sink_reserved_at_grant_offer_only\":true},\"retired\":"<<retired<<",\"warm_loads\":"<<warm<<",\"measured_loads\":"<<roi<<",\"measured_iterations\":"<<program.measuredIterations<<",\"roi_instructions_including_loop\":"<<oracle.roiInstructions<<",\"roi_loop_overhead_retired\":"<<oracle.roiLoop<<",\"speculative_unretired_load_starts\":"<<speculative<<",\"unretired_completed_load_owners\":"<<unretiredCompleted<<",\"cancelled_load_owners\":"<<cancelled<<",\"roi_started_before_or_at_last_warm_retire\":"<<roiEarly<<",\"owner_classification\":\"final_retired_full_token_and_precomputed_per_PC_occurrence\",\"window_traffic\":\"all_actual_traffic_in_inclusive_cycle_window_including_speculation\",\"offer_semantics\":\"final_qualified_backend_offer_not_unconditional_supply\",\"work_cycles\":"<<workCycles<<",\"roi_entry_fence_retire_cycle\":"<<*roiFenceRetire<<",\"terminal_trap_cycle\":"<<*trapCycle<<",\"roi_work_cycles\":"<<roiWork.cycles<<",\"roi_retired\":"<<roiRetired<<",\"roi_architectural_after_entry_fence\":"<<(retired-roiFenceEvent-1)<<",\"roi_useful_loads_per_work_cycle\":"<<double(roi)/roiWork.cycles<<",\"roi_started_before_or_at_entry_fence_retire\":"<<roiEarlyFence<<",\"roi_work_boundary\":\"entry_FENCE_retire_plus_1_through_EBREAK_trap_inclusive_excludes_drain_and_inspection\",\"work_ipc\":"<<double(retired)/workCycles<<",\"drain_cycles\":"<<drainCycles<<",\"inspection_cycles\":"<<inspectionCycles<<",\"issue_first\":"<<issueFirst<<",\"issue_last\":"<<issueLast<<",\"retire_first\":"<<retireFirst<<",\"retire_last\":"<<retireLast<<",\"roi_loads_per_issue_window_cycle\":"<<double(roi)/(issueLast-issueFirst+1)<<",\"roi_loads_per_retire_window_cycle\":"<<double(roi)/(retireLast-retireFirst+1)<<",\"roi_owner_physical\":"<<roiPhysical<<",\"roi_owner_hits\":"<<roiHits<<",\"roi_owner_misses\":"<<roiMisses<<",\"roi_owner_start_gaps\":"<<histJson(roiStartGaps)<<",\"roi_start_to_physical_hist\":"<<histJson(startPhysical)<<",\"roi_physical_to_reply_hist\":"<<histJson(physicalReply)<<",\"roi_start_to_complete_hist\":"<<histJson(startComplete)<<",\"roi_start_to_retire_hist\":"<<histJson(startRetire)<<",\"pte_requests\":"<<pteRequests<<",\"pte_replies\":"<<pteReplies<<",\"dtlb_hit_observations\":"<<dtlbHits<<",\"translation_requests\":"<<translationRequests<<",\"translation_replies\":"<<translationReplies<<",\"prechecked_starts\":"<<prechecked<<",\"instruction_A\":"<<instructionAudit.accepted<<",\"instruction_D_beats\":"<<instructionAudit.returned<<",\"data_A\":"<<dataAudit.accepted<<",\"demand_A\":"<<dataAudit.demandA<<",\"prefetch_A\":"<<dataAudit.prefetchA<<",\"data_Grant\":"<<dataAudit.returned<<",\"data_E\":"<<dataAudit.acks<<",\"A_to_Grant_hist\":"<<histJson(dataAudit.latencies)<<",\"clear_requests\":"<<clearRequests<<",\"clear_replies\":"<<clearReplies<<",\"qualified_first_witness\":"<<firstQualified.value_or("null")<<",\"qualified_first_roi_work_witness\":"<<firstRoiQualified.value_or("null")<<",\"whole_work\":"<<whole.json()<<",\"roi_work\":"<<roiWork.json()<<",\"issue_window\":"<<issue.json()<<",\"retire_window\":"<<retireWindow.json()<<"}\n";
  if(trace)for(const auto&[t,o]:loads)std::cout<<"LOAD_OWNER {\"guest\":\""<<program.name<<"\",\"index\":"<<t.first<<",\"tag\":"<<t.second<<",\"pc\":"<<o.pc<<",\"va\":"<<o.va<<",\"start\":"<<o.start<<",\"observed_PC_occurrence\":"<<o.observedOccurrence<<",\"retired\":"<<(o.retired?"true":"false")<<",\"cancelled\":"<<(o.cancelled?"true":"false")<<",\"architectural_PC_occurrence\":"<<(o.event?oracle.events[*o.event].occurrence:0)<<",\"roi\":"<<((o.event&&oracle.events[*o.event].roi)?"true":"false")<<"}\n";
 }
public:
 Run(const Program&p,bool t):program(p),oracle(p),storage(std::make_unique<GsimModelStorage<SCommonA1VmPipelineGsim>>()),dut(storage->get()),instruction(p),instructionAudit(p),data(p.dataLatency()),dataAudit(p.dataLatency()),trace(t){drive(true,0);dut.set_reset(true);dut.step();dut.step();dut.set_reset(false);}
 void run(){unsigned quiet=0;while(cycle<maxCycles&&quiet<4){if(tick())++quiet;else quiet=0;}require(quiet==4,"30000-cycle bound before precise trap/full owner drain");require(retired==oracle.events.size()&&instructionAudit.accepted==instructionAudit.completed&&instructionAudit.idle(),"instruction/retirement conservation");require(clearRequests==1&&clearReplies==1,"final trap must clear reservation exactly once");require(pteRequests==pteReplies&&pteRequests==3,"one Sv39 page PTE owner conservation");require(dataAudit.accepted==dataAudit.returned&&dataAudit.returned==dataAudit.acks&&dataAudit.idle(),"A/Grant/E owner conservation");for(unsigned n=0;n<32;++n){require(tick(true,n),"GPR inspection reopened drained owner");require(dut.get_io$$committedValue()==oracle.registers[n],"final GPR mismatch x"+std::to_string(n));}report();proofReport();}
};
#endif
} // namespace
int main(int argc,char**argv){try{
 bool trace=false,oracleOnly=false,dump=false;std::string selected;
#ifdef A1_LOAD_ORACLE_ONLY
 oracleOnly=true;
#endif
 for(int i=1;i<argc;++i){const std::string a=argv[i];if(a=="--trace")trace=true;else if(a=="--oracle-only")oracleOnly=true;else if(a=="--dump-programs")dump=true;else if(a=="--guest"&&i+1<argc)selected=argv[++i];else throw std::runtime_error("unknown option "+a);}
 require(selected.empty()||selected=="hot_loads"||selected=="delayed_cold_loads","unknown guest");
 if(oracleOnly)dataOracleSelfTest();
 for(bool cold:{false,true}){const Program p=makeProgram(cold);if(!selected.empty()&&selected!=p.name)continue;
  if(dump){const Oracle o(p);std::cout<<"LOAD_SUPPLY_PROGRAM {\"name\":\""<<p.name<<"\",\"body_entry_fence_pc\":"<<p.bodyEntry<<",\"body_first_load_pc\":"<<p.body<<",\"body_end_pc\":"<<p.bodyEnd<<",\"loop_end_pc\":"<<p.loopEnd<<",\"trap_pc\":"<<o.trapPc<<",\"boot\":[";for(size_t i=0;i<p.boot.size();++i){if(i)std::cout<<',';std::cout<<'"'<<hex(p.boot[i])<<'"';}std::cout<<"],\"code\":[";for(size_t i=0;i<p.code.size();++i){if(i)std::cout<<',';std::cout<<'"'<<hex(p.code[i])<<'"';}std::cout<<"]}\n";continue;}
  if(oracleOnly){const Oracle o(p);std::cout<<"LOAD_SUPPLY_ORACLE {\"name\":\""<<p.name<<"\",\"retired\":"<<o.events.size()<<",\"warm_loads\":"<<o.warmLoads<<",\"roi_loads\":"<<o.roiLoads<<",\"roi_loop\":"<<o.roiLoop<<",\"body_entry_fence_pc\":"<<p.bodyEntry<<",\"body_first_load_pc\":"<<p.body<<",\"body_end_pc\":"<<p.bodyEnd<<",\"trap_pc\":"<<o.trapPc<<"}\n";}
#ifndef A1_LOAD_ORACLE_ONLY
  else Run(p,trace).run();
#endif
 }
 std::cout<<"LOAD_SUPPLY_PASS\n";return 0;
 }catch(const std::exception&e){std::cerr<<"LOAD_SUPPLY_FAIL "<<e.what()<<'\n';return 1;}}
