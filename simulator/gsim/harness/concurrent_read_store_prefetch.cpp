#include "prefetch_demand_adoption_oracle.h"
using namespace dual_prefetch;
static void episode(bool storeFirst,bool flush,unsigned fault) {
    Gate g;const uint64_t r=base+512,s=base+2048;
    g.permission(false);g.store(s+stride,0x55);g.store(s+2*stride,0x55);
    g.prepare(r,false);g.prepare(s,true);
    g.send({r-128});g.permission(true);g.hold(false,false,true,false);
    if(fault){g.t.ddr.denyReadAddress=uint32_t((storeFirst?s:r)-base);
        g.t.d.set_io$$adoption$$faultMode(fault);g.t.d.set_io$$adoption$$faultBeat(fault==1?0:7);}
    g.trigger(storeFirst?s:r,storeFirst);
    g.until([&]{return g.active[0]||g.active[1];},"first PF owner absent");
    if(storeFirst)g.until([&]{return g.n("dirty_pf_capture")>=1&&
        (!g.wb[0]||g.wb[0]->sent)&&(!g.wb[1]||g.wb[1]->sent);},"saved dirty victim was not fully sent");
    g.trigger(storeFirst?r:s,!storeFirst);
    g.until([&]{return g.active[0]&&g.active[1];},"opposite PF failed to use second existing MSHR");
    const auto& a=g.owners.at(*g.active[0]);const auto& b=g.owners.at(*g.active[1]);
    check(a.pf&&b.pf&&a.store!=b.store&&a.address!=b.address,"coexistence lacks two independent PF origins");
    check(set(a.address)!=set(b.address),"coexistence crossed PF whole-set exclusion");
    g.permission(false);g.ticks(6);
    if(flush){g.startFlush();g.ticks(4);check(!g.t.d.get_io$$flushDone(),"flush ignored real held E owners");}
    g.hold(false,false,false,false);
    if(flush)g.finishFlush();
    g.settle();
    check(g.n("dirty_pf_acks")>=1,"saved dirty STORE PF writeback not exercised");
    if(fault)check(g.n("pf_error")==1&&g.n("pf_install")==1,"real failed PF result installed or error path not exercised");
    g.t.ddr.denyReadAddress.reset();g.t.d.set_io$$adoption$$faultMode(0);
    if(!fault&&!flush){check(g.present(g.token[0])&&g.present(g.token[1]),"independent origins failed to install resident tokens");
        g.dma({s,false});g.send({r});g.store(s,0x55);}
    g.finish((std::string(storeFirst?"store_read":"read_store")+(flush?"_flush":"")+"_error"+std::to_string(fault)).c_str());
}
static void demand_first() {
    Gate g;const uint64_t r=base+512,s=base+2048,demand=s+stride;
    g.permission(false);g.prepare(r,false);g.prepare(s,true);g.send({r-128});
    g.permission(true);g.hold(false,false,true,false);g.trigger(s,true);
    g.until([&]{return g.active[0]||g.active[1];},"priority fixture lacks STORE PF");
    g.trigger(r,false,false); // offer the demand on the next candidate allocation edge, not after its hit reply
    g.permission(false);g.begin({demand});
    g.until([&]{return !g.offered;},"same-set distinct-way demand was blocked by PF candidate");
    bool found=false;for(const auto& o:g.active)if(o)found|=!g.owners.at(*o).pf&&g.owners.at(*o).address==demand;
    check(found,"READ PF stole demand's second physical miss owner");
    g.hold(false,false,false,false);g.finish("same_set_demand_first");
}
int main(int argc,char**argv){try{
    if(argc==2){const std::string a=argv[1];check(a.rfind("--inject-",0)==0,"unknown mutation");mutation=a.substr(9);}
    for(bool first:{false,true}){episode(first,false,0);episode(first,true,0);episode(first,false,1);episode(first,false,2);}
    demand_first();
    check(mutation.empty(),"requested mutation did not trigger");
    std::cout<<"CONCURRENT_READ_STORE_PREFETCH_PASS cases="<<completedCases<<" mshrs=2 wb=2 independent_bytes=1 real_E=1\n";return 0;
}catch(const std::exception&e){std::cerr<<"CONCURRENT_READ_STORE_PREFETCH_FAIL "<<e.what()<<'\n';return 1;}}
