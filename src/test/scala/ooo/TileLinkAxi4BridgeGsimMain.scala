package ooo

import _root_.circt.stage.ChiselStage
import soc.core.ooo.TileLinkAxi4Bridge
import soc.bus.tilelink.TLParams

object TileLinkAxi4BridgeGsimMain extends App {
    val addressWidth = args.lift(1).map(_.toInt).getOrElse(64)
    val maxWrites = args.lift(2).map(_.toInt).getOrElse(4)
    val burstEnabled = args.lift(3).contains("burst")
    val maxBurstBeats = args.lift(4).map(_.toInt).getOrElse(16)
    val tlParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3,
        sizeBits = if (maxBurstBeats > 16) 4 else 3)
    ChiselStage.emitCHIRRTLFile(new TileLinkAxi4Bridge(axiAddressWidth = addressWidth,
        maxWrites = maxWrites, burstEnabled = burstEnabled,
        maxBurstBeats = maxBurstBeats, tlParams = tlParams,
        axiAddressBase = args.lift(5).map(BigInt(_)).getOrElse(BigInt(0)),
        axiWindowBytes = args.lift(6).map(BigInt(_)).getOrElse(BigInt(0))),
        Array("--target-dir", args.head))
}

object TileLinkAxi4BridgeRtlMain extends App {
    val addressWidth = args.lift(1).map(_.toInt).getOrElse(64)
    val maxBurstBeats = args.lift(2).map(_.toInt).getOrElse(16)
    val tlParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3,
        sizeBits = if (maxBurstBeats > 16) 4 else 3)
    ChiselStage.emitSystemVerilogFile(
        new TileLinkAxi4Bridge(axiAddressWidth = addressWidth,
            maxBurstBeats = maxBurstBeats, tlParams = tlParams),
        Array("--target-dir", args.head),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
