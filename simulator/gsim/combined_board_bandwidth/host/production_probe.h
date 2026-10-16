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
    unsigned homeDirectory(unsigned i) {return d.board$platform$coherentHome$directory[i];}
    bool owned(unsigned i) {return d.board$platform$coherentHome$owned[i];}
#if FUTURE_WAY_RESERVATION
    // Accepted protocol signals only; the ledger never reads futurePaired,
    // captureEntry, capturing, releaseBeat, releaseDirectories or NEXT state.
    uint64_t homeResidentPa(unsigned dir) {return (uint64_t(dir<256?d.board$platform$coherentHome$tagBanks_0[dir&255]:d.board$platform$coherentHome$tagBanks_1[dir&255])<<14)|(uint64_t(dir&255)<<6);}
    bool homeCValid() {return d.get_cpuSupplyPrefetch$$cValid();}
    bool homeCReady() {return d.get_cpuSupplyPrefetch$$cReady();}
    uint64_t homeCPa() {return d.board$platform$privateCache$_io_tl_c_bits_address_T;}
    unsigned homeCSource() {return d.board$platform$privateCache$_io_tl_c_bits_source_T_2;}
    unsigned homeCOpcode() {return d.get_cpuSupplyPrefetch$$cOpcode();}
    unsigned homeCParam() {return d.get_cpuSupplyPrefetch$$cParam();}
    unsigned homeCSize() {return d.get_cpuSupplyPrefetch$$cSize();}
    uint64_t homeCData() {return d.get_cpuSupplyPrefetch$$cData();}
    bool homeEValid() {return d.board$platform$privateCache$engine$ackQueue$_io_deq_valid_T;}
    bool homeEFire() {return d.board$platform$privateCache$engine$ackQueue$_do_deq_T;}
    unsigned homeESink() {return d.board$platform$privateCache$engine$io$$e$$bits$$sink;}
    bool homeGrantValid() {return d.board$platform$coherentHome$_grantFire_io_lineGrants_0_valid_T_1;}
    bool homeGrantFire() {return d.board$platform$coherentHome$grantFire;}
    unsigned homeGrantEntry() {return d.board$platform$coherentHome$grantEntry;}
    unsigned homeGrantSource() {return d.board$platform$coherentHome$io$$lineGrants$$bits$$source;}
    bool homeGrantDenied() {return d.board$platform$coherentHome$errors[homeGrantEntry()];}
    bool homeAckFire() {return d.board$platform$privateCache$evictionRetiring;}
    unsigned homeAckSource() {return d.board$platform$coherentHome$_io_clients_0_d_bits_source_T;}
#endif
};
