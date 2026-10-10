#pragma once
#include "admission_observer.hpp"
namespace admission {
template<class D> struct Access { D& d;
 uint64_t cpuFire()const{return d.board$platform$privateCache$cpuFire;}
 uint64_t ordinary()const{return d.board$platform$privateCache$ordinary;}
 uint64_t lastValid()const{return d.board$platform$privateCache$lastValid;}
 uint64_t lastLine()const{return d.board$platform$privateCache$lastLine;}
 uint64_t postedPrefetchAllowed()const{return d.board$platform$privateCache$postedPrefetchAllowed;}
 uint64_t candidateValid()const{return d.board$platform$privateCache$candidateValid;}
 uint64_t candidateRemaining()const{
#if PREFETCH_CANDIDATE_CYCLES > 1
#ifdef PREFETCH_CANDIDATE_REMAINING
  return PREFETCH_CANDIDATE_REMAINING(d);
#else
  static_assert(sizeof(D)==0,"life16 requires actual-header-audited PREFETCH_CANDIDATE_REMAINING(d) mapping");return 0;
#endif
#else
  return 0;
#endif
 }
 uint64_t candidateAddress()const{return d.board$platform$privateCache$candidateAddress;}
 uint64_t candidateStore()const{return d.board$platform$privateCache$candidateStore;}
 uint64_t liveOwner()const{return d.board$platform$privateCache$liveOwner;}
 uint64_t releaseBusy()const{return d.board$platform$privateCache$releaseBusy;}
 uint64_t trackedValid()const{return d.board$platform$privateCache$trackedValid;}
 uint64_t trackedAddress()const{return d.board$platform$privateCache$trackedAddress;}
 uint64_t trackedIndex()const{return d.board$platform$privateCache$trackedIndex;}
 uint64_t observedTrackedStore()const{return d.board$platform$privateCache$observedTrackedStore;}
 uint64_t consume()const{return d.board$platform$privateCache$consume;}
 uint64_t pfIndex()const{return d.board$platform$privateCache$pfIndex;}
 uint64_t canAllocate()const{return d.board$platform$privateCache$canAllocate;}
 uint64_t freeMshr()const{return d.board$platform$privateCache$freeMshr;}
 uint64_t needsMissSlot()const{return d.board$platform$privateCache$needsMissSlot;}
 uint64_t reservedSet()const{return d.board$platform$privateCache$reservedSet;}
 uint64_t barrierRequest()const{return d.board$platform$privateCache$barrierRequest;}
 uint64_t barrier()const{return d.board$platform$privateCache$barrier;}
 uint64_t flushActive()const{return d.board$platform$privateCache$flushActive;}
 uint64_t bypassState()const{return d.board$platform$privateCache$bypassState;}
 uint64_t probeState()const{return d.board$platform$privateCache$probeState;}
 uint64_t queuedEvictWanted()const{return d.board$platform$privateCache$queuedEvictWanted;}
 uint64_t evictionState()const{return d.board$platform$privateCache$evictionState;}
 uint64_t phase(unsigned i)const{return d.board$platform$privateCache$phase[i];}
 uint64_t pendingIndex(unsigned i)const{return d.board$platform$privateCache$pendingIndex[i];}
 uint64_t prefetchOwner(unsigned i)const{return d.board$platform$privateCache$prefetchOwner[i];}
 uint64_t storePrefetchOwner(unsigned i)const{return d.board$platform$privateCache$storePrefetchOwner[i];}
 uint64_t wbLive(unsigned i)const{return d.board$platform$privateCache$wbLive[i];}
 uint64_t wbAddress(unsigned i)const{return d.board$platform$privateCache$wbAddress[i];}
 uint64_t wbPrefetch(unsigned i)const{return d.board$platform$privateCache$wbPrefetch[i];}
 uint64_t valid(unsigned i)const{return d.board$platform$privateCache$valid[i];}
 uint64_t dirty(unsigned i)const{return d.board$platform$privateCache$dirty[i];}
 uint64_t candidateTags(unsigned i)const{return d.board$platform$privateCache$candidateTags[i];}
 uint64_t pendingAddress(unsigned i)const{return d.board$platform$privateCache$pending$$address[i];}
 uint64_t reset()const{return d.get_backendReset();}
 uint64_t cacheValid()const{return d.get_lineage$$cache$$valid();}
 uint64_t cacheReady()const{return d.get_lineage$$cache$$ready();}
 uint64_t address()const{return d.get_lineage$$cache$$request$$address();}
 uint64_t write()const{return d.get_lineage$$cache$$request$$write();}
 uint64_t hint()const{return d.get_lineage$$cache$$request$$prefetchNextAllowed();}
 uint64_t flush()const{return d.get_lineage$$flushRequest();}
 uint64_t tlBValid()const{return d.get_lineage$$tlB$$valid();}
 uint64_t origin()const{return d.get_dataPrefetchOriginEvents();}
 uint64_t events()const{return d.get_dataPrefetchEvents();}
};
template<class A> Sample readAccess(const A&a){
 Sample s;s.reset=a.reset();if(s.reset)return s;
 s.valid=a.cacheValid();s.ready=a.cacheReady();s.cpuFire=a.cpuFire();
 if(s.valid){s.ordinary=a.ordinary();s.address=a.address();s.write=a.write();s.hint=a.hint();}
 s.lastValid=a.lastValid();if(s.lastValid)s.lastLine=a.lastLine();
 s.postedAllowed=a.postedPrefetchAllowed();s.live=a.liveOwner();s.release=a.releaseBusy();s.flush=a.flush();s.origin=a.origin();s.events=a.events();
 s.cv=a.candidateValid();s.tracked=a.trackedValid();
 if(s.tracked){s.trackedAddress=a.trackedAddress();s.trackedIndex=a.trackedIndex();need(s.trackedIndex<512,"admission tracked index range");s.trackedPresent=a.valid(s.trackedIndex);s.trackedStore=a.observedTrackedStore();}
 s.consume=a.consume();bool observedLive=false,observedRelease=false;
 for(unsigned i=0;i<2;++i){auto&m=s.mshrs[i];m.phase=a.phase(i);if(m.phase){m.pf=a.prefetchOwner(i);if(m.pf)m.store=a.storePrefetchOwner(i);m.address=a.pendingAddress(i);m.index=a.pendingIndex(i);observedLive|=m.pf;}}

 for(unsigned i=0;i<2;++i){auto&w=s.wbs[i];w.live=a.wbLive(i);if(w.live){w.pf=a.wbPrefetch(i);observedRelease|=w.pf;w.address=a.wbAddress(i);}}
 need(s.live==observedLive&&s.release==observedRelease,"admission PF live/release ownership mismatch");
 if(s.cv){
  s.ca=a.candidateAddress();s.cs=a.candidateStore();
#if PREFETCH_CANDIDATE_CYCLES > 1
  s.remaining=a.candidateRemaining();
#endif
  s.pi=a.pfIndex();need(s.pi<512,"admission PF index range");s.can=a.canAllocate();
  const auto set=(s.ca>>6)&255,tag=(s.ca>>14)&0x7ffff;
  bool present=false;for(unsigned w=0;w<2;++w){s.wayValid[w]=a.valid(set+256*w);if(s.wayValid[w]){s.wayTag[w]=a.candidateTags(w);s.wayDirty[w]=a.dirty(set+256*w);present|=s.wayTag[w]==tag;}}
  present=present&&s.ca>=0x80200000ULL&&s.ca<0x100200000ULL;
  bool reserved=false,victim=false,free=false;for(auto&m:s.mshrs){free|=!m.phase;if(m.phase)reserved|=(m.index&255)==set;}
  for(unsigned i=0;i<2;++i)if(s.wbs[i].live)victim|=(s.wbs[i].address>>6)==(s.ca>>6);
  need((s.pi&255)==set,"admission PF selected another set");s.victimValid=s.wayValid[s.pi>>8];s.victimDirty=s.wayDirty[s.pi>>8];if(s.victimValid)s.victimAddress=(s.wayTag[s.pi>>8]<<14)|(set<<6);
  if(s.valid){s.needsMiss=a.needsMissSlot();s.demandReserved=a.reservedSet();s.barrierRequest=a.barrierRequest();}
  s.evictionState=a.evictionState();s.queuedEvict=a.queuedEvictWanted();
  s.barrier=a.barrier();s.flushActive=a.flushActive();s.bypassState=a.bypassState();s.probeState=a.probeState();s.tlB=a.tlBValid();
  s.gates=s.deriveGates();
  if(s.allocated()){s.freeMshr=a.freeMshr();need(s.freeMshr<2&&!s.mshrs[s.freeMshr].phase,"admission allocated nonfree MSHR");}
 }
 validate(s);return s;
}

template<class D> Sample read(D& d){return readAccess(Access<D>{d});}
}
