#pragma once
#include <array>
#include <cstdint>
#include <ostream>
namespace pfdrain {
constexpr std::array<const char*,18> names={"lsu_live","request_fifo","adapter_and_return_counts","backend_offer_valid","adapter_wait_or_ack","pf_busy_owners","pf_candidate",
 "cache_mshr_engine","cache_writeback","cache_responses","cache_control","home_acquire_release_probe","home_transfer","home_dma_owners","shared_state_owners","translation_walkers","dma_busy","axi_holders_and_offers"};
struct Snapshot {
    std::array<uint64_t,names.size()> value{};
    bool empty()const{for(auto n:value)if(n)return false;return true;}
    void print(std::ostream& o)const{for(unsigned i=0;i<value.size();i++)o<<" "<<names[i]<<"="<<value[i];}
};
template<class A>uint64_t any(const A& a){uint64_t value=0;for(auto n:a)value|=n;return value;}
// Passive real state, not a new token/translation oracle. State enum idle/free=0
// is pinned to the common source and actual generated model header/FIR.
template<class D,class M>Snapshot read(D& d,const M& m){
    Snapshot s;auto& v=s.value;
    v[0]=(d.get_backendSlotState()|d.get_backendSlotStateHi())&3;
    v[1]=d.get_backendFifoCount();v[2]=d.get_dataPathCounts();
    v[3]=d.get_backendEvents()&((1ULL<<19)|(1ULL<<20)|(1ULL<<22)|(1ULL<<24)|(1ULL<<26)|(1ULL<<28));
    v[4]=d.get_dataPathEvents()&((1ULL<<24)|(1ULL<<28));
    v[5]=d.get_dataPrefetchEvents()&0x7f0;v[6]=d.board$platform$privateCache$candidateValid;
    v[7]=any(d.board$platform$privateCache$phase)|any(d.board$platform$privateCache$engine$phase);
    v[8]=any(d.board$platform$privateCache$wbLive);
    v[9]=any(d.board$platform$privateCache$responseOwned);
    v[10]=d.board$platform$privateCache$flushActive|d.board$platform$privateCache$flushWaiting|d.board$platform$privateCache$bypassState|
          d.board$platform$privateCache$probeState|d.board$platform$privateCache$evictionState;
    v[11]=any(d.board$platform$coherentHome$phase)|any(d.board$platform$coherentHome$releasePhases)|any(d.board$platform$coherentHome$probe$phase);
    v[12]=any(d.board$platform$coherentHome$transfer$reader$phase)|any(d.board$platform$coherentHome$transfer$writer$phase)|
          any(d.board$platform$coherentHome$transfer$arbiter$occupied[0])|any(d.board$platform$coherentHome$transfer$arbiter$occupied[1]);
    v[13]=any(d.board$platform$coherentHome$ownedLines);
    v[14]=d.board$platform$shared$unit$state|d.board$platform$shared$unit$owners$_io_deq_valid_T;
    v[15]=d.board$platform$physicalData_walkers_0$state|d.board$platform$physicalData_walkers_1$state|
          d.board$platform$physicalData_walkers_0$walker$state|d.board$platform$physicalData_walkers_1$walker$state;
    v[16]=d.board$platform$dma$busy;
    v[17]=!m.pendingReads.empty()||bool(m.heldRead)||m.writing||m.responding||m.writeWaiting||
          d.get_io$$ddrAxi$$ar$$valid()||d.get_io$$ddrAxi$$aw$$valid()||d.get_io$$ddrAxi$$w$$valid();
    return s;
}
}
