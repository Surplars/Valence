#include "HypervisorTranslatedCoreGsim.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <stdexcept>
#include <type_traits>
static constexpr uint64_t BASE=0x80000000, HS=BASE+0x2000, MT=BASE+0x3000, VA=0x40000000, DATA=VA+0x1000;
static constexpr uint64_t GROOT=0x80010000, GMID=0x80014000, GPTLEAF=0x80015000, GDATALEAF=0x80016000;
static constexpr uint64_t VROOT=0x10000000, VMID=0x10001000, VLEAF=0x10002000;
static uint32_t addi(unsigned d,unsigned s,int n){return(uint32_t(n)&4095)<<20|s<<15|d<<7|0x13;}
static uint32_t shift(unsigned d,unsigned s,unsigned n){return n<<20|s<<15|1<<12|d<<7|0x13;}
static uint32_t csrw(unsigned c,unsigned r){return c<<20|r<<15|1<<12|0x73;}
static uint32_t csrr(unsigned c,unsigned r){return c<<20|2<<12|r<<7|0x73;}
static uint32_t ld(unsigned d,unsigned a,int n=0){return(uint32_t(n)&4095)<<20|a<<15|3<<12|d<<7|3;}
static uint32_t sd(unsigned s,unsigned a,int n=0){unsigned u=n&4095;return(u>>5)<<25|s<<20|a<<15|3<<12|(u&31)<<7|0x23;}
static int64_t sext(uint64_t v,unsigned w){return int64_t(v<<(64-w))>>(64-w);}
struct Memory {
 std::map<uint64_t,uint8_t> bytes;uint64_t reads=0,writes=0;
 void put(uint64_t a,uint64_t d,unsigned n){for(unsigned i=0;i<n;i++)bytes[a+i]=d>>(8*i);}
 uint64_t get(uint64_t a,unsigned n){uint64_t d=0;for(unsigned i=0;i<n;i++){auto p=bytes.find(a+i);if(p==bytes.end())throw std::runtime_error("unmapped physical memory "+std::to_string(a));d|=uint64_t(p->second)<<(8*i);}return d;}
 void pte(uint64_t a,uint64_t ppn,unsigned f){put(a,(ppn>>12)<<10|f,8);}
 void page(uint64_t a){for(unsigned i=0;i<4096;i++)bytes[a+i]=0;}
};
struct Program {
 std::map<uint64_t,uint32_t> code;std::map<uint64_t,std::pair<unsigned,uint64_t>> faults;uint64_t pc=BASE;
 void emit(uint32_t i){code[pc]=i;pc+=(i&3)==3?4:2;}
 void li(unsigned r,uint64_t n){emit(addi(r,0,0));bool seen=false;for(int b=7;b>=0;b--){unsigned v=(n>>(8*b))&255;if(!seen&&!v)continue;if(seen)emit(shift(r,r,8));emit(addi(r,r,v));seen=true;}}
 void csr(unsigned c,uint64_t v){li(1,v);emit(csrw(c,1));}
 void fault(unsigned cause,uint64_t gpa,uint32_t inst){uint64_t next=pc+4*10+4; // Patch return-address materialization after knowing its length.
   auto save=pc;li(30,0);pc=save;code.erase(save); // All relevant VAs are 4-byte constants, use fixed LUI+ADDI.
   uint64_t resume=pc+12;emit(uint32_t((resume+0x800)&0xfffff000)|(30<<7)|0x37);emit(addi(30,30,int(resume&4095)));
   faults[pc]={cause,gpa};emit(inst);
 }
 Program(){
  csr(0x3b0,~0ULL);csr(0x3a0,31);csr(0x305,MT);csr(0x105,HS);csr(0x302,0xf00400);
  csr(0x280,(8ULL<<60)|(VROOT>>12));csr(0x680,(8ULL<<60)|(GROOT>>12));csr(0x600,1<<8);
  unsigned contextIndex=0;
  for(unsigned pp: {0u,1u,3u}) for(unsigned mpv: {0u,1u}) for(unsigned mprv: {0u,1u}) {
   csr(0x300,(uint64_t(mpv)<<39)|(uint64_t(mprv)<<17)|(pp<<11));
   bool guest=mprv&&mpv&&pp!=3;uint64_t a=guest?(pp==0?VA+0x5000:DATA):0x80201000;
   li(2,a);emit(ld(7,2));li(3,0x80+contextIndex++);emit(sd(3,2,24));emit(ld(8,2,24));
  }
  csr(0x300,0);
  li(2,DATA);emit((0x6c0u<<20)|(2<<15)|(4<<12)|(5<<7)|0x73); // HLV.D
  li(3,0x99);li(2,DATA+8);emit((0x6e0u<<20)|(3<<20)|(2<<15)|(4<<12)|0x73); // HSV.D
  li(2,VA+0x3000);emit((0x643u<<20)|(2<<15)|(4<<12)|(6<<7)|0x73); // HLVX.HU
  emit(0x22000073);emit(0x62000073);
  csr(0x341,VA);csr(0x300,(1ULL<<39)|(1<<11));emit(0x30200073);
  pc=VA;emit((2<<13)|(9<<7)|(7<<2)|1);li(2,DATA);emit(ld(10,2));emit(ld(11,2,8));li(3,0x55);emit(sd(3,2,16));emit(ld(12,2,16));
  li(2,VA+0x2000);fault(21,0x30000000,ld(13,2));fault(23,0x30000000,sd(3,2));
  li(2,VA+0x200000);fault(21,0x10003000,ld(14,2));
  li(2,VA+0x3ffe);uint64_t resume=pc+12;emit(uint32_t((resume+0x800)&0xfffff000)|(30<<7)|0x37);emit(addi(30,30,int(resume&4095)));emit((2<<15)|0x67);faults[VA+0x3ffe]={20,0x30001000};
  emit(addi(31,0,99));emit(0x6f);
  pc=HS;emit(csrr(0x142,20));emit(csrr(0x143,21));emit(csrr(0x643,22));emit(csrr(0x64a,23));emit(csrr(0x600,24));emit(csrr(0x141,25));emit(csrw(0x141,30));emit(0x10200073);
  pc=MT;emit(addi(31,0,-1));emit(0x6f);
 }
 void load(Memory&m){
  for(unsigned i=0;i<4;i++)m.page(BASE+4096*i);
  for(uint64_t p:std::initializer_list<uint64_t>{GROOT,GROOT+4096,GROOT+8192,GROOT+12288,GMID,GPTLEAF,GDATALEAF,0x80300000ULL,0x80301000ULL,0x80302000ULL,0x80200000ULL,0x80201000ULL,0x80203000ULL,0x80205000ULL})m.page(p);
  m.pte(GROOT,GMID,1);m.pte(GMID+128*8,GPTLEAF,1);m.pte(GMID+256*8,GDATALEAF,1);
  for(unsigned i=0;i<3;i++)m.pte(GPTLEAF+i*8,0x80300000+i*4096,0xdf);
  m.pte(GDATALEAF,0x80200000,0xdf);m.pte(GDATALEAF+8,0x80201000,0xdf);m.pte(GDATALEAF+24,0x80203000,0xdf);m.pte(GDATALEAF+40,0x80205000,0xdf);
  m.pte(0x80300000+8,VMID,1);m.pte(0x80301000,VLEAF,1);m.pte(0x80301000+8,VROOT+0x3000,1);
  m.pte(0x80302000,0x20000000,0xcb);m.pte(0x80302008,0x20001000,0xc7);m.pte(0x80302010,0x30000000,0xc7);
  m.pte(0x80302018,0x20003000,0xc9);m.pte(0x80302020,0x30001000,0xcb);m.pte(0x80302028,0x20005000,0xd7);
  m.put(0x80203ffe,0x0013,2);
  m.put(0x80201000,0x1122334455667788ULL,8);m.put(0x80203000,0x887766554433abcdULL,8);m.put(0x80205000,0x0123456789abcdefULL,8);
  for(auto [va,i]:code)m.put(va>=VA&&va<VA+0x1000?va-VA+0x80200000:va,i,(i&3)==3?4:2);
 }
};
struct Oracle {
 uint64_t status=0;std::map<uint64_t,uint64_t> memory{{0x80201000,0x1122334455667788ULL},{0x80203000,0x887766554433abcdULL},{0x80205000,0x0123456789abcdefULL}};
 uint64_t r[32]{},pc=BASE,sepc=0,scause=0,stval=0,htval=0,htinst=0;bool v=false;unsigned traps=0;uint64_t checks=0,commits=0;
 void check(uint64_t a,uint64_t b,const char*l){checks++;if(a!=b){std::cerr<<l<<" pc="<<std::hex<<pc<<" actual="<<a<<" expected="<<b<<std::dec<<"\n";throw std::runtime_error(l);}}
 uint64_t address(uint64_t a,bool forced=false){
  bool guest=forced||v||((status&(1ULL<<17))&&(status&(1ULL<<39))&&((status>>11)&3)!=3);
  if(!guest)return a;
  if(a>=DATA&&a<DATA+4096)return 0x80201000+(a-DATA);
  if(a>=VA+0x3000&&a<VA+0x4000)return 0x80203000+(a-VA-0x3000);
  if(a>=VA+0x5000&&a<VA+0x6000)return 0x80205000+(a-VA-0x5000);
  throw std::runtime_error("oracle unexpected guest data address");
 }
 uint64_t csr(unsigned c){switch(c){case 0x142:return scause;case 0x143:return stval;case 0x643:return htval;case 0x64a:return htinst;case 0x600:return(2ULL<<32)|0x1c0;case 0x141:return sepc;default:return 0;}}
 void commit(uint64_t apc,uint32_t i,unsigned rd,uint64_t value,uint64_t anext,const Program&p){
  check(apc,pc,"retired PC");check(i,p.code.at(pc),"retired instruction");unsigned op=i&127,d=(i>>7)&31,a=(i>>15)&31,b=(i>>20)&31,f=(i>>12)&7;uint64_t val=0,next=pc+((i&3)==3?4:2);bool wr=d!=0;
  if((i&3)!=3){d=(i>>7)&31;wr=d!=0;val=sext(((i>>12)&1)<<5|((i>>2)&31),6);}
  else if(op==0x13)val=f==0?r[a]+sext(i>>20,12):r[a]<<((i>>20)&63);
  else if(op==0x37)val=sext(i&0xfffff000,32);
  else if(op==3){uint64_t va=r[a]+sext(i>>20,12);val=memory.at(address(va));}
  else if(op==0x23){wr=false;int64_t off=sext((i>>25)<<5|((i>>7)&31),12);memory[address(r[a]+off)]=r[b];}
  else if(op==0x67){next=(r[a]+sext(i>>20,12))&~1ULL;val=pc+4;}
  else if(op==0x73&&f==4){if(i>>25==0x36)val=memory.at(address(r[a],true));else if(i>>25==0x32)val=memory.at(address(r[a],true))&65535;else{wr=false;memory[address(r[a],true)]=r[b];}}
  else if(op==0x73&&f){unsigned c=i>>20;val=csr(c);if(f==1&&c==0x141)sepc=r[a];if(f==1&&c==0x300)status=r[a];}
  else if(i==0x30200073){wr=false;next=VA;v=true;}
  else if(i==0x10200073){wr=false;next=sepc;v=true;}
  else if(i==0x22000073||i==0x62000073)wr=false;
  else throw std::runtime_error("unexpected retired instruction");
  check(anext,next,"next PC");if(wr){check(rd,d,"RD");check(value,val,"retired value");r[d]=val;}pc=next;commits++;
 }
 void trap(uint64_t apc,uint64_t cause,uint64_t tv,uint64_t gpa,bool gp,bool ga,bool implicit,const Program&p){
  check(apc,pc,"precise fault PC");auto expected=p.faults.at(pc);check(cause,expected.first,"guest fault cause");check(gpa,expected.second,"owner raw GPA");check(gp,1,"guest page fault classification");check(ga,1,"guest virtual address provenance");
  bool ip=expected.second==0x10003000;check(implicit,ip,"implicit VS PTE provenance");check(tv,cause==20?pc+2:r[2],"original fault VA");
  sepc=pc;scause=cause;stval=tv;htval=gpa>>2;htinst=ip?0x3000:0;pc=HS;v=false;traps++;
 }
};
struct Pending {bool valid=false;uint64_t data=0;unsigned delay=0;};
int main(){try{
 Program p;Memory m;p.load(m);Oracle o;SHypervisorTranslatedCoreGsim d;static_assert(std::is_trivially_copyable_v<SHypervisorTranslatedCoreGsim>);memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();d.set_reset(1);d.step();d.step();d.set_reset(0);d.set_io$$enable(1);
 Pending fi,fp,dp,da;unsigned fetched=0,pteReads=0,dataOps=0;
 for(unsigned c=0;c<100000;c++){
  d.set_io$$commitEnable(c%7!=3);auto advance=[](Pending&x){if(x.delay)x.delay--;};advance(fi);advance(fp);advance(dp);advance(da);
#define DRIVE(P,N) bool ready_##N=!P.valid&&c%5!=2; d.set_io$$##N##$$request$$ready(ready_##N);d.set_io$$##N##$$response$$valid(P.valid&&!P.delay);d.set_io$$##N##$$response$$bits(P.data)
  DRIVE(fi,instruction);d.set_io$$instruction$$responseError(0);d.set_io$$instruction$$responsePageFault(0);
#undef DRIVE
#define PTEDRIVE(P,N) bool ready_##N=!P.valid&&c%5!=2; d.set_io$$##N##$$request$$ready(ready_##N);d.set_io$$##N##$$response$$valid(P.valid&&!P.delay);d.set_io$$##N##$$response$$bits$$data(P.data);d.set_io$$##N##$$response$$bits$$error(0)
  PTEDRIVE(fp,fetchPte);PTEDRIVE(dp,dataPte);
#undef PTEDRIVE
  bool ready_data=!da.valid&&c%5!=2;d.set_io$$data$$request$$ready(ready_data);d.set_io$$data$$response$$valid(da.valid&&!da.delay);d.set_io$$data$$response$$bits$$data(da.data);d.set_io$$data$$response$$bits$$error(0);d.set_io$$data$$response$$bits$$pageFault(0);
  d.step();
#define DONE(P,N) if(P.valid&&!P.delay&&d.get_io$$##N##$$response$$ready())P.valid=false
  DONE(fi,instruction);DONE(fp,fetchPte);DONE(dp,dataPte);DONE(da,data);
#undef DONE
#define REQUEST(P,N,SIZE,COUNT) if(d.get_io$$##N##$$request$$valid()&&ready_##N){o.check(P.valid,0,"one physical owner");P={true,m.get(d.get_io$$##N##$$request$$bits(),SIZE),1+c%3};COUNT++;}
  REQUEST(fi,instruction,2,fetched);REQUEST(fp,fetchPte,8,pteReads);REQUEST(dp,dataPte,8,pteReads);
#undef REQUEST
  if(d.get_io$$data$$request$$valid()&&ready_data){
   uint64_t a=d.get_io$$data$$request$$bits$$address(),base=a&~7ULL;bool wr=d.get_io$$data$$request$$bits$$write();
   o.check(d.get_io$$data$$request$$bits$$virtualized(),0,"physical offer strips virtual proof");o.check(a>=0x80201000&&a<0x80206000,1,"data translated to SPA");
   if(wr){uint64_t value=d.get_io$$data$$request$$bits$$data();unsigned mask=d.get_io$$data$$request$$bits$$mask();for(unsigned b=0;b<8;b++)if(mask&(1<<b))m.put(base+b,value>>(8*b),1);m.writes++;}
   da={true,m.get(base,8),2+c%4};dataOps++;
  }
#define COMMIT(N) if(d.get_io$$commit##N##$$valid())o.commit(d.get_io$$commit##N##$$bits$$pc(),d.get_io$$commit##N##$$bits$$instruction(),d.get_io$$commit##N##$$bits$$rd(),d.get_io$$commit##N##$$bits$$data(),d.get_io$$commit##N##$$bits$$nextPc(),p)
  COMMIT(0);COMMIT(1);
#undef COMMIT
  if(d.get_io$$trap$$valid())o.trap(d.get_io$$trap$$bits$$pc(),d.get_io$$trap$$bits$$cause(),d.get_io$$trap$$bits$$tval(),d.get_io$$trap$$bits$$guestFault$$guestPhysicalAddress(),d.get_io$$trap$$bits$$guestFault$$guestPageFault(),d.get_io$$trap$$bits$$guestFault$$guestAddress(),d.get_io$$trap$$bits$$guestFault$$implicitPte(),p);
  if(o.r[31]==99){o.check(o.traps,4,"four precise guest faults");o.check(m.get(0x80201008,8),0x99,"HSV store physical destination");o.check(m.get(0x80201010,8),0x55,"VS store physical destination");std::cout<<"H_OOO_TRANSLATED_PASS cycles="<<c<<" commits="<<o.commits<<" traps="<<o.traps<<" pteReads="<<pteReads<<" fetches="<<fetched<<" dataOps="<<dataOps<<" checks="<<o.checks<<"\n";return 0;}
  if(o.r[31]==~0ULL)throw std::runtime_error("unexpected machine trap");
 }
 throw std::runtime_error("translated core timeout");
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
