#define main retained_ready_main
#include "observed_backend.cpp"
#undef main
int main()try{
 for(unsigned irq=0;irq<2;++irq){
  Bench b;b.expectedQuery=true;b.configure();b.warm();b.constant(25,(va+4096)*7);b.constant(26,7);
  if(irq){b.csr(0x304,1ULL<<7);b.csr(0x300,(1ULL<<17)|(1ULL<<11)|(1ULL<<3));}
  auto owners=b.submit(irq?std::vector<uint32_t>{divu(29,25,26),ld(20,29)}:
   std::vector<uint32_t>{divu(30,25,26),divu(29,25,26),beq(30),ld(20,29)});
  auto load=owners.back();auto producer=owners[irq?0:1];bool waiting=false;
  for(unsigned n=0;n<30&&!waiting;n++){
   waiting=b.dut.get_io$$descriptorValid()&&b.dut.get_io$$descriptorToken$$index()==load.index&&
    b.dut.get_io$$descriptorToken$$tag()==load.tag&&!b.entries.at(producer).completed;
   if(!waiting)b.tick();
  }
  b.check(waiting,"cancel fixture did not reserve unready Q");
  if(irq){
   const auto clearsBefore=b.observedClear;
   b.expectedTimerIrq=true;b.dut.set_io$$control$$timerInterrupt(true);
   for(unsigned n=0;n<600&&!b.traps;++n)b.tick();
   b.check(b.traps==1&&b.observedClear>clearsBefore&&b.c1Irq>0,"waiting IRQ clear absent");
   b.dut.set_io$$control$$timerInterrupt(false);
  }else{
   for(unsigned n=0;n<600&&!b.entries.at(load).killed;++n)b.tick();
   b.check(b.entries.at(load).killed&&b.observedKill>0,"waiting exact-token redirect clear absent");
  }
  b.drain();b.check(!b.entries.at(load).started&&!b.entries.at(load).retired,"cancelled waiting load affected memory/retirement");
  std::cout<<"EARLY_WAITING_CANCEL_PASS irq="<<irq<<"\n";
 }
}catch(const std::exception&e){std::cerr<<"EARLY_WAITING_CANCEL_FAIL "<<e.what()<<'\n';return 1;}
