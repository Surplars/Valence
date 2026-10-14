#include "FpMiscGsim.h"
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <type_traits>
#ifndef TAG_BITS
#define TAG_BITS 16
#endif
static void check(bool v,const char*msg){if(!v)throw std::runtime_error(msg);}
struct Inputs {bool valid=false,ready=true,flush=false,d=false;uint64_t a=0,b=0,integer=0,tag=0;uint32_t inst=0;unsigned rm=0;};
struct Out {bool ready,valid,illegal;uint64_t value,tag;unsigned flags,index;};
struct Test {
 SFpMiscGsim m;uint64_t cycle=0,lastFast=UINT64_MAX,seq=1;unsigned tests=0,retired=0,killedPrepared=0,killedResult=0,stalls=0,nonconvert=0,illegal=0,ii3=0;uint32_t acceptedHigh=0;bool expectIdle=false;
 Test(){static_assert(std::is_trivially_copyable_v<SFpMiscGsim>);std::memset(&m,0,sizeof(m));m.activateAll();m.set_reset(1);tick({});tick({});m.set_reset(0);}
 Out tick(Inputs x){m.set_io$$valid(x.valid);m.set_io$$resultReady(x.ready);m.set_io$$flush(x.flush);m.set_io$$double(x.d);m.set_io$$bits(x.a);m.set_io$$bitsB(x.b);m.set_io$$integer(x.integer);m.set_io$$token(x.tag);m.set_io$$instruction(x.inst);m.set_io$$rm(x.rm);m.step();++cycle;
 Out o{bool(m.get_io$$ready()),bool(m.get_io$$resultValid()),bool(m.get_io$$illegal()),m.get_io$$value(),m.get_io$$ownerTag(),unsigned(m.get_io$$flags()),unsigned(m.get_io$$ownerIndex())};
 if(expectIdle){check(m.get_io$$allIdle()&&m.get_io$$baseAllIdle(),"RETIRE_NOT_IDLE");expectIdle=false;}
 check(o.ready==bool(m.get_io$$baseReady())&&o.valid==bool(m.get_io$$baseValid()),"HANDSHAKE_MISMATCH");
 if(o.valid)check(o.value==m.get_io$$baseValue()&&o.flags==m.get_io$$baseFlags()&&o.illegal==bool(m.get_io$$baseIllegal())&&o.tag==m.get_io$$baseOwnerTag()&&o.index==m.get_io$$baseOwnerIndex(),"MISC_BASELINE_MISMATCH");return o;}
 void transaction(bool d,uint32_t inst,unsigned rm,uint64_t a,uint64_t b,uint64_t integer,bool oracle,uint64_t expected,unsigned flags,bool illegalExpected,unsigned mode){
 Inputs x;x.d=d;x.inst=inst;x.rm=rm;x.a=a;x.b=b;x.integer=integer;x.valid=true;
 x.tag=TAG_BITS==64?(UINT64_C(0x1235)|(UINT64_C(1)<<(32+seq%32))):seq;seq++;uint64_t owner=TAG_BITS==64?x.tag:x.tag&0xffff;unsigned index=x.tag&15;
 auto o=tick(x);check(o.ready&&!o.valid,"IDLE_NOT_READY");acceptedHigh|=x.tag>>32;
 if(mode==0&&lastFast!=UINT64_MAX){check(cycle-lastFast==3,"II_NOT_3");++ii3;}lastFast=mode==0?cycle:UINT64_MAX;
 x.valid=false;x.a=~a;x.integer=~integer;x.tag^=TAG_BITS==64?UINT64_C(0xffff000000000000):99;
 x.flush=mode==1;x.ready=!(mode==2||mode==3);o=tick(x);check(!o.valid&&!o.ready,"LATENCY_STAGE1_OR_BUSY");
 if(mode==1){x.flush=false;o=tick(x);check(!o.valid&&o.ready,"FLUSH_PREPARED_GHOST");++killedPrepared;}
 else{
 o=tick(x);check(o.valid&&!o.ready,"LATENCY_STAGE2_OR_REFILL");check(o.tag==owner&&o.index==index,"OWNER_CHANGED");
 if(oracle)check(o.value==expected&&o.flags==flags&&o.illegal==illegalExpected,"MISC_ORACLE_MISMATCH");
 if(mode==2){for(unsigned i=0;i<3;i++){x.valid=true;auto held=tick(x);check(held.valid&&!held.ready&&held.value==o.value&&held.flags==o.flags&&held.tag==owner&&held.index==index,"BACKPRESSURE_UNSTABLE");++stalls;}x.valid=false;x.ready=true;auto held=tick(x);check(held.valid&&held.tag==owner,"RELEASE_LOST_OWNER");}
 if(mode==3){x.flush=true;x.ready=true;x.valid=true;o=tick(x);check(!o.valid&&!o.ready,"FLUSH_RESULT_HANDSHAKE");x.flush=false;x.valid=false;o=tick(x);check(!o.valid&&o.ready,"FLUSH_RESULT_GHOST");++killedResult;}
 else {++retired;expectIdle=true;}
 }++tests;
 }
};
static unsigned fpflags(unsigned x){return ((x&6)?16:0)|(x&1);}
int main(int argc,char**argv){try{
 Test t;
 if(TAG_BITS==16){check(argc==2,"usage misc VECTORS");std::ifstream f(argv[1]);check(bool(f),"open vectors");unsigned d,s,rm,nf,wf;uint64_t bits,n,w,row=0;
 while(f>>std::dec>>d>>s>>rm>>std::hex>>bits>>n>>nf>>w>>wf){if(row%53==0){unsigned mode=t.tests%17==1?1:t.tests%19==2?2:t.tests%23==3?3:0;uint64_t a=d?bits:UINT64_C(0xffffffff00000000)|uint32_t(bits);uint32_t inst=0xc0000053|(d<<25)|((!s)<<20)|(rm<<12);t.transaction(d,inst,rm,a,0,0,true,n,fpflags(nf),false,mode);t.transaction(d,inst|(2<<20),rm,a,0,0,true,w,fpflags(wf),false,0);}++row;}check(f.eof()&&row==122840,"VECTOR_PARSE_COVERAGE");}
 else{for(unsigned d=0;d<2;d++)for(unsigned mode=0;mode<4;mode++){uint64_t a=d?UINT64_C(0x3ff8000000000000):UINT64_C(0xffffffff3fc00000);uint32_t inst=0xc0000053|(d<<25);t.transaction(d,inst,0,a,0,0,true,2,1,false,mode);t.transaction(d,inst,0,a,0,0,true,2,1,false,0);t.transaction(d,inst|(2<<20),0,a,0,0,true,2,1,false,0);}for(unsigned d=0;d<2;d++){t.transaction(d,0xc0000053|(d<<25),0,d?UINT64_C(0x41e0000000000000):UINT64_C(0xffffffff4f000000),0,0,true,0x7fffffff,16,false,2);t.transaction(d,0xc0000053|(d<<25)|(1<<20),0,d?UINT64_C(0x7ff0000000000001):UINT64_C(0xffffffff7f800001),0,0,true,UINT64_MAX,16,false,0);}}
 for(unsigned d=0;d<2;d++)for(unsigned j=0;j<(TAG_BITS==64?1:5);j++)for(unsigned k=0;k<12;k++){
 const uint32_t ops[]={0x20000053,0x20001053,0x20002053,0x28000053,0x28001053,0xa0000053,0xa0001053,0xa0002053,0xe0001053,0xe0000053,0xf0000053,0xd0000053};uint32_t inst=ops[k]|(d<<25);if(k==11)inst|=((j%4)<<20)|(j<<12);
 t.transaction(d,inst,j,d?UINT64_C(0xbff8000000000000):UINT64_C(0xffffffffbfc00000),d?UINT64_C(0x7ff0000000000001):UINT64_C(0xffffffff7f800001),UINT64_C(0x80000000ffffffff),false,0,0,false,t.tests%4);++t.nonconvert;}
 for(unsigned d=0;d<2;d++)for(unsigned j=0;j<(TAG_BITS==64?1:5);j++){t.transaction(d,0x40000053|(d<<25)|((!d)<<20)|(j<<12),j,d?UINT64_C(0xffffffff00000001):1,0,0,false,0,0,false,0);++t.nonconvert;}
 for(unsigned d=0;d<2;d++)for(unsigned j=5;j<8;j++){t.transaction(d,0xc0000053|(d<<25)|(j<<12),j,0,0,0,true,0,0,true,0);++t.illegal;}
 t.tick({}); // Discharge final retirement idle obligation, including both formats.
 check(t.tests==(TAG_BITS==64?60:4772)&&t.nonconvert==(TAG_BITS==64?26:130)&&t.illegal==6&&t.killedPrepared>1&&t.killedResult>1&&t.ii3>1,"COVERAGE");if(TAG_BITS==64)check(t.acceptedHigh==UINT32_MAX,"HIGH_TAG_COVERAGE");
 std::cout<<"GSIM_MISC_PASS tagBits="<<TAG_BITS<<" tests="<<t.tests<<" retired="<<t.retired<<" prepared_flush="<<t.killedPrepared<<" result_flush="<<t.killedResult<<" stall_cycles="<<t.stalls<<" nonconvert="<<t.nonconvert<<" illegal="<<t.illegal<<" II3_checks="<<t.ii3<<" latency2=1 same_cycle_refill=0\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
