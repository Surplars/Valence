#define main retained_ready_main
#include "observed_backend.cpp"
#undef main
int main()try{
 for(unsigned irq=0;irq<2;irq++){
 Bench b;b.expectedQuery=true;b.configure();b.warm();
 if(irq){b.csr(0x304,1ULL<<7);b.csr(0x300,(1ULL<<17)|(1ULL<<11)|(1ULL<<3));}
 const Bytes before=b.expected;b.latency=180;
 auto t=b.submit({divu(30,25,26),irq?0x13u:beq(30),st(10,30),st(10,30,8),ld(20,11),ld(21,11,16),ld(22,11,32),ld(23,11,48)});
 b.oldStore=t[2];b.secondStore=t[3];b.youngLoad=t[4];b.secondLoad=t[5];b.thirdLoad=t[6];
 for(unsigned n=0;n<150&&!(b.earlyStarts==2&&b.dut.get_io$$descriptorValid());++n)b.tick();
 b.check(b.earlyStarts==2&&b.dut.get_io$$descriptorValid(),"actual allocator live Q plus two credits absent");
 if(irq){b.expectedTimerIrq=true;b.dut.set_io$$control$$timerInterrupt(true);for(unsigned n=0;n<650&&!b.traps;++n)b.tick();b.check(b.traps==1&&b.observedContext>0,"live Q context cancel absent");b.dut.set_io$$control$$timerInterrupt(false);}
 else {for(unsigned n=0;n<200&&!b.entries.at(*b.youngLoad).killed;++n)b.tick();b.check(b.entries.at(*b.youngLoad).killed&&b.observedKill>0,"live Q exact-owner kill absent");}
 b.expected=before;b.drain();b.check(!b.entries.at(*b.oldStore).started&&!b.entries.at(*b.youngLoad).retired,"cancelled owner had architectural effect");
 std::cout<<"QLIVE_CANCEL_PASS irq="<<irq<<"\n";
 }
}catch(const std::exception&e){std::cerr<<"QLIVE_CANCEL_FAIL "<<e.what()<<'\n';return 1;}
