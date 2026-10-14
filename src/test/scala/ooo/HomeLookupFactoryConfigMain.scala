package ooo
import chisel3._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.TLParams
import soc.core.ooo._
object HomeLookupFactoryConfigMain extends App {
    val configurations = Seq((true, 512, 4, false, true), (false, 512, 4, false, false),
        (true, 256, 4, false, false), (true, 512, 2, false, false), (true, 512, 4, true, false))
    for ((overlap, lines, dmaEntries, future, expected) <- configurations) {
        ChiselStage.elaborate(new Module {
            val h = CoherentLineHomeModule.build(TLParams(addrWidth=64,dataWidth=64,sourceBits=3,sinkBits=1),
                BigInt("80200000",16), BigInt(2)*1024*1024*1024, trackedLines=lines, trackedWays=2,
                acquireEntries=2, writebackEntries=2, mixedReadWrite=true,
                tagConfig=CacheTagConfig(compact=true,bankedStorage=true), dmaLineTransfers=true,
                dmaLineEntries=dmaEntries,lineTransferDispatchFlow=true,lineReadChannel=true,
                internalLineGrant=true,memoryScheduleOverlap=overlap,futureHomeWayReservation=future)
            require(h.asInstanceOf[MixedCoherentLineHome].sharedLookupMatch == expected,
                "factory actual shared lookup opt-in differs")
        })
        println(s"HOME_LOOKUP_FACTORY_PASS overlap=$overlap lines=$lines dma=$dmaEntries future=$future shared=$expected")
    }
}
