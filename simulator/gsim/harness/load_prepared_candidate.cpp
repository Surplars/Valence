#include "LoadPreparedCandidateGsim.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <type_traits>
#ifndef REGISTER_QUERY
#define REGISTER_QUERY 0
#endif
namespace {
constexpr uint64_t VA=0x40000000ULL, RAM=0x80010000ULL;
void check(bool v,const char*s){if(!v)throw std::runtime_error(s);}
struct Token {unsigned index=3;uint64_t tag=0x8000000000000031ULL;bool operator==(const Token&)const=default;};
struct Desc {Token token;uint64_t va=VA,pa=RAM;unsigned size=3,epoch=7;bool normal=true,allowed=true;};
struct Inputs {bool load=false,reply=true,stable=true,pause=false;unsigned flush=0,clear=0,epoch=7,replyEpoch=7,pbmt=0,cfg=0x1f,size=3;uint64_t va=VA,pa=RAM;Token token;std::optional<Token> consume;};
struct Bench {
 SLoadPreparedCandidateGsim d; Inputs in; std::optional<Desc> selected,translated,saved;
 unsigned cycle=0,queries=0,proofs=0,firstFlushWitness=0; std::string mutation;
 Bench(){static_assert(std::is_trivially_copyable_v<SLoadPreparedCandidateGsim>);std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();tick(true);tick(true);tick();}
 bool clears(Token t)const{return (in.clear&(1u<<t.index))||(in.consume&&*in.consume==t);}
 void tick(bool reset=false){
  d.set_reset(reset);d.set_io$$load$$valid(in.load);d.set_io$$load$$bits$$token$$index(in.token.index);d.set_io$$load$$bits$$token$$tag(in.token.tag);d.set_io$$load$$bits$$address(in.va);d.set_io$$load$$bits$$size(in.size);
  d.set_io$$reply$$valid(in.reply);d.set_io$$reply$$bits$$physicalAddress(in.pa);d.set_io$$reply$$bits$$epoch(in.replyEpoch);d.set_io$$reply$$bits$$pbmt(in.pbmt);
  d.set_io$$epoch(in.epoch);d.set_io$$stable(in.stable);d.set_io$$flushCauses(in.flush);d.set_io$$clear(in.clear);d.set_io$$pause(in.pause);d.set_io$$pmpCfg(in.cfg);
  d.set_io$$consume$$valid(bool(in.consume));d.set_io$$consume$$bits$$index(in.consume?in.consume->index:0);d.set_io$$consume$$bits$$tag(in.consume?in.consume->tag:0);
  d.step();++cycle;
  if(reset){d.resetAll();selected.reset();translated.reset();saved.reset();return;}
  const bool active=in.stable&&!in.flush;const bool offer=in.load&&!in.pause&&active;
  std::optional<Desc> q;
  if(REGISTER_QUERY){if(selected&&active&&selected->epoch==in.epoch)q=selected;}
  else if(offer)q=Desc{in.token,in.va,0,in.size,in.epoch,false,false};
  check(bool(d.get_io$$query$$valid())==bool(q),"ORACLE_QUERY_VALID");
  if(q){check(d.get_io$$query$$bits$$address()==q->va&&d.get_io$$query$$bits$$size()==q->size&&!d.get_io$$query$$bits$$write(),"ORACLE_QUERY_TUPLE");++queries;}
  bool candidate=saved&&in.stable&&saved->epoch==in.epoch;
  bool strict=candidate&&!in.flush;
  if(candidate&&in.flush){++firstFlushWitness;if(mutation=="candidate"){std::cout<<"FLUSH_CANDIDATE_ANCHOR first_flush_retained_proof\n"<<std::flush;candidate=false;}}
  check(bool(d.get_io$$candidate())==candidate,"ORACLE_INTRINSIC_CANDIDATE");
  check(bool(d.get_io$$prepared$$valid())==strict,"ORACLE_STRICT_VALID");
  if(strict){++proofs;auto expected=*saved;
   if(mutation=="token"){std::cout<<"FLUSH_CANDIDATE_ANCHOR full_token\n"<<std::flush;expected.token.tag^=1ULL<<63;}
   if(mutation=="allowed"){std::cout<<"FLUSH_CANDIDATE_ANCHOR permission\n"<<std::flush;expected.allowed=!expected.allowed;}
   check(d.get_io$$prepared$$bits$$token$$index()==expected.token.index&&d.get_io$$prepared$$bits$$token$$tag()==expected.token.tag,"ORACLE_FULL_TOKEN");
   check(d.get_io$$prepared$$bits$$address()==expected.va&&d.get_io$$prepared$$bits$$physicalAddress()==expected.pa&&d.get_io$$prepared$$bits$$size()==expected.size&&d.get_io$$prepared$$bits$$epoch()==expected.epoch,"ORACLE_CERTIFICATE_TUPLE");
   check(bool(d.get_io$$prepared$$bits$$allowed())==expected.allowed,"ORACLE_PERMISSION");
  }
  auto next=saved;
  if(translated&&active&&translated->epoch==in.epoch&&!clears(translated->token)){
   auto t=*translated;const uint64_t bytes=1ULL<<t.size;
   t.allowed=t.normal&&(in.cfg&1)&&((in.cfg>>3)&3)==3&&t.size<=3&&!(t.va&(bytes-1))&&!(t.pa&(bytes-1))&&((t.va&4095)==(t.pa&4095))&&t.pa>=RAM&&(__uint128_t(t.pa)+bytes<=__uint128_t(RAM)+65536);next=t;
  }
  // Original retained-owner cancellation has last priority, even over a new result.
  if(!active||(saved&&(saved->epoch!=in.epoch||clears(saved->token))))next.reset();
  saved=next;
  translated.reset();
  if(q&&active&&(!REGISTER_QUERY||!clears(q->token))){auto t=*q;t.pa=in.reply?in.pa:0;t.normal=in.reply&&!in.pbmt&&in.replyEpoch==in.epoch;translated=t;}
  selected.reset();if(offer&&!clears(in.token))selected=Desc{in.token,in.va,0,in.size,in.epoch,false,false};
 }
 void wait(unsigned n){while(n--)tick();}
 void prepare(){in.load=true;wait(5);in.load=false;wait(3);check(saved.has_value(),"TEST_SETUP_NO_SAVED_PROOF");}
};
}
int main(int argc,char**argv){try{
 const std::string mode=argc>1?argv[1]:"";
 for(unsigned f=0;f<16;++f){Bench b;b.prepare();check(b.saved->allowed,"TEST_SETUP_DENIED");b.in.flush=f;if(mode=="--oracle-candidate"&&f==1)b.mutation="candidate";b.tick();if(f)check(!b.saved,"FLUSH_DID_NOT_CLEAR_NEXT_STATE");b.in.flush=0;b.wait(2);if(f)check(!b.saved,"FLUSH_PROOF_REVIVED");std::cout<<"FLUSH_CANDIDATE_CASE first_flush="<<f<<" witness="<<b.firstFlushWitness<<'\n';}
 for(unsigned fault=0;fault<8;++fault){Bench b;if(fault==0)b.in.reply=false;if(fault==1)b.in.pbmt=1;if(fault==2)b.in.cfg=0x18;if(fault==3)b.in.replyEpoch=6;if(fault==4)b.in.pa=0x10000000;if(fault==5)b.in.va=VA+1;if(fault==6)b.in.pa=RAM+1;if(fault==7)b.in.pa=RAM+8;b.prepare();check(!b.saved->allowed,"DENIED_CERTIFICATE_GRANTED");std::cout<<"FLUSH_CANDIDATE_CASE denied="<<fault<<'\n';}
 for(unsigned kind=0;kind<6;++kind){Bench b;b.prepare();const Token old=b.in.token;
  if(kind==0)b.in.stable=false;if(kind==1)++b.in.epoch;if(kind==2)b.in.clear=1u<<old.index;if(kind==3)b.in.consume=old;
  if(kind==4)b.in.consume=Token{old.index,old.tag^(1ULL<<63)};
  if(kind==5){b.in.token.tag^=1ULL<<63;b.in.load=true;}
  b.tick();if(kind<4)check(!b.saved,"OWNER_EPOCH_CLEAR_FAILED");else check(b.saved.has_value(),"STALE_CONSUME_OR_INCOMING_REPLACED_TOO_EARLY");
  b.in.stable=true;b.in.replyEpoch=b.in.epoch;b.in.clear=0;b.in.consume.reset();b.prepare();check(b.saved->token==b.in.token,"FULL_GENERATION_REUSE_FAILED");std::cout<<"FLUSH_CANDIDATE_CASE owner="<<kind<<'\n';}
 for(unsigned k=0;k<3;++k){Bench b;b.in.load=true;for(unsigned n=0;n<5&&!b.translated;++n)b.tick();check(b.translated.has_value(),"TEST_SETUP_NO_CAPTURE");b.in.load=false;if(k==0)b.in.flush=8;if(k==1)b.in.clear=1u<<b.in.token.index;if(k==2)b.in.consume=b.in.token;b.tick();check(!b.saved,"SAME_EDGE_CLEAR_LOST_TO_CAPTURE");b.in.flush=0;b.in.clear=0;b.in.consume.reset();b.wait(3);check(!b.saved,"CANCELLED_CAPTURE_REVIVED");std::cout<<"FLUSH_CANDIDATE_CASE capture_priority="<<k<<'\n';}
 {Bench b;b.prepare();const Token old=b.in.token;b.in.token={4,0xc000000000000041ULL};b.in.load=true;
  for(unsigned n=0;n<5;++n){b.tick();if(b.translated&&b.translated->token==b.in.token)break;}
  check(b.translated&&b.translated->token==b.in.token,"TEST_SETUP_NO_REPLACEMENT");b.in.load=false;b.in.clear=1u<<old.index;b.tick();check(!b.saved,"OLD_OWNER_CLEAR_LOST_TO_NEW_CAPTURE");b.in.clear=0;b.wait(3);std::cout<<"FLUSH_CANDIDATE_CASE old_clear_over_new_capture\n";}
 {Bench b;b.prepare();if(mode=="--oracle-token")b.mutation="token";if(mode=="--oracle-allowed")b.mutation="allowed";b.tick();}
 if(!mode.empty())throw std::runtime_error("NEGATIVE_CONTROL_ESCAPED");
 std::cout<<"LOAD_PREPARED_CANDIDATE_PASS register_query="<<REGISTER_QUERY<<" flush_cases=16 denied=8 owner=6 capture_priority=3\n";return 0;
 }catch(const std::exception&e){std::cerr<<"LOAD_PREPARED_CANDIDATE_REJECT "<<e.what()<<'\n';return 1;}}
