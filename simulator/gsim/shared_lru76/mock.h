struct Mock {
#define FIELD(t,n) t board$platform$privateCache$##n
    FIELD(bool,valid)[512]={};FIELD(bool,dirty)[512]={};FIELD(unsigned,replacement)[256]={};
    FIELD(uint32_t,tagBanks_0)[256]={};FIELD(uint32_t,tagBanks_1)[256]={};
    FIELD(unsigned,phase)[2]={};FIELD(unsigned,pendingIndex)[2]={};FIELD(uint64_t,pending$$address)[2]={};
    FIELD(bool,wbLive)[2]={};FIELD(uint64_t,wbAddress)[2]={};
    FIELD(bool,needsMissSlot)=false;FIELD(bool,reservedSet)=false;FIELD(bool,bypass)=false;
    FIELD(bool,postedPrefetchAllowed)=true;FIELD(bool,liveOwner)=false;FIELD(bool,releaseBusy)=false;
    FIELD(bool,barrier)=false;FIELD(bool,flushActive)=false;FIELD(unsigned,bypassState)=0;FIELD(unsigned,probeState)=0;
    FIELD(bool,queuedEvictWanted)=false;FIELD(unsigned,evictionState)=0;
#undef FIELD
    bool board$platform$platformRouter$_io_memory_request_valid_T_2=false;
    bool board$platform$core$core$core$backend$systemUnit$_io_fenceIFlush_T=false;
    bool board$platform$coherentHome$probe$sendQueue$_io_deq_valid_T=false;
    bool tokenValid[2]={},tokenConsumed[2]={};uint64_t tokenPa[2]={};unsigned tokenIndex[2]={};
    bool get_cpuTagged$$cache$$valid(){return false;}
    unsigned get_cpuSupplyPrefetch$$mshrStoreMask(){return 0;}
    uint64_t get_dataPathRequest9Meta(){return 0;}
    unsigned get_cpuSupplyPrefetch$$mshrLiveMask(){return 0;}
    unsigned get_cpuSupplyPrefetch$$mshrPrefetchMask(){return 0;}
    unsigned get_cpuSupplyPrefetch$$mshrDemandAttachedMask(){return 0;}
    unsigned get_cpuSupplyPrefetch$$wbLiveMask(){return 0;}
    unsigned get_cpuSupplyPrefetch$$wbPrefetchMask(){return 0;}
    unsigned get_cpuSupplyPrefetch$$wbSentMask(){return 0;}
    bool get_cpuSupplyPrefetch$$readTokenValid(){return tokenValid[0];}
    bool get_cpuSupplyPrefetch$$readTokenConsume(){return tokenConsumed[0];}
    bool get_cpuSupplyPrefetch$$storeTokenValid(){return tokenValid[1];}
    bool get_cpuSupplyPrefetch$$storeTokenConsume(){return tokenConsumed[1];}
    uint64_t get_cpuSupplyPrefetch$$readTokenAddress(){return tokenPa[0];}
    unsigned get_cpuSupplyPrefetch$$readTokenIndex(){return tokenIndex[0];}
    uint64_t get_cpuSupplyPrefetch$$storeTokenAddress(){return tokenPa[1];}
    unsigned get_cpuSupplyPrefetch$$storeTokenIndex(){return tokenIndex[1];}
    bool get_cpuSupplyPrefetch$$pendingCandidateValid(){return false;}uint64_t get_cpuSupplyPrefetch$$pendingCandidateAddress(){throw std::runtime_error("invalid candidate address");}
};
