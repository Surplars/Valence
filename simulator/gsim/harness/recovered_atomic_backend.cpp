// Original lifecycle source is copied verbatim except for renaming its main entry point.
#include "retained_lifecycle.cpp"

static void transportMetrics(const char *name, Bench &b) {
    require(b.dut.get_audit$$accepted()==b.dut.get_audit$$drained(), "atomic transport failed to drain");
    std::cout << "RECOVERED_TRANSPORT " << name
              << " accepted=" << b.dut.get_audit$$accepted()
              << " drained=" << b.dut.get_audit$$drained()
              << " stalled=" << b.dut.get_audit$$stalled()
              << " cancel_queued=" << b.dut.get_audit$$cancelledQueued()
              << " cancel_resident=" << b.dut.get_audit$$cancelledResident()
              << " canonical=" << b.dut.get_audit$$canonical()
              << " frozen=" << b.dut.get_audit$$frozen()
              << " posted=" << b.dut.get_audit$$posted() << '\n';
}
int main(int argc, char **argv) try {
    const int original = retained_lifecycle_main(argc, argv);
    if (original) return original;
    { Bench b; b.expectedQuery=true; b.configure(); b.warm(); b.latency=180;
      b.physicalHold=b.cycle+80; b.responseHold=b.cycle+240;
      b.dualWorkload(); b.drain(); b.dualWitness();
      require(b.dut.get_audit$$canonical() && b.dut.get_audit$$frozen(),
          "canonical/frozen real FIFO coverage absent");
      transportMetrics("held_physical_response",b); }
    { Bench b; b.expectedQuery=true; b.configure(); b.warm(); b.latency=180;
      const Bytes before=b.expected;
      b.physicalHold=b.cycle+80; b.responseHold=b.cycle+240;
      b.dualWorkload(2,false); b.expected=before;
      b.drain(); b.dualWitness(false,true);
      require(b.recoveryWithLiveRead && b.creditReturns==b.earlyStarts,
          "cancelled resident owners did not drain physical response credits");
      require(b.dut.get_audit$$cancelledResident(), "resident cancellation coverage absent");
      transportMetrics("full_kill_held_response",b); }
    std::cout << "RECOVERED_BACKEND_PASS posted_cache=NOT_EXERCISED\n";
    return 0;
} catch(const std::exception &e) { std::cerr << "RECOVERED_BACKEND_FAIL " << e.what() << '\n'; return 1; }
