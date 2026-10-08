#include "EthernetTxQueueEventGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void check(bool value,const char *why){if(!value)throw std::runtime_error(why);}
struct Test {
    SEthernetTxQueueEventGsim d;
    Test(){S(offset,240);S(data,0);S(accessWrite,0);S(write,0);S(engineIdle,1);S(engineDone,0);S(engineFailed,0);S(engineBytes,0);d.set_reset(1);d.step();d.step();d.set_reset(0);d.step();}
    void tick(){d.step();}
    void access(unsigned offset,uint64_t data){S(offset,offset);S(data,data);S(accessWrite,1);S(write,0);tick();check(G(allowed),"queue MMIO unexpectedly illegal");S(write,1);tick();S(write,0);S(accessWrite,0);tick();}
    uint64_t read(unsigned offset){S(offset,offset);S(accessWrite,0);S(write,0);tick();check(G(allowed),"queue read unexpectedly illegal");return G(readData);}
    void stage(uint64_t address,unsigned length){access(224,address);access(232,length);}
};
int main(int argc,char**){try{
    Test t;t.access(240,1);t.S(engineIdle,0);t.stage(0x100001000ULL,64);t.access(240,4);
    t.stage(0x100002000ULL,65);
    // Accept a second POST exactly when the first pending owner launches.
    t.S(offset,240);t.S(data,4);t.S(accessWrite,1);t.S(write,1);t.S(engineIdle,1);t.tick();
    t.S(write,0);t.S(accessWrite,0);t.S(engineIdle,0);t.tick();
    check(t.d.get_postLaunchCount()==1,"missing simultaneous POST/launch witness");
    t.S(engineDone,1);t.S(engineBytes,64);t.tick();t.S(engineDone,0);t.tick();
    check(t.read(224)==(argc>1?0x100001008ULL:0x100001000ULL)&&t.read(232)==64,"queue independent owner/result mismatch");
    // Launch the second while retaining the first completion.
    t.S(engineIdle,1);t.tick();t.S(engineIdle,0);t.tick();
    // Consume first completion exactly as second frame finishes.
    t.S(offset,240);t.S(data,8);t.S(accessWrite,1);t.S(write,1);t.S(engineDone,1);t.S(engineBytes,65);t.tick();
    t.S(write,0);t.S(accessWrite,0);t.S(engineDone,0);t.tick();
    check(t.d.get_completePopCount()==1,"missing simultaneous completion/POP witness");
    check(t.read(224)==0x100002000ULL&&t.read(232)==65&&((t.read(248)>>8)&255)==1,"queue concurrent FIFO result mismatch");
    t.access(240,8);t.S(engineIdle,1);t.access(240,2);
    // STOP beats a potential launch in the same cycle and publishes cancellation.
    t.access(240,1);t.S(engineIdle,0);t.stage(0x100001000ULL,64);t.access(240,4);
    t.S(offset,240);t.S(data,16);t.S(accessWrite,1);t.S(write,1);t.S(engineIdle,1);t.tick();
    t.S(write,0);t.S(accessWrite,0);t.tick();
    check(t.d.get_postLaunchCount()==1&&t.read(232)==65536&&((t.read(248)>>17)&1),"STOP lost to pending launch");
    t.access(240,8);t.access(240,2);
    std::cout<<"ETHERNET_TX_QUEUE_EVENTS_PASS post_launch=1 completion_pop=1 stop_before_launch=1 high_address=1\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
