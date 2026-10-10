#pragma once
#include "copy_eviction.hpp"
namespace pfcopy {
template<class Tag>void verifyAcquireTag(Tag tag,unsigned mshr,unsigned kind,unsigned owner,uint64_t generation){
    require(mshr<2&&kind<3&&owner<2,"COPY full acquire identity geometry");
    require((tag>>68)==0 && unsigned(tag&1)==mshr && unsigned((tag>>1)&1)==owner && uint64_t(tag>>2)==generation && unsigned(tag>>66)==kind,"COPY full acquire kind/generation/owner/MSHR mismatch");
}
struct Installation {bool residentInstall,storePfInstall,storePfError;};
inline Installation classifyInstall(bool valid,bool ordinaryFire,bool postedInstall,bool error,bool prefetch,bool storePrefetch){
    require(!ordinaryFire||valid,"ordinary refill fire lacks valid");
    require(!(ordinaryFire&&postedInstall),"ordinary refill and posted install overlap");
    require(!storePrefetch||prefetch,"store PF refill lacks actual PF owner");
    return {(ordinaryFire&&!error)||postedInstall,ordinaryFire&&!error&&prefetch&&storePrefetch,ordinaryFire&&error&&prefetch&&storePrefetch};
}
}
