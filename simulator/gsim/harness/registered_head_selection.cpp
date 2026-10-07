#include "RegisteredHeadSelectionGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>

static void check(bool ok, const char* why) {
    if (!ok) throw std::runtime_error(std::string("registered head independent oracle mismatch: ") + why);
}
// Architectural circular order, not the DUT prefix network or head-mask formula.
static int oldest(uint16_t mask, unsigned head) {
    for (unsigned age=0; age<16; ++age) {
        unsigned slot=(head+age)%16;
        if ((mask>>slot)&1) return slot;
    }
    return -1;
}
static uint16_t bit(int index) { return index<0?0:uint16_t(1u<<index); }
int main(int argc, char** argv) { try {
    bool inject=argc==2 && std::string(argv[1])=="--inject-mismatch";
    SRegisteredHeadSelectionGsim d;
    d.set_io$$commits(0); d.set_io$$eligible(0); d.set_io$$issued(0); d.set_io$$issuedIndex(0);
    d.set_io$$mulEligible(0); d.set_io$$divEligible(0);
    d.set_io$$mulAvailable(0); d.set_io$$divAvailable(0);
    d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    unsigned head=0, wraps=0, checks=0; uint16_t heads=0;
    std::mt19937 random(0x632b80f1);
    for (unsigned mask=0; mask<65536; ++mask) {
        unsigned commits=random()%3, issuedIndex=random()%16;
        bool issued=random()&1, ma=random()&1, da=random()&1;
        uint16_t mul=random(), div=uint16_t(random()) & ~mul;
        d.set_io$$commits(commits); d.set_io$$eligible(mask);
        d.set_io$$issued(issued); d.set_io$$issuedIndex(issuedIndex);
        d.set_io$$mulEligible(mul); d.set_io$$divEligible(div);
        d.set_io$$mulAvailable(ma); d.set_io$$divAvailable(da); d.step();
        check(d.get_io$$head()==head,"same-edge head advancement");
        uint16_t boundary=0;
        for (unsigned slot=head; slot<16; ++slot) boundary|=1u<<slot;
        check(d.get_io$$headMask()==boundary,"boundary including wrap and zero commits");
        int first=oldest(mask,head), second=oldest(mask & ~bit(first),head);
        if(inject && mask==1) first=-1;
        check(d.get_io$$first()==bit(first) && d.get_io$$second()==bit(second),"oldest two owners");
        int memory=first;
        if (issued && first==int(issuedIndex)) memory=second;
        check(bool(d.get_io$$memoryValid())==(memory>=0),"late memory exclusion valid");
        if (memory>=0) check(d.get_io$$memoryIndex()==unsigned(memory),"late memory exclusion owner");
        int m=oldest(mul,head), v=oldest(div,head);
        check(d.get_io$$mulOwner()==bit(m) && d.get_io$$divOwner()==bit(v),"independent MUL/DIV owners");
        int grant=oldest((ma?bit(m):0)|(da?bit(v):0),head);
        check(bool(d.get_io$$mulGrant())==(grant>=0 && grant==m),"oldest available multiply");
        check(bool(d.get_io$$divGrant())==(grant>=0 && grant==v),"oldest available divide");
        heads |= 1u<<head; wraps += head+commits>=16; head=(head+commits)%16; ++checks;
    }
    check(heads==65535 && wraps>100,"all head positions and repeated wrap exercised");
    std::cout<<"GSIM registered head selection: PASS masks="<<checks<<" wraps="<<wraps
        <<" II=1 no extra issue cycle, memory late exclusion, split MUL/DIV\n";
    return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; } }
