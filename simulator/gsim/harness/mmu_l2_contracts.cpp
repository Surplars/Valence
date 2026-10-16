#include "VirtualLoadPrecheckGsim.h"
#include "mmu_l2_memory.h"
#include <deque>
#include <optional>
#include <tuple>
#include <vector>
#include <iostream>
#ifndef DTLB_WRITE_READ_REUSE
#define DTLB_WRITE_READ_REUSE 0
#endif
#ifndef DTLB_ENTRIES
#define DTLB_ENTRIES 8
#endif
using namespace virtual_load_test;
// Independent expected permissions/PA/ordered responses; no private TLB index
// or cached permission is consulted. Writes use the existing word value and
// AMOADD adds zero, so a missing or unauthorized physical operation is checked
// by the transaction ledger, not hidden by a mutable data oracle.
struct Op {
    uint64_t address, pa;
    bool write = false, atomic = false, fault = false, page = false;
};
struct Reply { uint64_t due, data; };
using PhysicalPayload = std::tuple<uint64_t, uint64_t, unsigned, unsigned, bool, bool, unsigned>;
class Bench {
    SVirtualLoadPrecheckGsim d;
    std::deque<Reply> ptes, replies;
    std::deque<Op> physicalExpected, responsesExpected;
    std::optional<PhysicalPayload> held;
    std::optional<std::tuple<uint64_t, bool, bool>> heldResponse;
public:
    PageTables tables;
    uint64_t cycle = 0, contextSatp = satp;
    unsigned privilege = 1, cfg = 0x1f, pteDelay = 12;
    unsigned accepted = 0, completed = 0, physicalAccepted = 0, walks = 0, hits = 0, pteReads = 0;
    unsigned blockPhysical = 0, blockResponse = 0, holds = 0;
    bool sum = false, mxr = false, flush = false, mutateAddress = false, mutatePermission = false;
    Bench() { drive({}); d.set_reset(1); d.step(); d.step(); d.set_reset(0); for (int i=0;i<4;++i) tick(); }
    void drive(std::optional<Op> op) {
        Op r = op.value_or(Op{});
        d.set_io$$upstream$$request$$valid(op.has_value());
        d.set_io$$upstream$$request$$bits$$address(r.address);
        d.set_io$$upstream$$request$$bits$$data(r.atomic ? 0 : readValue(r.pa));
        d.set_io$$upstream$$request$$bits$$size(3); d.set_io$$upstream$$request$$bits$$mask(255);
        d.set_io$$upstream$$request$$bits$$write(r.write); d.set_io$$upstream$$request$$bits$$atomic(r.atomic);
        d.set_io$$upstream$$request$$bits$$atomicOp(0);
        d.set_io$$upstream$$request$$bits$$virtualized(1); d.set_io$$upstream$$request$$bits$$uncached(0);
        d.set_io$$upstream$$request$$bits$$prefetchNextAllowed(0);
        d.set_io$$upstream$$request$$bits$$precheckedLoad(0); d.set_io$$upstream$$request$$bits$$translationEpoch(0);
        d.set_io$$upstream$$response$$ready(cycle >= blockResponse && cycle % 11 != 7);
        d.set_io$$physical$$request$$ready(cycle >= blockPhysical && cycle % 7 != 5);
        bool rv = !replies.empty() && replies.front().due <= cycle;
        d.set_io$$physical$$response$$valid(rv);
        d.set_io$$physical$$response$$bits$$data(rv ? replies.front().data : 0);
        d.set_io$$physical$$response$$bits$$error(0); d.set_io$$physical$$response$$bits$$pageFault(0);
        d.set_io$$pte$$request$$ready(cycle % 5 != 3);
        bool pv = !ptes.empty() && ptes.front().due <= cycle;
        d.set_io$$pte$$response$$valid(pv); d.set_io$$pte$$response$$bits$$data(pv ? ptes.front().data : 0);
        d.set_io$$pte$$response$$bits$$error(0);
        d.set_io$$context$$satp(contextSatp); d.set_io$$context$$dataPrivilege(privilege);
        d.set_io$$context$$sum(sum); d.set_io$$context$$mxr(mxr);
        d.set_io$$pmpCfg(cfg); d.set_io$$pmpAddress(allPmp);
        d.set_io$$queryValid(0); d.set_io$$queryAddress(va); d.set_io$$querySize(3); d.set_io$$flush(flush);
    }
    bool tick(std::optional<Op> op = {}) {
        bool rv = !replies.empty() && replies.front().due <= cycle;
        bool pv = !ptes.empty() && ptes.front().due <= cycle;
        drive(op); d.step();
        bool take = op && d.get_io$$upstream$$request$$ready();
        if (take) {
            Op e = *op;
            if (mutatePermission && e.fault) e.fault = e.page = false;
            responsesExpected.push_back(e); if (!e.fault) physicalExpected.push_back(e); ++accepted;
        }
        if (rv && d.get_io$$physical$$response$$ready()) replies.pop_front();
        if (pv && d.get_io$$pte$$response$$ready()) ptes.pop_front();
        if (d.get_io$$pte$$request$$valid() && cycle % 5 != 3) {
            uint64_t a = d.get_io$$pte$$request$$bits();
            require(a >= tables.rootAddress && a < tables.rootAddress + 16384 && !(a & 7), "unexpected PTE address");
            ptes.push_back({cycle + pteDelay, tables.pte(a)}); ++pteReads;
        }
        PhysicalPayload payload = {d.get_io$$physical$$request$$bits$$address(),
            d.get_io$$physical$$request$$bits$$data(), d.get_io$$physical$$request$$bits$$size(),
            d.get_io$$physical$$request$$bits$$mask(), bool(d.get_io$$physical$$request$$bits$$write()),
            bool(d.get_io$$physical$$request$$bits$$atomic()), d.get_io$$physical$$request$$bits$$atomicOp()};
        bool valid = d.get_io$$physical$$request$$valid(), ready = cycle >= blockPhysical && cycle % 7 != 5;
        if (held) require(valid && payload == *held, "DTLB physical payload changed while held");
        held = valid && !ready ? std::optional{payload} : std::nullopt; holds += valid && !ready;
        if (valid && ready) {
            require(!physicalExpected.empty(), "DTLB unauthorized or duplicate physical operation");
            Op e = physicalExpected.front(); physicalExpected.pop_front();
            PhysicalPayload wanted = {e.pa ^ (mutateAddress ? 8ULL : 0ULL), e.atomic ? 0 : readValue(e.pa),
                3, 255, e.write, e.atomic, 0};
            require(payload == wanted, "DTLB independent physical operation mismatch");
            require(!d.get_io$$physical$$request$$bits$$virtualized() &&
                !d.get_io$$physical$$request$$bits$$precheckedLoad(), "DTLB private authorization escaped");
            replies.push_back({cycle + 16, e.write && !e.atomic ? 0 : readValue(e.pa)}); ++physicalAccepted;
        }
        auto response = std::make_tuple(uint64_t(d.get_io$$upstream$$response$$bits$$data()),
            bool(d.get_io$$upstream$$response$$bits$$error()), bool(d.get_io$$upstream$$response$$bits$$pageFault()));
        bool responseValid = d.get_io$$upstream$$response$$valid();
        bool responseReady = cycle >= blockResponse && cycle % 11 != 7;
        if (heldResponse) require(responseValid && response == *heldResponse, "DTLB held response changed");
        heldResponse = responseValid && !responseReady ? std::optional{response} : std::nullopt;
        if (responseValid && responseReady) {
            require(!responsesExpected.empty(), "DTLB response has no independent owner");
            Op e = responsesExpected.front(); responsesExpected.pop_front();
            uint64_t data = e.fault || (e.write && !e.atomic) ? 0 : readValue(e.pa);
            require(response == std::make_tuple(data, e.fault, e.page), "DTLB independent ordered permission/fault mismatch");
            ++completed;
        }
        walks += d.get_io$$translationWalk(); hits += d.get_io$$translationHit(); ++cycle; return take;
    }
    void stream(const std::vector<Op>& ops) {
        const unsigned target = completed + ops.size(); unsigned sent = 0;
        for (unsigned n=0;n<2000000 && completed<target;++n) {
            if (sent < ops.size()) { if (tick(ops[sent])) ++sent; } else tick();
        }
        require(completed == target && sent == ops.size(), "DTLB stream did not complete");
        for (int n=0;n<4;++n) tick();
        require(d.get_io$$idle() && ptes.empty() && replies.empty() && physicalExpected.empty() && responsesExpected.empty(),
            "DTLB adapter/walker/independent owners did not drain");
    }
    void run(Op op) { stream({op}); }
    void invalidate() { flush = true; tick(); flush = false; for (int i=0;i<4;++i) tick(); }
};


static Op a(unsigned n,bool write=false){return {va+0x20000+4096ULL*n+64ULL*n,ram+0x20000+4096ULL*n+64ULL*n,write};}
static Op bpage(unsigned n,bool write=true){return {va+0x240000+4096ULL*n+64ULL*n,ram+0x40000+4096ULL*n+64ULL*n,write};}
static void evict(Bench& b){for(unsigned i=1;i<16;i++)b.run(a(i));b.run(bpage(1));b.run(bpage(2));}
static void warm(Bench& b){for(unsigned i=0;i<16;i++){b.run(a(i));b.run(bpage(i));}}
#ifndef MISS_CACHE_ENTRIES
#define MISS_CACHE_ENTRIES 64
#endif
static Op collide(unsigned way=1){return {va+0x20000+4096ULL*(MISS_CACHE_ENTRIES/2)*way,ram+0x20000+4096ULL*(MISS_CACHE_ENTRIES/2)*way,false};}
static bool poisonAddress=false,poisonPermission=false;
static void contracts(){
 {Bench b;b.mutateAddress=poisonAddress;warm(b);auto w=b.walks;
  b.blockResponse=b.cycle+100;b.run(a(0));require(b.walks==w,"L2 warm hit unexpectedly walked");
  require(b.holds>0,"missing physical backpressure coverage");}
 for(unsigned flags:{0xc3U,0x47U}){
  Bench b;b.mutatePermission=poisonPermission;b.tables.flags[32]=flags;warm(b);auto w=b.walks;
  auto op=a(0,true);op.fault=op.page=true;b.run(op);require(b.walks==w+1,"L2 read incorrectly authorized store");
  w=b.walks;b.run(a(0));require(b.walks==w,"failed store destroyed L2 read authorization");
 }
 {Bench b;warm(b);auto peer=MISS_CACHE_ENTRIES==128?collide():bpage(0);if(MISS_CACHE_ENTRIES==128)b.run(peer);auto w=b.walks;b.run(a(0,true));require(b.walks==w+1,"write upgrade skipped real PTW");
  evict(b);w=b.walks;b.run(a(0,true));b.run(a(0));b.run(peer);
  require(b.walks==w,"L2 write upgrade allocated extra way or failed read subsumption");}
 {Bench b;b.tables.flags[32]=0xe7;warm(b);auto w=b.walks;b.contextSatp^=1ULL<<44;b.run(a(0));
  require(b.walks==w+1,"global L2 entry crossed original exact ASID key");
  w=b.walks;b.sum=true;b.run(a(0));require(b.walks==w+1,"L2 SUM context leak");
  w=b.walks;b.mxr=true;b.run(a(0));require(b.walks==w+1,"L2 MXR context leak");
  b.privilege=0;auto op=a(0);op.fault=op.page=true;b.run(op);b.privilege=1;
  b.tables.rootAddress=root+0x10000;b.contextSatp=(8ULL<<60)|(7ULL<<44)|(b.tables.rootAddress>>12);
  w=b.walks;b.run(a(0));require(b.walks==w+1,"L2 root key leak");}
 {Bench b;warm(b);b.tables.physicals[32]=ram+0x120000;b.invalidate();auto op=a(0);op.pa=ram+0x120000;
  auto w=b.walks;b.run(op);require(b.walks==w+1,"flush retained stale L2 mapping");}
 {Bench b;warm(b);b.cfg=0x18;auto op=a(0);op.fault=true;op.page=false;auto w=b.walks;b.run(op);
  require(b.walks==w,"PMP denial scenario did not exercise cached L2 translation");}
 {Bench b;b.run(a(0));b.run(collide());b.run(collide(2));evict(b);auto w=b.walks;b.run(a(0));
  require(b.walks==w+1,"L2 two-way conflict did not replace oldest slot");}
 std::cout<<"MMU_L2_PERMISSION_CONTEXT_FLUSH_CONFLICT_PASS\n";
}
int main(int argc,char** argv){try{std::string arg=argc>1?argv[1]:"";poisonAddress=arg=="--mutate-address";poisonPermission=arg=="--mutate-permission";contracts();return 0;}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
