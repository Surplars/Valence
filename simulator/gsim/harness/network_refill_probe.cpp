#define main existing_cache_suite_main
#include "coherent_cache_ways.cpp"
#undef main
int main() { try {
    unsigned cases=0;
    for(unsigned phase=0;phase<3;++phase) {
        Test t;
        t.forceReady=true; t.blockCpuResponse=true;
        t.access(base,true,0x0123456789abcdefULL,255,false);
        // Observe a public E handshake. Home may now probe, but the acquire
        // engine's reply still has to install its new tag and synchronous data.
        for(unsigned n=0;;++n) {
            check(n<512,"GrantAck timeout"); t.tick();
            if(t.dut.get_io$$tl$$e$$valid() && (t.cycles-1)%3!=0) break;
        }
        t.probing=true; t.probeAddress=base;
        t.tick();
        check(!t.probeAccepted,"probe raced a not-yet-installed refill");
        t.blockCpuResponse=phase!=0; t.blockC=phase==1;
        t.tick();
        check(t.probeAccepted,"probe blocked by completed refill CPU response");
        if(phase==0) check(t.expected.empty(),"B/refill CPU reply simultaneous handshake lost");
        if(phase==1) {
            for(unsigned n=0;n<12;++n) {
                t.tick(); check(t.dut.get_io$$upstream$$response$$valid() &&
                              t.dut.get_io$$upstream$$response$$bits$$data()==0,
                              "stalled miss reply withdrew/changed during probe");
            }
            t.blockCpuResponse=false; t.tick();
            check(t.expected.empty(),"miss reply blocked by stalled probe C");
            t.blockC=false;
        }
        for(unsigned n=0;!t.probeDone;++n) {
            check(n<128,"refill probe timeout"); t.tick();
        }
        if(phase==2) {
            check(t.expected.size()==1,"held miss response lost");
            t.blockCpuResponse=false; t.tick();
            check(t.expected.empty(),"probe did not restore held miss reply");
        }
        t.probing=false; t.tick();
        t.access(base); check(t.architectural.at(base)==0x0123456789abcdefULL,"refill dirty data lost");
        ++cases;
    }
    std::cout<<"NETWORK_REFILL_PROBE_PASS cases="<<cases<<" installation_barrier=1 stable_miss_reply=1\n";
    return 0;
} catch(const std::exception& e) { std::cerr<<"NETWORK_REFILL_PROBE_FAIL "<<e.what()<<"\n"; return 1; } }
