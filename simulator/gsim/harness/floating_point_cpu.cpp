#include "FloatingPointCpuGsim.h"
#include <array>
#include <cstdint>
#include <deque>
#include <fstream>
#include <iostream>
#include <map>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
static constexpr uint64_t base=0x80000000,handler=base+0x4000;
static void check(bool ok,const std::string& why) {if(!ok)throw std::runtime_error("FP CPU mismatch: "+why);}
static uint64_t sext(uint32_t x) {return uint64_t(int64_t(int32_t(x)));}
static uint64_t box(uint32_t x) {return 0xffffffff00000000ULL|x;}
struct Vector {uint64_t a,b,value;unsigned sub,rm,flags;};
using Key=std::tuple<uint64_t,uint64_t,unsigned,unsigned>;
static std::map<Key,Vector> reference;
static std::vector<Vector> vectors;
#ifdef FP_MEMORY
static Vector memoryBoxingVector;
#endif
static uint32_t csr(unsigned a,unsigned f,unsigned rd,unsigned rs) {return a<<20|rs<<15|f<<12|rd<<7|0x73;}
static uint32_t mvwf(unsigned f,unsigned x) {return 0xf0000053U|x<<15|f<<7;}
static uint32_t mvfx(unsigned x,unsigned f) {return 0xe0000053U|f<<15|x<<7;}
static uint32_t add(unsigned rd,unsigned a,unsigned b,unsigned rm,bool sub=false) {return (sub?0x08000000U:0)|b<<20|a<<15|rm<<12|rd<<7|0x53;}
static void constant(std::vector<uint32_t>& p,unsigned rd,uint32_t value) {
    p.push_back(((value+0x800U)&0xfffff000U)|rd<<7|0x37);
    p.push_back((value&0xfff)<<20|rd<<15|rd<<7|0x1b);
    p.push_back(32U<<20|rd<<15|1U<<12|rd<<7|0x13);
    p.push_back(32U<<20|rd<<15|5U<<12|rd<<7|0x13);
}
#ifdef FP_MEMORY
static constexpr uint64_t ram=0x80010000,accessFaultAddress=0x80012000,pageFaultAddress=0x80012008;
static constexpr uint64_t deniedAddress=0x80011800;
using Bytes=std::map<uint64_t,uint8_t>;
static uint64_t readBytes(const Bytes& b,uint64_t address,unsigned length) {
    uint64_t value=0;for(unsigned n=0;n<length;++n) {
        auto i=b.find(address+n);if(i!=b.end())value|=uint64_t(i->second)<<(8*n);
    }return value;
}
static void writeBytes(Bytes& b,uint64_t address,uint64_t value,unsigned length) {
    for(unsigned n=0;n<length;++n)b[address+n]=value>>(8*n);
}
static Bytes initialMemory() {
    Bytes b;for(unsigned n=0;n<4096;++n)b[ram+n]=uint8_t((n*73)^(n>>3)^0xa5);
    for(unsigned n=0;n<32;++n)writeBytes(b,ram+n*8,
        n%4==0?0x0123456789abcdefULL:n%4==1?0x7ff00000ffc12345ULL:
        n%4==2?0xffffffff7fa12345ULL:0x8000000080000000ULL,8);
    writeBytes(b,ram+0x100,0xffffffff3f800000ULL,8);
    writeBytes(b,ram+0x108,0xffffffff33800000ULL,8);
    writeBytes(b,ram+0x110,memoryBoxingVector.a,8);
    writeBytes(b,ram+0x118,memoryBoxingVector.b,8);
    writeBytes(b,0,0x7654321089abcdefULL,8);return b;
}
static uint32_t fpLoad(unsigned f,unsigned x,int offset,unsigned width) {
    return (uint32_t(offset)&4095)<<20|x<<15|width<<12|f<<7|7;
}
static uint32_t fpStore(unsigned f,unsigned x,int offset,unsigned width) {
    unsigned o=unsigned(offset)&4095;return (o>>5)<<25|f<<20|x<<15|width<<12|(o&31)<<7|0x27;
}
static void memoryProgram(std::vector<uint32_t>& c) {
    constant(c,14,uint32_t(ram));
    // The architectural FS Off gate must stop every memory class before the bus.
    c.push_back(csr(0x300,1,0,0));
    for(unsigned width:{2U,3U}) {c.push_back(fpLoad(0,14,0,width));c.push_back(fpStore(0,14,0,width));}
    for(unsigned state:{1U,2U,3U}) {
        constant(c,15,state<<13);c.push_back(csr(0x300,1,0,15));
        c.push_back(fpStore(0,14,0x400,3));c.push_back(csr(0x300,2,16,0));
        c.push_back(fpLoad(0,14,0,3));c.push_back(csr(0x300,2,16,0));
    }
    // frm=7 and nonzero fflags: transfers ignore rounding and never change flags.
    constant(c,15,0xf1);c.push_back(csr(3,1,0,15));
    for(unsigned f=0;f<32;++f) {
        c.push_back(fpLoad(f,14,int(f*8),3));
        c.push_back(fpStore(f,14,int(0x400+f*8),3));
        c.push_back(fpStore(f,14,int(0x604+f*8),2)); // high beat lanes, even invalid NaN boxing
        c.push_back(fpLoad(f,14,int(f*8+4),2));
        c.push_back(fpStore(f,14,int(0x200+f*8),3));
        c.push_back(mvfx(17,f));
    }
    // Previously acknowledged buffered integer stores must be visible to a FP load.
    constant(c,1,0x7fa54321);
    c.push_back(0x00172023U|(0x700U>>5)<<25|(0x700U&31)<<7); // sw x1,0x700(x14)
    c.push_back(fpLoad(0,14,0x700,2));c.push_back(fpStore(0,14,0x708,3));
    c.push_back(0x70873783U); // ld x15,0x708(x14), younger load must not pass FSD
    constant(c,13,uint32_t(ram+0x800));
    c.push_back(fpLoad(1,13,-2048,3));c.push_back(fpStore(1,14,2040,3));
    c.push_back(0xff800693U);c.push_back(fpLoad(2,13,8,3)); // XLEN wrap: -8 + 8 = 0
    // Arithmetic after a raw invalid-box load must use canonical NaN (not transfer rules).
    c.push_back(csr(2,5,0,0));c.push_back(fpLoad(1,14,0x110,3));c.push_back(fpLoad(2,14,0x118,3));
    c.push_back(add(3,1,2,0));c.push_back(fpStore(3,14,0x780,3));
    c.push_back(fpLoad(1,14,0x100,3));c.push_back(fpLoad(2,14,0x108,3));
    c.push_back(add(3,1,2,0));c.push_back(fpStore(3,14,0x788,3));
    // Misalignment traps dominate access denial and must never issue a request.
    for(unsigned width:{2U,3U})for(unsigned offset:{1U,2U,3U,5U,6U,7U}) {
        c.push_back(fpLoad(0,14,int(offset),width));c.push_back(fpStore(0,14,int(offset),width));
    }
    constant(c,13,uint32_t(accessFaultAddress));
    for(unsigned width:{2U,3U}){c.push_back(fpLoad(0,13,0,width));c.push_back(fpStore(0,13,0,width));}
    // Virtual request metadata comes from real satp/MPRV CSRs. Fault response is
    // injected at the CPU boundary; this is NOT a page-table-walker/Linux test.
    constant(c,15,0x80000000);c.push_back(32U<<20|15U<<15|1U<<12|15U<<7|0x13);
    c.push_back(csr(0x180,1,0,15));constant(c,15,0x24800);c.push_back(csr(0x300,1,0,15));
    c.push_back(fpLoad(0,14,0,3));c.push_back(fpStore(0,14,0x790,3));
    constant(c,13,uint32_t(pageFaultAddress));
    for(unsigned width:{2U,3U}){c.push_back(fpLoad(0,13,0,width));c.push_back(fpStore(0,13,0,width));}
    constant(c,15,0x4000);c.push_back(csr(0x300,1,0,15));c.push_back(csr(0x180,1,0,0));
    // Locked 8-byte NAPOT denial applies even to M-mode, without a bus request.
    constant(c,15,uint32_t(deniedAddress>>2));c.push_back(csr(0x3b0,1,0,15));
    constant(c,15,0x98);c.push_back(csr(0x3a0,1,0,15));constant(c,13,uint32_t(deniedAddress));
    for(unsigned width:{2U,3U}){c.push_back(fpLoad(0,13,0,width));c.push_back(fpStore(0,13,0,width));}
    c.push_back(fpLoad(0,13,1,3));c.push_back(fpStore(0,13,1,3));
}
#endif
struct Program {std::vector<uint32_t> code;uint64_t stop;std::set<uint64_t> wrong;};
static Program program(unsigned count) {
    Program p;auto& c=p.code;
    constant(c,28,uint32_t(handler));c.push_back(csr(0x305,1,0,28));
    // FS=Off: every implemented instruction class and fcsr access must trap.
    c.push_back(mvwf(0,0));c.push_back(mvfx(7,0));c.push_back(add(0,0,0,0));
    c.push_back(add(0,0,0,0,true));c.push_back(csr(3,2,7,0));
    constant(c,27,0x2000);c.push_back(csr(0x100,1,0,27));
    c.push_back(csr(0x300,2,8,0));c.push_back(csr(0x100,2,9,0));
    for(unsigned f=0;f<32;++f) {constant(c,1,f%2?0xffc12345U:0x80000000U);c.push_back(mvwf(f,1));c.push_back(mvfx(10,f));}
    constant(c,27,0x4000);c.push_back(csr(0x300,1,0,27));
    c.push_back(mvfx(0,0));c.push_back(csr(0x300,2,8,0)); // raw read does not dirty
    constant(c,1,0x3f800000);constant(c,2,0x33800000);c.push_back(mvwf(1,1));c.push_back(mvwf(2,2));
    c.push_back(csr(3,5,0,0));c.push_back(add(3,1,2,0));c.push_back(csr(1,2,10,0));
    c.push_back(csr(2,5,0,4));c.push_back(add(4,1,2,7));c.push_back(add(5,4,1,1,true));c.push_back(mvfx(11,5));
    for(unsigned i=0;i<count;++i) {
        auto v=vectors[(i*173+48)%vectors.size()];
        check((v.a>>32)==0xffffffffULL&&(v.b>>32)==0xffffffffULL,"FMV setup requires boxed reference operands");
        const unsigned a=i%32,b=(i+1)%32;
        constant(c,1,uint32_t(v.a));constant(c,2,uint32_t(v.b));
        c.push_back(mvwf(a,1));c.push_back(mvwf(b,2));
        c.push_back(csr(3,5,0,0));c.push_back(csr(2,5,0,v.rm));
        c.push_back(csr(0x100,1,0,27)); // Clean, read back shared aliases after arithmetic
        c.push_back(add(a,a,b,i%2?7:v.rm,v.sub));c.push_back(mvfx(10,a));
        c.push_back(csr(3,2,11,0));c.push_back(csr(0x100,2,12,0));c.push_back(csr(0x300,2,13,0));
    }
    // CSR write/set/clear, zero-source read, reserved high bits, and reserved frm.
    constant(c,1,0xffffffff);c.push_back(csr(3,1,10,1));c.push_back(csr(1,7,11,16));
    c.push_back(csr(1,6,12,16));c.push_back(csr(3,3,13,0));
    for(unsigned rm:{5U,6U}) c.push_back(add(6,1,2,rm));
    for(unsigned frm:{5U,6U,7U}) {c.push_back(csr(2,5,0,frm));c.push_back(add(6,1,2,7));}
    c.push_back(mvfx(10,0));c.push_back(mvwf(0,1)); // moves ignore frm
    c.push_back(mvfx(10,0));c.push_back(csr(3,2,11,0));
    c.push_back(csr(0x100,1,0,0));c.push_back(csr(1,2,7,0));
    constant(c,27,0x2000);c.push_back(csr(0x300,1,0,27));c.push_back(csr(3,2,10,0));
    c.push_back(mvwf(0,0)|(1U<<20));c.push_back(mvfx(0,0)|(2U<<12)); // f3=1 is now legal FCLASS.S
    c.push_back(0x06000053);c.push_back(0x04000053); // unsupported Q / H formats
    c.push_back(csr(2,5,0,0));
#ifdef FP_MEMORY
    memoryProgram(c);
#endif
    // Slow integer dependency creates a speculative wrong path containing FP/CSR work.
    c.push_back(0x020042b3); // div x5,x0,x0 => -1
    c.push_back(0x00528863); // beq x5,x5,+16
#ifdef FP_MEMORY
    for(auto instruction:{fpStore(0,14,0x798,3),fpLoad(0,14,0,3),csr(3,5,0,31)}) {
#else
    for(auto instruction:{mvwf(0,1),csr(3,5,0,31),add(0,0,0,0)}) {
#endif
        p.wrong.insert(base+c.size()*4);c.push_back(instruction);
    }
    c.push_back(mvfx(10,0));c.push_back(csr(3,2,11,0));
    c.push_back(csr(0x301,2,12,0)); // misa F/D remain zero
    for(unsigned f=0;f<32;++f)c.push_back(mvfx(10,f));
    p.stop=base+c.size()*4;
    check(c.size()<0x4000/4,"program fits before trap handler");
    c.resize(0x4000/4,0x13);
    c.push_back(csr(0x342,2,30,0));c.push_back(csr(0x343,2,31,0));
    c.push_back(csr(0x341,2,29,0));c.push_back(4U<<20|29U<<15|29U<<7|0x13);
    c.push_back(csr(0x341,1,0,29));c.push_back(0x30200073);
    return p;
}
struct Model {
    std::array<uint64_t,32> x{},f{};uint64_t pc=base,status=0xa00000000,epc=0,cause=0,tval=0,mtvec=0;
    unsigned fs=0,frm=0,flags=0,arith=0,moves=0,csrOps=0;std::array<unsigned,5> modes{};
#ifdef FP_MEMORY
    Bytes memory=initialMemory();uint64_t satp=0,pmpAddress=0,pmpConfig=0;
    unsigned fpLoads=0,fpStores=0;
    bool virtualized()const {return (status&(1ULL<<17))&&(status>>11&3)!=3&&(satp>>60)!=0;}
    unsigned memoryCause(uint64_t address,unsigned length,bool store)const {
        if(address&(length-1))return store?6:4;
        bool lockedDeny=pmpConfig==0x98&&address<deniedAddress+8&&address+length>deniedAddress;
        if((!virtualized()&&lockedDeny)||address==accessFaultAddress)return store?7:5;
        if(address==pageFaultAddress)return store?15:13;return 0;
    }
#endif
    uint64_t mstatus()const {return status|(uint64_t(fs)<<13)|(uint64_t(fs==3)<<63);}
    uint64_t read(unsigned a)const {
        switch(a) {case 1:return flags;case 2:return frm;case 3:return frm*32+flags;
        case 0x100:return 0x200000000ULL|(mstatus()&0x8000000000006122ULL);
        case 0x300:return mstatus();case 0x301:return 0x8000000000141100ULL;
        case 0x305:return mtvec;case 0x341:return epc;case 0x342:return cause;case 0x343:return tval;
#ifdef FP_MEMORY
        case 0x180:return satp;case 0x3b0:return pmpAddress;case 0x3a0:return pmpConfig;
#endif
        }
        throw std::runtime_error("unknown test CSR");
    }
    struct Result {unsigned rd=0;uint64_t data=0,next=0,tval=0;unsigned cause=2;bool fault=false;};
    Result step(uint32_t inst) {
        Result r;r.next=pc+4;r.tval=inst;unsigned op=inst&127,rd=inst>>7&31,rs1=inst>>15&31,rs2=inst>>20&31;
        unsigned funct=inst>>12&7,funct7=inst>>25;r.rd=rd;
        if(op==0x53) {
            bool to=(inst&0xfff0707f)==0xf0000053,from=(inst&0xfff0707f)==0xe0000053;
            bool arithmetic=(inst&0xfe00007f)==0x53||(inst&0xfe00007f)==0x08000053;
            unsigned rm=funct==7?frm:funct;
            if(!fs||!(to||from||arithmetic)||(arithmetic&&rm>4)) {r.fault=true;return r;}
            if(to) {f[rd]=box(uint32_t(x[rs1]));r.rd=0;fs=3;++moves;}
            else if(from) {r.data=sext(uint32_t(f[rs1]));++moves;}
            else {
                // Reference keys retain raw operands; the independently built
                // SoftFloat adapter, not this CPU model, implements NaN boxing.
                auto found=reference.find({f[rs1],f[rs2],funct7==4,rm});
                check(found!=reference.end(),"reference vector covers current architectural operands");
                f[rd]=found->second.value;flags|=found->second.flags;fs=3;r.rd=0;++arith;++modes[rm];
            }
        }
#ifdef FP_MEMORY
        else if(op==7||op==0x27||op==3||op==0x23) {
            bool fp=op==7||op==0x27,store=op==0x27||op==0x23;
            if(fp&&(!fs||(funct!=2&&funct!=3))){r.fault=true;return r;}
            int64_t offset=store?int64_t(int32_t((inst&0xfe000000)|((inst>>7&31)<<20))>>20):int64_t(int32_t(inst)>>20);
            uint64_t address=x[rs1]+uint64_t(offset);unsigned length=1U<<(funct&3);
            r.tval=address;r.cause=memoryCause(address,length,store);
            if(r.cause){r.fault=true;return r;}
            if(store){writeBytes(memory,address,fp?f[rs2]:x[rs2],length);r.rd=0;if(fp)++fpStores;}
            else if(fp){f[rd]=readBytes(memory,address,length);if(length==4)f[rd]=box(uint32_t(f[rd]));fs=3;r.rd=0;++fpLoads;}
            else {r.data=readBytes(memory,address,length);if(length==4)r.data=sext(uint32_t(r.data));}
        }
#endif
        else if(op==0x73&&funct) {
            unsigned a=inst>>20;bool write=(funct&3)==1||rs1!=0;
            if(a<=3&&!fs){r.fault=true;return r;}
            uint64_t old=read(a),source=funct&4?rs1:x[rs1];r.data=old;++csrOps;
            uint64_t value=(funct&3)==1?source:(funct&3)==2?old|source:old&~source;
            if(write) switch(a) {
            case 1:flags=value&31;fs=3;break;case 2:frm=value&7;fs=3;break;
            case 3:flags=value&31;frm=value>>5&7;fs=3;break;
            case 0x100:fs=value>>13&3;status=(status&~0x122ULL)|(value&0x122);break;
            case 0x300:fs=value>>13&3;status=(status&~0x219aaULL)|(value&0x219aa);break;
#ifdef FP_MEMORY
            case 0x180:satp=value;break;case 0x3b0:pmpAddress=value;break;case 0x3a0:pmpConfig=value;break;
#endif
            case 0x305:mtvec=value&~3ULL;break;case 0x341:epc=value&~3ULL;break;
            default:check(false,"unexpected CSR write");}
        } else if(inst==0x30200073) {
            r.rd=0;r.next=epc;status=(status&~0x1888ULL)|0x80|((status>>4)&8);
        } else if(op==0x37) r.data=sext(inst&0xfffff000U);
        else if(op==0x1b) r.data=sext(uint32_t(x[rs1]+uint64_t(int64_t(int32_t(inst)>>20))));
        else if(op==0x13) {
            unsigned shift=inst>>20&63;
            if(funct==0)r.data=x[rs1]+uint64_t(int64_t(int32_t(inst)>>20));
            else if(funct==1)r.data=x[rs1]<<shift;else if(funct==5)r.data=x[rs1]>>shift;
            else check(false,"unexpected integer instruction");
        } else if(inst==0x020042b3)r.data=~uint64_t(0);
        else if(inst==0x00528863) {r.rd=0;r.next=pc+16;}
        else {r.fault=true;return r;}
        if(r.rd)x[r.rd]=r.data;x[0]=0;pc=r.next;return r;
    }
    void trap(const Result& r) {
        epc=pc;cause=r.cause;tval=r.tval;status=(status&~0x1888ULL)|0x1800|((status&8)<<4);pc=mtvec;
    }
};
static void run(const Program& p,unsigned seed,bool inject,bool injectFp=false,bool injectBus=false) {
    SFloatingPointCpuGsim d;Model m;std::mt19937 random(seed);
    d.set_io$$instruction0$$valid(false);d.set_io$$instruction1$$valid(false);
    d.set_io$$commitEnable(false);d.set_io$$inspectRegister(0);d.set_reset(1);d.step();d.step();d.set_reset(0);
#ifdef FP_MEMORY
    struct Pending {uint64_t data;bool error,page;unsigned delay;};
    std::deque<Pending> pending;Bytes busMemory=initialMemory();
    bool fpOwner=false;uint32_t fpInstruction=0;uint64_t fpPc=0,fpAddress=0,fpData=0;
    unsigned fpRequests=0,busRequests=0,busResponses=0,requestStalls=0,responseStalls=0,inspectFp=0;
    bool heldRequest=false;std::tuple<uint64_t,uint64_t,unsigned,unsigned,bool,bool> savedRequest;
    std::map<unsigned,unsigned> faultCounts;
    d.set_io$$memory$$request$$ready(false);d.set_io$$memory$$response$$valid(false);
    d.set_io$$memory$$response$$bits$$data(0);d.set_io$$memory$$response$$bits$$error(false);
    d.set_io$$memory$$response$$bits$$pageFault(false);d.set_io$$inspectFpRegister(0);
#endif
    uint64_t fetch=base;unsigned commits=0,traps=0,redirects=0,held=0,hold=0,wrongOffers=0,fpRetires=0,heldComplete=0;
    unsigned frozenFs=0,frozenFcsr=0;bool done=false;
    for(unsigned cycle=0;cycle<80000;++cycle) {
        bool allow=!hold&&(seed==0||random()%5!=0),supply=seed==0||random()%7!=0;
#ifdef FP_MEMORY
        supply=supply&&!d.get_io$$pauseFetch();
        bool requestReady=pending.size()<8&&(seed==0||random()%4!=0);
        bool responseValid=!pending.empty()&&pending.front().delay==0;
        d.set_io$$memory$$request$$ready(requestReady);
        d.set_io$$memory$$response$$valid(responseValid);
        d.set_io$$memory$$response$$bits$$data(responseValid?pending.front().data:0);
        d.set_io$$memory$$response$$bits$$error(responseValid&&pending.front().error);
        d.set_io$$memory$$response$$bits$$pageFault(responseValid&&pending.front().page);
        d.set_io$$inspectFpRegister(inspectFp);
#endif
        d.set_io$$commitEnable(allow);d.set_io$$inspectRegister(cycle%32);
        for(unsigned lane=0;lane<2;++lane) {
            uint64_t pc=fetch+4*lane;bool valid=supply&&pc>=base&&(pc-base)/4<p.code.size()&&pc!=p.stop;
            uint32_t inst=valid?p.code[(pc-base)/4]:0;
            if(lane==0){d.set_io$$instruction0$$valid(valid);d.set_io$$instruction0$$bits(inst);}
            else {d.set_io$$instruction1$$valid(valid);d.set_io$$instruction1$$bits(inst);}
            if(!valid)supply=false;
        }
        d.step();check(d.get_io$$fetchPc()==fetch,"fetch device cursor");
        check(d.get_io$$committedValue()==m.x[cycle%32],"integer architectural RF");
#ifdef FP_MEMORY
        uint64_t expectedFp=m.f[inspectFp];
        if(injectFp&&m.fpLoads){expectedFp^=1;injectFp=false;}
        check(d.get_io$$committedFpValue()==expectedFp,"FP architectural RF");
        inspectFp=(cycle+1)%32;
#endif
        if(hold) {
            check(!allow&&d.get_io$$fpFs()==frozenFs&&d.get_io$$fpFcsr()==frozenFcsr,"FP state changed before ROB retirement");
#ifdef FP_MEMORY
            bool writesFp=(fpInstruction&127)==7||((fpInstruction&127)==0x53&&
                (fpInstruction&0xfff0707f)!=0xe0000053);
            if(writesFp)inspectFp=fpInstruction>>7&31;
#endif
            heldComplete+=d.get_io$$fpComplete();--hold;++held;
        }
        if(d.get_io$$fpStart()) {
            check(d.get_io$$fpStartPc()==m.pc&&!p.wrong.count(m.pc),"FP execution must own architectural head");
            hold=7;frozenFs=d.get_io$$fpFs();frozenFcsr=d.get_io$$fpFcsr();
#ifdef FP_MEMORY
            fpInstruction=p.code[(m.pc-base)/4];fpOwner=(fpInstruction&127)==7||(fpInstruction&127)==0x27;
            fpPc=m.pc;fpRequests=0;
            inspectFp=fpInstruction>>7&31;
            bool store=(fpInstruction&127)==0x27;
            int64_t offset=store?int64_t(int32_t((fpInstruction&0xfe000000)|((fpInstruction>>7&31)<<20))>>20):int64_t(int32_t(fpInstruction)>>20);
            fpAddress=m.x[fpInstruction>>15&31]+uint64_t(offset);fpData=m.f[fpInstruction>>20&31];
#endif
        }
#ifdef FP_MEMORY
        if(d.get_io$$memory$$request$$valid()) {
            uint64_t address=d.get_io$$memory$$request$$bits$$address();
            uint64_t data=d.get_io$$memory$$request$$bits$$data();
            unsigned size=d.get_io$$memory$$request$$bits$$size(),mask=d.get_io$$memory$$request$$bits$$mask();
            bool write=d.get_io$$memory$$request$$bits$$write(),virt=d.get_io$$memory$$request$$bits$$virtualized();
            auto request=std::make_tuple(address,data,size,mask,write,virt);
            if(heldRequest)check(request==savedRequest,"stalled memory request changed");
            heldRequest=!requestReady;savedRequest=request;requestStalls+=!requestReady;
            check(!d.get_io$$memory$$request$$bits$$atomic()&&!d.get_io$$memory$$request$$bits$$uncached(),"ordinary memory metadata");
            if(fpOwner) {
                bool store=(fpInstruction&127)==0x27;unsigned length=1U<<(fpInstruction>>12&3);
                unsigned expectedMask=((1U<<length)-1)<<(fpAddress&7);
                if(injectBus&&store){expectedMask^=1;injectBus=false;}
                check(m.pc==fpPc&&address==fpAddress&&write==store&&size==(fpInstruction>>12&3)&&
                    mask==expectedMask&&virt==m.virtualized()&&
                    (!store||data==(fpData<<((fpAddress&7)*8))),"FP memory request payload");
                check(m.fs!=0&&(address&(length-1))==0,"illegal or misaligned FP reached memory");
            }
            if(requestReady) {
                bool error=address==accessFaultAddress,page=address==pageFaultAddress;
                if(fpOwner){check(fpRequests++==0,"duplicate FP memory request");}
                check(size<=3&&(address&((1U<<size)-1))==0,"memory natural alignment");
                uint64_t beat=readBytes(busMemory,address&~7ULL,8);
                if(write&&!error&&!page)for(unsigned n=0;n<8;++n)if(mask>>n&1)
                    busMemory[(address&~7ULL)+n]=data>>(8*n);
                pending.push_back({beat,error,page,seed==0?2U:unsigned(random()%11)});++busRequests;
            }
        } else {check(!heldRequest,"stalled irrevocable request withdrawn");}
        if(responseValid&&d.get_io$$memory$$response$$ready()){pending.pop_front();++busResponses;}
        responseStalls+=!pending.empty()&&pending.front().delay!=0;
        if(!pending.empty()&&pending.front().delay)--pending.front().delay;
#endif
        for(unsigned lane=0;lane<2;++lane)if(lane?d.get_io$$accepted1():d.get_io$$accepted0())wrongOffers+=p.wrong.count(fetch+lane*4);
        uint64_t nextFetch=fetch+4*(d.get_io$$accepted0()+d.get_io$$accepted1());
        unsigned retiredFp=0;
        auto commit=[&](bool valid,uint64_t pc,uint32_t inst,unsigned rd,bool writes,uint64_t value,uint64_t next) {
            if(!valid)return;check(allow&&pc==m.pc,"ordered commit PC at "+std::to_string(pc));
            check(pc>=base&&(pc-base)/4<p.code.size()&&p.code[(pc-base)/4]==inst,"committed instruction");
            auto r=m.step(inst);check(!r.fault,"faulting instruction retired");
            if(inject&&(inst&0xfff0707f)==0xe0000053) {r.data^=1;inject=false;}
            check(rd==r.rd&&writes==(rd!=0)&&next==r.next&&(rd==0||value==r.data),"commit value/metadata pc="+std::to_string(pc));
            retiredFp+=(inst&127)==0x53;
#ifdef FP_MEMORY
            if((inst&127)==7||(inst&127)==0x27) {
                check(fpOwner&&fpPc==pc&&fpRequests==1,"one FP request before retirement");
                fpOwner=false;++retiredFp;
            }
            if((inst&127)==7||((inst&127)==0x53&&(inst&0xfff0707f)!=0xe0000053))inspectFp=inst>>7&31;
#endif
            ++commits;
        };
#define C(n) commit(d.get_io$$commit##n##$$valid(),d.get_io$$commit##n##$$bits$$pc(),d.get_io$$commit##n##$$bits$$instruction(),d.get_io$$commit##n##$$bits$$rd(),d.get_io$$commit##n##$$bits$$writesRd(),d.get_io$$commit##n##$$bits$$data(),d.get_io$$commit##n##$$bits$$nextPc())
        C(0);C(1);
#undef C
        check(bool(d.get_io$$fpRetire())==(retiredFp!=0),"FP state retirement tied to real ROB commit");fpRetires+=retiredFp;
        if(d.get_io$$trap$$valid()) {
            check(allow&&!d.get_io$$commit0$$valid()&&!d.get_io$$commit1$$valid(),"precise trap boundary");
            uint32_t inst=p.code[(m.pc-base)/4];auto copy=m;auto r=copy.step(inst);
            check(r.fault&&d.get_io$$trap$$bits$$pc()==m.pc&&d.get_io$$trap$$bits$$cause()==r.cause&&d.get_io$$trap$$bits$$tval()==r.tval,"trap metadata");
#ifdef FP_MEMORY
            ++faultCounts[r.cause];
            if((inst&127)==7||(inst&127)==0x27) {
                bool needsBus=r.cause!=2&&r.cause!=4&&r.cause!=6&&r.tval!=deniedAddress;
                check(fpOwner&&fpPc==m.pc&&fpRequests==unsigned(needsBus),"faulting FP bus ownership");fpOwner=false;
            }
#endif
            m.trap(r);++traps;check(d.get_io$$redirect$$valid()&&d.get_io$$redirect$$bits$$target()==m.pc,"trap redirect");
        }
        if(d.get_io$$redirect$$valid()){nextFetch=d.get_io$$redirect$$bits$$target();++redirects;}
        fetch=nextFetch;
        if(m.pc==p.stop) {done=true;break;}
    }
    check(done&&traps==
#ifdef FP_MEMORY
        57
#else
        15
#endif
        &&wrongOffers>0&&heldComplete>0&&m.arith>10&&fpRetires>100,"coverage/progress; traps="+std::to_string(traps));
    for(auto n:m.modes)check(n>0,"all five rounding modes");
#ifdef FP_MEMORY
    check(pending.empty()&&busRequests==busResponses&&busMemory==m.memory,"memory side effects and response credits");
    check(m.fpLoads>64&&m.fpStores>96&&responseStalls>0&&(seed==0||requestStalls>0),"memory coverage");
    for(unsigned cause:{2U,4U,5U,6U,7U,13U,15U})check(faultCounts[cause]>0,"all FP fault classes");
    d.set_io$$instruction0$$valid(false);d.set_io$$instruction1$$valid(false);d.set_io$$commitEnable(false);
    d.set_io$$memory$$response$$valid(false);
    for(unsigned f=0;f<32;++f){d.set_io$$inspectFpRegister(f);d.step();check(d.get_io$$committedFpValue()==m.f[f],"final FP architectural RF");}
    std::cout<<"FP_MEMORY_PASS seed="<<seed<<" loads="<<m.fpLoads<<" stores="<<m.fpStores
        <<" requests="<<busRequests<<" responses="<<busResponses<<" request_stalls="<<requestStalls
        <<" response_delay_cycles="<<responseStalls<<"\n";
#endif
    std::cout<<"FP_CPU_PASS seed="<<seed<<" commits="<<commits<<" traps="<<traps<<" arithmetic="<<m.arith
        <<" moves="<<m.moves<<" fp_retires="<<fpRetires<<" held_cycles="<<held<<" held_complete="<<heldComplete
        <<" wrong_path_accepted="<<wrongOffers<<" redirects="<<redirects<<"\n";
}
int main(int argc,char** argv) {try {
    check(argc>=2,"vector path required");std::ifstream input(argv[1]);Vector v;
    while(input>>std::hex>>v.a>>v.b>>v.sub>>v.rm>>v.value>>v.flags) {
        reference[{v.a,v.b,v.sub,v.rm}]=v;
        if((v.a>>32)==0xffffffffULL&&(v.b>>32)==0xffffffffULL)vectors.push_back(v);
    }
    check(input.eof()&&reference.size()>10000,"reference loaded");
#ifdef FP_MEMORY
    bool selected=false;for(const auto& [key,answer]:reference) {
        if((answer.a>>32)!=0xffffffffULL&&(answer.b>>32)==0xffffffffULL&&!answer.sub&&!answer.rm) {
            memoryBoxingVector=answer;selected=true;break;
        }
    }
    check(selected,"independent malformed-box memory vector available");
#endif
    std::string negative=argc>2?argv[2]:"";
    auto p=program(120);for(unsigned seed:{0U,17U})run(p,seed,negative=="--inject-mismatch",
        negative=="--inject-fp-memory",negative=="--inject-memory-request");
    return 0;
} catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}}
