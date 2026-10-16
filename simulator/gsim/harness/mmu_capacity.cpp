#include "VirtualLoadPrecheckGsim.h"
#include "mmu_capacity_memory.h"
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

static void sweep(unsigned pages, bool copy, bool huge) {
    Bench b; b.tables.huge=huge;
    std::vector<Op> pass;
    for(unsigned i=0;i<pages;i++) {
        const uint64_t off=4096ULL*i+64ULL*i;
        pass.push_back({va+0x20000+off,0x80020000ULL+off});
        if(copy)pass.push_back({va+0x240000+off,0x80040000ULL+off,true});
    }
    b.stream(pass);
    unsigned warmWalks=b.walks;
    auto w=b.walks,h=b.hits,p=b.pteReads,a=b.accepted,c=b.completed;
    auto start=b.cycle;
    for(unsigned round=0;round<128;round++) {
        b.stream(pass);
        if(round==0)std::cout << "FIRST_PASS entries="<<DTLB_ENTRIES<<" huge="<<huge<<" copy="<<copy<<" pages="<<pages<<" walks="<<b.walks-w<<" hits="<<b.hits-h<<" cycles="<<b.cycle-start<<"\n";
    }
    require(b.accepted-a==pass.size()*128 && b.completed-c==pass.size()*128,"capacity transaction count mismatch");
    std::cout<<"CAPACITY_RESULT entries="<<DTLB_ENTRIES<<" huge="<<huge<<" copy="<<copy<<" pages="<<pages<<" warm_walks="<<warmWalks<<" operations="<<b.accepted-a<<" walks="<<b.walks-w<<" hits="<<b.hits-h<<" pte_reads="<<b.pteReads-p<<" cycles="<<b.cycle-start<<"\n";
}
int main(){try {
    for(bool huge:{false,true}) {
        for(unsigned n:{16,17,32})sweep(n,false,huge);
        for(unsigned n:{8,9,16,32})sweep(n,true,huge);
    }
    std::cout<<"MMU_SERVICE_CAPACITY_PASS\n";
    return 0;
} catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
