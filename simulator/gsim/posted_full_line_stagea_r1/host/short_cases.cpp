#include "PostedShortPoliciesGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
struct Oracle {
  int limit; bool live=false, accepted=false, decided=false, kind=false;
  uint64_t allocated=0, generation=0, frozenAge=0;
};
static void need(bool v, const char* s) { if(!v) throw std::runtime_error(s); }
int main() { try {
  SPostedShortPoliciesGsim d;
  uint64_t cycle=0, checks=0, timeouts=0, fulls=0, seals=0;
  Oracle a{3},b{4};
  auto tick=[&](bool reset, bool allocate, bool allocateSealed, uint64_t gen, bool full,
                bool seal, bool ready, bool release) {
    d.set_reset(reset);d.set_io$$allocate(allocate);d.set_io$$allocateSealed(allocateSealed);
    d.set_io$$generation(gen);d.set_io$$full(full);d.set_io$$seal(seal);
    d.set_io$$ready(ready);d.set_io$$release(release);d.step();
    if(reset) { a=Oracle{3};b=Oracle{4};++cycle;return; }
    auto check=[&](Oracle& o,bool valid,bool kind,uint64_t age,bool open,bool accepted,uint64_t generation) {
      const auto expectedAge=o.decided ? o.frozenAge : (o.live ? cycle-o.allocated-1 : 0);
      const bool expired=o.live && expectedAge>=uint64_t(o.limit-1);
      need(valid==(o.live&&o.decided&&!o.accepted),"SHORT_VALID");
      need(accepted==(o.live&&o.accepted),"SHORT_ACCEPTED");
      need(open==(o.live&&!o.decided&&!full&&!seal&&!expired),"SHORT_JOIN");
      if(o.live) {
        need(age==expectedAge,"SHORT_MONOTONIC_AGE");
        need(generation==o.generation,"SHORT_OWNER");
        if(o.decided) need(kind==o.kind,"SHORT_FROZEN_KIND");
      }
      ++checks;
      const bool wasDecided=o.decided;
      if(o.live&&!o.decided&&(full||seal||expired)) {
        o.decided=true;o.kind=full;o.frozenAge=expectedAge;
        if(full) ++fulls;else if(seal) ++seals;else ++timeouts;
      }
      if(valid&&ready) o.accepted=true;
      if(release) { need(o.live&&o.accepted,"SHORT_RELEASE_PREMISE");o.live=false; }
      if(allocate) {
        need(!o.live&&!release,"SHORT_ALLOC_PREMISE");
        o.live=true;o.allocated=cycle;o.generation=gen;o.decided=allocateSealed;
        o.accepted=false;o.kind=false;o.frozenAge=0;
        if(allocateSealed) ++seals;
      }
      (void)wasDecided;
    };
    check(a,d.get_io$$valid3(),d.get_io$$kind3(),d.get_io$$age3(),d.get_io$$open3(),d.get_io$$accepted3(),d.get_io$$generation3());
    check(b,d.get_io$$valid4(),d.get_io$$kind4(),d.get_io$$age4(),d.get_io$$open4(),d.get_io$$accepted4(),d.get_io$$generation4());
    ++cycle;
  };
  tick(true,0,0,0,0,0,0,0);tick(true,0,0,0,0,0,0,0);
  for(unsigned scenario=0;scenario<48;++scenario) {
    // Reuse both slots without reset; deliberately change external identity while held.
    tick(false,1,scenario%6==3,scenario+1,0,0,0,0);
    for(unsigned n=0;n<12;++n) {
      bool full=(scenario%6==1 && n==1) || (scenario%6==4 && n==1) || (scenario%6==5 && n==2);
      bool seal=((scenario%6==2 || scenario%6==4) && n==1) || n==6;
      tick(false,0,0,255,full,seal,n>=8,0);
    }
    tick(false,0,0,255,0,0,0,1);
  }
  // Coordinated reset discards both endpoint ledgers, distinct from recovery seal.
  tick(false,1,0,99,0,0,0,0);tick(false,0,0,0,0,0,0,0);
  tick(true,0,0,0,0,0,0,0);tick(false,0,0,0,0,0,0,0);
  need(timeouts>=16 && fulls==48 && seals>=32,"SHORT_NONVACUITY");
  std::cout<<"SHORT_POLICY_PASS checks="<<checks<<" timeouts="<<timeouts<<" full="<<fulls<<" seals="<<seals<<"\n";
  return 0;
 } catch(const std::exception& e) {std::cerr<<e.what()<<"\n";return 1;}}
