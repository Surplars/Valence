#include "Aplic.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <random>
#include <stdexcept>
#include <vector>
#ifndef APLIC_SOURCES
#define APLIC_SOURCES 31
#endif
static constexpr unsigned N=APLIC_SOURCES;
static constexpr uint64_t base=0x0c000000, msiBase=0x24000000;
static void check(bool x,const char*s){if(!x)throw std::runtime_error(s);}
struct Request {unsigned offset;uint32_t data;bool write;unsigned size=2,mask=15;};
struct Oracle {
    std::array<unsigned,N+1> mode{},target{};
    std::array<bool,N+1> pending{},enable{},previous{};
    uint64_t lines=0;bool ie=false;
    bool input(unsigned i)const{return mode[i]>=4 && (((lines>>(i-1))&1)^(mode[i]&1));}
    void sample(){for(unsigned i=1;i<=N;++i){bool x=input(i);if(x&&!previous[i])pending[i]=true;if(mode[i]>=6&&!x)pending[i]=false;previous[i]=x;}}
    uint32_t read(unsigned a)const {
        if(!a)return 0x80000004U|(ie?256:0);
        if(a==0x1bc0)return msiBase>>12;if(a==0x1bc4)return 0x80000000;
        if(a>=4&&a<=4*N)return mode[a/4];
        if(a>=0x3004&&a<=0x3000+4*N)return target[(a-0x3000)/4];
        uint32_t r=0;
        for(unsigned i=1;i<=N;++i){unsigned word=4*(i/32);bool b=false;
            if(a==0x1c00+word)b=pending[i];if(a==0x1d00+word)b=input(i);if(a==0x1e00+word)b=enable[i];
            if(b)r|=1U<<(i%32);
        }return r;
    }
    void write(unsigned a,uint32_t v) {
        if(!a){ie=v&256;return;}
        if(a>=4&&a<=4*N){unsigned i=a/4,m=v&7;if((v&1024)||m==2||m==3)m=0;mode[i]=m;
            if(!m){pending[i]=enable[i]=false;target[i]=0;}
            else if(input(i))pending[i]=true;
            if(m>=6&&!input(i))pending[i]=false;previous[i]=input(i);return;}
        if(a>=0x3004&&a<=0x3000+4*N){unsigned i=(a-0x3000)/4;if(mode[i])target[i]=v&127;return;}
        if(a==0x2004)v=__builtin_bswap32(v);
        for(unsigned i=1;i<=N;++i)if(mode[i]) {
            bool set=(a==0x1c00+4*(i/32)&&(v>>(i%32)&1))||((a==0x1cdc||a==0x2000||a==0x2004)&&v==i);
            bool clear=(a==0x1d00+4*(i/32)&&(v>>(i%32)&1))||(a==0x1ddc&&v==i);
            if(clear)pending[i]=false;if(set&&(mode[i]<6||input(i)))pending[i]=true;
            if((a==0x1e00+4*(i/32)&&(v>>(i%32)&1))||(a==0x1edc&&v==i))enable[i]=true;
            if((a==0x1f00+4*(i/32)&&(v>>(i%32)&1))||(a==0x1fdc&&v==i))enable[i]=false;
        }
    }
};
struct Driver {
    SAplic d;Oracle model;std::mt19937_64 rng{761};
    struct Reply{uint64_t data;bool error;};
    struct Ack{unsigned due;bool error;};
    std::deque<Reply> replies;std::deque<Ack> acks;
    std::map<unsigned,unsigned> expected;
    std::vector<unsigned> sent;
    unsigned cycle=0,transactions=0,held=0,consecutive=0,maxConsecutive=0,delay=3;
    bool random=true,block=false,blockResponses=false,holdMmio=false,errorNext=false,failed=false,inject=false;
    bool previousHeld=false;uint64_t heldData=0;
    Driver(){reset();}
    void reset(){
        d.set_io$$sources(0);d.set_io$$mmio$$request$$valid(0);d.set_io$$mmio$$request$$bits$$address(base);
        d.set_io$$mmio$$request$$bits$$data(0);d.set_io$$mmio$$request$$bits$$write(0);
        d.set_io$$mmio$$request$$bits$$size(2);d.set_io$$mmio$$request$$bits$$byteEnable(15);
        d.set_io$$mmio$$response$$ready(0);d.set_io$$msi$$request$$ready(0);
        d.set_io$$msi$$response$$valid(0);d.set_io$$msi$$response$$bits$$data(0);d.set_io$$msi$$response$$bits$$error(0);
        d.set_reset(1);d.step();d.step();d.set_reset(0);
        model=Oracle{};replies.clear();acks.clear();expected.clear();sent.clear();previousHeld=false;failed=false;
    }
    bool tick(const Request* r=nullptr,uint64_t readValue=0,bool readError=false) {
        d.set_io$$sources(model.lines);d.set_io$$mmio$$request$$valid(r!=nullptr);
        if(r){d.set_io$$mmio$$request$$bits$$address(base+r->offset);d.set_io$$mmio$$request$$bits$$data(r->data);
            d.set_io$$mmio$$request$$bits$$write(r->write);d.set_io$$mmio$$request$$bits$$size(r->size);d.set_io$$mmio$$request$$bits$$byteEnable(r->mask);}
        bool responseReady=!holdMmio&&(!random||rng()%4),ready=!block&&(!random||rng()%3);
        bool response=!blockResponses&&!acks.empty()&&acks.front().due<=cycle;
        d.set_io$$mmio$$response$$ready(responseReady);d.set_io$$msi$$request$$ready(ready);
        d.set_io$$msi$$response$$valid(response);d.set_io$$msi$$response$$bits$$error(response&&acks.front().error);
        d.step();
        check(bool(d.get_io$$msiError())==failed,"MSI error status");
        if(d.get_io$$mmio$$response$$valid()) {
            check(!replies.empty(),"unsolicited MMIO response");
            check(d.get_io$$mmio$$response$$bits$$data()==replies.front().data&&bool(d.get_io$$mmio$$response$$bits$$error())==replies.front().error,"MMIO oracle mismatch");
            if(responseReady)replies.pop_front();
        }
        bool accept=r&&d.get_io$$mmio$$request$$ready();
        if(accept){replies.push_back({r->write?0:readValue,readError});++transactions;}
        if(previousHeld)check(d.get_io$$msi$$request$$valid()&&d.get_io$$msi$$request$$bits$$data()==heldData,"MSI changed under backpressure");
        previousHeld=d.get_io$$msi$$request$$valid()&&!ready;heldData=d.get_io$$msi$$request$$bits$$data();
        if(previousHeld)++held;
        if(response&&d.get_io$$msi$$response$$ready()){failed|=acks.front().error;acks.pop_front();}
        if(d.get_io$$msi$$request$$valid()&&ready){
            check(d.get_io$$msi$$request$$bits$$address()==msiBase&&d.get_io$$msi$$request$$bits$$write()&&d.get_io$$msi$$request$$bits$$size()==2&&d.get_io$$msi$$request$$bits$$byteEnable()==15,"MSI format/address");
            unsigned id=d.get_io$$msi$$request$$bits$$data();if(inject){id^=64;inject=false;}
            check(expected[id]>0,"unexpected MSI identity/count");--expected[id];sent.push_back(id);
            acks.push_back({cycle+delay,errorNext});errorNext=false;
            ++consecutive;if(consecutive>maxConsecutive)maxConsecutive=consecutive;
        }else consecutive=0;
        model.sample();++cycle;return accept;
    }
    void idle(unsigned n){while(n--)tick();}
    void access(Request r,bool checkModel=true,uint64_t value=0){
        bool error=r.offset>=16384||(r.offset&3)||r.size!=2||(r.write&&r.mask!=15);
        uint64_t before=checkModel?model.read(r.offset):value;
        unsigned start=cycle;while(!tick(&r,error?0:before,error))check(cycle-start<1000,"MMIO timeout");
        if(!error&&r.write&&checkModel)model.write(r.offset,r.data);
        while(!replies.empty()){tick();check(cycle-start<1000,"MMIO response timeout");}
    }
    void w(unsigned a,uint32_t v){access({a,v,true});}
    void r(unsigned a){access({a,0,false});}
    void drain(){unsigned start=cycle;for(;;){bool done=true;for(auto [id,n]:expected)done&=n==0;
        if(done&&acks.empty()){idle(10);return;}tick();check(cycle-start<4000,"MSI drain timeout");}}
    void expect(unsigned id){++expected[id];}
    void readState(){r(0);for(unsigned i=1;i<=N;++i){r(i*4);r(0x3000+i*4);}for(unsigned g=0;g<=(N/32);++g){r(0x1c00+4*g);r(0x1d00+4*g);r(0x1e00+4*g);}}
};
int main(int argc,char**argv){try{
    Driver t;t.inject=argc>1;
    t.random=false;t.holdMmio=true;Request readDomain{0,0,false};
    check(t.tick(&readDomain,0x80000004),"MMIO first credit");
    check(t.tick(&readDomain,0x80000004),"MMIO second credit");
    check(!t.tick(&readDomain,0x80000004),"MMIO response overflow");
    t.holdMmio=false;t.idle(3);
    for(unsigned i=0;i<256;++i)check(t.tick(&readDomain,0x80000004),"MMIO II=1");
    t.idle(3);t.random=true;t.readState();t.r(0x1bc0);t.r(0x1bc4);
    for(unsigned i=0;i<4000;++i){unsigned id=1+t.rng()%N;unsigned a=0;uint32_t v=t.rng();
        switch(t.rng()%11){case 0:a=4*id;v=t.rng()%8;break;case 1:a=0x3000+4*id;break;
        case 2:a=0x1cdc;v=t.rng()%(N+3);break;case 3:a=0x1ddc;v=t.rng()%(N+3);break;
        case 4:a=0x1edc;v=t.rng()%(N+3);break;case 5:a=0x1fdc;v=t.rng()%(N+3);break;
        case 6:a=0x1c00+4*(id/32);break;case 7:a=0x1d00+4*(id/32);break;
        case 8:a=0x1e00+4*(id/32);break;case 9:a=0x1f00+4*(id/32);break;
        default:t.model.lines=t.rng()&((UINT64_C(1)<<N)-1);t.idle(3);a=0x2004;v=__builtin_bswap32(id);}
        t.w(a,v);t.r(4*id);t.r(0x1c00+4*(id/32));t.r(0x1d00+4*(id/32));t.r(0x1e00+4*(id/32));
    }
    for(auto r:std::vector<Request>{{1,1,true},{4,1,true,1},{4,1,true,2,3},{0x4000,0,false},{0,0,false,3}})t.access(r);
    t.w(4,0x404);t.r(4);t.r(0x3004);t.r(0x1c00);t.r(0x1e00);
    t.reset();t.random=false;t.delay=1;
    for(unsigned i=1;i<=N;++i){t.w(4*i,1);t.w(0x3000+4*i,i);t.w(0x1edc,i);t.w(0x1cdc,i);t.expect(i);}
    t.w(0,256);t.drain();check(t.maxConsecutive>=N-2,"MSI streaming throughput");
    t.reset();t.w(4,1);t.w(0x3004,0xabcdef7f);t.w(0x1edc,1);t.w(0x1cdc,1);t.expect(127);t.w(0,256);t.drain();
    t.w(0x3004,0);t.expect(0);t.w(0x2000,1);t.drain();
    t.w(4*(N+1),4);t.r(4*(N+1));t.w(0x3000+4*(N+1),1);t.r(0x3000+4*(N+1));
    // Both edge polarities and both level polarities, with no repeat while asserted.
    for(unsigned mode:{4U,5U,6U,7U}){
        t.reset();t.random=true;t.model.lines=(mode&1)?1:0;t.idle(3);
        t.w(4,mode);t.w(0x3004,7);t.w(0x1edc,1);t.w(0,256);
        t.expect(7);t.model.lines^=1;t.drain();t.idle(30);
        if(mode>=6){t.expect(7);t.w(0x1cdc,1);t.drain();}
        t.model.lines^=1;t.idle(4);
        if(mode>=6){t.w(0x1cdc,1);t.idle(20);}
        t.expect(7);t.model.lines^=1;t.drain();
    }
    // Level withdrawal before enabling must remove the pending event.
    t.reset();t.w(4,6);t.w(0x3004,5);t.w(0x1edc,1);t.model.lines=1;t.idle(3);t.model.lines=0;t.idle(3);t.w(0,256);t.idle(20);
    // Backpressured MSI captures its identity; a later edge survives behind it.
    t.reset();t.block=true;t.w(4,4);t.w(0x3004,9);t.w(0x1edc,1);t.w(0,256);
    t.expect(9);t.model.lines=1;t.idle(5);t.w(0x3004,10);t.model.lines=0;t.idle(3);
    t.expect(10);t.model.lines=1;t.idle(5);t.block=false;t.drain();
    // genmsi ordering and Busy write suppression even with domain IE disabled.
    t.reset();t.block=true;t.w(4,1);t.w(0x3004,3);t.w(0x1edc,1);t.w(0x1cdc,1);t.expect(3);t.w(0,256);t.idle(4);t.w(0,0);
    t.expect(17);t.access({0x3000,17,true},false);t.access({0x3000,0,false},false,4096|17);
    t.access({0x3000,18,true},false);t.block=false;t.drain();check(t.sent==std::vector<unsigned>({3,17}),"genmsi ordering/busy");t.access({0x3000,0,false},false,17);
    // Four downstream credits, error reporting, and reset with queued output.
    t.reset();t.blockResponses=true;t.random=false;
    for(unsigned i=1;i<=8;++i){t.w(4*i,1);t.w(0x3000+4*i,i);t.w(0x1edc,i);t.w(0x1cdc,i);t.expect(i);}
    t.errorNext=true;t.w(0,256);t.idle(30);check(t.sent.size()==4,"MSI outstanding credit limit");t.blockResponses=false;t.drain();check(t.failed,"MSI error not reported");
    t.reset();t.block=true;t.w(4,1);t.w(0x3004,3);t.w(0x1edc,1);t.w(0x1cdc,1);t.w(0,256);t.idle(8);t.reset();t.block=false;t.readState();t.idle(12);
    std::cout<<"GSIM APLIC: PASS sources="<<N<<" transactions="<<t.transactions<<" held="<<t.held<<" stream="<<t.maxConsecutive<<" random=4000\n";
}catch(const std::exception&e){std::cerr<<"GSIM APLIC: FAIL "<<e.what()<<'\n';return 1;}}
