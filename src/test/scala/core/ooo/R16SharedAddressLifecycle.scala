package soc.core.ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.reflect.DataMirror
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files,Paths}
import _root_.ooo.{PostedBoardConfiguration}

/** Exact current backend. Environment inputs remain public; no internal force ports. */
class R16SharedAddressLifecycle(shared: Boolean) extends Module {
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
    def outputTap[T <: Data](x: T, name: String): Unit = {
        val o = IO(Output(chiselTypeOf(x))); o.suggestName(name)
        // Bore only directionless leaves. A mixed-direction Decoupled aggregate
        // would create a backwards ready connection into the observed module.
        def leaves(source: Data, sink: Data): Unit = source match {
            case b: Bundle => b.elements.foreach { case (n, value) =>
                leaves(value, sink.asInstanceOf[Bundle].elements(n))
            }
            case v: Vec[_] => v.zipWithIndex.foreach { case (value, i) =>
                leaves(value, sink.asInstanceOf[Vec[Data]](i))
            }
            case leaf => sink := BoringUtils.bore(leaf)
        }
        leaves(x, o)
    }
    outputTap(lookup.response, "lookupReply")
    outputTap(backend.pendingStoreProof.get.io.proofs(0), "proof0")
    outputTap(backend.pendingStoreProof.get.io.proofs(1), "proof1")
    outputTap(backend.pendingStoreProof.get.io.bound, "proofBound")
    outputTap(backend.pendingStoreProof.get.io.bind, "proofBind")
    outputTap(backend.pendingStoreProof.get.io.consume, "proofConsume")
    outputTap(backend.pendingStoreRelied, "proofRelied")
    outputTap(backend.pendingStoreBoundMatches, "boundMatches")
    outputTap(backend.pendingStoreCredit.get.io.reserve, "creditReserve")
    outputTap(backend.pendingStoreCredit.get.io.consume, "creditConsume")
    outputTap(backend.lsu.io.start.bits, "startPayload")
    outputTap(backend.lsu.io.complete, "lsuCompletion")
    outputTap(backend.lsu.io.fastLoadPreview, "lsuPreview")
    outputTap(backend.lsu.io.discarded, "lsuDiscarded")
    outputTap(backend.lsu.io.requestOwner, "requestOwner")
    for (i <- 0 until p.memoryEntries) {
        outputTap(backend.lsu.io.live(i), s"slotLive$i")
        outputTap(backend.lsu.io.owner(i), s"slotOwner$i")
        outputTap(backend.lsu.io.cancel(i), s"slotCancel$i")
        outputTap(backend.lsu.io.loadResultPublish.get(i), s"slotPublish$i")
        outputTap(backend.lsu.io.heldLoadValue.get(i), s"slotHeld$i")
    }

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
    val observation = IO(Output(new Bundle {
        val loadWrite = Bool(); val startFire = Bool(); val startStore = Bool(); val startAtomic = Bool()
        val actualIndex = UInt(p.robBits.W); val actualTag = UInt(p.tagBits.W)
        val canonicalAddress = UInt(64.W); val canonicalLanes = UInt(8.W)
        val storeWrites0 = UInt(p.robEntries.W); val storeWrites1 = UInt(p.robEntries.W)
        val killed = UInt(p.robEntries.W)
        val live = UInt(p.robEntries.W); val pending = UInt(p.robEntries.W)
        val known = UInt(p.robEntries.W); val canonical = UInt(p.robEntries.W)
        val replayValid = Bool(); val replayIndex = UInt(p.robBits.W)
    }))
    def tap[T <: Data](x: T): T = BoringUtils.bore(x)
    observation.startFire := tap(backend.lsu.io.start.valid) && tap(backend.lsu.io.start.ready)
    observation.startStore := tap(backend.lsu.io.start.bits.store)
    observation.startAtomic := tap(backend.lsu.io.start.bits.atomic)
    observation.loadWrite := observation.startFire && !observation.startStore && !observation.startAtomic
    observation.actualIndex := tap(backend.actualMemoryIndex)
    observation.actualTag := tap(backend.lsu.io.start.bits.token.tag)
    observation.canonicalAddress := tap(backend.actualCanonicalAddress)
    observation.canonicalLanes := tap(backend.actualLanes)
    observation.storeWrites0 := (if (shared) VecInit((0 until 16).map(i => tap(backend.sharedAddressStoreWrites.get(i)(0)))).asUInt else 0.U)
    observation.storeWrites1 := (if (shared) VecInit((0 until 16).map(i => tap(backend.sharedAddressStoreWrites.get(i)(1)))).asUInt else 0.U)
    observation.killed := VecInit((0 until 16).map(i => tap(backend.killed(i)))).asUInt
    observation.live := VecInit((0 until 16).map(i => tap(backend.memoryLive(i)))).asUInt
    observation.pending := VecInit((0 until 16).map(i => tap(backend.pending(i)))).asUInt
    observation.known := VecInit((0 until 16).map(i => tap(backend.storeAddressKnown(i)))).asUInt
    observation.canonical := VecInit((0 until 16).map(i => tap(backend.memoryCanonical.get(i)))).asUInt
    observation.replayValid := tap(backend.replaySelector.io.valid)
    observation.replayIndex := tap(backend.replaySelector.io.index)
}
object R16SharedAddressLifecycleMain extends App {
    require(args.length == 2 && Set("off","on").contains(args(1)))
    val out = Paths.get(args(0)); require(!Files.exists(out), "fresh output required")
    var actual: Option[OooParams] = None
    ChiselStage.emitCHIRRTLFile({val d = new R16SharedAddressLifecycle(args(1)=="on");actual=Some(d.backend.p);d}, Array("--target-dir",out.toString))
    Files.writeString(out.resolve("actual-core.json"),PostedBoardConfiguration.json(actual.get)+"\n")
}
