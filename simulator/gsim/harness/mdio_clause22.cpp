#include "MdioClause22.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>
#include <vector>

static void check(bool ok,const char *why) { if(!ok) throw std::runtime_error(why); }
struct Command { unsigned phy,reg; bool write; uint16_t data,rx; bool noAck; };
static std::vector<bool> wireBits(const Command &c) {
    std::vector<bool> bits(32,true);
    auto append=[&](unsigned value,unsigned width) {
        for(unsigned n=width;n>0;--n) bits.push_back((value>>(n-1))&1);
    };
    append(1,2); append(c.write?1:2,2); append(c.phy,5); append(c.reg,5);
    append(2,2); append(c.data,16); return bits;
}
int main(int argc,char **argv) { try {
    const bool inject=argc==2 && std::string_view(argv[1])=="--inject-mismatch";
    SMdioClause22 d;
    d.set_io$$command$$valid(0); d.set_io$$response$$ready(0); d.set_io$$mdioIn(1);
    d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    unsigned reads=0,writes=0,noacks=0,resetCases=0;
    std::mt19937_64 random(0x20261004d10ULL);
    for(unsigned test=0;test<96;++test) {
        Command c{unsigned(random()%32),unsigned(random()%32),bool(test%3==0),
            uint16_t(random()),uint16_t(random()),bool(test%7==0)};
        const auto expected=wireBits(c);
        bool accepted=false,complete=false,prevMdc=false;
        unsigned rises=0,falls=0,lastEdge=0;
        uint16_t sampled=0;
        bool heldReply=false; uint16_t heldData=0; bool heldNoAck=false;
        for(unsigned cycle=0;cycle<1200 && !complete;++cycle) {
            const bool ready=cycle>900 && cycle%3!=1;
            // PHY changes its next bit during MDC low; reference cursor is based on edges.
            unsigned index=falls;
            bool in=true;
            if(!c.write && index==47) in=c.noAck;
            if(!c.write && index>=48 && index<64) in=(c.rx>>(63-index))&1;
            d.set_io$$mdioIn(in);
            d.set_io$$command$$valid(!accepted);
            d.set_io$$command$$bits$$phy(c.phy); d.set_io$$command$$bits$$register(c.reg);
            d.set_io$$command$$bits$$write(c.write); d.set_io$$command$$bits$$data(c.data);
            d.set_io$$response$$ready(ready); d.step();
            if(!accepted && d.get_io$$command$$ready()) accepted=true;
            bool mdc=d.get_io$$mdc();
            if(mdc!=prevMdc) {
                check(cycle-lastEdge==4 || (rises==0 && falls==0),"MDIO clock divider/edge spacing mismatch");
                lastEdge=cycle;
                if(mdc) {
                    unsigned bit=rises++;
                    check(bit<64,"MDIO excess clock edges");
                    bool oe=c.write || bit<46;
                    check(bool(d.get_io$$mdioOe())==oe,"MDIO turnaround drive ownership mismatch");
                    if(oe) check(bool(d.get_io$$mdioOut())==(expected.at(bit)^(inject && test==0 && bit==36)),
                        "MDIO independent wire oracle mismatch");
                    if(!c.write && bit>=48) sampled=uint16_t((sampled<<1)|in);
                } else ++falls;
            }
            prevMdc=mdc;
            if(d.get_io$$response$$valid()) {
                uint16_t value=d.get_io$$response$$bits$$data(); bool error=d.get_io$$response$$bits$$noAck();
                check(rises==64 && falls==64 && !mdc && !d.get_io$$mdioOe(),"MDIO frame did not release bus");
                check(value==(c.write?c.data:c.rx) && error==(!c.write && c.noAck) &&
                    (c.write || sampled==c.rx),"MDIO read response/TA acknowledgement mismatch");
                if(heldReply) check(value==heldData && error==heldNoAck,"MDIO response changed under backpressure");
                heldReply=true; heldData=value; heldNoAck=error;
                check(!d.get_io$$command$$ready(),"MDIO command accepted before reply consumption");
                complete=ready;
            }
        }
        check(accepted && complete,"MDIO transaction timed out");
        if(c.write)++writes; else {++reads;noacks+=c.noAck;}
        d.set_io$$command$$valid(0);d.set_io$$response$$ready(1);d.step();d.step();
    }
    // Cancel at preamble/op/address/turnaround/data, including MDC-high epochs.
    for(unsigned position: {1U,17U,130U,260U,370U,390U,430U,500U}) {
        d.set_io$$command$$valid(1); d.set_io$$command$$bits$$write(0);
        d.set_io$$response$$ready(0); d.step();d.set_io$$command$$valid(0);
        for(unsigned n=0;n<position;++n)d.step();
        d.set_reset(1);d.step();d.step();d.set_reset(0);d.step();
        check(!d.get_io$$busy() && !d.get_io$$mdc() && !d.get_io$$mdioOe() &&
            !d.get_io$$response$$valid() && d.get_io$$command$$ready(),"MDIO reset failed to cancel transaction");
        ++resetCases;
    }
    std::cout<<"MDIO_CLAUSE22_PASS transactions=96 reads="<<reads<<" writes="<<writes
        <<" noack="<<noacks<<" reset_cases="<<resetCases<<" divider=4\n";return 0;
} catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;} }
