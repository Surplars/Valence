#include "FloatingPointStateGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

struct Token { unsigned index=0; uint64_t tag=0; bool operator==(const Token&) const = default; };
struct Command {
    Token token{}; uint32_t instruction=0x02000053;
    std::array<unsigned,3> source{}; std::array<bool,3> boxed{};
    uint64_t integer=0; unsigned destination=0, rm=0;
    bool single=false, writes=true, flags=true, rounding=true;
};
struct Result { Token token{}; uint64_t value=0,tval=0; unsigned flags=0,cause=0; bool fault=false; };
struct Input {
    bool head=true, flush=false, issue=false, executeReady=true, result=false, retire=false;
    bool fsWrite=false, csr=false, csrWrite=false;
    unsigned fs=0, csrAddress=3, csrOperation=0; uint64_t csrValue=0;
    Command command{}; Result response{}; Token retireToken{};
};

class Oracle {
public:
    SFloatingPointStateGsim dut;
    std::array<uint64_t,32> regs{};
    unsigned fs=0,frm=0,flags=0,state=0;
    Command pending{}; Result response{}; std::array<uint64_t,3> operands{}; unsigned rm=0;
    unsigned cycles=0,issued=0,committed=0,stale=0,blocked=0,faults=0,boxed=0;
    std::array<unsigned,4> cancelled{};
    bool inject=false;
    void check(bool ok,const char* why) {
        if(!ok) throw std::runtime_error(std::string("FP oracle mismatch: ")+why+" at cycle "+std::to_string(cycles));
    }
    void drive(const Input& x) {
        dut.set_io$$headAuthorized(x.head); dut.set_io$$flush(x.flush);
        dut.set_io$$issue$$valid(x.issue);
        dut.set_io$$issue$$bits$$token$$index(x.command.token.index);
        dut.set_io$$issue$$bits$$token$$tag(x.command.token.tag);
        dut.set_io$$issue$$bits$$instruction(x.command.instruction);
#define SRC(n) dut.set_io$$issue$$bits$$sources_##n(x.command.source[n]); \
        dut.set_io$$issue$$bits$$checkSingleBox_##n(x.command.boxed[n])
        SRC(0); SRC(1); SRC(2);
#undef SRC
        dut.set_io$$issue$$bits$$integerSource(x.command.integer);
        dut.set_io$$issue$$bits$$destination(x.command.destination);
        dut.set_io$$issue$$bits$$singleResult(x.command.single);
        dut.set_io$$issue$$bits$$writesFp(x.command.writes);
        dut.set_io$$issue$$bits$$writesFlags(x.command.flags);
        dut.set_io$$issue$$bits$$usesRounding(x.command.rounding);
        dut.set_io$$issue$$bits$$rounding(x.command.rm);
        dut.set_io$$execute$$ready(x.executeReady);
        dut.set_io$$result$$valid(x.result);
        dut.set_io$$result$$bits$$token$$index(x.response.token.index);
        dut.set_io$$result$$bits$$token$$tag(x.response.token.tag);
        dut.set_io$$result$$bits$$value(x.response.value);
        dut.set_io$$result$$bits$$flags(x.response.flags);
        dut.set_io$$result$$bits$$exception(x.response.fault);
        dut.set_io$$result$$bits$$cause(x.response.cause);
        dut.set_io$$result$$bits$$tval(x.response.tval);
        dut.set_io$$retire$$valid(x.retire);
        dut.set_io$$retire$$bits$$index(x.retireToken.index);
        dut.set_io$$retire$$bits$$tag(x.retireToken.tag);
        dut.set_io$$setFs$$valid(x.fsWrite); dut.set_io$$setFs$$bits(x.fs);
        dut.set_io$$csr$$valid(x.csr); dut.set_io$$csr$$bits$$address(x.csrAddress);
        dut.set_io$$csr$$bits$$operation(x.csrOperation); dut.set_io$$csr$$bits$$write(x.csrWrite);
        dut.set_io$$csr$$bits$$value(x.csrValue);
    }
    void reset() {
        drive({}); dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        regs.fill(0); fs=frm=flags=state=0;
    }
    void tick(const Input& x={}) {
        drive(x); dut.step();
        const bool idle=state==0 && x.head && !x.flush;
        const bool fsReady=idle, csrReady=idle&&!x.fsWrite, issueReady=csrReady&&!x.csr;
        const bool executing=state==1&&!x.flush, complete=state==3&&!x.flush;
        const bool retire=complete&&x.retire&&x.head&&x.retireToken==pending.token;
        const uint64_t csrRead=x.csrAddress==1?flags:x.csrAddress==2?frm:x.csrAddress==3?((frm<<5)|flags):0;
        const bool csrIllegal=fs==0 || x.csrAddress<1 || x.csrAddress>3 || x.csrOperation==3;
        check(dut.get_io$$fs()==fs && bool(dut.get_io$$sd())==(fs==3),"FS/SD commit state");
        check((dut.get_io$$fcsr() ^ unsigned(inject&&cycles==100))==((frm<<5)|flags),"fcsr commit state");
        check(dut.get_io$$csrRead()==csrRead && bool(dut.get_io$$csrIllegal())==csrIllegal,"CSR read/legality");
        check(bool(dut.get_io$$setFs$$ready())==fsReady && bool(dut.get_io$$csr$$ready())==csrReady,"serialized context credit");
        check(bool(dut.get_io$$issue$$ready())==issueReady && bool(dut.get_io$$busy())==(state!=0),"issue/occupancy");
        check(bool(dut.get_io$$execute$$valid())==executing && bool(dut.get_io$$complete$$valid())==complete,"latency/cancellation");
        check(dut.get_io$$result$$ready() && bool(dut.get_io$$retireAccepted())==retire,"result drain/retirement token");
        if(executing) {
            check(dut.get_io$$execute$$bits$$command$$token$$index()==pending.token.index &&
                  dut.get_io$$execute$$bits$$command$$token$$tag()==pending.token.tag,"execution owner");
            check(dut.get_io$$execute$$bits$$rounding()==rm,"dynamic rounding snapshot");
            check(dut.get_io$$execute$$bits$$command$$integerSource()==pending.integer &&
                  dut.get_io$$execute$$bits$$command$$instruction()==pending.instruction,"request payload hold");
#define OPERAND(n) check(dut.get_io$$execute$$bits$$operands_##n()==operands[n],"RF/boxing operand")
            OPERAND(0); OPERAND(1); OPERAND(2);
#undef OPERAND
        }
        if(complete) {
            check(dut.get_io$$complete$$bits$$token$$index()==response.token.index &&
                  dut.get_io$$complete$$bits$$token$$tag()==response.token.tag,"completion owner");
            check(dut.get_io$$complete$$bits$$value()==response.value &&
                  dut.get_io$$complete$$bits$$flags()==response.flags,"held result/flags");
            check(bool(dut.get_io$$complete$$bits$$exception())==response.fault &&
                  dut.get_io$$complete$$bits$$cause()==response.cause &&
                  dut.get_io$$complete$$bits$$tval()==response.tval,"precise fault metadata");
        }
        const unsigned oldState=state;
        if(x.fsWrite&&fsReady) fs=x.fs;
        if(x.csr&&csrReady&&x.csrWrite&&!csrIllegal) {
            const uint64_t value=x.csrOperation==0?x.csrValue:x.csrOperation==1?(csrRead|x.csrValue):(csrRead&~x.csrValue);
            if(x.csrAddress==1) flags=value&31;
            if(x.csrAddress==2) frm=value&7;
            if(x.csrAddress==3) { flags=value&31;frm=(value>>5)&7; }
            fs=3;
        }
        if((x.csr||x.fsWrite)&&!idle) ++blocked;
        if(x.issue&&issueReady) {
            pending=x.command; rm=pending.rm==7?frm:pending.rm;
            for(unsigned j=0;j<3;++j) {
                operands[j]=regs[pending.source[j]];
                if(pending.boxed[j] && (operands[j]>>32)!=0xffffffffULL) {
                    operands[j]=0xffffffff7fc00000ULL;++boxed;
                }
            }
            const bool illegal=fs==0 || (pending.rounding && rm>4);
            response={};response.token=pending.token;response.fault=illegal;
            if(illegal) {response.cause=2;response.tval=pending.instruction;++faults;}
            state=illegal?3:1;++issued;
        }
        if(executing&&x.executeReady) state=2;
        if(x.result) {
            if(oldState==2&&!x.flush&&x.response.token==pending.token) {response=x.response;state=3;}
            else ++stale;
        }
        if(retire) {
            if(!response.fault) {
                if(pending.writes) regs[pending.destination]=pending.single?(0xffffffff00000000ULL|uint32_t(response.value)):response.value;
                if(pending.flags) flags|=response.flags;
                if(pending.writes||pending.flags) fs=3;
            }
            state=0;++committed;
        }
        if(x.flush) {++cancelled[oldState];state=0;}
        ++cycles;
    }
    void context(unsigned value) { Input x; x.fsWrite=true;x.fs=value;tick(x);tick(); }
    void csr(unsigned address,uint64_t value,unsigned operation=0,bool write=true) {
        Input x;x.csr=true;x.csrWrite=write;x.csrAddress=address;x.csrValue=value;x.csrOperation=operation;tick(x);tick();
    }
    void transaction(Command c,uint64_t value,unsigned resultFlags=0,bool fault=false,unsigned cancelPhase=0) {
        Input x;x.issue=true;x.command=c;tick(x);
        if(state==1) {
            x={};x.executeReady=false;tick(x);tick(x); // held payload under backpressure
            if(cancelPhase==1) {x.flush=true;tick(x);tick();return;}
            x={};tick(x);
            x={};x.result=true;x.response.token={c.token.index,c.token.tag^0x100000000ULL};
            x.response.flags=31;tick(x); // same ROB slot, stale generation
            x={};x.csr=true;x.csrWrite=true;x.csrAddress=2;x.csrValue=4;tick(x);
            x={};x.fsWrite=true;x.fs=0;tick(x);
            if(cancelPhase==2) {x={};x.flush=true;tick(x);x={};x.result=true;x.response.token=c.token;x.response.flags=31;tick(x);return;}
            x={};x.result=true;x.response={c.token,value,0x80000ffc, resultFlags, fault?13U:0U,fault};tick(x);
        }
        x={};x.retire=true;x.retireToken={c.token.index,c.token.tag^1};tick(x);
        if(cancelPhase==3) {x.flush=true;x.retireToken=c.token;tick(x);tick();return;}
        x={};x.retire=true;x.retireToken=c.token;x.head=false;tick(x);
        x.head=true;tick(x);tick();
    }
};

int main(int argc,char** argv) {try {
    Oracle m;m.inject=argc>1&&std::string_view(argv[1])=="--inject-mismatch";m.reset();
    std::mt19937_64 random(0xf1e64001);uint64_t tag=1;
    auto command=[&](unsigned rd) {Command c;c.token={unsigned(tag%16),tag++};c.destination=rd;
        c.source={rd,(rd+1)%32,(rd+31)%32};c.integer=random();return c;};
    m.csr(3,255); // FS=Off: CSR write must trap without state modification
    m.transaction(command(0),123,31); // FS=Off: no execution request
    for(unsigned i=0;i<32;++i) {m.context(2);m.transaction(command(i),random(),i%32);}
    // Bit-preserving S transfers include +/-0, infinities, sNaN/qNaN and subnormals.
    const std::array<uint32_t,8> bits={0,0x80000000,0x7f800000,0xff800000,0x7f800001,0x7fc12345,1,0x007fffff};
    for(unsigned i=0;i<32;++i) {auto c=command(i);c.single=true;c.boxed={true,true,false};m.transaction(c,bits[i%8]);}
    // Raw moves/stores must not canonicalize; computational S operands must.
    for(unsigned i=0;i<32;++i) {auto c=command(i);c.writes=false;c.flags=false;c.rounding=false;
        c.boxed={false,true,true};c.rm=7;m.transaction(c,0);}
    for(unsigned f=0;f<8;++f) for(unsigned r=0;r<8;++r) {
        m.context(2);m.csr(2,f);auto c=command(r);c.rm=r;m.transaction(c,random(),7);
    }
    m.context(2);m.csr(3,~uint64_t(0));m.csr(1,0);m.csr(2,0);
    m.csr(1,17,1);m.csr(1,16,2);m.csr(2,4,1);m.csr(3,255,0,false);m.csr(0x300,255);m.csr(3,255,3);
    for(unsigned i=0;i<300;++i) {
        if(i%17==0) {m.context(2);m.csr(2,i%5);}
        auto c=command(i%32);c.single=i%2;c.boxed={bool(i%2),bool(i%3),bool(i%5)};
        c.rm=i%3==0?7:i%5;c.writes=i%7!=0;c.flags=i%11!=0;
        m.transaction(c,random(),random()%32,i%13==0,i%9==0?1+(i/9)%3:0);
    }
    m.context(0);m.context(1); // context FS changes do not silently erase registers/FCSR
    for(unsigned i=0;i<32;++i) {auto c=command(i);c.rounding=false;c.writes=false;c.flags=false;m.transaction(c,0);}
    // Existing matrix: 16 static reserved rm + 3 reserved dynamic frm + 1 FS=Off.
    // Pin this count before extending coverage: the former >20 assertion was wrong.
    m.check(m.faults==20,"original illegal matrix must contain exactly 20 cases");
    // Even non-rounding/raw operations trap with FS=Off, for every instruction rm.
    m.context(0);
    for(unsigned r=0;r<8;++r) {auto c=command(0);c.rm=r;c.rounding=false;m.transaction(c,~uint64_t(0),31);}
    m.context(1);
    // Reserved rm/frm do not trap when the decoded operation ignores rounding.
    for(unsigned f=5;f<8;++f) for(unsigned r=5;r<8;++r) {
        m.csr(2,f);auto c=command(r);c.rm=r;c.rounding=false;c.writes=false;c.flags=false;m.transaction(c,0);
    }
    m.check(m.faults==28,"FS=Off and rounding-independent legality coverage");
    m.csr(2,0);
    // Flush concurrently with a matching response; neither payload nor flags survive.
    auto killed=command(0);Input x;x.issue=true;x.command=killed;m.tick(x);m.tick();
    x={};x.flush=true;x.result=true;x.response={killed.token,~uint64_t(0),0,31,0,false};m.tick(x);m.tick();
    auto read=command(0);read.writes=false;read.flags=false;read.rounding=false;m.transaction(read,0);
    // Flush and denied head authorization block all competing state changes.
    x={};x.flush=true;x.issue=true;x.command=command(1);x.fsWrite=true;x.fs=0;
    x.csr=true;x.csrWrite=true;x.csrValue=255;m.tick(x);
    x.flush=false;x.head=false;m.tick(x);m.tick();
    // Earliest possible next issue overlaps the delayed physical commit write.
    // Each address is exercised as all three simultaneous sources, raw and boxed.
    // A following younger flush must preserve the already accepted older write.
    for(unsigned rd=0;rd<32;++rd) for(unsigned youngerFlush=0;youngerFlush<2;++youngerFlush) {
        auto write=command(rd);write.rounding=false;write.single=rd%2;write.flags=false;
        x={};x.issue=true;x.command=write;m.tick(x);m.tick();
        const uint64_t data=random();
        x={};x.result=true;x.response={write.token,data,0,0,0,false};m.tick(x);
        x={};x.retire=true;x.retireToken=write.token;m.tick(x);
        if(youngerFlush) {x={};x.flush=true;m.tick(x);}
        auto next=command(rd);next.source={rd,rd,rd};next.boxed={false,true,false};
        next.rounding=false;next.writes=false;next.flags=false;
        m.transaction(next,0);
    }
    // Reset at every transaction boundary, including after committed nonzero state.
    // A real integration must reset/drain the producer too; generations are not reused.
    for(unsigned phase=0;phase<4;++phase) {
        m.context(2);m.transaction(command(0),~uint64_t(0),31);
        auto old=command(31);
        if(phase) {x={};x.issue=true;x.command=old;m.tick(x);}
        if(phase>=2) m.tick();
        if(phase==3) {x={};x.result=true;x.response={old.token,123,0,31,0,false};m.tick(x);}
        m.check(m.state==phase,"reset boundary exercised");m.reset();m.tick();
        x={};x.result=true;x.response={old.token,~uint64_t(0),0,31,0,false};m.tick(x);m.tick();
        m.context(1);
        for(unsigned i=0;i<32;++i) {auto c=command(i);c.rounding=false;c.writes=false;c.flags=false;m.transaction(c,0);}
    }
    m.check(m.issued>450&&m.committed>400&&m.stale>400&&m.blocked>600&&m.boxed>50,"coverage");
    m.check(m.cancelled[1]>5&&m.cancelled[2]>5&&m.cancelled[3]>5&&m.faults==28,"fault/flush coverage");
    std::cout<<"FP_STATE_PASS cycles="<<m.cycles<<" issued="<<m.issued<<" retired="<<m.committed
             <<" stale="<<m.stale<<" blocked_context="<<m.blocked<<" box_canonicalized="<<m.boxed
             <<" illegal="<<m.faults<<" flush_send="<<m.cancelled[1]<<" flush_wait="<<m.cancelled[2]
             <<" flush_done="<<m.cancelled[3]<<" reset_boundaries=4 simultaneous_response_flush=1 immediate_forwarding=32x3 older_commit_younger_flush=32\n";
    return 0;
} catch(const std::exception& e) {std::cerr<<e.what()<<"\n";return 1;}}
