// Independent interface state: context blockNew need not imply posted busy.
#define main retained_ready_main
#include "observed_backend.cpp"
#undef main
int main()try{
 Bench b;b.expectedQuery=true;b.configure();b.warm();b.readySpareWorkload();
 const auto requests=b.physicalCount;
 b.dut.set_io$$control$$blockNew(true);
 for(unsigned n=0;n<8;++n)b.tick();
 b.check(b.physicalCount==requests && b.earlyStarts==0 && b.expectedCredits.empty() &&
   !b.entries.at(*b.youngLoad).started,"blockNew with no posted work admitted memory, credit or binding");
 b.dut.set_io$$control$$blockNew(false);b.drain();
 b.check(b.entries.at(*b.oldStore).retired && b.entries.at(*b.youngLoad).retired,
   "blockNew release failed independent architectural progress");
 std::cout<<"C1_INDEPENDENT_BLOCK_NEW_PASS postedBusy=0\n";return 0;
}catch(const std::exception&e){std::cerr<<"C1_INDEPENDENT_BLOCK_NEW_FAIL "<<e.what()<<'\n';return 1;}
