#pragma once
#include "canonical_observer.hpp"
namespace canonical_overlap {
// Exact names verified in the actual generated header. No guessed packed bit positions.
// Request-derived cache predicates are read only with that real request valid.
template<class D>void attachCache(Sample&s,D&d){
 s.cacheObserved=true;s.cacheBarrier=d.board$platform$privateCache$barrier;
 s.cache.valid=d.get_lineage$$cache$$valid();s.cache.ready=d.get_lineage$$cache$$ready();
 if(s.cache.valid){
  auto&r=s.cache;r.address=d.get_lineage$$cache$$request$$address();r.data=d.get_lineage$$cache$$request$$data();
  r.size=d.get_lineage$$cache$$request$$size();r.mask=d.get_lineage$$cache$$request$$mask();
  r.write=d.get_lineage$$cache$$request$$write();r.atomic=d.get_lineage$$cache$$request$$atomic();
  r.virtualized=d.get_lineage$$cache$$request$$virtualized();r.prechecked=d.get_lineage$$cache$$request$$precheckedLoad();
  r.epoch=d.get_lineage$$cache$$request$$translationEpoch();r.uncached=d.get_lineage$$cache$$request$$uncached();
  s.cacheOrdinary=d.board$platform$privateCache$ordinary;
  s.cacheFound=d.board$platform$privateCache$found;s.cacheReadHit=d.board$platform$privateCache$readHit;
  s.cacheWriteHit=d.board$platform$privateCache$writeHit;s.cacheBarrierRequest=d.board$platform$privateCache$barrierRequest;
  // Match the production barrier predicate: real posted acceptance, not an offered proof.
  s.cachePosted=d.get_lineage$$owner$$accepted$$valid();
 }
 s.cacheResponse.valid=d.get_lineage$$cache$$responseValid();s.cacheResponse.ready=d.get_lineage$$cache$$responseReady();
 if(s.cacheResponse.valid){s.cacheResponse.error=d.get_lineage$$cache$$response$$error();s.cacheResponse.pageFault=d.get_lineage$$cache$$response$$pageFault();}
}
}
