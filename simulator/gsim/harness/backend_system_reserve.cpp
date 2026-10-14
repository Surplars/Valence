#define main retained_board_boot_main
#include "board_boot.cpp"
#undef main
#include "tagged_board_probe.h"
#include "backend_system_reserve_symbols.h"
#include "backend_system_reserve_bindings.h"
#include <map>
#define B(x) d.board$platform$core$core$core$backend$##x
struct Observer {
 Test* test=nullptr; tagged_board::Probe tagged; std::string mutation;
 uint64_t witness=0,firstCycle=0,cycles=0,reserves=0,intrinsics=0,proofMatch=0,loadCommits=0,traps=0;
 bool applied=false; unsigned witnessIndex=0; uint64_t witnessTag=0;
 std::map<uint64_t,uint64_t> expected; std::map<unsigned,std::pair<uint64_t,bool>> owed;
 static void observe(SBoardSocGsim& d,void* p){static_cast<Observer*>(p)->sample(d);}
 void sample(SBoardSocGsim& d){
  const uint64_t cycle=test->cycles; ++cycles;
  tagged.sample(d,cycle);
  const auto raw=d.get_dataPathEvents();
  if(raw&(1ULL<<19)) {
   const auto address=d.get_dataPathRequest9Address(),meta=d.get_dataPathRequest9Meta();
   check(expected.contains(address),"ORACLE_PHYSICAL_ADDRESS");
   check(!(meta&2)&&!(address&7)&&((meta>>7)&3)==3&&((meta>>9)&255)==255,"ORACLE_PHYSICAL_SHAPE");
   if(meta&1)check(d.get_dataPathRequest9Data()==expected.at(address),"ORACLE_STORE_DATA");
   check(owed.emplace(tagged.requestHandle,std::make_pair(expected.at(address),bool(meta&1))).second,"ORACLE_DUPLICATE_HANDLE");
  }
  if(raw&(1ULL<<21)) {
   check(owed.contains(tagged.replyHandle),"ORACLE_REPLY_OWNER");
   check(d.get_dataPathReply0Flags()==0,"ORACLE_REPLY_FAULT");
   if(!owed.at(tagged.replyHandle).second)check(d.get_dataPathReply0Data()==owed.at(tagged.replyHandle).first,"ORACLE_READ_DATA");
   owed.erase(tagged.replyHandle);
  }
  const bool reserve=reserve_probe::system(d), intrinsic=B(pendingStoreProof$loadPreparedIntrinsicValid);
  reserves+=reserve;intrinsics+=intrinsic;proofMatch+=intrinsic&&B(preparedLoadPayloadMatches);
  if(reserve|| (intrinsic&&B(preparedLoadPayloadMatches))) {
   std::cout<<"TRACE cycle="<<cycle<<" head=0x"<<std::hex<<d.get_io$$headProfile$$pc()<<" candidatePc=0x"<<d.get_io$$headProfile$$candidateLoadPc()<<std::dec<<" reserve="<<reserve<<" intrinsic="<<intrinsic<<" match="<<unsigned(B(preparedLoadPayloadMatches))<<" candidate="<<unsigned(B(candidatePrecheckedLoad))<<" strict="<<unsigned(B(precheckedLoad))<<" start="<<unsigned(reserve_probe::start(d))<<" olderSystem="<<unsigned(B(olderSystem))<<" flush="<<unsigned(reserve_probe::flush(d))<<" context="<<unsigned(B(contextMemoryEpoch))<<"\n";
  }
  const bool hit=reserve&&intrinsic&&B(candidatePrecheckedLoad)&&B(preparedLoadPayloadMatches)&&d.get_io$$headProfile$$pc()==RESERVE_CSR&&d.get_io$$headProfile$$candidateLoadPc()==YOUNGER_LOAD;
  if(hit){
   ++witness;if(!firstCycle)firstCycle=cycle;
   check(!B(ledger$recovering)&&!B(contextMemoryEpoch)&&!reserve_probe::interrupt(d),"ORACLE_ISOLATED_SYSTEM_FLUSH");
   for(unsigned row=0;row<2;++row)check(!B(pendingStoreProof$bound$NEXT)[row]||B(pendingStoreProof$bound)[row],"ORACLE_NO_FLUSH_BIND");
   const auto i=B(pendingStoreProof$load$$token$$index); const auto tag=B(pendingStoreProof$load$$token$$tag);
   witnessIndex=i;witnessTag=tag;
   check(i<16&&B(pending)[i]&&B(queue$$renamed$$token$$index)[i]==i&&B(queue$$renamed$$token$$tag)[i]==tag,"ORACLE_RETAINED_FULL_TOKEN");
   check(B(pendingStoreProof$load$$address)==0x40000008ULL&&B(pendingStoreProof$load$$physicalAddress)==0x80400008ULL&&B(pendingStoreProof$load$$allowed)&&B(pendingStoreProof$load$$size)==3,"ORACLE_RETAINED_CERTIFICATE");
   bool start=reserve_probe::start(d), strict=B(precheckedLoad);
   // Mutate only the host observation, never any DUT input/state.
   if(mutation=="--leaked-permit"){std::cerr<<"NEGATIVE_REACHED leaked_final_permit cycle="<<cycle<<"\n";start=true;applied=true;}
   if(mutation=="--stale-strict"){std::cerr<<"NEGATIVE_REACHED strict_flush_omitted cycle="<<cycle<<"\n";strict=true;applied=true;}
   check(!start&&!B(originalMemoryEligible)&&!reserve_probe::memory_reserve(d),"ORACLE_FINAL_FLUSH_PERMISSION");
   check(!strict&&reserve_probe::flush(d),"ORACLE_STRICT_FLUSH_PUBLICATION");
   check(!reserve_probe::credit_reserve(d)&&!reserve_probe::credit_consume(d),"ORACLE_FLUSH_CREDIT");
   check(!B(pendingStoreProof$loadValid$NEXT),"ORACLE_FLUSH_CLEARS_RETAINED_CERTIFICATE");
   std::cout<<"ACTUAL_RESERVE_RETAINED_CERTIFICATE cycle="<<cycle<<" index="<<unsigned(i)<<" tag="<<tag<<" actual_start=0 strict=0 credit=0 other_F=0 bind_rise=0\n";
  }
  for(unsigned lane=0;lane<2;++lane) if(lane?d.get_io$$commit1():d.get_io$$commit0()){
   const auto pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();if(pc==YOUNGER_LOAD)++loadCommits;
  }
  if(d.get_io$$trap$$valid()) {check(d.get_io$$trap$$bits$$cause()==9&&d.get_io$$trap$$bits$$pc()==TERMINAL_ECALL,"ORACLE_PRECISE_TERMINAL_TRAP");++traps;}
 }
};
int main(int argc,char** argv){Observer o;try{
 check(argc==2||argc==3,"guest.bin [--leaked-permit|--stale-strict]");if(argc==3)o.mutation=argv[2];
 auto image=readFile(argv[1]);Bytes rom;word(rom,0x00200297);word(rom,0x00028067);Test t(rom);t.running=false;o.test=&t;o.tagged.mode=1;o.tagged.bytes=4096;
 auto seed=[&](uint64_t pa,uint64_t value){t.ddr.memory[uint32_t(pa-ramBase)]=value;o.expected[pa]=value;};
 for(size_t off=0;off<image.size();off+=8){uint64_t value=0;for(unsigned b=0;b<8&&off+b<image.size();++b)value|=uint64_t(image[off+b])<<(8*b);seed(ramBase+off,value);}
 auto branch=[](uint64_t pa){return ((pa>>12)<<10)|1ULL;};auto leaf=[](uint64_t pa){return ((pa>>12)<<10)|0xcfULL;};
 seed(0x80300000+16,branch(0x80301000));seed(0x80301000+8,leaf(0x80200000));seed(0x80301000+24,leaf(0x80600000));
 seed(0x80300000+8,branch(0x80302000));seed(0x80302000,branch(0x80303000));seed(0x80303000,leaf(0x80400000));
 seed(0x80400000,0x1020304050607080ULL);seed(0x80400008,0x1122334455667788ULL);
 seed(0x80600000,0);seed(0x80600008,0);o.expected[0x80600000]=0x1122334455667788ULL;o.expected[0x80600008]=UINT64_MAX/7;
 t.observer=Observer::observe;t.observerContext=&o;
 while(t.cycles<20000&&!o.traps)t.tick();
 check(o.traps==1,"ORACLE_TERMINAL_TIMEOUT");
 check(o.witness>0,"UNREACHED_ACTUAL_RESERVE_RETAINED_CERTIFICATE");
 check(o.loadCommits==1,"ORACLE_YOUNGER_LOAD_RETIRE_ONCE");
 check(t.ddr.memory.at(0x400000)==0x1122334455667788ULL&&t.ddr.memory.at(0x400008)==UINT64_MAX/7,"ORACLE_ARCHITECTURAL_MAILBOX");
 t.idle(128);o.tagged.finish();t.fabric.finish();check(o.owed.empty(),"ORACLE_UNDRAINED_REPLY");
 check(t.ddr.pendingReads.empty()&&t.ddr.pendingWrites.empty()&&t.ddr.pendingB.empty(),"ORACLE_UNDRAINED_AXI");
 std::cout<<"ACTUAL_BACKEND_RESERVE_PASS witness="<<o.witness<<" first="<<o.firstCycle<<" reserves="<<o.reserves<<" intrinsic_cycles="<<o.intrinsics<<" matched_cycles="<<o.proofMatch<<" load_commits="<<o.loadCommits<<" cycles="<<t.cycles<<"\n";return 0;
 }catch(const std::exception& e){std::cerr<<"ACTUAL_BACKEND_RESERVE_FAIL applied="<<o.applied<<" witness="<<o.witness<<" reserves="<<o.reserves<<" intrinsics="<<o.intrinsics<<" matches="<<o.proofMatch<<" "<<e.what()<<"\n";return !o.mutation.empty()&&!o.applied?3:1;}}
