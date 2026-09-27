#include "Imsic.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

static void check(bool ok, const char *what) { if (!ok) throw std::runtime_error(what); }
constexpr unsigned count = IMSIC_IDENTITIES, files = 2 + IMSIC_GUESTS;
constexpr uint64_t machineBase = 0x24000000, supervisorBase = 0x28000000;
static unsigned pages() { unsigned n=1; while(n<1+IMSIC_GUESTS)n*=2; return n; }
struct Csr { unsigned file=0, selector=0x70, op=0; uint64_t data=0; bool topei=false; };
struct Bus { uint64_t address=machineBase, data=0; unsigned size=2, mask=15; bool write=true; };
struct Reply { uint64_t data=0; bool error=false; bool operator==(const Reply&) const = default; };
struct File {
    std::vector<bool> pending=std::vector<bool>(count+1), enabled=std::vector<bool>(count+1);
    bool delivery=false;
    unsigned threshold=0;
    unsigned top() const {
        for(unsigned id=1;id<=count;++id)
            if(pending[id]&&enabled[id]&&(!threshold||id<threshold))return id;
        return 0;
    }
};
// Independent state-machine oracle: per-identity Boolean arrays and ascending linear search.
struct Model {
    std::vector<File> state=std::vector<File>(files);
    Reply csr(Csr r) {
        if(r.file>=files||(!r.topei&&(r.selector<0x70||r.selector>0xff||(r.selector>=0x80&&(r.selector&1)))))
            return {0,true};
        auto &f=state[r.file]; uint64_t old=0;
        if(r.topei) {unsigned top=f.top();old=uint64_t(top)*0x10001; if(r.op&&top)f.pending[top]=false;return {old,false};}
        const bool bitmap=r.selector>=0x80;
        const unsigned start=(r.selector%64)*32;
        if(r.selector==0x70)old=f.delivery;
        if(r.selector==0x72)old=f.threshold;
        if(bitmap)for(unsigned b=0;b<64;++b) {
            unsigned id=start+b;
            if(id&&id<=count&&(r.selector<0xc0?f.pending[id]:f.enabled[id]))old|=UINT64_C(1)<<b;
        }
        uint64_t value=r.op==1?r.data:r.op==2?old|r.data:r.op==3?old&~r.data:old;
        if(r.op) {
            if(r.selector==0x70)f.delivery=value%2;
            if(r.selector==0x72&&value<=count)f.threshold=value;
            if(bitmap)for(unsigned b=0;b<64;++b) {
                unsigned id=start+b;
                if(id&&id<=count)(r.selector<0xc0?f.pending[id]:f.enabled[id])=bool((value>>b)&1);
            }
        }
        return {old,false};
    }
    Reply bus(Bus r) {
        bool machine=r.address>=machineBase&&r.address<machineBase+4096;
        bool supervisor=r.address>=supervisorBase&&r.address<supervisorBase+4096*pages();
        bool error=(!machine&&!supervisor)||r.size!=2||r.address%4||(r.write&&r.mask!=15);
        if(error)return {0,true};
        unsigned file=machine?0:1+(r.address-supervisorBase)/4096;
        if(!r.write||file>=files||(r.address%4096!=0&&r.address%4096!=4))return {};
        uint32_t id=r.data;
        if(r.address%4096==4) {
            id=0;for(unsigned i=0;i<4;++i)id|=uint32_t(uint8_t(r.data>>(i*8)))<<((3-i)*8);
        }
        if(id&&id<=count)state[file].pending[id]=true;
        return {};
    }
    uint64_t interrupts() const {
        uint64_t result=0;for(unsigned f=0;f<files;++f)if(state[f].delivery&&state[f].top())result|=UINT64_C(1)<<f;
        return result;
    }
};
static Bus msi(unsigned file,unsigned id,bool big=false) {
    uint64_t value=id;
    if(big) {value=0;for(unsigned i=0;i<4;++i)value|=uint64_t(uint8_t(id>>(i*8)))<<((3-i)*8);}
    return {(file?supervisorBase+4096*(file-1):machineBase)+(big?4:0),value,2,15,true};
}
struct Bench {
    SImsic dut;
    Model model;
    std::deque<Reply> csrQueue, busQueue;
    unsigned csrAccepted=0,busAccepted=0,csrHeld=0,busHeld=0,simultaneous=0,errors=0;
    bool inject=false;
    explicit Bench(bool negative=false):inject(negative) {
        drive({}, {}, true, true);dut.set_reset(1);dut.step();dut.step();dut.set_reset(0);
    }
    void drive(std::optional<Csr> c,std::optional<Bus> b,bool cr,bool br) {
        Csr r=c.value_or(Csr{}); Bus m=b.value_or(Bus{});
        dut.set_io$$csrRequest$$valid(c.has_value());dut.set_io$$csrRequest$$bits$$file(r.file);
        dut.set_io$$csrRequest$$bits$$selector(r.selector);dut.set_io$$csrRequest$$bits$$operation(r.op);
        dut.set_io$$csrRequest$$bits$$data(r.data);dut.set_io$$csrRequest$$bits$$topei(r.topei);
        dut.set_io$$csrResponse$$ready(cr);dut.set_io$$mmio$$response$$ready(br);
        dut.set_io$$mmio$$request$$valid(b.has_value());dut.set_io$$mmio$$request$$bits$$address(m.address);
        dut.set_io$$mmio$$request$$bits$$write(m.write);dut.set_io$$mmio$$request$$bits$$size(m.size);
        dut.set_io$$mmio$$request$$bits$$data(m.data);dut.set_io$$mmio$$request$$bits$$byteEnable(m.mask);
    }
    std::pair<bool,bool> tick(std::optional<Csr> c={},std::optional<Bus> b={},bool cr=true,bool br=true) {
        drive(c,b,cr,br);dut.step();
        check(dut.get_io$$interrupts()==model.interrupts(),"interrupt level/isolation mismatch");
        const bool cReady=csrQueue.size()<2,bReady=busQueue.size()<2;
        check(bool(dut.get_io$$csrRequest$$ready())==cReady,"CSR response credit ready");
        check(bool(dut.get_io$$mmio$$request$$ready())==bReady,"MMIO response credit ready");
        check(bool(dut.get_io$$csrResponse$$valid())==!csrQueue.empty(),"CSR response latency/valid");
        check(bool(dut.get_io$$mmio$$response$$valid())==!busQueue.empty(),"MMIO response latency/valid");
        if(!csrQueue.empty()) {
            Reply got{dut.get_io$$csrResponse$$bits$$data(),bool(dut.get_io$$csrResponse$$bits$$error())};
            check(got==csrQueue.front(),"CSR response mismatch");
            if(cr)csrQueue.pop_front();else ++csrHeld;
        }
        if(!busQueue.empty()) {
            Reply got{dut.get_io$$mmio$$response$$bits$$data(),bool(dut.get_io$$mmio$$response$$bits$$error())};
            check(got==busQueue.front(),"MMIO response mismatch");
            if(br)busQueue.pop_front();else ++busHeld;
        }
        bool cf=c.has_value()&&cReady,bf=b.has_value()&&bReady;
        if(cf) {
            Reply reply=model.csr(*c);errors+=reply.error;
            if(inject) {reply.data^=1;inject=false;}
            csrQueue.push_back(reply);++csrAccepted;
        }
        if(bf) {Reply reply=model.bus(*b);errors+=reply.error;busQueue.push_back(reply);++busAccepted;}
        simultaneous+=cf&&bf;
        return {cf,bf};
    }
    void access(Csr c) {for(unsigned n=0;n<10;++n)if(tick(c).first)return;throw std::runtime_error("CSR stuck");}
    void access(Bus b) {for(unsigned n=0;n<10;++n)if(tick({},b).second)return;throw std::runtime_error("MSI stuck");}
    void drain() {for(unsigned i=0;i<4;++i)tick();check(csrQueue.empty()&&busQueue.empty(),"response drain");}
};
static void run(bool negative) {
    Bench b(negative);
    for(unsigned f=0;f<files;++f) {
        for(unsigned g=0;g<(count+1)/64;++g)b.access(Csr{f,0xc0+2*g,1,UINT64_MAX});
        b.access(msi(f,count));b.access(msi(f,1,true));
        b.access(Csr{f,0,0,0,true}); // delivery=0 must not suppress topei
        check(b.model.state[f].top()==1,"disabled delivery lost top identity");
        b.access(Csr{f,0x70,1,1});b.drain();
        check(b.model.interrupts()&(UINT64_C(1)<<f),"file did not assert irq");
        b.access(Csr{f,0x72,1,1});b.drain();
        check(!(b.model.interrupts()&(UINT64_C(1)<<f)),"threshold equality must mask");
        b.access(Csr{f,0x72,1,0});b.drain();
        // Claim + a fresh MSI for the same identity: new request must remain pending.
        auto both=b.tick(Csr{f,0,1,UINT64_MAX,true},msi(f,1));
        check(both.first&&both.second,"collision stimulus was not accepted");b.drain();
        check(b.model.state[f].top()==1,"claim/MSI lost the new interrupt");
        b.access(Csr{f,0,2,0,true}); // any actual write, even set with zero, claims
        b.access(Csr{f,0,0,0,true});b.drain();
        check(b.model.state[f].top()==count,"claim did not expose next identity");
        // Direct pending-array clear and incoming MSI also serialize CSR before MSI.
        both=b.tick(Csr{f,0x80,1,0},msi(f,1));
        check(both.first&&both.second,"pending write/MSI stimulus");b.drain();
        check(b.model.state[f].pending[1],"pending-array write lost MSI");
        both=b.tick(Csr{f,0x80,3,UINT64_MAX},msi(f,63));
        check(both.first&&both.second,"pending clear/MSI stimulus");b.drain();
        check(b.model.state[f].pending[63],"pending-array clear lost MSI");
        for(unsigned selector=0;selector<512;++selector)b.access(Csr{f,selector,0});
        for(unsigned selector=0x70;selector<256;++selector) {
            b.access(Csr{f,selector,1,UINT64_MAX});b.access(Csr{f,selector,0});
            b.access(Csr{f,selector,3,UINT64_MAX});b.access(Csr{f,selector,0});
        }
    }
    b.access(Csr{255,0x70,1,1});b.access(Csr{0,0xff0,1,1});
    for(unsigned page=0;page<pages();++page)for(unsigned offset=0;offset<4096;offset+=4) {
        Bus r{supervisorBase+4096*page+offset,17,2,15,true};b.access(r);r.write=false;b.access(r);
    }
    for(uint64_t address:{machineBase-4,machineBase+4096,supervisorBase-4,supervisorBase+4096*pages(),UINT64_MAX})
        b.access(Bus{address,1,2,15,true});
    for(unsigned size=0;size<8;++size)for(unsigned offset=0;offset<8;++offset)
        for(unsigned mask:{0U,1U,15U,255U})b.access(Bus{machineBase+offset,1,size,mask,true});
    // All implemented identities, repeated MSI coalescing, zero and high-bit rejection.
    for(unsigned f=0;f<files;++f) {
        for(unsigned id=0;id<=count+1;++id) {b.access(msi(f,id,id&1));b.access(msi(f,id));}
        b.access(msi(f,0x80000001));b.access(msi(f,0x10001));
        for(unsigned g=0;g<(count+1)/64;++g)b.access(Csr{f,0x80+2*g,0});
    }
    b.drain();
    for(unsigned i=0;i<256;++i) {
        auto accepted=b.tick(Csr{0,0,0,0,true},msi(0,1));
        check(accepted.first&&accepted.second,"one-per-cycle dual-port throughput");
    }
    b.drain();
    std::mt19937_64 rng(0xa1a+count);
    std::optional<Csr> c; std::optional<Bus> m;
    for(unsigned cycle=0;cycle<20000;++cycle) {
        if(!c) {
            unsigned selectors[]={0x70,0x72,0x80+2*unsigned(rng()%32),0xc0+2*unsigned(rng()%32),0x81,0x71,0x100};
            c=Csr{unsigned(rng()%(files+1)),selectors[rng()%7],unsigned(rng()%4),rng(),rng()%5==0};
            if(c->selector==0x70)c->data=rng()%2;
            if(c->selector==0x72)c->data=rng()%(count+2);
        }
        if(!m) {
            m=msi(rng()%files,rng()%(count+2),rng()&1);
            if(rng()%7==0)m->size=rng()%8;
            if(rng()%11==0)m->mask=rng()%256;
        }
        bool cr=cycle>=100&&rng()%3==0,br=cycle>=150&&rng()%4==0;
        auto accepted=b.tick(c,m,cr,br);if(accepted.first)c.reset();if(accepted.second)m.reset();
    }
    if(c)b.access(*c);if(m)b.access(*m);b.drain();
    // Read every implemented word to check pending/enable state beyond externally asserted irq.
    for(unsigned f=0;f<files;++f)for(unsigned g=0;g<(count+1)/64;++g) {
        b.access(Csr{f,0x80+2*g,0});b.access(Csr{f,0xc0+2*g,0});
    }
    b.drain();
    // Reset while both response queues hold work: no old reply or pending state may leak afterward.
    b.tick(Csr{0,0x70,1,1},msi(0,1),false,false);
    b.tick(Csr{0,0xc0,1,UINT64_MAX},msi(0,count),false,false);
    b.drive({}, {}, false, false);b.dut.set_reset(1);b.dut.step();b.dut.step();b.dut.set_reset(0);
    b.model=Model{};b.csrQueue.clear();b.busQueue.clear();b.tick();
    for(unsigned f=0;f<files;++f) {
        b.access(Csr{f,0x70,0});b.access(Csr{f,0x72,0});b.access(Csr{f,0,0,0,true});
        for(unsigned g=0;g<(count+1)/64;++g) {
            b.access(Csr{f,0x80+2*g,0});b.access(Csr{f,0xc0+2*g,0});
        }
    }
    b.drain();
    check(b.csrHeld>500&&b.busHeld>500&&b.simultaneous>500&&b.errors>200,"coverage thresholds");
    std::cout<<"GSIM IMSIC: PASS identities="<<count<<" files="<<files<<" csr="<<b.csrAccepted
        <<" mmio="<<b.busAccepted<<" simultaneous="<<b.simultaneous<<" held="<<b.csrHeld<<"/"<<b.busHeld
        <<" errors="<<b.errors<<" steady=256 latency=1 II=1\n";
}
int main(int argc,char**argv) {
    try {run(argc==2&&std::string(argv[1])=="--inject-mismatch");}
    catch(const std::exception&e) {std::cerr<<"GSIM IMSIC: FAIL "<<e.what()<<'\n';return 1;}
}
