package ooo

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.TLParams
import soc.core.ooo._

/** New opt-in tested separately; existing HomeLookupFactoryConfigMain remains unchanged. */
object SharedFuture75FactoryConfigMain extends App {
    def check(future: Boolean, allow: Boolean, expected: Boolean, lines: Int = 512): Unit = {
        ChiselStage.elaborate(new Module {
            val home = CoherentLineHomeModule.build(TLParams(addrWidth=64,dataWidth=64,sourceBits=3,sinkBits=1),
                BigInt("80200000",16), BigInt(2)*1024*1024*1024, trackedLines=lines, trackedWays=2,
                acquireEntries=2, writebackEntries=2, mixedReadWrite=true,
                tagConfig=CacheTagConfig(compact=true,bankedStorage=true), dmaLineTransfers=true,
                dmaLineEntries=4, lineTransferDispatchFlow=true, lineReadChannel=true,
                internalLineGrant=true, memoryScheduleOverlap=true, futureHomeWayReservation=future,
                allowSharedFutureLookup=allow)
            require(home.asInstanceOf[MixedCoherentLineHome].sharedLookupMatch == expected)
            require(home.asInstanceOf[MixedCoherentLineHome].futureWayReservation == future)
        })
    }
    check(false, false, true) // Existing73/74 geometry.
    check(true, false, false) // Existing future profiles remain unshared by default.
    check(true, true, true) // Explicit new75 combination.
    var rejected = 0
    def reject(body: => Unit): Unit = {
        var failed = false
        try { body } catch { case _: IllegalArgumentException => failed = true }
        require(failed); rejected += 1
    }
    reject { check(false, true, true) }
    reject { check(true, true, true, lines=256) }
    println(s"PASS_SHARED_FUTURE75_FACTORY positive=3 negative=$rejected")
}
