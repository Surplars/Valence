#include "EthernetTxQueueEventGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void check(bool value,const char *why){if(!value)throw std::runtime_error(why);}
struct Test {
    SEthernetTxQueueEventGsim d;
    Test(){S(offset,240);S(data,0);S(accessWrite,0);S(write,0);S(acceptedWrite,0);S(engineIdle,1);S(engineDone,0);S(engineFailed,0);S(engineBytes,0);d.set_reset(1);d.step();d.step();d.set_reset(0);d.step();}
    void tick(){d.step();}
    void access(unsigned offset,uint64_t data){S(offset,offset);S(data,data);S(accessWrite,1);S(write,0);S(acceptedWrite,0);tick();check(G(allowed),"queue MMIO unexpectedly illegal");S(write,1);S(acceptedWrite,1);tick();S(write,0);S(acceptedWrite,0);S(accessWrite,0);tick();}
    uint64_t read(unsigned offset){S(offset,offset);S(accessWrite,0);S(write,0);S(acceptedWrite,0);tick();check(G(allowed),"queue read unexpectedly illegal");return G(readData);}
    // No setup/idle tick: successive calls are accepted on adjacent clocks.
    void writeNow(unsigned offset,uint64_t data){S(offset,offset);S(data,data);S(accessWrite,1);S(write,1);S(acceptedWrite,1);tick();}
    void stage(uint64_t address,unsigned length){access(224,address);access(232,length);}
};
static void consecutiveStagePost() {
    constexpr uint64_t end=0x100200000ULL;
    unsigned cases=0;
    for(bool addressLast:{false,true})for(unsigned length:{1U,7U,8U,9U,2047U,2048U}) {
        Test t;t.access(240,1);t.S(engineIdle,0);
        uint64_t address=end-((uint64_t(length)+7)&~7ULL);
        // Poison the old field so a stale registered proof/count cannot pass.
        if(addressLast){t.access(232,length);t.access(224,~7ULL);t.writeNow(224,address);}
        else {t.access(224,address);t.access(232,~0ULL);t.writeNow(232,length);}
        t.writeNow(240,4);t.S(write,0);t.S(acceptedWrite,0);t.S(accessWrite,0);
        check((t.read(248)&255)==1,"consecutive staging/POST lost accepted owner");
        t.S(engineIdle,1);t.S(engineBytes,length);t.tick();
        t.S(engineDone,1);t.tick();t.S(engineDone,0);t.tick();
        check(t.read(224)==address&&t.read(232)==length,"consecutive staging/POST stale descriptor");
        t.access(240,8);t.access(240,2);++cases;
    }
    for(uint64_t length:{0ULL,2049ULL,1ULL<<63,~0ULL}) {
        Test t;t.access(240,1);t.S(engineIdle,0);t.access(224,end-8);t.access(232,8);
        t.writeNow(232,length);t.S(offset,240);t.S(data,4);t.S(write,0);t.S(acceptedWrite,0);t.tick();
        check(!t.G(allowed),"consecutive invalid length/POST reused legal proof");
        check((t.read(248)&255)==0,"invalid consecutive POST acquired owner");++cases;
    }
    // A legal length still fails when its rounded read would exceed the aperture.
    Test t;t.access(240,1);t.S(engineIdle,0);t.access(224,end-8);t.access(232,8);
    t.writeNow(232,9);t.S(offset,240);t.S(data,4);t.S(write,0);t.S(acceptedWrite,0);t.tick();
    check(!t.G(allowed),"consecutive rounded endpoint/POST reused old word count");
    std::cout<<"ETHERNET_TX_QUEUE_CONSECUTIVE_PASS cases="<<cases+1<<'\n';
}
static void stopAcceptance() {
    // A presented but unaccepted STOP must not steal a launch. Conversely an
    // accepted illegal command is an error response, not a STOP or descriptor.
    for (unsigned command : {16U, 17U}) {
        Test t;t.access(240,1);t.S(engineIdle,0);t.stage(0x100001000ULL,64);t.access(240,4);
        t.S(offset,240);t.S(data,command);t.S(accessWrite,1);t.S(write,0);
        t.S(acceptedWrite,command==17);t.S(engineIdle,1);t.tick();
        t.S(acceptedWrite,0);t.S(accessWrite,0);
        auto status=t.read(248);
        check((status&255)==0&&((status>>16)&1)&&!((status>>17)&1),
              "unaccepted STOP or illegal command cancelled a pending launch");
    }
    Test disabled;disabled.S(offset,240);disabled.S(data,16);disabled.S(accessWrite,1);
    disabled.S(write,0);disabled.S(acceptedWrite,1);disabled.tick();
    disabled.S(acceptedWrite,0);disabled.S(accessWrite,0);
    check(disabled.read(248)==0,"disabled queue accepted illegal STOP");
    std::cout<<"ETHERNET_TX_STOP_ACCEPTANCE_PASS unaccepted_stop=1 illegal_command=1 disabled_stop=1\n";
}
int main(int argc,char**){try{
    consecutiveStagePost();
    stopAcceptance();
    Test t;t.access(240,1);t.S(engineIdle,0);t.stage(0x100001000ULL,64);t.access(240,4);
    t.stage(0x100002000ULL,65);
    // Accept a second POST exactly when the first pending owner launches.
    t.S(offset,240);t.S(data,4);t.S(accessWrite,1);t.S(write,1);t.S(acceptedWrite,1);t.S(engineIdle,1);t.tick();
    t.S(write,0);t.S(acceptedWrite,0);t.S(accessWrite,0);t.S(engineIdle,0);t.tick();
    check(t.d.get_postLaunchCount()==1,"missing simultaneous POST/launch witness");
    t.S(engineDone,1);t.S(engineBytes,64);t.tick();t.S(engineDone,0);t.tick();
    check(t.read(224)==(argc>1?0x100001008ULL:0x100001000ULL)&&t.read(232)==64,"queue independent owner/result mismatch");
    // Launch the second while retaining the first completion.
    t.S(engineIdle,1);t.tick();t.S(engineIdle,0);t.tick();
    // Consume first completion exactly as second frame finishes.
    t.S(offset,240);t.S(data,8);t.S(accessWrite,1);t.S(write,1);t.S(acceptedWrite,1);t.S(engineDone,1);t.S(engineBytes,65);t.tick();
    t.S(write,0);t.S(acceptedWrite,0);t.S(accessWrite,0);t.S(engineDone,0);t.tick();
    check(t.d.get_completePopCount()==1,"missing simultaneous completion/POP witness");
    check(t.read(224)==0x100002000ULL&&t.read(232)==65&&((t.read(248)>>8)&255)==1,"queue concurrent FIFO result mismatch");
    t.access(240,8);t.S(engineIdle,1);t.access(240,2);
    // STOP beats a potential launch in the same cycle and publishes cancellation.
    t.access(240,1);t.S(engineIdle,0);t.stage(0x100001000ULL,64);t.access(240,4);
    t.S(offset,240);t.S(data,16);t.S(accessWrite,1);t.S(write,1);t.S(acceptedWrite,1);t.S(engineIdle,1);t.tick();
    t.S(write,0);t.S(acceptedWrite,0);t.S(accessWrite,0);t.tick();
    check(t.d.get_postLaunchCount()==1&&t.read(232)==65536&&((t.read(248)>>17)&1),"STOP lost to pending launch");
    t.access(240,8);t.access(240,2);
    std::cout<<"ETHERNET_TX_QUEUE_EVENTS_PASS post_launch=1 completion_pop=1 stop_before_launch=1 high_address=1\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
