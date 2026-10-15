package soc.core.ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.reflect.DataMirror
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files,Paths}
import _root_.ooo.{PostedBoardConfiguration}

/** Exact current backend. Environment inputs remain public; no internal force ports. */
class R16SharedAddressLifecycleBare(shared: Boolean) extends Module {
    val p = _root_.ooo.TimingReady73Profile.on.coreParams.copy(sharedMemoryAddressState=shared)
    val backend = Module(new IntegerBackend(p, registerCanonicalStoreEvent=p.registeredCanonicalStoreEvent,
        retirementSlotIdentity=p.retirementSlotIdentity))
    def expose(data: Data, name: String): Unit = data match {
        case b: Bundle => b.elements.foreach { case (n,x) => expose(x,name+"_"+n) }
        case v: Vec[_] => v.zipWithIndex.foreach { case (x,i) => expose(x,name+"_"+i) }
        case leaf if name.startsWith("io_loadPrecheck_response") => ()
        case leaf =>
            val input = DataMirror.directionOf(leaf) == ActualDirection.Input
            val port = IO(if (input) Input(chiselTypeOf(leaf)) else Output(chiselTypeOf(leaf)))
            port.suggestName(name)
            if (input) leaf := port else port := leaf
    }
    expose(backend.io,"io")
    require(p.productArity == 177 && p.robEntries == 16 && p.physicalRegs == 48 &&
        p.memoryEntries == 4 && p.issueWidth == 2 && p.tagBits == 64 &&
        !p.reconstructIssueTokenIndex && !p.memoryProofFrontier)
    // One effective response driver. There are no host response ports for this lookup.
    val mappingEnable = IO(Input(Bool()))
    val mappingRead = IO(Input(Bool()))
    val mappingWrite = IO(Input(Bool()))
    val mappingEpoch = IO(Input(UInt(32.W)))
    val lookup = backend.io.loadPrecheck.get
    val query = lookup.request.bits
    val transferBytes = MuxLookup(query.size, 0.U(13.W))(Seq(
        0.U -> 1.U(13.W), 1.U -> 2.U(13.W), 2.U -> 4.U(13.W), 3.U -> 8.U(13.W)))
    val alignmentMask = MuxLookup(query.size, 7.U(3.W))(Seq(0.U -> 0.U, 1.U -> 1.U, 2.U -> 3.U))
    val legal = query.size <= 3.U && (query.address(2,0) & alignmentMask) === 0.U &&
        (Cat(0.U(1.W), query.address(11,0)) + transferBytes) <= 4096.U
    lookup.response.valid := lookup.request.valid && mappingEnable && lookup.stable &&
        mappingEpoch === lookup.epoch && query.address(63,12) === "h80401".U && legal &&
        Mux(query.write, mappingWrite, mappingRead)
    lookup.response.bits.physicalAddress := Cat("h80201".U(52.W), query.address(11,0))
    lookup.response.bits.pbmt := 0.U
    lookup.response.bits.epoch := mappingEpoch
    val instruction0 = IO(Input(Valid(UInt(32.W))))
    val instruction1 = IO(Input(Valid(UInt(32.W))))
    val pc0 = IO(Input(UInt(64.W)))
    val pc1 = IO(Input(UInt(64.W)))
    val instructions = Seq(instruction0,instruction1)
    val pcs = Seq(pc0,pc1)
    for (i <- 0 until 2) {
        val decode = Module(new IntegerDecode(enableSystem = true, enableAtomic = true,
            parallelLegality = p.parallelDecodeLegality, parallelBitLegality = p.parallelBitLegality))
        decode.io.instruction := instructions(i).bits
        decode.io.pc := pcs(i)
        backend.io.allocate(i).valid := instructions(i).valid
        backend.io.allocate(i).bits := decode.io.decoded
        backend.io.rawDestinations.foreach(_(i) := decode.io.decoded.rename.rd)
        backend.io.rawRequests.foreach(_(i) := decode.io.decoded.rename)
    }

}
object R16SharedAddressLifecycleBareMain extends App {
    require(args.length == 2 && Set("off","on").contains(args(1)))
    val out = Paths.get(args(0)); require(!Files.exists(out), "fresh output required")
    var actual: Option[OooParams] = None
    ChiselStage.emitCHIRRTLFile({val d = new R16SharedAddressLifecycleBare(args(1)=="on");actual=Some(d.backend.p);d}, Array("--target-dir",out.toString))
    Files.writeString(out.resolve("actual-core.json"),PostedBoardConfiguration.json(actual.get)+"\n")
}
