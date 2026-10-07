#include "FloatingPointAddStateGsim.h"
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
struct Vector {uint64_t a,b,value;unsigned sub,rm,flags;};
class Driver {
public:
    SFloatingPointAddStateGsim dut;
    unsigned cycles=0,fs=0,frm=0,flags=0,checks=0;uint64_t tag=0x100000000ULL;
    bool inject=false;
    void check(bool good,const char* why) {
        if(!good) throw std::runtime_error(std::string("FP integration mismatch: ")+why+" cycle="+std::to_string(cycles));
    }
    void tick() {
        dut.step();++cycles;
        check(dut.get_io$$fs()==fs&&bool(dut.get_io$$sd())==(fs==3),"FS at retirement");
        check(dut.get_io$$fcsr()==((frm<<5)|flags),"fcsr at retirement");
    }
    void controls() {
        dut.set_io$$headAuthorized(true);dut.set_io$$flush(false);dut.set_io$$issue$$valid(false);
        dut.set_io$$execute$$ready(true);dut.set_io$$result$$valid(false);dut.set_io$$retire$$valid(false);
        dut.set_io$$csr$$valid(false);dut.set_io$$setFs$$valid(false);
    }
    void reset() {controls();dut.set_reset(1);dut.step();dut.step();dut.set_reset(0);tick();}
    void context(unsigned value) {
        dut.set_io$$setFs$$valid(true);dut.set_io$$setFs$$bits(value);tick();
        check(dut.get_io$$setFs$$ready(),"FS write credit");fs=value;controls();tick();
    }
    void csr(unsigned address,unsigned value) {
        dut.set_io$$csr$$valid(true);dut.set_io$$csr$$bits$$address(address);
        dut.set_io$$csr$$bits$$operation(0);dut.set_io$$csr$$bits$$value(value);dut.set_io$$csr$$bits$$write(true);
        tick();check(dut.get_io$$csr$$ready()&&!dut.get_io$$csrIllegal(),"CSR authorization");
        if(address==1) flags=value;else frm=value;
        fs=3;controls();tick();
    }
    uint64_t issue(unsigned instruction,unsigned rd,unsigned rounding,bool write,bool arithmetic) {
        ++tag;dut.set_io$$issue$$valid(true);dut.set_io$$issue$$bits$$token$$index(tag%16);
        dut.set_io$$issue$$bits$$token$$tag(tag);dut.set_io$$issue$$bits$$instruction(instruction);
        dut.set_io$$issue$$bits$$sources_0(arithmetic?0:rd);dut.set_io$$issue$$bits$$sources_1(1);
        dut.set_io$$issue$$bits$$sources_2(2);dut.set_io$$issue$$bits$$checkSingleBox_0(arithmetic);
        dut.set_io$$issue$$bits$$checkSingleBox_1(arithmetic);dut.set_io$$issue$$bits$$checkSingleBox_2(false);
        dut.set_io$$issue$$bits$$integerSource(0);dut.set_io$$issue$$bits$$destination(rd);
        dut.set_io$$issue$$bits$$singleResult(arithmetic);dut.set_io$$issue$$bits$$writesFp(write);
        dut.set_io$$issue$$bits$$writesFlags(arithmetic);dut.set_io$$issue$$bits$$usesRounding(arithmetic);
        dut.set_io$$issue$$bits$$rounding(rounding);tick();check(dut.get_io$$issue$$ready(),"issue accepted");
        controls();return tag;
    }
    void result(uint64_t owner,uint64_t value) {
        dut.set_io$$result$$valid(true);dut.set_io$$result$$bits$$token$$index(owner%16);
        dut.set_io$$result$$bits$$token$$tag(owner);dut.set_io$$result$$bits$$value(value);
        dut.set_io$$result$$bits$$flags(0);dut.set_io$$result$$bits$$exception(false);
        dut.set_io$$result$$bits$$cause(0);dut.set_io$$result$$bits$$tval(0);tick();controls();
    }
    void retire(uint64_t owner,bool write,unsigned accrued=0,bool fault=false) {
        dut.set_io$$retire$$valid(true);dut.set_io$$retire$$bits$$index(owner%16);
        dut.set_io$$retire$$bits$$tag(owner^0x100000000ULL);tick();
        check(!dut.get_io$$retireAccepted(),"stale retirement rejected");
        dut.set_io$$retire$$bits$$tag(owner);dut.set_io$$headAuthorized(false);tick();
        check(!dut.get_io$$retireAccepted(),"head authorization required");
        dut.set_io$$headAuthorized(true);tick();check(dut.get_io$$retireAccepted(),"retire accepted");
        if(!fault) {flags|=accrued;if(write) fs=3;}
        controls();tick();
    }
    // Explicit fixture-only register setup; does not claim FLW/FLD implementation.
    void setup(unsigned rd,uint64_t value,bool write=true) {
        auto owner=issue(0x7b,rd,0,write,false);tick();
        check(dut.get_io$$execute$$valid(),"setup execute");
        if(!write) check(dut.get_io$$execute$$bits$$operands_0()==value,"committed RF value");
        result(owner,value);tick();check(dut.get_io$$complete$$valid(),"setup completion");retire(owner,write);
    }
    void arithmetic(const Vector& v,unsigned i,unsigned cancel=0,bool illegal=false) {
        setup(0,v.a);setup(1,v.b);setup(2,0x123456789abcdef0ULL);
        csr(2,v.rm);context(2);
        const unsigned instruction=(v.sub?0x08000000U:0)|0x53;
        auto owner=issue(instruction,2,illegal?6:(i%2?7:v.rm),true,true);
        if(!illegal) {
            dut.set_io$$execute$$ready(false);tick();tick();
            check(dut.get_io$$execute$$valid(),"held arithmetic issue");
            if(cancel==1) {dut.set_io$$flush(true);tick();controls();tick();setup(2,0x123456789abcdef0ULL,false);return;}
            controls();tick(); // producer accepts
            if(cancel==2) {dut.set_io$$flush(true);tick();controls();tick();setup(2,0x123456789abcdef0ULL,false);return;}
            tick(); // registered normalized raw result reaches the rounding stage
            tick(); // real arithmetic result reaches state
        }
        tick();check(dut.get_io$$complete$$valid(),"arithmetic completion");
        check(dut.get_io$$complete$$bits$$token$$tag()==owner,"completion token");
        check(bool(dut.get_io$$complete$$bits$$exception())==illegal,"legality");
        if(illegal) check(dut.get_io$$complete$$bits$$cause()==2&&
            dut.get_io$$complete$$bits$$tval()==instruction,"illegal metadata");
        else {
            check((dut.get_io$$complete$$bits$$value()^uint64_t(inject&&checks==20))==v.value,"SoftFloat value");
            check(dut.get_io$$complete$$bits$$flags()==v.flags,"SoftFloat flags");
        }
        tick(); // completion held, still no architectural flags/Dirty change
        if(cancel==3) {dut.set_io$$flush(true);tick();controls();tick();setup(2,0x123456789abcdef0ULL,false);return;}
        retire(owner,true,v.flags,illegal);setup(2,illegal?0x123456789abcdef0ULL:v.value,false);++checks;
    }
};
int main(int argc,char** argv) {try {
    if(argc<2) throw std::runtime_error("vector file required");
    std::ifstream input(argv[1]);std::vector<Vector> cases;Vector v;
    while(input>>std::hex>>v.a>>v.b>>v.sub>>v.rm>>v.value>>v.flags) cases.push_back(v);
    if(!input.eof()||cases.size()!=34840) throw std::runtime_error("invalid vector file");
    Driver d;d.inject=argc>2;d.reset();d.context(1);
    for(unsigned i=0;i<500;++i) {
        if(i%23==0) d.csr(1,0);
        d.arithmetic(cases[(i*73)%cases.size()],i);
    }
    for(unsigned phase=1;phase<=3;++phase) d.arithmetic(cases[5000+phase],phase,phase);
    d.arithmetic(cases[31000],0,0,true);
    std::cout<<"FP_ADD_STATE_PASS vectors=500 cycles="<<d.cycles<<" checked="<<d.checks
             <<" flush_phases=3 illegal=1 raw_setup=test_only\n";
    return 0;
} catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}}
