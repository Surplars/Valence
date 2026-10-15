// Reuse the independent exact-profile interpreter, memory and lifecycle oracle.
// No DUT predicate is reused to decide architectural correctness.
#define main retained_ready_query_main
#include "ready_store_query77_backend.cpp"
#undef main

static void metrics(const char *name, const Bench &b) {
    std::cout << "C0_LIFECYCLE_METRICS " << name << " cycles=" << b.cycle
              << " retired=" << b.retired << " accepted=" << b.accepted
              << " physical=" << b.physicalCount << " responses=" << b.responseCount
              << " early=" << b.earlyStarts << " credit_returns=" << b.creditReturns << '\n';
}
int main(int argc, char **argv) try {
    const std::string mode = argc > 1 ? argv[1] : "";
    { Bench b; b.expectedQuery=true; b.configure(); b.warm(); b.latency=140;
      b.physicalHold=b.cycle+32; b.dualWorkload();
      for(unsigned n=0;n<160&&b.earlyStarts<2;++n)b.tick();
      require(b.earlyStarts==2,"bounded wait failed two legal early starts");
      const auto epoch=b.dut.get_io$$epoch();
      b.tables.pages[0].physical=ram+4096;
      b.drain(); b.dualWitness();
      require(b.dut.get_io$$epoch()==epoch,"same-epoch edit changed authorization epoch");
      metrics("two_bound_store_capture_frozen_pte_two_credits",b); }
    { Bench b; b.expectedQuery=true; b.configure(); b.warm(); b.latency=140; b.faultStore=true;
      b.dualWorkload(); b.drain(); b.dualWitness(true);
      require(b.traps==1&&!b.entries.at(*b.oldStore).retired&&!b.entries.at(*b.secondStore).retired&&
          !b.entries.at(*b.youngLoad).retired&&!b.entries.at(*b.secondLoad).retired,
          "oldest-store late fault allowed younger architectural effect");
      metrics("oldest_store_late_fault_precise",b); }
    for(unsigned kind=1;kind<=2;++kind) {
      Bench b; b.expectedQuery=true; b.configure(); b.warm(); b.latency=180; const Bytes before=b.expected;
      b.injectRetire=mode=="--mutate-retirement"; b.dualWorkload(kind,false);
      for(unsigned n=0;n<200&&!b.entries.at(*b.youngLoad).killed;++n)b.tick();
      require(b.entries.at(*b.youngLoad).killed&&b.entries.at(*b.secondLoad).killed&&
          !b.entries.at(*b.youngLoad).response&&!b.entries.at(*b.secondLoad).response&&b.recoveryWithLiveRead,
          "decoded redirect did not kill two accepted undrained reads");
      require(b.creditReturns==0,"accepted killed owner returned credit before true response drain");
      if(kind==2)b.expected=before;
      b.drain(); b.dualWitness(false,kind==2);
      require(!b.entries.at(*b.youngLoad).retired&&!b.entries.at(*b.secondLoad).retired,"killed early result retired");
      metrics(kind==1?"selective_kill_bound_store_survives":"full_kill_credit_response_drain",b);
    }
    std::cout << "C0_LIFECYCLE_PASS rows=3 credits=2 lsu=4\n";
    return 0;
} catch(const std::exception &e) { std::cerr << "C0_LIFECYCLE_FAIL " << e.what() << '\n'; return 1; }
