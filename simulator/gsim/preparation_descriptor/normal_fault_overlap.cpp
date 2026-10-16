// Reuse the independent exact-profile interpreter, memory and lifecycle oracle.
// No DUT predicate is reused to decide architectural correctness.
#define main retained_ready_query_main
#include "observed_backend.cpp"
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
    std::cout << "C0_LIFECYCLE_PASS rows=3 credits=2 lsu=4\n";
    return 0;
} catch(const std::exception &e) { std::cerr << "C0_LIFECYCLE_FAIL " << e.what() << '\n'; return 1; }
