// Reuse only cold programming and transport sampling from the sealed source.
#define main archived_main
#include "hypervisor_platform.cpp"
#undef main
#include <vector>
#include <fstream>
struct HOp { uint64_t pc,va,pa; unsigned width; bool store,sign; uint64_t data; };
static uint64_t signextend(uint64_t x,unsigned n){if(n==8)return x;uint64_t sign=1ULL<<(n*8-1);return (x^sign)-sign;}
static void widths(bool supervisor,bool negative,const std::string& traceDir){
 std::ofstream trace(traceDir+"/trace-"+std::string(negative?"negative":supervisor?"hs-s":"hs-u")+".log"); trace<<std::hex;
 Program p(1,false);p.code.clear();p.pc=BASE;
 p.csr(0x3b0,~0ULL);p.csr(0x3a0,31);p.csr(0x305,MT);p.csr(0x105,MT);
 p.csr(0x280,(8ULL<<60)|(VROOT>>12));p.csr(0x680,(8ULL<<60)|(GROOT>>12));
 p.csr(0x600,supervisor?256:0);p.csr(0x341,HS);p.csr(0x300,1ULL<<11);p.emit(0x30200073);
 p.pc=HS;std::vector<HOp> ops;std::map<uint64_t,size_t> bypc;
 auto add=[&](unsigned width,bool st,bool sg,bool execute,unsigned offset,uint64_t data){
   uint64_t va=DATA+offset+(execute?4096:0),pa=SPA_DATA+offset+(execute?4096:0);
   p.li(2,va);if(st)p.li(3,data);
   unsigned log=width==1?0:width==2?1:width==4?2:3;
   // Ratified instruction fields, independently cross-checked with GNU assembler.
   uint32_t i=(st?0x62004073:0x60004073)+(log<<26)|(2<<15);
   if(st)i|=3<<20;else i|=(execute?3:sg||width==8?0:1)<<20|10<<7;
   bypc[p.pc]=ops.size();ops.push_back({p.pc,va,pa,width,st,sg,data});p.emit(i);
 };
 for(unsigned n:{1U,2U,4U,8U})for(unsigned off=0;off<8;off+=n){add(n,false,true,false,off,0);if(n!=8)add(n,false,false,false,off,0);}
 for(unsigned n:{2U,4U})for(unsigned off=0;off<8;off+=n)add(n,false,false,true,off,0);
 for(unsigned n:{1U,2U,4U,8U})for(unsigned off=0;off<8;off+=n){uint64_t data=0xfedcba9876543280ULL+off+n;add(n,true,false,false,32+off,data);add(n,false,true,false,32+off,0);if(n!=8)add(n,false,false,false,32+off,0);}
 p.li(31,99);uint64_t stop=p.pc;p.emit(0x6f);
 Memory phys;p.load(phys);phys.pte(0x80209008,0x20001000,0xc7|(supervisor?0:16));
 phys.pte(GDATALEAF+16,SPA_DATA+4096,0xd9);phys.pte(0x80209010,0x20002000,0xc9|(supervisor?0:16));
 phys.put(SPA_DATA,0x80ff81fe82fd83fcULL,8);phys.put(SPA_DATA+4096,0x91aa92bb93cc94ddULL,8);
 Memory arch=phys;Oracle checks(1,false);auto dptr=std::make_unique<SHypervisorPlatformGsim>();auto& d=*dptr;std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();initialize(d,phys);
 uint64_t pc=BASE,regs[32]{};bool hs=false;unsigned retired=0,physical=0,ptes=0,fetches=0,hret=0;std::deque<Request> owners[2];std::deque<uint64_t> expected[2];
 Request heldQ[2];Response heldR[2];bool hq[2]{},hr[2]{};unsigned stalls[2]{},nextowner[2]{};
 auto ck=[&](uint64_t a,uint64_t e,const char* n){checks.pc=pc;checks.check(a,e,n);};
 for(unsigned cycle=0;cycle<200000;cycle++){
  d.set_io$$enable(1);d.set_io$$commitEnable(cycle%11!=3);d.set_io$$allowRequest((cycle%5==1?0:1)|(cycle%7==2?0:2));d.set_io$$allowResponse((cycle%7<3?0:1)|(cycle%9<4?0:2));d.step();
  for(unsigned lane=0;lane<2;lane++){
   auto q=request(d,lane);auto r=response(d,lane);bool qr=(d.get_io$$scalarRequestReady()>>lane)&1,rr=(d.get_io$$scalarResponseReady()>>lane)&1;
   if(hq[lane])ck(q==heldQ[lane],1,"held request");if(hr[lane])ck(r==heldR[lane],1,"held response");hq[lane]=q.valid&&!qr;hr[lane]=r.valid&&!rr;heldQ[lane]=q;heldR[lane]=r;stalls[lane]+=hq[lane]+hr[lane];
   if(r.valid&&rr){trace<<"R "<<cycle<<" "<<lane<<" "<<r.owner<<" "<<r.data<<" "<<r.error<<" "<<r.pageFault<<"\n";ck(!owners[lane].empty(),1,"response owned");auto prior=owners[lane].front();owners[lane].pop_front();ck(r.owner,prior.owner,"response owner");ck(r.error||r.pageFault||r.clear,0,"successful native response");if(!prior.write)ck(r.data,expected[lane].front(),"full physical read beat");expected[lane].pop_front();}
   if(q.valid&&qr){trace<<"Q "<<cycle<<" "<<lane<<" "<<q.owner<<" "<<q.address<<" "<<q.size<<" "<<q.mask<<" "<<q.write<<" "<<q.data<<"\n";ck(q.owner,nextowner[lane]++&15,"request owner");ck(q.clear||q.atomic||q.virtualized||q.prechecked||q.prefetch||q.epoch,0,"plain physical request");ck(q.lookup,1,"actual fabric lookup");
    if(lane==0){ck(hs,1,"H access originates in HS");ck(physical<ops.size(),1,"bounded H access count");const auto& op=ops.at(physical++);unsigned sz=op.width==1?0:op.width==2?1:op.width==4?2:3;
      ck(q.address,op.pa,"H physical byte address");ck(q.size,sz,"H physical size");ck(q.mask,((1U<<op.width)-1)<<(op.pa&7),"H byte mask");ck(q.write,op.store,"H physical direction");
      if(op.store){ck(q.data,op.data<<((op.pa&7)*8),"H shifted store data");for(unsigned b=0;b<8;b++)if(q.mask&(1U<<b))phys.put((q.address&~7ULL)+b,q.data>>(8*b),1);}
    }else{ck(q.write,0,"IF/PTE read only");if(q.size==1){fetches++;ck(q.address>=BASE&&q.address<BASE+0x4000,1,"HS physical instruction fetch");ck(q.mask,3U<<(q.address&7),"IF mask");}else{ptes++;ck(q.size,3,"PTE size");ck(q.mask,255,"PTE mask");ck(q.address>=GROOT&&q.address<0x8020a000,1,"actual nested table address");}}
    owners[lane].push_back(q);expected[lane].push_back(q.write?0:phys.get(q.address&~7ULL,8));
   }
  }
  auto commit=[&](uint64_t ap,uint32_t i,unsigned rd,uint64_t value,uint64_t np,bool wr){
   trace<<"C "<<cycle<<" "<<ap<<" "<<i<<" "<<wr<<" "<<rd<<" "<<value<<" "<<np<<"\n";
   ck(ap,pc,"retired PC");ck(i,p.code.at(pc),"retired instruction");uint64_t v=0,next=pc+4;unsigned dest=(i>>7)&31,a=(i>>15)&31;bool writes=dest!=0;
   if(bypc.count(pc)){ck(hs,1,"HS architectural origin");auto& op=ops.at(bypc.at(pc));ck(regs[2],op.va,"independent H VA");if(op.store){writes=false;arch.put(op.pa,regs[3],op.width);}else{v=arch.get(op.pa,op.width);if(op.sign)v=signextend(v,op.width);if(negative&&hret==0)v^=1;}hret++;}
   else if((i&127)==0x13){if(((i>>12)&7)==1)v=regs[a]<<((i>>20)&63);else v=regs[a]+sext(i>>20,12);}
   else if(i==0x30200073){hs=true;writes=false;next=HS;}
   else if((i&127)==0x73){writes=false;}
   else if(i==0x6f){writes=false;next=pc;}
   else throw std::runtime_error("unknown oracle instruction");
   ck(wr,writes,"retirement write enable");ck(np,next,"retirement next PC");if(writes){ck(rd,dest,"retirement RD");ck(value,v,"independent architectural data");regs[dest]=v;}pc=next;retired++;
  };
#define C(N) if(d.get_io$$commit##N##$$valid())commit(d.get_io$$commit##N##$$bits$$pc(),d.get_io$$commit##N##$$bits$$instruction(),d.get_io$$commit##N##$$bits$$rd(),d.get_io$$commit##N##$$bits$$data(),d.get_io$$commit##N##$$bits$$nextPc(),d.get_io$$commit##N##$$bits$$writesRd());
  C(0);C(1);
#undef C
  ck(d.get_io$$trap$$valid(),0,"all HS H operations successful");
  if(regs[31]==99&&pc==stop){ck(physical,ops.size(),"all native H operations");ck(hret,ops.size(),"all H retirements");ck(owners[0].empty(),1,"H responses completed");ck(ptes>0&&fetches>0&&stalls[0]>0&&stalls[1]>0,1,"nested walks and both lane stalls");std::cout<<"HS_WIDTH_PASS SPVP="<<supervisor<<" VS_U="<<!supervisor<<" cycles="<<cycle+1<<" retired="<<retired<<" h_ops="<<hret<<" ptes="<<ptes<<" fetches="<<fetches<<" checks="<<checks.checks<<" stalls="<<stalls[0]<<","<<stalls[1]<<" finite_sentinel=99\n";return;}
 }
 throw std::runtime_error("timeout");
}
int main(int argc,char** argv){try{if(argc<2)throw std::runtime_error("usage: hypervisor_hs_widths TRACE_DIRECTORY [wrong-data]");bool negative=argc>2;widths(false,negative,argv[1]);if(negative)throw std::runtime_error("negative was not detected");widths(true,false,argv[1]);return 0;}catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<"\n";return 1;}}
