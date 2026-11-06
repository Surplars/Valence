#define CACHE_BYTES 32768
#define CACHE_METADATA 1
static bool classInject=false;
#define main originalDataCacheMain
#include "five_stage_cache.cpp"
#undef main
int main(int argc,char **) {try {
    classInject=argc>1;
    Test t;
    // Exercise every prefix, all parcel positions, cached and uncached returns.
    for(unsigned i=0;i<t.memory.size();i+=2) t.memory[i]=(t.memory[i]&0xe0)|((i/2)&31);
    auto read=[&](uint64_t a) {auto got=t.transact(a);need(!got[1]&&got[0]==t.load(a),"independent packed cache byte-memory oracle");};
    read(BASE+16);auto requests=t.requests;read(BASE+16);
    need(t.requests==requests,"packed IF repeated read missed");
    for(unsigned offset=0;offset<CACHE_BYTES;offset+=8) read(BASE+offset);
    requests=t.requests;
    for(unsigned offset=CACHE_BYTES;offset;offset-=8) read(BASE+offset-8);
    need(t.requests==requests,"packed IF bank/word sweep lost an installed line");
    t.responseReady=true;t.d.set_io$$response$$ready(1);
    unsigned sent=0,received=0,cycles=0;
    for(;cycles<40&&received<16;++cycles) {
        uint64_t a=BASE+sent*64;
        t.d.set_io$$request$$valid(sent<16);t.d.set_io$$request$$bits$$address(a);
        t.d.set_io$$request$$bits$$write(0);t.step();
        if(sent<16&&t.d.get_io$$request$$ready())++sent;
        if(t.d.get_io$$response$$valid()) {
            need(received<sent&&t.d.get_io$$response$$bits$$data()==t.load(BASE+received*64),
                "independent packed IF streamed owner/data oracle");++received;
        }
    }
    need(sent==16&&received==16&&cycles==17,"packed IF added a hit cycle or throughput bubble");
    t.d.set_io$$request$$valid(0);t.responseReady=false;t.d.set_io$$response$$ready(0);
    t.invalidate();t.errorBeat=3;
    auto failed=t.transact(BASE+16);need(failed[1],"packed refill error lost");t.errorBeat=999;
    requests=t.requests;read(BASE+16);need(t.requests==requests+1,"failed packed refill installed a line");
    t.invalidate();t.invalidateFill=true;read(BASE+16);t.invalidateFill=false;
    requests=t.requests;read(BASE+16);need(t.requests==requests+1,"invalidated packed fill resurrected");
    read(0x10000000);read(BASE+CACHE_BYTES);read(BASE);
    std::mt19937_64 random(0x17429);
    for(unsigned i=0;i<1000;++i) {read(BASE+(random()%(CACHE_BYTES/8))*8);if(i%97==0)t.invalidate();}
    need(t.unownedChanges>100,"unowned packed IF input coverage missing");
    std::cout<<"I1_PACKED_FETCH_PASS bytes="<<CACHE_BYTES<<" class_prefixes=32 lanes=4 flow_cycles="<<cycles
             <<" requests="<<t.requests<<" backpressure_error_invalidation_bypass=PASS\n";
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
