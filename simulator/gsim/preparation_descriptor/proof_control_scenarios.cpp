// Independent decoded instruction/memory oracle plus explicit external-control scenarios.
#define main retained_ready_main
#include "observed_backend.cpp"
#undef main
int main() try {
    for(unsigned kind=0;kind<3;++kind) {
        Bench b; b.expectedQuery=true;b.configure();b.warm();
        if(kind==1)b.constant(31,satp);
        const auto before=b.physicalCount; const auto beforeRedirects=b.c1SystemRedirects; const Bytes beforeMemory=b.expected;
        b.dut.set_io$$control$$prefetchBusy(kind==0);
        b.dut.set_io$$control$$holdFetch(kind==1);
        b.commitEnable=kind!=2;
        const uint32_t system=kind==1?(0x180u<<20|31u<<15|1u<<12|0x73):(0x340u<<20|1u<<12|0x73);
        const auto tokens=b.submit({system,divu(30,25,26),st(10,30),ld(20,11)});
        b.oldStore=tokens[2];b.youngLoad=tokens[3];
        for(unsigned n=0;n<80;++n)b.tick();
        b.check(b.c1SystemWait>=60 && b.physicalCount==before && b.earlyStarts==0,
            "head-system waiting admitted memory or failed independent wait witness");
        b.dut.set_io$$control$$prefetchBusy(false);b.dut.set_io$$control$$holdFetch(false);b.commitEnable=true;
        if(kind==1) {
            for(unsigned n=0;n<400&&b.c1SystemRedirects==beforeRedirects;++n)b.tick();
            b.check(b.c1SystemRedirects==beforeRedirects+1 && b.entries.at(tokens[2]).killed &&
                b.entries.at(tokens[3]).killed, "SATP sequential redirect failed exact younger cancellation");
            b.expected=beforeMemory; b.drain();
            const auto replay=b.submit({divu(30,25,26),st(10,30),ld(20,11)});
            b.oldStore=replay[1];b.youngLoad=replay[2];
        }
        b.drain();
        std::cout << "C1_SYSTEM_WAIT_PASS kind=" << kind << '\n';
    }
    { Bench b;b.expectedQuery=true;b.configure();b.warm();
      b.csr(0x304,1ULL<<7);b.csr(0x300,(1ULL<<17)|(1ULL<<11)|(1ULL<<3));
      const Bytes before=b.expected;b.latency=180;b.dualWorkload();
      for(unsigned n=0;n<180&&b.earlyStarts<2;++n)b.tick();
      b.check(b.earlyStarts==2 && !b.entries.at(*b.oldStore).started,"IRQ setup lacked two accepted early loads and pending stores");
      b.expectedTimerIrq=true;b.dut.set_io$$control$$timerInterrupt(true);
      for(unsigned n=0;n<600&&!b.traps;++n)b.tick();
      b.check(b.traps==1 && b.c1Irq && b.expectedCredits.empty(),"IRQ did not wait for actual accepted memory drain");
      b.dut.set_io$$control$$timerInterrupt(false);b.expected=before;b.drain();
      b.check(!b.entries.at(*b.oldStore).started && !b.entries.at(*b.youngLoad).retired,
          "IRQ allowed pending STORE or younger architectural retirement");
      std::cout << "C1_TIMER_IRQ_DRAIN_PASS\n";
    }
    std::cout << "C1_CONTROL_SCENARIOS_PASS\n";return 0;
} catch(const std::exception&e) {std::cerr<<"C1_CONTROL_SCENARIOS_FAIL "<<e.what()<<'\n';return 1;}
