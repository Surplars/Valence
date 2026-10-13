#include "supply_ledger.h"
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
    bool token=false;uint64_t tokenPa=0;unsigned tokenIndex=0;
    uint64_t get_dataPathRequest9Meta(){return 0;}
    unsigned get_cpuSupplyPrefetch$$mshrLiveMask(){return 0;}
    unsigned get_cpuSupplyPrefetch$$mshrPrefetchMask(){return 0;}
    unsigned get_cpuSupplyPrefetch$$mshrDemandAttachedMask(){return 0;}
    unsigned get_cpuSupplyPrefetch$$wbLiveMask(){return 0;}
    unsigned get_cpuSupplyPrefetch$$wbPrefetchMask(){return 0;}
    unsigned get_cpuSupplyPrefetch$$wbSentMask(){return 0;}
    bool get_cpuSupplyPrefetch$$readTokenValid(){return false;}bool get_cpuSupplyPrefetch$$readTokenConsume(){throw std::runtime_error("invalid read consume");}
    bool get_cpuSupplyPrefetch$$storeTokenValid(){return token;}bool get_cpuSupplyPrefetch$$storeTokenConsume(){return false;}
    uint64_t get_cpuSupplyPrefetch$$readTokenAddress(){throw std::runtime_error("invalid read address");}unsigned get_cpuSupplyPrefetch$$readTokenIndex(){throw std::runtime_error("invalid read index");}
    uint64_t get_cpuSupplyPrefetch$$storeTokenAddress(){SupplyLedger::require(token,"invalid store address");return tokenPa;}unsigned get_cpuSupplyPrefetch$$storeTokenIndex(){SupplyLedger::require(token,"invalid store index");return tokenIndex;}
    bool get_cpuSupplyPrefetch$$pendingCandidateValid(){return false;}uint64_t get_cpuSupplyPrefetch$$pendingCandidateAddress(){throw std::runtime_error("invalid candidate address");}
};
int main(int argc,char **argv){try{std::string mode=argc>1?argv[1]:"";Mock d;SupplyLedger ledger;uint64_t pa=0x80400000;
    auto clean=ledger.guard(d,pa,false);SupplyLedger::require(clean.mask==0&&clean.index==0,"clean read eligibility");
    d.board$platform$privateCache$valid[0]=d.board$platform$privateCache$valid[256]=true;
    d.board$platform$privateCache$tagBanks_0[0]=0x81400000ULL>>14;d.board$platform$privateCache$tagBanks_1[0]=0x82400000ULL>>14;
    d.board$platform$privateCache$dirty[0]=d.board$platform$privateCache$dirty[256]=true;
    auto dirty=ledger.guard(d,pa,false);if(mode=="--dirty")dirty.mask=0;
    SupplyLedger::require(dirty.mask==(1U<<7),"dirty read exclusion");SupplyLedger::require(ledger.guard(d,pa,true).mask==0,"store dirty victim allowed");
    d.token=true;d.tokenPa=0x81400000ULL;d.tokenIndex=0;auto protectedWay=ledger.guard(d,pa,false);if(mode=="--token")protectedWay.index=0;
    SupplyLedger::require(protectedWay.index==256,"opposite token full identity protection");
    d.board$platform$privateCache$dirty[0]=false;
    auto cleanProtected=ledger.guard(d,pa,false);
    SupplyLedger::require(cleanProtected.index==256&&cleanProtected.mask==(READ_PREFETCH_DIRTY_RETRY?0:(1U<<7)),"protected clean store-token alternate dirty permission");
    d.board$platform$privateCache$dirty[0]=true;
    d.board$platform$privateCache$phase[0]=3;d.board$platform$privateCache$pendingIndex[0]=0;d.board$platform$privateCache$pending$$address[0]=pa;
    auto reserved=ledger.guard(d,pa,false);if(mode=="--reserved")reserved.mask&=~(1U<<4);
    SupplyLedger::require((reserved.mask&(1U<<4))&&(reserved.dup&2),"target reservation exclusion");
    d.board$platform$privateCache$wbLive[0]=true;d.board$platform$privateCache$wbAddress[0]=pa;auto wb=ledger.guard(d,pa,false);if(mode=="--wb")wb.mask&=~(1U<<5);
    SupplyLedger::require((wb.mask&(1U<<5))&&(wb.dup&4),"WB target full identity exclusion");
    ledger.wb[0]={true,true,true,7,0x81404000ULL,0x81408000ULL,100,9,1};
    auto beforeAck=ledger.wb;ledger.wb[0].live=false;ledger.wb[0]={true,false,false,8,0x80404000ULL,0,150,0,0};
    if(mode=="--ack-block")beforeAck=ledger.wb;
    SupplyLedger::require(beforeAck[0].live&&beforeAck[0].pf&&beforeAck[0].store&&beforeAck[0].seq==7&&beforeAck[0].ownerSeq==9&&beforeAck[0].pa==0x81404000ULL,"same-edge ACK BLOCK must retain old PF WB identity");
    PassiveSupply::Sample accepted;accepted.cacheFire=accepted.reqFire=true;accepted.pa=pa;accepted.meta=0;if(mode=="--payload")accepted.pa.reset();SupplyLedger::requireAccepted(accepted);
    if(mode=="--pa")ledger.guard(d,pa+(1ULL<<34),false);
    ledger.owners[0].live=true;ledger.owners[0].pf=false;ledger.owners[0].pa=pa;
    ledger.bindPosted(0,pa,1,7,1,7,3);
    ledger.complete(0,pa+(mode=="--posted-pa"?64:0),true);
    if(mode=="--posted-duplicate")ledger.complete(0,pa,true);
    if(mode!="--posted-missing-install")ledger.installed(0,pa,1,mode=="--posted-generation"?8:7,1,7,3);
    ledger.retired(0);
    AdoptionLedger attachment;
    AdoptionLedger::Tag tag{0,4};
    attachment.allocated(0,1,pa,true,false,100);
    attachment.issued(0,pa,0,tag,110);
    auto id=attachment.attach(0,1,pa+(mode=="--attach-pa"?64:24),0,tag,120);
    if(mode=="--attach-duplicate")attachment.attach(0,1,pa+24,0,tag,121);
    if(mode=="--attach-lost-binding")attachment.ticketBindings[0]=0;
    attachment.bound(0,pa+24,mode=="--attach-ticket"?1:0,true);
    attachment.refill(0,pa+24,tag,true,0,false,130);
    attachment.response(id,pa+24,false,false,135);
    std::cout<<"LEDGER_GUARD_CONTROLS_PASS nonzero_blockers=dirty,opposite_token,reservation,writeback\n";return 0;
}catch(const std::exception&e){std::cerr<<"LEDGER_CONTROL_FAIL "<<e.what()<<"\n";return 1;}}
