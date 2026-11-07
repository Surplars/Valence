// Additional VS-origin platform PMA checks. This does not exercise the restricted
// M-origin guest-page-fault review. All faulting instructions originate in VS.
#define main platform_positive_main
#include "hypervisor_platform.cpp"
#undef main

static void faultCase(unsigned kind){
    Program p(1,false);p.code.clear();p.pc=BASE;
    p.csr(0x3b0,~0ULL);p.csr(0x3a0,31);p.csr(0x305,MT);p.csr(0x105,HS);
    p.csr(0x302,(1<<7)|(1<<1)|(1<<5));p.csr(0x280,(8ULL<<60)|(VROOT>>12));p.csr(0x680,(8ULL<<60)|(GROOT>>12));
    p.csr(0x341,VA);p.csr(0x300,(1ULL<<39)|(1<<11));p.emit(0x30200073);
    p.pc=VA;p.emit((2<<13)|(9<<7)|(7<<2)|1);p.li(2,VA+8192);p.li(3,0x44);
    uint64_t faultPc=p.pc;p.emit(sd(3,2));p.li(31,~0ULL);p.emit(0x6f);
    p.pc=HS;p.emit(csrr(0x142,16));p.emit(csrr(0x141,17));p.emit(csrr(0x143,18));p.emit(csrr(0x600,19));p.emit(csrr(0x643,20));p.li(31,99);p.emit(0x6f);
    p.pc=MT;p.li(31,~0ULL);p.emit(0x6f);
    Memory m;p.load(m);
    if(kind==0){m.pte(0x80209010,0x20002000,0xc7);m.pte(GDATALEAF+16,BASE,0xdf);}
    if(kind==1)m.pte(GDATALEAF,0x0c000000,0xdf); // final instruction SPA points at APLIC
    if(kind==2)m.pte(GPTLEAF,0x0c000000,0xdf); // VS PTE SPA points at APLIC
    auto allocated=std::make_unique<SHypervisorPlatformGsim>();auto&d=*allocated;
    std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();initialize(d,m);
    Oracle o(1,true);unsigned trapCount=0,clears=0,scalarOps=0,pteOps=0;uint64_t trappedPc=0;
    std::deque<Request> owners[2];unsigned nextOwner[2]{};
    const uint64_t expectedCause=kind==0?7:1,expectedTval=kind==0?VA+8192:VA;
    for(unsigned c=0;c<100000;c++){
        d.set_io$$enable(1);d.set_io$$commitEnable(c%5!=3);d.set_io$$allowRequest(3);d.set_io$$allowResponse(3);d.set_io$$allowMsi(1);d.set_io$$allowMsiResponse(1);d.set_io$$allowDrain(1);d.step();
        for(unsigned lane=0;lane<2;lane++){
            auto q=request(d,lane);auto r=response(d,lane);
            if(r.valid&&((d.get_io$$scalarResponseReady()>>lane)&1)){
                o.check(!owners[lane].empty(),1,"PMA scenario real response owner");auto prior=owners[lane].front();owners[lane].pop_front();o.check(r.owner,prior.owner,"PMA scenario owner identity");o.check(r.clear,prior.clear,"PMA scenario clear identity");o.check(r.error||r.pageFault,0,"issued physical memory remains legal");if(!prior.clear)o.check(r.data,m.get(prior.address&~7ULL,8),"PMA scenario independent physical beat");
            }
            if(q.valid&&((d.get_io$$scalarRequestReady()>>lane)&1)){
                o.check(q.owner,nextOwner[lane]++&15,"PMA scenario owner sequence");
                if(q.clear){clears++;o.check(owners[0].empty()&&owners[1].empty(),1,"clear cannot pass either native owner lane");}
                else{
                    scalarOps++;o.check(lane,1,"faulting VS store must not issue physical data request");o.check(q.write||q.atomic,0,"PMA scenario read-only traffic");o.check((q.address>=BASE&&q.address<BASE+16384)||(q.address>=0x80200000&&q.address<0x80210000),1,"no MMIO or unmapped transaction escapes PMA");if(q.size==3)pteOps++;
                }
                owners[lane].push_back(q);
            }
        }
#define C(N) if(d.get_io$$commit##N##$$valid()){auto pc=d.get_io$$commit##N##$$bits$$pc();auto ins=d.get_io$$commit##N##$$bits$$instruction();o.check(pc,o.pc,"PMA precise retirement PC");o.check(ins,p.code.at(pc),"PMA retired software instruction");unsigned rd=(ins>>7)&31,a=(ins>>15)&31,f=(ins>>12)&7;uint64_t value=0,next=pc+((ins&3)==3?4:2);bool wr=rd!=0;if((ins&3)!=3)value=sext(((ins>>12)&1)<<5|((ins>>2)&31),6);else if((ins&127)==0x13)value=f==0?o.r[a]+sext(ins>>20,12):o.r[a]<<((ins>>20)&63);else if(ins==0x30200073){wr=false;next=VA;o.v=true;}else if((ins&127)==0x73&&f){if(f==2){unsigned csr=ins>>20;value=csr==0x142?expectedCause:csr==0x141?trappedPc:csr==0x143?expectedTval:csr==0x600?0x2000001c0ULL:0;}else{wr=false;}}else if(ins==0x6f){wr=false;next=pc;}else throw std::runtime_error("faulting instruction was incorrectly retired");o.check(d.get_io$$commit##N##$$bits$$writesRd(),wr,"PMA retirement write-enable");o.check(d.get_io$$commit##N##$$bits$$nextPc(),next,"PMA retirement nextPC");if(wr){o.check(d.get_io$$commit##N##$$bits$$rd(),rd,"PMA retirement RD");o.check(d.get_io$$commit##N##$$bits$$data(),value,"PMA trap CSR/data");o.r[rd]=value;}o.pc=next;o.commits++;}
        C(0);C(1);
#undef C
        if(d.get_io$$trap$$valid()){
            o.check(trapCount++,0,"one VS-origin PMA exception");o.check(o.v,1,"fault originates in VS");trappedPc=d.get_io$$trap$$bits$$pc();o.check(trappedPc,kind==0?faultPc:VA,"precise fault EPC");o.check(trappedPc,o.pc,"fault matches next architectural PC");o.check(d.get_io$$trap$$bits$$cause(),expectedCause,"PMA access-fault cause");o.check(d.get_io$$trap$$bits$$tval(),expectedTval,"PMA virtual fault address");o.check(d.get_io$$trap$$bits$$guestFault$$guestAddress(),1,"VS PMA retains guest address provenance");o.check(d.get_io$$trap$$bits$$guestFault$$guestPageFault(),0,"PMA not guest page fault");o.check(d.get_io$$trap$$bits$$guestFault$$guestPhysicalAddress(),0,"PMA guest-fault GPA zero");o.check(d.get_io$$trap$$bits$$guestFault$$implicitPte(),0,"PMA implicit guest-fault flag zero");o.pc=HS;o.v=false;
        }
        o.check(d.get_io$$msiRequest$$valid(),0,"PMA probes never activate APLIC or MSI");
        if(o.r[31]==99&&clears==1&&owners[0].empty()){o.check(trapCount,1,"PMA exception handled");o.check(pteOps>0,1,"real nested page walk occurred");std::cout<<"PLATFORM_PMA_PASS kind="<<kind<<" cycles="<<c+1<<" commits="<<o.commits<<" checks="<<o.checks<<" physicalOps="<<scalarOps<<" pteOps="<<pteOps<<'\n';return;}
    }throw std::runtime_error("PMA exception timeout");
}
int main(){try{for(unsigned i=0;i<3;i++)faultCase(i);std::cout<<"PLATFORM_VS_PMA_EXCEPTIONS_PASS\n";return 0;}catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}}
