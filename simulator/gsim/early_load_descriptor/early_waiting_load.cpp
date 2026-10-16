#define main retained_ready_main
#include "observed_backend.cpp"
#undef main
int main()try{
 Bench b;b.expectedQuery=true;b.configure();b.warm();
 // A real renamed DIVU producer supplies a valid virtual address after a long wait.
 b.constant(25,(va+4096)*7);b.constant(26,7);
 const auto owners=b.submit({divu(29,25,26),ld(20,29)});
 unsigned waiting=0,startedBeforeProducer=0;uint64_t firstQ=0,producerComplete=0,firstS=0;
 for(unsigned n=0;n<600&&!b.entries.at(owners[1]).retired;n++){
  const auto &producer=b.entries.at(owners[0]);const auto &load=b.entries.at(owners[1]);
  bool q=b.dut.get_io$$descriptorValid()&&b.dut.get_io$$descriptorToken$$index()==owners[1].index&&b.dut.get_io$$descriptorToken$$tag()==owners[1].tag;
  bool s=b.dut.get_io$$poolStageValid()&&b.dut.get_io$$poolStageToken$$index()==owners[1].index&&b.dut.get_io$$poolStageToken$$tag()==owners[1].tag;
  if(q&&!firstQ)firstQ=b.cycle;
  if(q&&!producer.completed){waiting++;b.check(!s&&!load.started,"waiting load captured operands before accepted producer completion");}
  if(producer.completed&&!producerComplete)producerComplete=producer.complete;
  if(s&&!firstS)firstS=b.cycle;
  if(load.started&&!producer.completed)startedBeforeProducer++;
  b.tick();
 }
 b.drain();
 b.check(waiting>=4&&firstQ&&producerComplete&&firstS&&firstQ<producerComplete,"no real early-Q dependency overlap");
 b.check(firstS>=producerComplete&&!startedBeforeProducer,"pre-ready S/LSU ownership");
 b.check(b.entries.at(owners[1]).retired&&b.entries.at(owners[1]).address==va+4096,"waiting dependency result/address mismatch");
 std::cout<<"EARLY_WAITING_LOAD_PASS waiting_cycles="<<waiting<<" first_q="<<firstQ<<" producer_complete="<<producerComplete<<" first_s="<<firstS<<"\n";
}catch(const std::exception&e){std::cerr<<"EARLY_WAITING_LOAD_FAIL "<<e.what()<<'\n';return 1;}
