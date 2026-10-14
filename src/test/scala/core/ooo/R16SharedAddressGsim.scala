package soc.core.ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.reflect.DataMirror
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files,Paths}
import _root_.ooo.{R16SharedAddressNative, PostedBoardConfiguration}

/** Exact current backend. Environment inputs remain public; no internal force ports. */
class R16SharedAddressGsim(shared: Boolean) extends Module {
    val p = _root_.ooo.TimingReady73Profile.on.coreParams.copy(sharedMemoryAddressState=shared)
    val backend = Module(new IntegerBackend(p, registerCanonicalStoreEvent=p.registeredCanonicalStoreEvent,
        retirementSlotIdentity=p.retirementSlotIdentity))
    def expose(data: Data, name: String): Unit = data match {
        case b: Bundle => b.elements.foreach { case (n,x) => expose(x,name+"_"+n) }
        case v: Vec[_] => v.zipWithIndex.foreach { case (x,i) => expose(x,name+"_"+i) }
        case leaf =>
            val input = DataMirror.directionOf(leaf) == ActualDirection.Input
            val port = IO(if (input) Input(chiselTypeOf(leaf)) else Output(chiselTypeOf(leaf)))
            port.suggestName(name)
            if (input) leaf := port else port := leaf
    }
    expose(backend.io,"io")
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
object R16SharedAddressGsimMain extends App {
    require(args.length == 2 && Set("off","on").contains(args(1)))
    val out = Paths.get(args(0)); require(!Files.exists(out), "fresh output required")
    var actual: Option[OooParams] = None
    ChiselStage.emitCHIRRTLFile({val d = new R16SharedAddressGsim(args(1)=="on");actual=Some(d.backend.p);d}, Array("--target-dir",out.toString))
    Files.writeString(out.resolve("actual-core.json"),PostedBoardConfiguration.json(actual.get)+"\n")
}
