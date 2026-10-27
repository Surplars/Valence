// Independent scalar contract: 256 counters, halfword index, reset 01,
// pre-edge read and ordered lane0 then lane1 saturating updates. No DUT internals.
#ifndef BHT256_HOST_ONLY
#include "BranchPredictor256Gsim.h"
#endif
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>

struct Update { bool valid=false; uint64_t pc=0; bool taken=false; };
using Updates=std::array<Update,2>;
using Queries=std::array<uint64_t,2>;
struct Scalar {
    std::array<unsigned,256> counter{};
    std::string mutation;
    explicit Scalar(std::string m="") : mutation(m) { reset(); }
    unsigned index(uint64_t pc) const { return (pc / (mutation=="wrong-index" ? 4 : 2)) % 256; }
    void reset() { counter.fill(mutation=="wrong-reset" ? 0 : 1); }
    static unsigned advance(unsigned c, bool taken) {
        // Fixed state transition table independent of hardware arithmetic/mux fold.
        static constexpr unsigned transition[4][2]={{0,1},{0,2},{1,3},{2,3}};
        return transition[c][taken];
    }
    bool predict(uint64_t pc) const { return counter[index(pc)]>=2; }
    void edge(const Updates &u) {
        for(unsigned n=0;n<2;++n) {
            unsigned lane=mutation=="wrong-order" ? 1-n : n;
            if(u[lane].valid) {
                auto &c=counter[index(u[lane].pc)]; c=advance(c,u[lane].taken);
            }
        }
    }
};

int main(int argc,char **argv) { try {
    const std::string mode=argc>1 ? argv[1] : "";
    if(!mode.empty() && mode!="wrong-index" && mode!="wrong-order" &&
       mode!="wrong-reset" && mode!="write-through") throw std::runtime_error("unknown negative mode");
    // Independent fixed truth cases: columns TT, TF, FT, FF. In particular,
    // saturation makes old3/TF ->2, while an incorrect aggregate net sum gives3.
    static constexpr unsigned truth[4][4]={{2,0,1,0},{3,1,1,0},{3,2,2,0},{3,2,3,1}};
    for(unsigned old=0;old<4;++old) for(unsigned pair=0;pair<4;++pair) {
        Scalar test; test.counter[0]=old;
        test.edge({{{true,0,pair<2},{true,512,(pair%2)==0}}});
        if(test.counter[0]!=truth[old][pair]) throw std::runtime_error("scalar fixed truth mismatch");
    }
    Scalar oracle, mutant(mode);
#ifndef BHT256_HOST_ONLY
    SBranchPredictor256Gsim dut;
#endif
    unsigned observations=0, edges=0, resets=0, same=0, different=0, invalid=0;
    auto drive=[&](Queries q,Updates u,bool reset) {
#ifndef BHT256_HOST_ONLY
        dut.set_reset(reset);
        dut.set_io$$pc0(q[0]); dut.set_io$$pc1(q[1]);
        dut.set_io$$train0$$valid(u[0].valid); dut.set_io$$train1$$valid(u[1].valid);
        dut.set_io$$train0$$bits$$pc(u[0].pc); dut.set_io$$train1$$bits$$pc(u[1].pc);
        dut.set_io$$train0$$bits$$taken(u[0].taken); dut.set_io$$train1$$bits$$taken(u[1].taken);
        dut.step(); // GSIM getters expose this step's combinational pre-edge outputs.
#else
        (void)q; (void)u; (void)reset;
#endif
    };
    auto reset=[&]() {
        // Reset is checked on a following non-reset observation, not unspecified
        // pre-edge power-on values. Assert two edges as in existing GSIM harnesses.
        drive({0,2},{},true); drive({0,2},{},true);
        oracle.reset(); mutant.reset(); ++resets;
    };
    auto cycle=[&](Queries q,Updates u) {
        drive(q,u,false);
        Scalar visible=mutant;
        if(mode=="write-through") visible.edge(u);
        for(unsigned lane=0;lane<2;++lane) {
            const bool expected=oracle.predict(q[lane]);
#ifdef BHT256_HOST_ONLY
            bool actual=visible.predict(q[lane]);
#else
            bool actual=lane ? bool(dut.get_io$$taken1()) : bool(dut.get_io$$taken0());
            // Negative observation guard substitutes a separately maintained
            // wrong-policy observation; it never changes DUT inputs or oracle.
            if(!mode.empty()) actual=visible.predict(q[lane]);
#endif
            if(actual!=expected) throw std::runtime_error("BHT256 observation mismatch mode="+mode+
                " edge="+std::to_string(edges)+" lane="+std::to_string(lane));
            ++observations;
        }
        if(u[0].valid && u[1].valid) {
            if(oracle.index(u[0].pc)==oracle.index(u[1].pc)) ++same; else ++different;
        }
        if(!u[0].valid || !u[1].valid) ++invalid;
        oracle.edge(u); mutant.edge(u); ++edges;
    };
    auto check=[&](Queries q,Updates u) { cycle(q,u); cycle(q,{}); }; // post-edge read via idle edge
    reset();
    // Full table reset observation, including halfword bit and high-PC aliases.
    for(unsigned i=0;i<256;i+=2) check({2ULL*i,0xfffffffffffffe00ULL+2*(i+1)},{});
    // Reset 00 is indistinguishable at first read but fails after one taken edge.
    check({0,2},{{{true,0,true},{false,2,true}}});
    // Bit1 must distinguish adjacent halfwords; +512 and high bits must alias.
    check({2,512},{});
    check({0xfffffffffffffe00ULL,0},{{{true,512,true},{false,0,false}}});
    // At old3, T then F is 2 (not naive net-sum3); next F exposes 2 vs3.
    check({0,512},{{{true,0,true},{true,512,false}}});
    check({0,512},{{{true,0,false},{false,512,true}}});
    // Exhaust all 4 old states x 4 ordered outcomes; follow-up decrement
    // discriminates internal states 2 and3 using public one-bit predictions.
    for(unsigned old=0;old<4;++old) for(unsigned pair=0;pair<4;++pair) {
        reset();
        check({6,518},{{{true,6,false},{true,518,false}}}); // force0
        for(unsigned n=0;n<old;++n) check({6,518},{{{true,6,true},{false,0,false}}});
        check({6,518},{{{true,6,bool(pair&2)},{true,518,bool(pair&1)}}});
        check({6,518},{{{true,6,false},{false,0,false}}});
    }
    // All indices, distinct dual writes, invalid updates, and large address aliases.
    for(unsigned i=0;i<256;++i) {
        uint64_t p=0xfedcba9876540000ULL+2*i, other=p^2;
        check({p,other},{{{true,p,true},{true,other,false}}});
        check({p,other},{{{false,p,false},{false,other,true}}});
        check({p+512,other+1024},{});
    }
    reset(); // midstream clears every trained entry; scan all256 again.
    for(unsigned i=0;i<256;i+=2) check({2ULL*i,2ULL*(i+1)},{});
    std::mt19937_64 rng(0x256b17);
    for(unsigned n=0;n<4096;++n) {
        uint64_t a=rng()&~1ULL,b=n%2 ? a+512 : rng()&~1ULL;
        Updates u{{{bool(rng()%4),a,bool(rng()&1)},{bool(rng()%4),b,bool(rng()&1)}}};
        Queries q=n%3 ? Queries{a,b} : Queries{rng()&~1ULL,rng()&~1ULL};
        check(q,u);
    }
    if(!same || !different || !invalid || resets!=18) throw std::runtime_error("BHT256 coverage missing");
    if(!mode.empty()) throw std::runtime_error("NEGATIVE_GUARD_NOT_DETECTED");
#ifdef BHT256_HOST_ONLY
    std::cout<<"BHT256_HOST_MODEL_PASS";
#else
    std::cout<<"BHT256_GSIM_PASS";
#endif
    std::cout<<" observations="<<observations<<" edges="<<edges<<" resets="<<resets
        <<" sameIndexDual="<<same<<" differentIndexDual="<<different<<" invalidLane="<<invalid<<'\n';
    return 0;
} catch(const std::exception &e) { std::cerr<<e.what()<<'\n'; return 1; } }
