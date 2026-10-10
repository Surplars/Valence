#pragma once
#include "canonical_observer.hpp"
#include <sstream>
#include <vector>
namespace memory_frontier {
using canonical_overlap::need;
enum Field { Enabled=0, Epoch=1, Stable=2, StartValid=3, StartReady=4, StartAccepted=5, StartIndex=6, StartTag=7, StartEpoch=8, StartVa=9, StartPa=10, StartSize=11, StartStore=12, StartAtomic=13, StartPrechecked=14, StartParallel=15, StartSlot=16, StartFrontier=17, StartIsHead=18, Reserved=19, Allowed=20, Bound=21, ScanState=22, SnapshotLive=23, ReadSelectedGrant=24, ReadCandidateGrant=25, ReadScanGrant=26, WriteGrant=27, Evict=28, ClearMask=29, Pause=30, Flush=31, AdmissionValid=32, AdmissionIndex=33, AdmissionTag=34, AdmissionEpoch=35, AdmissionVa=36, AdmissionWrite=37, AdmissionSize=38, AdmissionRow=39, QueryValid=40, QueryIndex=41, QueryTag=42, QueryEpoch=43, QueryVa=44, QueryPa=45, QueryWrite=46, QuerySize=47, QueryMask=48, QueryRow=49, ResultValid=50, ResultIndex=51, ResultTag=52, ResultEpoch=53, ResultVa=54, ResultPa=55, ResultWrite=56, ResultSize=57, ResultMask=58, ResultRow=59, SelectedValid=60, SelectedIndex=61, SelectedTag=62, SelectedEpoch=63, SelectedVa=64, SelectedPa=65, SelectedWrite=66, SelectedSize=67, SelectedMask=68, FrontierValid=69, FrontierIndex=70, FrontierTag=71, FrontierEpoch=72, FrontierVa=73, FrontierPa=74, FrontierWrite=75, FrontierSize=76, FrontierMask=77, FrontierRow=78, QueryHit=79, QueryHitPa=80, QueryHitEpoch=81, QueryHitPbmt=82, ResultAllowed=83, ResultOwnerMatches=84, ResultReservation=85, ResultInserted=86, FrontierAccepted=87, FrontierCovered=88, FrontierRelied=89, Row0Valid=90, Row0State=91, Row0Index=92, Row0Tag=93, Row0Epoch=94, Row0Bound=95, Row1Valid=96, Row1State=97, Row1Index=98, Row1Tag=99, Row1Epoch=100, Row1Bound=101, Row2Valid=102, Row2State=103, Row2Index=104, Row2Tag=105, Row2Epoch=106, Row2Bound=107, Row3Valid=108, Row3State=109, Row3Index=110, Row3Tag=111, Row3Epoch=112, Row3Bound=113, Row4Valid=114, Row4State=115, Row4Index=116, Row4Tag=117, Row4Epoch=118, Row4Bound=119, Row5Valid=120, Row5State=121, Row5Index=122, Row5Tag=123, Row5Epoch=124, Row5Bound=125, Row6Valid=126, Row6State=127, Row6Index=128, Row6Tag=129, Row6Epoch=130, Row6Bound=131, Row7Valid=132, Row7State=133, Row7Index=134, Row7Tag=135, Row7Epoch=136, Row7Bound=137, Row8Valid=138, Row8State=139, Row8Index=140, Row8Tag=141, Row8Epoch=142, Row8Bound=143, Row9Valid=144, Row9State=145, Row9Index=146, Row9Tag=147, Row9Epoch=148, Row9Bound=149, Row10Valid=150, Row10State=151, Row10Index=152, Row10Tag=153, Row10Epoch=154, Row10Bound=155, Row11Valid=156, Row11State=157, Row11Index=158, Row11Tag=159, Row11Epoch=160, Row11Bound=161, Row12Valid=162, Row12State=163, Row12Index=164, Row12Tag=165, Row12Epoch=166, Row12Bound=167, Row13Valid=168, Row13State=169, Row13Index=170, Row13Tag=171, Row13Epoch=172, Row13Bound=173, Row14Valid=174, Row14State=175, Row14Index=176, Row14Tag=177, Row14Epoch=178, Row14Bound=179, Row15Valid=180, Row15State=181, Row15Index=182, Row15Tag=183, Row15Epoch=184, Row15Bound=185, Line0Valid=186, Line0Index=187, Line0Tag=188, Line0PaLine=189, Line1Valid=190, Line1Index=191, Line1Tag=192, Line1PaLine=193, Line2Valid=194, Line2Index=195, Line2Tag=196, Line2PaLine=197, Line3Valid=198, Line3Index=199, Line3Tag=200, Line3PaLine=201, PfAlloc=202, PfPa=203, PfSlot=204, DemandAlloc=205, DemandPa=206, DemandSlot=207, Refill=208, RefillPa=209, RefillSlot=210, RefillPrefetch=211, MshrLive=212, MshrPrefetch=213, TlAValid=214, TlAReady=215, TlAAddress=216, TlASource=217, TlAOpcode=218, TlASize=219, TlDValid=220, TlDReady=221, TlDSource=222, TlDOpcode=223, TlDSize=224, OtherValid=225, OtherReady=226, OtherPa=227, OtherSize=228, OtherWrite=229, OtherResponseValid=230, OtherResponseReady=231, FetchAccepted=232, FetchPa=233, FetchSize=234 };
struct Raw { uint64_t cycle=0;bool roi=false,reset=false;std::array<uint64_t,235> v{};bool ar=false,r=false,rReady=false,rLast=false;uint64_t arAddress=0,arId=0,arLen=0,arSize=0,rId=0,arBurst=0;std::array<uint64_t,2> mshrPa{};std::array<uint64_t,8> stage{}; };
template<class D,class M> Raw read(D&d,M&m,uint64_t cycle,bool roi) { Raw s;s.cycle=cycle;s.roi=roi;s.reset=d.get_backendReset();if(s.reset)return s;
 s.v[Enabled]=d.get_mpEnabled();
 s.v[Epoch]=d.get_mpEpoch();
 s.v[Stable]=d.get_mpStable();
 s.v[StartValid]=d.get_mpStartValid();
 s.v[StartReady]=d.get_mpStartReady();
 s.v[StartAccepted]=d.get_mpStartAccepted();
 if(s.v[StartValid])s.v[StartIndex]=d.get_mpStartIndex();
 if(s.v[StartValid])s.v[StartTag]=d.get_mpStartTag();
 if(s.v[StartValid])s.v[StartEpoch]=d.get_mpStartEpoch();
 if(s.v[StartValid])s.v[StartVa]=d.get_mpStartVa();
 if(s.v[StartValid])s.v[StartPa]=d.get_mpStartPa();
 if(s.v[StartValid])s.v[StartSize]=d.get_mpStartSize();
 if(s.v[StartValid])s.v[StartStore]=d.get_mpStartStore();
 if(s.v[StartValid])s.v[StartAtomic]=d.get_mpStartAtomic();
 if(s.v[StartValid])s.v[StartPrechecked]=d.get_mpStartPrechecked();
 if(s.v[StartValid])s.v[StartParallel]=d.get_mpStartParallel();
 if(s.v[StartAccepted])s.v[StartSlot]=d.get_mpStartSlot();
 if(s.v[StartValid])s.v[StartFrontier]=d.get_mpStartFrontier();
 if(s.v[StartValid])s.v[StartIsHead]=d.get_mpStartIsHead();
 s.v[Reserved]=d.get_mpReserved();
 s.v[Allowed]=d.get_mpAllowed();
 s.v[Bound]=d.get_mpBound();
 s.v[ScanState]=d.get_mpScanState();
 s.v[SnapshotLive]=d.get_mpSnapshotLive();
 s.v[ReadSelectedGrant]=d.get_mpReadSelectedGrant();
 s.v[ReadCandidateGrant]=d.get_mpReadCandidateGrant();
 s.v[ReadScanGrant]=d.get_mpReadScanGrant();
 s.v[WriteGrant]=d.get_mpWriteGrant();
 s.v[Evict]=d.get_mpEvict();
 s.v[ClearMask]=d.get_mpClearMask();
 s.v[Pause]=d.get_mpPause();
 s.v[Flush]=d.get_mpFlush();
 s.v[AdmissionValid]=d.get_mpAdmissionValid();
 if(s.v[AdmissionValid])s.v[AdmissionIndex]=d.get_mpAdmissionIndex();
 if(s.v[AdmissionValid])s.v[AdmissionTag]=d.get_mpAdmissionTag();
 if(s.v[AdmissionValid])s.v[AdmissionEpoch]=d.get_mpAdmissionEpoch();
 if(s.v[AdmissionValid])s.v[AdmissionVa]=d.get_mpAdmissionVa();
 if(s.v[AdmissionValid])s.v[AdmissionWrite]=d.get_mpAdmissionWrite();
 if(s.v[AdmissionValid])s.v[AdmissionSize]=d.get_mpAdmissionSize();
 if(s.v[AdmissionValid])s.v[AdmissionRow]=d.get_mpAdmissionRow();
 s.v[QueryValid]=d.get_mpQueryValid();
 if(s.v[QueryValid])s.v[QueryIndex]=d.get_mpQueryIndex();
 if(s.v[QueryValid])s.v[QueryTag]=d.get_mpQueryTag();
 if(s.v[QueryValid])s.v[QueryEpoch]=d.get_mpQueryEpoch();
 if(s.v[QueryValid])s.v[QueryVa]=d.get_mpQueryVa();
 if(s.v[QueryValid])s.v[QueryPa]=d.get_mpQueryPa();
 if(s.v[QueryValid])s.v[QueryWrite]=d.get_mpQueryWrite();
 if(s.v[QueryValid])s.v[QuerySize]=d.get_mpQuerySize();
 if(s.v[QueryValid])s.v[QueryMask]=d.get_mpQueryMask();
 if(s.v[QueryValid])s.v[QueryRow]=d.get_mpQueryRow();
 s.v[ResultValid]=d.get_mpResultValid();
 if(s.v[ResultValid])s.v[ResultIndex]=d.get_mpResultIndex();
 if(s.v[ResultValid])s.v[ResultTag]=d.get_mpResultTag();
 if(s.v[ResultValid])s.v[ResultEpoch]=d.get_mpResultEpoch();
 if(s.v[ResultValid])s.v[ResultVa]=d.get_mpResultVa();
 if(s.v[ResultValid])s.v[ResultPa]=d.get_mpResultPa();
 if(s.v[ResultValid])s.v[ResultWrite]=d.get_mpResultWrite();
 if(s.v[ResultValid])s.v[ResultSize]=d.get_mpResultSize();
 if(s.v[ResultValid])s.v[ResultMask]=d.get_mpResultMask();
 if(s.v[ResultValid])s.v[ResultRow]=d.get_mpResultRow();
 s.v[SelectedValid]=d.get_mpSelectedValid();
 if(s.v[SelectedValid])s.v[SelectedIndex]=d.get_mpSelectedIndex();
 if(s.v[SelectedValid])s.v[SelectedTag]=d.get_mpSelectedTag();
 if(s.v[SelectedValid])s.v[SelectedEpoch]=d.get_mpSelectedEpoch();
 if(s.v[SelectedValid])s.v[SelectedVa]=d.get_mpSelectedVa();
 if(s.v[SelectedValid])s.v[SelectedPa]=d.get_mpSelectedPa();
 if(s.v[SelectedValid])s.v[SelectedWrite]=d.get_mpSelectedWrite();
 if(s.v[SelectedValid])s.v[SelectedSize]=d.get_mpSelectedSize();
 if(s.v[SelectedValid])s.v[SelectedMask]=d.get_mpSelectedMask();
 s.v[FrontierValid]=d.get_mpFrontierValid();
 if(s.v[FrontierValid])s.v[FrontierIndex]=d.get_mpFrontierIndex();
 if(s.v[FrontierValid])s.v[FrontierTag]=d.get_mpFrontierTag();
 if(s.v[FrontierValid])s.v[FrontierEpoch]=d.get_mpFrontierEpoch();
 if(s.v[FrontierValid])s.v[FrontierVa]=d.get_mpFrontierVa();
 if(s.v[FrontierValid])s.v[FrontierPa]=d.get_mpFrontierPa();
 if(s.v[FrontierValid])s.v[FrontierWrite]=d.get_mpFrontierWrite();
 if(s.v[FrontierValid])s.v[FrontierSize]=d.get_mpFrontierSize();
 if(s.v[FrontierValid])s.v[FrontierMask]=d.get_mpFrontierMask();
 if(s.v[FrontierValid])s.v[FrontierRow]=d.get_mpFrontierRow();
 if(s.v[QueryValid])s.v[QueryHit]=d.get_mpQueryHit();
 if(s.v[QueryHit])s.v[QueryHitPa]=d.get_mpQueryHitPa();
 if(s.v[QueryHit])s.v[QueryHitEpoch]=d.get_mpQueryHitEpoch();
 if(s.v[QueryHit])s.v[QueryHitPbmt]=d.get_mpQueryHitPbmt();
 if(s.v[ResultValid])s.v[ResultAllowed]=d.get_mpResultAllowed();
 if(s.v[ResultValid])s.v[ResultOwnerMatches]=d.get_mpResultOwnerMatches();
 if(s.v[ResultValid])s.v[ResultReservation]=d.get_mpResultReservation();
 if(s.v[ResultValid])s.v[ResultInserted]=d.get_mpResultInserted();
 s.v[FrontierAccepted]=d.get_mpFrontierAccepted();
 if(s.v[FrontierValid])s.v[FrontierCovered]=d.get_mpFrontierCovered();
 if(s.v[FrontierValid])s.v[FrontierRelied]=d.get_mpFrontierRelied();
 s.v[Row0Valid]=d.get_mpRow0Valid();
 if(s.v[Row0Valid])s.v[Row0State]=d.get_mpRow0State();
 if(s.v[Row0Valid])s.v[Row0Index]=d.get_mpRow0Index();
 if(s.v[Row0Valid])s.v[Row0Tag]=d.get_mpRow0Tag();
 if(s.v[Row0Valid])s.v[Row0Epoch]=d.get_mpRow0Epoch();
 if(s.v[Row0Valid])s.v[Row0Bound]=d.get_mpRow0Bound();
 s.v[Row1Valid]=d.get_mpRow1Valid();
 if(s.v[Row1Valid])s.v[Row1State]=d.get_mpRow1State();
 if(s.v[Row1Valid])s.v[Row1Index]=d.get_mpRow1Index();
 if(s.v[Row1Valid])s.v[Row1Tag]=d.get_mpRow1Tag();
 if(s.v[Row1Valid])s.v[Row1Epoch]=d.get_mpRow1Epoch();
 if(s.v[Row1Valid])s.v[Row1Bound]=d.get_mpRow1Bound();
 s.v[Row2Valid]=d.get_mpRow2Valid();
 if(s.v[Row2Valid])s.v[Row2State]=d.get_mpRow2State();
 if(s.v[Row2Valid])s.v[Row2Index]=d.get_mpRow2Index();
 if(s.v[Row2Valid])s.v[Row2Tag]=d.get_mpRow2Tag();
 if(s.v[Row2Valid])s.v[Row2Epoch]=d.get_mpRow2Epoch();
 if(s.v[Row2Valid])s.v[Row2Bound]=d.get_mpRow2Bound();
 s.v[Row3Valid]=d.get_mpRow3Valid();
 if(s.v[Row3Valid])s.v[Row3State]=d.get_mpRow3State();
 if(s.v[Row3Valid])s.v[Row3Index]=d.get_mpRow3Index();
 if(s.v[Row3Valid])s.v[Row3Tag]=d.get_mpRow3Tag();
 if(s.v[Row3Valid])s.v[Row3Epoch]=d.get_mpRow3Epoch();
 if(s.v[Row3Valid])s.v[Row3Bound]=d.get_mpRow3Bound();
 s.v[Row4Valid]=d.get_mpRow4Valid();
 if(s.v[Row4Valid])s.v[Row4State]=d.get_mpRow4State();
 if(s.v[Row4Valid])s.v[Row4Index]=d.get_mpRow4Index();
 if(s.v[Row4Valid])s.v[Row4Tag]=d.get_mpRow4Tag();
 if(s.v[Row4Valid])s.v[Row4Epoch]=d.get_mpRow4Epoch();
 if(s.v[Row4Valid])s.v[Row4Bound]=d.get_mpRow4Bound();
 s.v[Row5Valid]=d.get_mpRow5Valid();
 if(s.v[Row5Valid])s.v[Row5State]=d.get_mpRow5State();
 if(s.v[Row5Valid])s.v[Row5Index]=d.get_mpRow5Index();
 if(s.v[Row5Valid])s.v[Row5Tag]=d.get_mpRow5Tag();
 if(s.v[Row5Valid])s.v[Row5Epoch]=d.get_mpRow5Epoch();
 if(s.v[Row5Valid])s.v[Row5Bound]=d.get_mpRow5Bound();
 s.v[Row6Valid]=d.get_mpRow6Valid();
 if(s.v[Row6Valid])s.v[Row6State]=d.get_mpRow6State();
 if(s.v[Row6Valid])s.v[Row6Index]=d.get_mpRow6Index();
 if(s.v[Row6Valid])s.v[Row6Tag]=d.get_mpRow6Tag();
 if(s.v[Row6Valid])s.v[Row6Epoch]=d.get_mpRow6Epoch();
 if(s.v[Row6Valid])s.v[Row6Bound]=d.get_mpRow6Bound();
 s.v[Row7Valid]=d.get_mpRow7Valid();
 if(s.v[Row7Valid])s.v[Row7State]=d.get_mpRow7State();
 if(s.v[Row7Valid])s.v[Row7Index]=d.get_mpRow7Index();
 if(s.v[Row7Valid])s.v[Row7Tag]=d.get_mpRow7Tag();
 if(s.v[Row7Valid])s.v[Row7Epoch]=d.get_mpRow7Epoch();
 if(s.v[Row7Valid])s.v[Row7Bound]=d.get_mpRow7Bound();
 s.v[Row8Valid]=d.get_mpRow8Valid();
 if(s.v[Row8Valid])s.v[Row8State]=d.get_mpRow8State();
 if(s.v[Row8Valid])s.v[Row8Index]=d.get_mpRow8Index();
 if(s.v[Row8Valid])s.v[Row8Tag]=d.get_mpRow8Tag();
 if(s.v[Row8Valid])s.v[Row8Epoch]=d.get_mpRow8Epoch();
 if(s.v[Row8Valid])s.v[Row8Bound]=d.get_mpRow8Bound();
 s.v[Row9Valid]=d.get_mpRow9Valid();
 if(s.v[Row9Valid])s.v[Row9State]=d.get_mpRow9State();
 if(s.v[Row9Valid])s.v[Row9Index]=d.get_mpRow9Index();
 if(s.v[Row9Valid])s.v[Row9Tag]=d.get_mpRow9Tag();
 if(s.v[Row9Valid])s.v[Row9Epoch]=d.get_mpRow9Epoch();
 if(s.v[Row9Valid])s.v[Row9Bound]=d.get_mpRow9Bound();
 s.v[Row10Valid]=d.get_mpRow10Valid();
 if(s.v[Row10Valid])s.v[Row10State]=d.get_mpRow10State();
 if(s.v[Row10Valid])s.v[Row10Index]=d.get_mpRow10Index();
 if(s.v[Row10Valid])s.v[Row10Tag]=d.get_mpRow10Tag();
 if(s.v[Row10Valid])s.v[Row10Epoch]=d.get_mpRow10Epoch();
 if(s.v[Row10Valid])s.v[Row10Bound]=d.get_mpRow10Bound();
 s.v[Row11Valid]=d.get_mpRow11Valid();
 if(s.v[Row11Valid])s.v[Row11State]=d.get_mpRow11State();
 if(s.v[Row11Valid])s.v[Row11Index]=d.get_mpRow11Index();
 if(s.v[Row11Valid])s.v[Row11Tag]=d.get_mpRow11Tag();
 if(s.v[Row11Valid])s.v[Row11Epoch]=d.get_mpRow11Epoch();
 if(s.v[Row11Valid])s.v[Row11Bound]=d.get_mpRow11Bound();
 s.v[Row12Valid]=d.get_mpRow12Valid();
 if(s.v[Row12Valid])s.v[Row12State]=d.get_mpRow12State();
 if(s.v[Row12Valid])s.v[Row12Index]=d.get_mpRow12Index();
 if(s.v[Row12Valid])s.v[Row12Tag]=d.get_mpRow12Tag();
 if(s.v[Row12Valid])s.v[Row12Epoch]=d.get_mpRow12Epoch();
 if(s.v[Row12Valid])s.v[Row12Bound]=d.get_mpRow12Bound();
 s.v[Row13Valid]=d.get_mpRow13Valid();
 if(s.v[Row13Valid])s.v[Row13State]=d.get_mpRow13State();
 if(s.v[Row13Valid])s.v[Row13Index]=d.get_mpRow13Index();
 if(s.v[Row13Valid])s.v[Row13Tag]=d.get_mpRow13Tag();
 if(s.v[Row13Valid])s.v[Row13Epoch]=d.get_mpRow13Epoch();
 if(s.v[Row13Valid])s.v[Row13Bound]=d.get_mpRow13Bound();
 s.v[Row14Valid]=d.get_mpRow14Valid();
 if(s.v[Row14Valid])s.v[Row14State]=d.get_mpRow14State();
 if(s.v[Row14Valid])s.v[Row14Index]=d.get_mpRow14Index();
 if(s.v[Row14Valid])s.v[Row14Tag]=d.get_mpRow14Tag();
 if(s.v[Row14Valid])s.v[Row14Epoch]=d.get_mpRow14Epoch();
 if(s.v[Row14Valid])s.v[Row14Bound]=d.get_mpRow14Bound();
 s.v[Row15Valid]=d.get_mpRow15Valid();
 if(s.v[Row15Valid])s.v[Row15State]=d.get_mpRow15State();
 if(s.v[Row15Valid])s.v[Row15Index]=d.get_mpRow15Index();
 if(s.v[Row15Valid])s.v[Row15Tag]=d.get_mpRow15Tag();
 if(s.v[Row15Valid])s.v[Row15Epoch]=d.get_mpRow15Epoch();
 if(s.v[Row15Valid])s.v[Row15Bound]=d.get_mpRow15Bound();
 s.v[Line0Valid]=d.get_mpLine0Valid();
 if(s.v[Line0Valid])s.v[Line0Index]=d.get_mpLine0Index();
 if(s.v[Line0Valid])s.v[Line0Tag]=d.get_mpLine0Tag();
 if(s.v[Line0Valid])s.v[Line0PaLine]=d.get_mpLine0PaLine();
 s.v[Line1Valid]=d.get_mpLine1Valid();
 if(s.v[Line1Valid])s.v[Line1Index]=d.get_mpLine1Index();
 if(s.v[Line1Valid])s.v[Line1Tag]=d.get_mpLine1Tag();
 if(s.v[Line1Valid])s.v[Line1PaLine]=d.get_mpLine1PaLine();
 s.v[Line2Valid]=d.get_mpLine2Valid();
 if(s.v[Line2Valid])s.v[Line2Index]=d.get_mpLine2Index();
 if(s.v[Line2Valid])s.v[Line2Tag]=d.get_mpLine2Tag();
 if(s.v[Line2Valid])s.v[Line2PaLine]=d.get_mpLine2PaLine();
 s.v[Line3Valid]=d.get_mpLine3Valid();
 if(s.v[Line3Valid])s.v[Line3Index]=d.get_mpLine3Index();
 if(s.v[Line3Valid])s.v[Line3Tag]=d.get_mpLine3Tag();
 if(s.v[Line3Valid])s.v[Line3PaLine]=d.get_mpLine3PaLine();
 s.v[PfAlloc]=d.get_mpPfAlloc();
 if(s.v[PfAlloc])s.v[PfPa]=d.get_mpPfPa();
 if(s.v[PfAlloc])s.v[PfSlot]=d.get_mpPfSlot();
 s.v[DemandAlloc]=d.get_mpDemandAlloc();
 if(s.v[DemandAlloc])s.v[DemandPa]=d.get_mpDemandPa();
 if(s.v[DemandAlloc])s.v[DemandSlot]=d.get_mpDemandSlot();
 s.v[Refill]=d.get_mpRefill();
 if(s.v[Refill])s.v[RefillPa]=d.get_mpRefillPa();
 if(s.v[Refill])s.v[RefillSlot]=d.get_mpRefillSlot();
 if(s.v[Refill])s.v[RefillPrefetch]=d.get_mpRefillPrefetch();
 s.v[MshrLive]=d.get_mpMshrLive();
 s.v[MshrPrefetch]=d.get_mpMshrPrefetch();
 s.v[TlAValid]=d.get_mpTlAValid();
 s.v[TlAReady]=d.get_mpTlAReady();
 if(s.v[TlAValid])s.v[TlAAddress]=d.get_mpTlAAddress();
 if(s.v[TlAValid])s.v[TlASource]=d.get_mpTlASource();
 if(s.v[TlAValid])s.v[TlAOpcode]=d.get_mpTlAOpcode();
 if(s.v[TlAValid])s.v[TlASize]=d.get_mpTlASize();
 s.v[TlDValid]=d.get_mpTlDValid();
 s.v[TlDReady]=d.get_mpTlDReady();
 if(s.v[TlDValid])s.v[TlDSource]=d.get_mpTlDSource();
 if(s.v[TlDValid])s.v[TlDOpcode]=d.get_mpTlDOpcode();
 if(s.v[TlDValid])s.v[TlDSize]=d.get_mpTlDSize();
 s.v[OtherValid]=d.get_mpOtherValid();
 s.v[OtherReady]=d.get_mpOtherReady();
 if(s.v[OtherValid])s.v[OtherPa]=d.get_mpOtherPa();
 if(s.v[OtherValid])s.v[OtherSize]=d.get_mpOtherSize();
 if(s.v[OtherValid])s.v[OtherWrite]=d.get_mpOtherWrite();
 s.v[OtherResponseValid]=d.get_mpOtherResponseValid();
 s.v[OtherResponseReady]=d.get_mpOtherResponseReady();
 s.v[FetchAccepted]=d.get_mpFetchAccepted();
 if(s.v[FetchAccepted])s.v[FetchPa]=d.get_mpFetchPa();
 if(s.v[FetchAccepted])s.v[FetchSize]=d.get_mpFetchSize();
 for(unsigned i=0;i<2;++i)if((s.v[MshrLive]>>i)&1)s.mshrPa[i]=d.board$platform$privateCache$pending$$address[i];
 s.stage={d.get_perfEvents(),d.get_perfOccupancy(),d.get_perfSupply(),d.get_perfCapture(),d.get_perfRename(),d.get_perfDiscard(),d.get_perfTranslationPhase(),d.get_backendEvents()};
 s.ar=d.get_io$$ddrAxi$$ar$$valid()&&m.arReady;if(s.ar){s.arAddress=uint64_t(ramBase)+d.get_io$$ddrAxi$$ar$$bits$$addr();s.arBurst=d.get_io$$ddrAxi$$ar$$bits$$burst();s.arId=d.get_io$$ddrAxi$$ar$$bits$$id();s.arLen=d.get_io$$ddrAxi$$ar$$bits$$len();s.arSize=d.get_io$$ddrAxi$$ar$$bits$$size();}
 s.r=m.rValid;s.rReady=d.get_io$$ddrAxi$$r$$ready();if(s.r){auto r=m.selected();need(r!=m.pendingReads.end(),"frontier R visible without actual DDR owner");s.rId=r->id;s.rLast=r->beat+1==r->count;}
 return s;}
class Observer {
 std::ofstream log;bool opened=false,pending=false,seen=false,ended=false;Raw prior;uint64_t last=0,sequence=0,begin=0,end=0,cycles=0;
 std::array<std::array<uint64_t,6>,16> rows{};
 std::array<std::array<uint64_t,4>,4> liveLines{};
 std::array<uint64_t,17> reserved{},allowed{},bound{},credit{};
 std::array<uint64_t,4> grants{};
 uint64_t queries=0,hits=0,results=0,inserts=0,frontierStarts=0,originalStarts=0;
 bool contextLive=false;uint64_t contextBegin=0,contextEnd=0;std::array<uint64_t,23> context{};
 void contextFlush(uint64_t cycle){if(!contextLive)return;prefix("span",cycle);log<<",\"begin\":"<<contextBegin<<",\"end\":"<<contextEnd<<",\"state\":[";for(unsigned i=0;i<context.size();++i){if(i)log<<',';log<<context[i];}log<<']';finishRow();}
 void contextSample(const Raw&s){const auto&v=s.v;std::array<uint64_t,23> state={uint64_t(s.roi),v[Enabled],v[Epoch],v[Stable],v[Reserved],v[Allowed],v[Bound],v[ReadSelectedGrant],v[ReadCandidateGrant],v[ReadScanGrant],v[WriteGrant],v[Pause],v[Flush],v[MshrLive],v[MshrPrefetch],s.stage[0],s.stage[1],s.stage[2],s.stage[3],s.stage[4],s.stage[5],s.stage[6],s.stage[7]};if(contextLive&&state!=context){contextFlush(s.cycle);contextLive=false;}if(!contextLive){contextBegin=s.cycle;context=state;contextLive=true;}contextEnd=s.cycle+1;}

 void prefix(const char*event,uint64_t cycle){log<<"{\"event\":\""<<event<<"\",\"sequence\":"<<sequence++<<",\"cycle\":"<<cycle;}
 void accepted(const char*event,const Raw&s){prefix(event,s.cycle);log<<",\"offer_cycle\":"<<s.cycle<<",\"accepted_cycle\":"<<s.cycle+1<<",\"roi\":"<<s.roi;}
 void finishRow(){log<<"}\n";}
 template<size_t N>static void histogram(std::ostream&o,const std::array<uint64_t,N>&a){o<<'[';for(size_t i=0;i<N;++i){if(i)o<<',';o<<a[i];}o<<']';}
 void consume(const Raw&s){const auto&v=s.v;
  if(s.reset)return;
  contextSample(s);
  need(v[Reserved]+v[Allowed]<=16&&v[Bound]<=v[Allowed],"proof bank credit/bound conservation");
  need(v[ReadSelectedGrant]+v[ReadCandidateGrant]+v[ReadScanGrant]<=1,"proof bank payload read overgrant");
  if(s.roi){need(!ended,"proof trace disjoint ROI");if(!cycles)begin=s.cycle;end=s.cycle+1;++cycles;++reserved[v[Reserved]];++allowed[v[Allowed]];++bound[v[Bound]];++credit[v[Reserved]+v[Allowed]];grants[0]+=v[ReadSelectedGrant];grants[1]+=v[ReadCandidateGrant];grants[2]+=v[ReadScanGrant];grants[3]+=v[WriteGrant];queries+=v[QueryValid];hits+=v[QueryHit];results+=v[ResultValid];inserts+=v[ResultInserted];frontierStarts+=v[StartAccepted]&&v[StartFrontier];originalStarts+=v[StartAccepted]&&!v[StartFrontier];}else if(cycles)ended=true;

  if(v[AdmissionValid]){accepted("admission",s);
   log<<",\"index\":"<<v[AdmissionIndex];
   log<<",\"tag\":"<<v[AdmissionTag];
   log<<",\"epoch\":"<<v[AdmissionEpoch];
   log<<",\"va\":"<<v[AdmissionVa];
   log<<",\"write\":"<<v[AdmissionWrite];
   log<<",\"size\":"<<v[AdmissionSize];
   log<<",\"row\":"<<v[AdmissionRow];
   finishRow();}
  if(v[QueryValid]){accepted("query",s);
   log<<",\"index\":"<<v[QueryIndex];
   log<<",\"tag\":"<<v[QueryTag];
   log<<",\"epoch\":"<<v[QueryEpoch];
   log<<",\"va\":"<<v[QueryVa];
   log<<",\"pa\":"<<v[QueryPa];
   log<<",\"write\":"<<v[QueryWrite];
   log<<",\"size\":"<<v[QuerySize];
   log<<",\"mask\":"<<v[QueryMask];
   log<<",\"row\":"<<v[QueryRow];
   log<<",\"hit\":"<<v[QueryHit];
   if(v[QueryHit])log<<",\"hitpa\":"<<v[QueryHitPa];
   if(v[QueryHit])log<<",\"hitepoch\":"<<v[QueryHitEpoch];
   if(v[QueryHit])log<<",\"hitpbmt\":"<<v[QueryHitPbmt];
   finishRow();}
  if(v[ResultValid]){accepted("result",s);
   log<<",\"index\":"<<v[ResultIndex];
   log<<",\"tag\":"<<v[ResultTag];
   log<<",\"epoch\":"<<v[ResultEpoch];
   log<<",\"va\":"<<v[ResultVa];
   log<<",\"pa\":"<<v[ResultPa];
   log<<",\"write\":"<<v[ResultWrite];
   log<<",\"size\":"<<v[ResultSize];
   log<<",\"mask\":"<<v[ResultMask];
   log<<",\"row\":"<<v[ResultRow];
   log<<",\"allowed\":"<<v[ResultAllowed];
   log<<",\"ownermatches\":"<<v[ResultOwnerMatches];
   log<<",\"reservation\":"<<v[ResultReservation];
   log<<",\"inserted\":"<<v[ResultInserted];
   finishRow();}
  if(v[FrontierAccepted]){accepted("frontier",s);
   log<<",\"index\":"<<v[FrontierIndex];
   log<<",\"tag\":"<<v[FrontierTag];
   log<<",\"epoch\":"<<v[FrontierEpoch];
   log<<",\"va\":"<<v[FrontierVa];
   log<<",\"pa\":"<<v[FrontierPa];
   log<<",\"write\":"<<v[FrontierWrite];
   log<<",\"size\":"<<v[FrontierSize];
   log<<",\"mask\":"<<v[FrontierMask];
   log<<",\"row\":"<<v[FrontierRow];
   log<<",\"accepted\":"<<v[FrontierAccepted];
   log<<",\"covered\":"<<v[FrontierCovered];
   log<<",\"relied\":"<<v[FrontierRelied];
   finishRow();}
  if(v[StartAccepted]){accepted("start",s);
   log<<",\"index\":"<<v[StartIndex];
   log<<",\"tag\":"<<v[StartTag];
   log<<",\"epoch\":"<<v[StartEpoch];
   log<<",\"va\":"<<v[StartVa];
   log<<",\"pa\":"<<v[StartPa];
   log<<",\"size\":"<<v[StartSize];
   log<<",\"store\":"<<v[StartStore];
   log<<",\"atomic\":"<<v[StartAtomic];
   log<<",\"prechecked\":"<<v[StartPrechecked];
   log<<",\"parallel\":"<<v[StartParallel];
   log<<",\"slot\":"<<v[StartSlot];
   log<<",\"frontier\":"<<v[StartFrontier];
   log<<",\"ishead\":"<<v[StartIsHead];
   finishRow();}
  {std::array<uint64_t,6> row={v[Row0Valid],v[Row0State],v[Row0Index],v[Row0Tag],v[Row0Epoch],v[Row0Bound]};if(row!=rows[0]){prefix("row_state",s.cycle);log<<",\"row\":0,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[0]=row;}}
  {std::array<uint64_t,6> row={v[Row1Valid],v[Row1State],v[Row1Index],v[Row1Tag],v[Row1Epoch],v[Row1Bound]};if(row!=rows[1]){prefix("row_state",s.cycle);log<<",\"row\":1,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[1]=row;}}
  {std::array<uint64_t,6> row={v[Row2Valid],v[Row2State],v[Row2Index],v[Row2Tag],v[Row2Epoch],v[Row2Bound]};if(row!=rows[2]){prefix("row_state",s.cycle);log<<",\"row\":2,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[2]=row;}}
  {std::array<uint64_t,6> row={v[Row3Valid],v[Row3State],v[Row3Index],v[Row3Tag],v[Row3Epoch],v[Row3Bound]};if(row!=rows[3]){prefix("row_state",s.cycle);log<<",\"row\":3,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[3]=row;}}
  {std::array<uint64_t,6> row={v[Row4Valid],v[Row4State],v[Row4Index],v[Row4Tag],v[Row4Epoch],v[Row4Bound]};if(row!=rows[4]){prefix("row_state",s.cycle);log<<",\"row\":4,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[4]=row;}}
  {std::array<uint64_t,6> row={v[Row5Valid],v[Row5State],v[Row5Index],v[Row5Tag],v[Row5Epoch],v[Row5Bound]};if(row!=rows[5]){prefix("row_state",s.cycle);log<<",\"row\":5,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[5]=row;}}
  {std::array<uint64_t,6> row={v[Row6Valid],v[Row6State],v[Row6Index],v[Row6Tag],v[Row6Epoch],v[Row6Bound]};if(row!=rows[6]){prefix("row_state",s.cycle);log<<",\"row\":6,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[6]=row;}}
  {std::array<uint64_t,6> row={v[Row7Valid],v[Row7State],v[Row7Index],v[Row7Tag],v[Row7Epoch],v[Row7Bound]};if(row!=rows[7]){prefix("row_state",s.cycle);log<<",\"row\":7,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[7]=row;}}
  {std::array<uint64_t,6> row={v[Row8Valid],v[Row8State],v[Row8Index],v[Row8Tag],v[Row8Epoch],v[Row8Bound]};if(row!=rows[8]){prefix("row_state",s.cycle);log<<",\"row\":8,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[8]=row;}}
  {std::array<uint64_t,6> row={v[Row9Valid],v[Row9State],v[Row9Index],v[Row9Tag],v[Row9Epoch],v[Row9Bound]};if(row!=rows[9]){prefix("row_state",s.cycle);log<<",\"row\":9,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[9]=row;}}
  {std::array<uint64_t,6> row={v[Row10Valid],v[Row10State],v[Row10Index],v[Row10Tag],v[Row10Epoch],v[Row10Bound]};if(row!=rows[10]){prefix("row_state",s.cycle);log<<",\"row\":10,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[10]=row;}}
  {std::array<uint64_t,6> row={v[Row11Valid],v[Row11State],v[Row11Index],v[Row11Tag],v[Row11Epoch],v[Row11Bound]};if(row!=rows[11]){prefix("row_state",s.cycle);log<<",\"row\":11,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[11]=row;}}
  {std::array<uint64_t,6> row={v[Row12Valid],v[Row12State],v[Row12Index],v[Row12Tag],v[Row12Epoch],v[Row12Bound]};if(row!=rows[12]){prefix("row_state",s.cycle);log<<",\"row\":12,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[12]=row;}}
  {std::array<uint64_t,6> row={v[Row13Valid],v[Row13State],v[Row13Index],v[Row13Tag],v[Row13Epoch],v[Row13Bound]};if(row!=rows[13]){prefix("row_state",s.cycle);log<<",\"row\":13,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[13]=row;}}
  {std::array<uint64_t,6> row={v[Row14Valid],v[Row14State],v[Row14Index],v[Row14Tag],v[Row14Epoch],v[Row14Bound]};if(row!=rows[14]){prefix("row_state",s.cycle);log<<",\"row\":14,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[14]=row;}}
  {std::array<uint64_t,6> row={v[Row15Valid],v[Row15State],v[Row15Index],v[Row15Tag],v[Row15Epoch],v[Row15Bound]};if(row!=rows[15]){prefix("row_state",s.cycle);log<<",\"row\":15,\"valid\":"<<row[0];if(row[0])log<<",\"state\":"<<row[1]<<",\"index\":"<<row[2]<<",\"tag\":"<<row[3]<<",\"epoch\":"<<row[4]<<",\"bound\":"<<row[5];finishRow();rows[15]=row;}}
  {std::array<uint64_t,4> line={v[Line0Valid],v[Line0Index],v[Line0Tag],v[Line0PaLine]};if(line!=liveLines[0]){prefix("line_state",s.cycle);log<<",\"slot\":0,\"valid\":"<<line[0];if(line[0])log<<",\"index\":"<<line[1]<<",\"tag\":"<<line[2]<<",\"pa_line\":"<<line[3]<<",\"context_epoch\":"<<v[Epoch];finishRow();liveLines[0]=line;}}
  {std::array<uint64_t,4> line={v[Line1Valid],v[Line1Index],v[Line1Tag],v[Line1PaLine]};if(line!=liveLines[1]){prefix("line_state",s.cycle);log<<",\"slot\":1,\"valid\":"<<line[0];if(line[0])log<<",\"index\":"<<line[1]<<",\"tag\":"<<line[2]<<",\"pa_line\":"<<line[3]<<",\"context_epoch\":"<<v[Epoch];finishRow();liveLines[1]=line;}}
  {std::array<uint64_t,4> line={v[Line2Valid],v[Line2Index],v[Line2Tag],v[Line2PaLine]};if(line!=liveLines[2]){prefix("line_state",s.cycle);log<<",\"slot\":2,\"valid\":"<<line[0];if(line[0])log<<",\"index\":"<<line[1]<<",\"tag\":"<<line[2]<<",\"pa_line\":"<<line[3]<<",\"context_epoch\":"<<v[Epoch];finishRow();liveLines[2]=line;}}
  {std::array<uint64_t,4> line={v[Line3Valid],v[Line3Index],v[Line3Tag],v[Line3PaLine]};if(line!=liveLines[3]){prefix("line_state",s.cycle);log<<",\"slot\":3,\"valid\":"<<line[0];if(line[0])log<<",\"index\":"<<line[1]<<",\"tag\":"<<line[2]<<",\"pa_line\":"<<line[3]<<",\"context_epoch\":"<<v[Epoch];finishRow();liveLines[3]=line;}}
  if(v[PfAlloc]){accepted("pf_alloc",s);log<<",\"pa\":"<<v[PfPa]<<",\"slot\":"<<v[PfSlot];finishRow();}
  if(v[DemandAlloc]){accepted("demand_alloc",s);log<<",\"pa\":"<<v[DemandPa]<<",\"slot\":"<<v[DemandSlot];finishRow();}
  if(v[Refill]){accepted("refill",s);log<<",\"pa\":"<<v[RefillPa]<<",\"slot\":"<<v[RefillSlot]<<",\"prefetch\":"<<v[RefillPrefetch];finishRow();}
  if(v[TlAValid]&&v[TlAReady]){accepted("tl_a",s);log<<",\"pa\":"<<v[TlAAddress]<<",\"source\":"<<v[TlASource]<<",\"opcode\":"<<v[TlAOpcode]<<",\"size\":"<<v[TlASize]<<",\"mshr_live\":"<<v[MshrLive]<<",\"mshr_pf\":"<<v[MshrPrefetch]<<",\"mshr_pa\":[";for(unsigned i=0;i<2;++i){if(i)log<<',';if((v[MshrLive]>>i)&1)log<<s.mshrPa[i];else log<<"null";}log<<']';finishRow();}
  if(v[TlDValid]){prefix("tl_d_visible",s.cycle);log<<",\"ready\":"<<v[TlDReady]<<",\"source\":"<<v[TlDSource]<<",\"opcode\":"<<v[TlDOpcode]<<",\"size\":"<<v[TlDSize];finishRow();}
  if(v[OtherValid]&&v[OtherReady]){accepted("other_request",s);log<<",\"pa\":"<<v[OtherPa]<<",\"size\":"<<v[OtherSize]<<",\"write\":"<<v[OtherWrite];finishRow();}
  if(v[OtherResponseValid]&&v[OtherResponseReady]){accepted("other_response",s);finishRow();}
  if(v[FetchAccepted]){accepted("fetch_request",s);log<<",\"pa\":"<<v[FetchPa]<<",\"size\":"<<v[FetchSize];finishRow();}
  if(s.ar){accepted("axi_ar",s);log<<",\"pa\":"<<s.arAddress<<",\"id\":"<<s.arId<<",\"len\":"<<s.arLen<<",\"size\":"<<s.arSize<<",\"burst\":"<<s.arBurst<<",\"offset\":"<<s.arAddress-uint64_t(ramBase);finishRow();}
  if(s.r){prefix("axi_r_visible",s.cycle);log<<",\"ready\":"<<s.rReady<<",\"last\":"<<s.rLast<<",\"id\":"<<s.rId;finishRow();}
 }
 public:
 template<class D,class M>void sample(D&d,M&m,uint64_t cycle,bool roi){
  if(!opened){auto p=std::getenv("MEMORY_PROOF_FRONTIER_TRACE");need(p&&*p,"memory proof trace path required");log.open(p);need(bool(log),"memory proof trace open");opened=true;}
  need(!seen||cycle==last+1,"memory proof duplicate/omitted sample");seen=true;last=cycle;Raw now=read(d,m,cycle,roi);
  if(pending){need(!now.reset&&cycle==prior.cycle+1,"proof acceptance next edge/reset mismatch");consume(prior);}
  prior=now;pending=!now.reset;
 }
 void finish(std::ostream&o){contextFlush(last);need(cycles&&end-begin==cycles,"proof ROI coverage");prefix("terminal",last);log<<",\"roi_first\":"<<begin<<",\"roi_end\":"<<end<<",\"roi_cycles\":"<<cycles<<",\"unaccepted_last_sample\":"<<pending;finishRow();log.flush();need(bool(log),"proof trace flush");
  o<<"MEMORY_PROOF_FRONTIER {\"cycles\":"<<cycles<<",\"roi_first\":"<<begin<<",\"roi_end\":"<<end<<",\"queries\":"<<queries<<",\"query_hits\":"<<hits<<",\"results\":"<<results<<",\"inserted\":"<<inserts<<",\"frontier_starts\":"<<frontierStarts<<",\"original_starts\":"<<originalStarts<<",\"reserved_histogram\":";histogram(o,reserved);o<<",\"allowed_histogram\":";histogram(o,allowed);o<<",\"bound_histogram\":";histogram(o,bound);o<<",\"credit_histogram\":";histogram(o,credit);o<<",\"grants_selected_candidate_scan_write\":";histogram(o,grants);o<<",\"token_index_bits\":6,\"token_tag_bits\":64,\"epoch_bits\":32,\"acceptance_confirmed_by_next_sample\":true}\n";
 }
};
}
