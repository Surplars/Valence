#pragma once
// Experimental strategy diagnostics; original byte/lifetime checks retained.
#ifndef CONCURRENT_READ_STORE_PREFETCH
#define CONCURRENT_READ_STORE_PREFETCH 0
#endif
#include <cstdint>
#ifndef READ_PREFETCH_DEMAND_ADOPTION
#define READ_PREFETCH_DEMAND_ADOPTION 0
#endif
#ifndef READ_PREFETCH_BEHIND_STORE
#define READ_PREFETCH_BEHIND_STORE 0
#endif
template<class D> struct ProductionSupplyProbe {
    D &d;
    bool reqValid() {return ((d.get_cpuBandwidthEvents()>>12)|(d.get_cpuBandwidthEvents()>>15))&1;}
    bool reqFire() {return (d.get_cpuBandwidthEvents()>>15)&1;}
    bool independentReqFire() {return (d.get_dataPathEvents()>>19)&1;}
    bool cacheFire() {return d.board$platform$privateCache$cpuFire;}
    bool flush() {return d.board$platform$core$core$core$backend$systemUnit$_io_fenceIFlush_T;}
    uint64_t reqPa() {return d.get_dataPathRequest9Address();}
    uint64_t reqMeta() {return d.get_dataPathRequest9Meta();}
    bool hint() {return (d.get_cpuFlowPhysicalAuth()>>52)&1;}
    bool ordinary() {return d.board$platform$privateCache$ordinary;}
    bool historyValid() {return d.board$platform$privateCache$lastValid;}
    uint64_t historyLine() {return d.board$platform$privateCache$lastLine;}
    bool candidate() {return d.get_cpuSupplyPrefetch$$candidate();}
    bool candidateStore() {return d.get_cpuSupplyPrefetch$$candidateStore();}
    bool allocate() {return d.get_cpuSupplyPrefetch$$allocated();}
    bool allocateStore() {return d.get_cpuSupplyPrefetch$$allocatedStore();}
    bool pending() {return d.get_cpuSupplyPrefetch$$pendingCandidateValid();}
    bool live() {return d.board$platform$privateCache$liveOwner;}
    bool release() {return d.board$platform$privateCache$releaseBusy;}
    bool readOwnerBlocked() {
#if READ_PREFETCH_DEMAND_ADOPTION
        unsigned owners=d.get_cpuSupplyPrefetch$$mshrLiveMask()&d.get_cpuSupplyPrefetch$$mshrPrefetchMask();
        owners&=~unsigned(d.get_cpuSupplyPrefetch$$mshrDemandAttachedMask());
        if(d.get_cpuSupplyPrefetch$$demandAttach())owners&=~(1U<<d.get_cpuSupplyPrefetch$$demandAttachSlot());
#if READ_PREFETCH_BEHIND_STORE
        // Count all live PFs, including attached READs. Only dereference posted
        // kind for a live PF owner; a sole nonposted unattached STORE is eligible.
        const unsigned allPf=d.get_cpuSupplyPrefetch$$mshrLiveMask()&d.get_cpuSupplyPrefetch$$mshrPrefetchMask();
        const unsigned attached=d.get_cpuSupplyPrefetch$$mshrDemandAttachedMask();
        const unsigned stores=d.get_cpuSupplyPrefetch$$mshrStoreMask();
        bool oneStore=false;
        if(allPf && !(allPf&(allPf-1)) && !(allPf&~3U))
            for(unsigned i=0;i<2;++i)if(allPf&(1U<<i))
                oneStore=(stores&(1U<<i)) && !(attached&(1U<<i)) && !d.board$platform$privateCache$postedMshr[i];
#if CONCURRENT_READ_STORE_PREFETCH
        return (owners & ~stores)!=0;
#else
        return owners!=0 && !oneStore;
#endif
#else
        return owners!=0;
#endif
#else
        return live();
#endif
    }
    bool readReleaseBlocked() {
#if READ_PREFETCH_DEMAND_ADOPTION
        return (d.get_cpuSupplyPrefetch$$wbLiveMask()&d.get_cpuSupplyPrefetch$$wbPrefetchMask()&~unsigned(d.get_cpuSupplyPrefetch$$wbSentMask()))!=0;
#else
        return release();
#endif
    }
    bool readResident() {return d.get_cpuSupplyPrefetch$$readTokenValid();}
    bool readConsume() {return d.get_cpuSupplyPrefetch$$readTokenConsume();}
    bool posted() {return d.board$platform$privateCache$postedPrefetchAllowed;}
    bool aValid() {return d.board$platform$privateCache$engine$sendQueue$_io_deq_valid_T;}
    bool aFire() {return d.board$platform$privateCache$engine$sendQueue$_do_deq_T;}
    uint64_t aPa() {return d.board$platform$privateCache$engine$io$$a$$bits$$address;}
    unsigned aSource() {return d.board$platform$privateCache$engine$io$$a$$bits$$source;}
    unsigned homePhase(unsigned i) {return d.board$platform$coherentHome$phase[i];}
    uint64_t homePa(unsigned i) {return d.board$platform$coherentHome$addresses[i];}
    unsigned homeSource(unsigned i) {return d.board$platform$coherentHome$sources[i];}
    bool owned(unsigned i) {return d.board$platform$coherentHome$owned[i];}
};
