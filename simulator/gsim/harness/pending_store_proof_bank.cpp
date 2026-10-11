#include "PendingStoreProofBankGsim.h"
#include "pending_store_proof_reference.h"
#include <array>
#include <cstring>
#include <iostream>
#include <optional>
#include <type_traits>
#ifndef PENDING_STORE_SLOTS
#define PENDING_STORE_SLOTS 1
#endif
using namespace pending_store_reference;
struct Owner { bool valid = false; Proof proof{}; };
struct Input {
    std::array<Owner, 3> owners{};
    unsigned head = 0, eligible = 0, clear = 0, bind = 0, pmp = 0x1f;
    bool pause = false, flush = false, stable = true, hit = true, load = false;
    unsigned pbmt = 0;
    uint32_t epoch = 7, replyEpoch = 7;
    uint64_t replyPa = ram;
    std::optional<Token> consume, reserve, creditConsume, cancel, live0, live1;
};
struct Snapshot {
    std::array<std::optional<Proof>,2> proofs{};
    unsigned bound = 0, reserved = 0, proved = 0;
    bool query = false, write = false, load = false, loadAllowed = false;
    uint64_t queryAddress = 0;
    bool available = false, creditReserved = false, active = false;
    Token creditOwner{};
};
struct Bench {
    SPendingStoreProofBankGsim dut;
    Input in;
    uint64_t cycles = 0;
    unsigned queries = 0, writes = 0, reads = 0, captures = 0;
    bool corruptExpectedTag = false;
    Bench() {
        static_assert(std::is_trivially_copyable_v<SPendingStoreProofBankGsim>);
        std::memset(&dut, 0, sizeof(dut)); dut.LOG_START = 1; dut.activateAll();
        tick(true); tick(true); tick(); tick();
    }
    Snapshot tick(bool reset = false) {
        dut.set_reset(reset);
#define OWNER(N) \
        dut.set_io$$owner##N##$$valid(in.owners[N].valid); \
        dut.set_io$$owner##N##$$bits$$token$$index(in.owners[N].proof.token.index); \
        dut.set_io$$owner##N##$$bits$$token$$tag(in.owners[N].proof.token.tag); \
        dut.set_io$$owner##N##$$bits$$address(in.owners[N].proof.original); \
        dut.set_io$$owner##N##$$bits$$size(in.owners[N].proof.size); \
        dut.set_io$$owner##N##$$bits$$mask(in.owners[N].proof.mask)
        OWNER(0); OWNER(1); OWNER(2);
#undef OWNER
#define TOKEN(PORT, OPT) \
        dut.set_io$$##PORT##$$valid((OPT).has_value()); \
        dut.set_io$$##PORT##$$bits$$index((OPT) ? (OPT)->index : 15); \
        dut.set_io$$##PORT##$$bits$$tag((OPT) ? (OPT)->tag : UINT64_MAX)
        TOKEN(consume, in.consume); TOKEN(creditReserve, in.reserve); TOKEN(creditConsume, in.creditConsume);
        TOKEN(creditCancel, in.cancel); TOKEN(live0, in.live0); TOKEN(live1, in.live1);
#undef TOKEN
        dut.set_io$$head(in.head); dut.set_io$$clearOwners(in.clear); dut.set_io$$queryEligible(in.eligible);
        dut.set_io$$pause(in.pause); dut.set_io$$flush(in.flush); dut.set_io$$stable(in.stable);
        dut.set_io$$epoch(in.epoch); dut.set_io$$bind(in.bind);
        dut.set_io$$pmpCfg(in.pmp); dut.set_io$$pmpAddress(allPmp);
        dut.set_io$$load$$valid(in.load); dut.set_io$$load$$bits$$token$$index(14);
        dut.set_io$$load$$bits$$token$$tag(0x8000000000001401ULL);
        dut.set_io$$load$$bits$$address(va); dut.set_io$$load$$bits$$size(3);
        dut.set_io$$reply$$valid(in.hit); dut.set_io$$reply$$bits$$physicalAddress(in.replyPa);
        dut.set_io$$reply$$bits$$epoch(in.replyEpoch); dut.set_io$$reply$$bits$$pbmt(in.pbmt);
        dut.step(); ++cycles;
        Snapshot s;
#define PROOF(N) \
        if (dut.get_io$$proof##N##$$valid()) { \
            Proof p{{unsigned(dut.get_io$$proof##N##$$bits$$token$$index()), \
                     uint64_t(dut.get_io$$proof##N##$$bits$$token$$tag())}, \
                     uint32_t(dut.get_io$$proof##N##$$bits$$epoch()), \
                     uint64_t(dut.get_io$$proof##N##$$bits$$payload$$address()), \
                     uint64_t(dut.get_io$$proof##N##$$bits$$payload$$physicalAddress()), \
                     bool(dut.get_io$$proof##N##$$bits$$payload$$write()), \
                     unsigned(dut.get_io$$proof##N##$$bits$$payload$$size()), \
                     unsigned(dut.get_io$$proof##N##$$bits$$payload$$mask())}; s.proofs[N] = p; \
        }
        PROOF(0); PROOF(1);
#undef PROOF
        s.bound = dut.get_io$$bound(); s.reserved = dut.get_io$$reservedCount(); s.proved = dut.get_io$$provedCount();
        s.query = dut.get_io$$query$$valid();
        if (s.query) { s.write = dut.get_io$$query$$bits$$write(); s.queryAddress = dut.get_io$$query$$bits$$address();
            ++queries; s.write ? ++writes : ++reads; }
        s.load = dut.get_io$$loadPrepared$$valid();
        if (s.load) s.loadAllowed = dut.get_io$$loadPrepared$$bits$$allowed();
        s.available = dut.get_io$$creditAvailable(); s.creditReserved = dut.get_io$$creditReserved();
        s.active = dut.get_io$$creditActive();
        if (!s.available) s.creditOwner = {unsigned(dut.get_io$$creditOwner$$index()), uint64_t(dut.get_io$$creditOwner$$tag())};
        if (reset) { dut.resetAll(); return {}; }
        require(s.reserved + s.proved <= PENDING_STORE_SLOTS, "bank capacity exceeded");
        require(unsigned(s.available) + unsigned(s.creditReserved) + unsigned(s.active) == 1,
                "credit state is not exclusive");
        for (const auto &p : s.proofs) if (p) {
            bool found = false;
            for (const auto &o : in.owners) if (o.valid && o.proof.token == p->token) {
                Proof expected = o.proof;
                if (corruptExpectedTag) expected.token.tag ^= 1ULL << 63;
                require(*p == expected, "pending-store independent full-tuple oracle mismatch"); found = true;
            }
            require(found, "stale or cleared full-token proof escaped"); ++captures;
        }
        return s;
    }
    Snapshot wait(unsigned n = 8) { Snapshot s; while(n--) s = tick(); return s; }
    Snapshot proved(unsigned count) {
        for(unsigned n = 0; n < 64; ++n) { auto s = tick();
            unsigned valid = 0; for (const auto &p : s.proofs) valid += p.has_value();
            if (valid == count) return s; }
        throw std::runtime_error("bounded proof capture deadline");
    }
    void owner(unsigned port, unsigned index, uint64_t tag) {
        in.owners[port] = {true, {{index,tag},in.epoch,va,ram,true,3,255}};
        in.eligible |= 1u << index;
    }
};
int main(int argc,char **argv) { try {
    const std::string mode = argc > 1 ? argv[1] : "";
    { Bench b; b.owner(0,15,0xfedcba9876543210ULL); b.in.head = 14; b.in.load = true;
      auto s = b.proved(1); require(b.writes && b.reads, "shared query fairness not exercised");
      const unsigned row = s.proofs[0] ? 0 : 1; b.in.bind = 1u << row; b.tick(); b.in.bind = 0;
      // rs2-ready is deliberately not an owner-liveness event: remove eligibility,
      // keep exact owner, continue unrelated loads, and retain the bound proof.
      b.in.eligible = 0; b.wait(); s = b.tick(); require(s.bound == (1u << row), "bound proof lost after query eligibility stopped");
      b.in.load = false; b.in.pause = true; b.in.flush = true; b.tick(); b.in.flush = false;
      s = b.wait(); require(s.bound == (1u << row) && s.proofs[row], "query cancellation killed surviving bound store");
      b.in.consume = b.in.owners[0].proof.token; b.tick(); b.in.consume.reset();
      b.in.owners[0].valid = false; s = b.wait(); require(!s.bound && !s.proved, "frozen store consume failed to release exact proof");
      b.in.pause = false; b.owner(0,15,0x7edcba9876543210ULL); b.proved(1);
      if(mode == "--mutate-full-tag") { b.corruptExpectedTag = true; b.tick(); }
      b.in.clear = 1u << 15; b.in.owners[0].proof.token.tag ^= 0x0100000000000000ULL;
      b.tick(); b.in.clear = 0; b.proved(1);
      std::cout << "PENDING_BANK_CASE retain_bind_fulltag queries=" << b.queries << " checks=" << b.captures << '\n'; }
    { Bench b; b.owner(0,1,0x8000000000000001ULL); b.in.load = true; b.proved(1);
      auto s = b.wait(); require(s.load && s.loadAllowed, "load preparation erased by store grant");
      b.in.clear = 1u << 1; b.tick(); b.in.owners[0].valid = false; b.in.clear = 0;
      b.in.load = false; b.in.epoch++; b.in.replyEpoch++; b.wait();
      b.owner(0,1,0x9000000000000001ULL); b.proved(1);
      std::cout << "PENDING_BANK_CASE epoch_reuse\n"; }
    for(unsigned denied=0; denied<5; ++denied) {
      Bench b; b.owner(0,3,0x8000000000003001ULL);
      if(denied==0) b.in.hit=false;
      if(denied==1) b.in.pbmt=1;
      if(denied==2) b.in.pmp=0x19; // R only
      if(denied==3) b.in.replyEpoch--;
      if(denied==4) b.in.replyPa=0x10000000;
      auto s=b.wait(20); require(!s.proved && !s.proofs[0] && !s.proofs[1], "denied store proof certified");
      std::cout << "PENDING_BANK_CASE deny_" << denied << '\n';
    }
    { Bench b; b.owner(0,2,0x8000000000000201ULL); b.tick(); b.tick();
      // Clear is asserted while a query/capture can be in flight, then replace
      // the exact ROB index with a distinct high generation.
      b.in.clear=1u<<2; b.in.owners[0].proof.token.tag=0xc000000000000201ULL; b.tick();
      b.in.clear=0; b.proved(1); std::cout << "PENDING_BANK_CASE capture_clear_allocate\n"; }
#if PENDING_STORE_SLOTS == 2
    { Bench b; b.in.head=14; b.owner(0,15,0x8000000000001501ULL); b.owner(1,0,0xa000000000000001ULL);
      auto s=b.proved(2); b.in.bind=3; b.tick(); b.in.bind=0;
      b.owner(2,1,0xe000000000000101ULL); s=b.wait(20);
      require(s.bound==3 && s.proved==2, "two bound rows overallocated or evicted");
      b.in.consume=b.in.owners[0].proof.token; b.tick(); b.in.consume.reset(); b.in.owners[0].valid=false;
      b.proved(2); std::cout << "PENDING_BANK_CASE two_slots_third_blocked\n"; }
#endif
    { Bench b; const Token a{3,0x8000000000000101ULL}, stale{3,0x0000000000000101ULL};
      b.in.reserve=a; b.tick(); b.in.reserve.reset(); auto s=b.wait();
      require(!s.available && s.creditReserved && s.creditOwner==a, "unconsumed reservation returned without cancel");
      if(mode=="--assert-double-reserve") { b.in.reserve=stale; b.tick(); return 3; }
      b.in.creditConsume=a; b.in.live0=a; b.tick(); b.in.creditConsume.reset();
      s=b.wait(); require(s.active && s.creditOwner==a, "consumed owner was not retained");
      b.in.live1=stale; b.in.live0.reset(); b.tick(); s=b.tick();
      require(s.available, "full-token credit did not return after original drain");
      b.in.reserve=stale; b.tick(); b.in.reserve.reset(); s=b.tick();
      require(s.creditReserved && s.creditOwner==stale, "reused ROB index did not receive distinct credit");
      b.in.cancel=stale; b.tick(); b.in.cancel.reset(); s=b.tick(); require(s.available,"reservation cancel lost credit");
      b.in.reserve=a; b.in.creditConsume=a; b.in.live0=a; b.tick(); b.in.reserve.reset(); b.in.creditConsume.reset();
      s=b.tick(); require(s.active,"same-edge reserve/consume failed");
      b.in.live0.reset(); b.in.live1.reset(); b.wait();
      std::cout << "PENDING_BANK_CASE credit_reserve_consume_drain_fulltag\n"; }
    std::cout << "PENDING_BANK_PASS slots=" << PENDING_STORE_SLOTS << '\n'; return 0;
} catch(const std::exception &e) { std::cerr << "PENDING_BANK_FAIL " << e.what() << '\n'; return 1; } }
