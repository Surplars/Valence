#include "I1FetchQueue.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <random>
#include <stdexcept>
struct Packet {
    uint64_t pc,prediction;
    uint32_t instruction;
    unsigned flags;
    bool operator==(const Packet&) const = default;
};
static void need(bool value,const char *message){if(!value)throw std::runtime_error(message);}
int main(int argc,char**) {try {
    SI1FetchQueue d;std::mt19937_64 random(0x4946435245444954ULL);std::deque<Packet> expected;
    d.set_reset(1);d.set_io$$input$$valid(0);d.set_io$$output$$ready(0);d.set_io$$cancelInput(0);d.set_io$$flush(0);
    d.step();d.step();d.set_reset(0);
    Packet held{};bool holding=false;
    unsigned full=0,simultaneous=0,cancelled=0,flushes=0,retired=0,continuous=0;
    for(unsigned cycle=0;cycle<30000;++cycle){
        const bool first=cycle<2000;
        bool valid=first||holding||random()%5!=0;
        const bool ready=first||(cycle<2500?false:random()%3!=0);
        const bool cancel=!first&&random()%19==0,flush=!first&&random()%83==0;
        if(!holding)held={random(),random(),uint32_t(random()),unsigned(random()%16)};
        d.set_io$$input$$valid(valid);d.set_io$$output$$ready(ready);d.set_io$$cancelInput(cancel);d.set_io$$flush(flush);
        d.set_io$$input$$bits$$pc(held.pc);d.set_io$$input$$bits$$predictedNextPc(held.prediction);
        d.set_io$$input$$bits$$instruction(held.instruction);d.set_io$$input$$bits$$fetchError(held.flags&1);
        d.set_io$$input$$bits$$fetchPageFault((held.flags>>1)&1);d.set_io$$input$$bits$$compressed((held.flags>>2)&1);
        d.set_io$$input$$bits$$fetchSecondHalfFault((held.flags>>3)&1);d.step();
        need(bool(d.get_io$$input$$ready())==(expected.size()<2),"IF queue registered credit mismatch");
        need(bool(d.get_io$$output$$valid())==!expected.empty(),"IF queue owner-valid mismatch");
        if(!expected.empty()){
            Packet actual{d.get_io$$output$$bits$$pc(),d.get_io$$output$$bits$$predictedNextPc(),
                uint32_t(d.get_io$$output$$bits$$instruction()),unsigned(d.get_io$$output$$bits$$fetchError())|
                unsigned(d.get_io$$output$$bits$$fetchPageFault())<<1|unsigned(d.get_io$$output$$bits$$compressed())<<2|
                unsigned(d.get_io$$output$$bits$$fetchSecondHalfFault())<<3};
            Packet gold=expected.front();if(argc>1)gold.pc^=4;
            need(actual==gold,"independent IF queue packet oracle mismatch");
        }
        const bool push=valid&&expected.size()<2,pop=ready&&!expected.empty();
        full+=expected.size()==2;simultaneous+=push&&pop;cancelled+=push&&cancel;
        if(pop){expected.pop_front();++retired;if(first)++continuous;}
        if(push&&!cancel)expected.push_back(held);
        if(flush){expected.clear();++flushes;}
        holding=valid&&!push;
    }
    d.set_reset(1);d.set_io$$input$$valid(0);d.step();d.step();d.set_reset(0);d.step();
    need(!d.get_io$$output$$valid(),"IF queue warm reset leaked a packet");
    need(continuous==1999&&full>1000&&simultaneous>1000&&cancelled>100&&flushes>100,
        "IF queue supply/full/cancel/flush coverage missing");
    std::cout<<"I1_FETCH_QUEUE_PASS cycles=30000 capacity=2 continuous_retired="<<continuous
        <<" full="<<full<<" simultaneous="<<simultaneous<<" cancelled="<<cancelled<<" flushes="<<flushes
        <<" held_payload_no_loss_duplicate_reorder_warm_reset=PASS\n";
    return 0;
}catch(const std::exception &error){std::cerr<<error.what()<<'\n';return 1;}}
