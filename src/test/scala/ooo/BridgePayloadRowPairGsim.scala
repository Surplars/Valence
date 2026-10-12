package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.core.ooo.TileLinkAxi4OutstandingBridge
import soc.ip.tilelink.LineReadMemoryPort

/** Actual board-geometry outstanding bridges, differing only in the candidate flag.
  * The host controls every real ingress and supplies an independent byte/owner oracle.
  * instrument_pair_state.py adds complete retained-state and payload comparisons to
  * emitted CHIRRTL, including otherwise inaccessible local arbiter/Queue registers.
  * Every fixture observer is scalar; no nested Vec top accessor is required.
  */
class BridgePayloadRowPairGsim(sizeBits: Int = 3) extends Module {
    require(sizeBits == 3 || sizeBits == 4)
    // The coherent board manager adds one source bit to its four-bit upstream port.
    val p = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 5, sizeBits = sizeBits)
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(p))
        val lineRead = Flipped(new LineReadMemoryPort())
        val ddrAxi = new soc.ip.axi.Axi4MemoryPort(32, 4)
        val mutateCandidateRData = Input(Bool())
        val interfaceEqual = Output(Bool())
        val referenceFlags = Output(UInt(5.W))
        val candidateFlags = Output(UInt(5.W))
        val payloadWriteMask = Output(UInt(64.W))
        val firstWriteSlots = Output(UInt(4.W))
        val continuationSlots = Output(UInt(4.W))
        val readCaptureSlots = Output(UInt(4.W))
        val deniedDrainSlots = Output(UInt(4.W))
        val activeSlots = Output(UInt(4.W))
        val lineSlots = Output(UInt(4.W))
        val collecting = Output(Bool())
        val allocationSlot = Output(UInt(2.W))
        val finishAndAllocate = Output(Bool())
    })
    def make(local: Boolean) = Module(new TileLinkAxi4OutstandingBridge(
        tlParams = p, axiAddressWidth = 32, axiIdWidth = 4, maxBurstBeats = 16,
        axiCache = 0, axiProt = 0, axiQos = 0,
        axiAddressBase = BigInt("80200000", 16), axiWindowBytes = BigInt(1) << 31,
        maxOutstanding = 4, maxOutstandingWrites = 2, unorderedResponses = true,
        writeCollectionFlow = true, lineReadChannel = true, localPayloadWriteEnable = true, localPayloadWriteRow = local))
    val reference = make(false)
    val candidate = make(true)
    val referenceFlags = Seq(reference.localPayloadWriteRow) ++ reference.slots.map(_.localPayloadWriteRow)
    val candidateFlags = Seq(candidate.localPayloadWriteRow) ++ candidate.slots.map(_.localPayloadWriteRow)
    require(referenceFlags.forall(!_))
    require(candidateFlags.forall(identity))
    require(reference.localPayloadWriteEnable && candidate.localPayloadWriteEnable)
    require(reference.slots.forall(_.localPayloadWriteEnable) && candidate.slots.forall(_.localPayloadWriteEnable))
    println(s"ROW_PAIR_CONSTRUCTORS sizeBits=$sizeBits maxBurstBeats=16 localWE=reference:true,true,true,true,true candidate:true,true,true,true,true localRow=reference:${referenceFlags.mkString(",")} candidate:${candidateFlags.mkString(",")}")
    io.referenceFlags := VecInit(referenceFlags.map(_.B)).asUInt
    io.candidateFlags := VecInit(candidateFlags.map(_.B)).asUInt
    io.tl <> reference.io.tl
    io.lineRead <> reference.io.lineRead.get
    io.ddrAxi <> reference.io.axi
    candidate.io.tl.a.valid := io.tl.a.valid
    candidate.io.tl.a.bits := io.tl.a.bits
    candidate.io.tl.b.ready := io.tl.b.ready
    candidate.io.tl.c.valid := io.tl.c.valid
    candidate.io.tl.c.bits := io.tl.c.bits
    candidate.io.tl.d.ready := io.tl.d.ready
    candidate.io.tl.e.valid := io.tl.e.valid
    candidate.io.tl.e.bits := io.tl.e.bits
    candidate.io.lineRead.get.request.valid := io.lineRead.request.valid
    candidate.io.lineRead.get.request.bits := io.lineRead.request.bits
    candidate.io.lineRead.get.response.ready := io.lineRead.response.ready
    candidate.io.axi.ar.ready := io.ddrAxi.ar.ready
    candidate.io.axi.aw.ready := io.ddrAxi.aw.ready
    candidate.io.axi.w.ready := io.ddrAxi.w.ready
    candidate.io.axi.r.valid := io.ddrAxi.r.valid
    candidate.io.axi.r.bits := io.ddrAxi.r.bits
    candidate.io.axi.r.bits.data := io.ddrAxi.r.bits.data ^ io.mutateCandidateRData.asUInt
    candidate.io.axi.b.valid := io.ddrAxi.b.valid
    candidate.io.axi.b.bits := io.ddrAxi.b.bits

    val r = reference.io
    val c = candidate.io
    val pairs = Seq(
        r.tl.a.ready.asUInt -> c.tl.a.ready.asUInt,
        r.tl.b.asUInt -> c.tl.b.asUInt,
        r.tl.c.ready.asUInt -> c.tl.c.ready.asUInt,
        r.tl.d.asUInt -> c.tl.d.asUInt,
        r.tl.e.ready.asUInt -> c.tl.e.ready.asUInt,
        r.axi.ar.asUInt -> c.axi.ar.asUInt,
        r.axi.aw.asUInt -> c.axi.aw.asUInt,
        r.axi.w.asUInt -> c.axi.w.asUInt,
        r.axi.r.ready.asUInt -> c.axi.r.ready.asUInt,
        r.axi.b.ready.asUInt -> c.axi.b.ready.asUInt,
        r.lineRead.get.request.ready.asUInt -> c.lineRead.get.request.ready.asUInt,
        r.lineRead.get.response.asUInt -> c.lineRead.get.response.asUInt)
    io.interfaceEqual := pairs.map { case (a, b) => a === b }.reduce(_ && _)
    assert(io.interfaceEqual, "paired bridge full interface mismatch")

    // These probes observe the original generic event, not a reimplementation of
    // localized WE. The all-memory comparison sees actual writes independently.
    val writeMask = candidate.slots.map { s =>
        val enable = BoringUtils.bore(s.payloadWrite)
        val index = BoringUtils.bore(s.payloadWriteIndex)
        Mux(enable, (1.U(16.W) << index)(15, 0), 0.U(16.W))
    }
    io.payloadWriteMask := Cat(writeMask.reverse)
    io.firstWriteSlots := VecInit(candidate.slots.map { s =>
        BoringUtils.bore(s.io.tl.a.valid) && BoringUtils.bore(s.io.tl.a.ready) &&
            BoringUtils.bore(s.state) === 0.U && BoringUtils.bore(s.isWrite) &&
            BoringUtils.bore(s.acceptedWindow)
    }).asUInt
    io.continuationSlots := VecInit(candidate.slots.map { s =>
        BoringUtils.bore(s.io.tl.a.valid) && BoringUtils.bore(s.io.tl.a.ready) &&
            BoringUtils.bore(s.state) === 1.U && !BoringUtils.bore(s.writeError)
    }).asUInt
    io.readCaptureSlots := VecInit(candidate.slots.map { s =>
        BoringUtils.bore(s.io.axi.r.valid) && BoringUtils.bore(s.io.axi.r.ready)
    }).asUInt
    io.deniedDrainSlots := VecInit(candidate.slots.map { s =>
        BoringUtils.bore(s.io.tl.a.valid) && BoringUtils.bore(s.io.tl.a.ready) &&
            BoringUtils.bore(s.isWrite) && Mux(BoringUtils.bore(s.state) === 0.U,
                !BoringUtils.bore(s.acceptedWindow), BoringUtils.bore(s.writeError))
    }).asUInt
    io.activeSlots := BoringUtils.bore(candidate.active).asUInt
    io.lineSlots := BoringUtils.bore(candidate.lineOrigins).asUInt
    io.collecting := BoringUtils.bore(candidate.collecting)
    io.allocationSlot := BoringUtils.bore(candidate.allocationSlot)
    val referenceRemaining = BoringUtils.bore(reference.replyRemaining)
    val referenceReplySlot = BoringUtils.bore(reference.replySlot)
    // Static observer taps avoid the pinned generator's dynamic-Vec ordering defect.
    val selectedRemaining = Mux1H((0 until 4).map(i =>
        (referenceReplySlot === i.U) -> referenceRemaining(i)))
    val finalPrimary = r.tl.d.fire && selectedRemaining === 1.U
    io.finishAndAllocate := (finalPrimary || r.lineRead.get.response.fire) &&
        ((r.tl.a.fire && !BoringUtils.bore(reference.collecting)) || r.lineRead.get.request.fire)
}

object BridgePayloadRowPairGsimMain extends App {
    require(args.length == 1 || args.length == 2,
        "usage: BridgePayloadRowPairGsimMain <target-dir> [size-bits=3]")
    ChiselStage.emitCHIRRTLFile(new BridgePayloadRowPairGsim(args.lift(1).map(_.toInt).getOrElse(3)),
        Array("--target-dir", args.head))
}

/** One Scala run emits the six supported native row widths, with no observer ports. */
object BridgePayloadRowNativeMain extends App {
    require(args.length == 1, "usage: BridgePayloadRowNativeMain <target-dir>")
    for (beats <- Seq(8, 16, 32, 64, 128, 256); local <- Seq(false, true)) {
        val target = java.nio.file.Paths.get(args.head, beats.toString, if (local) "on" else "off")
        java.nio.file.Files.createDirectories(target)
        val bits = if (beats <= 16) 3 else 4
        var flags = Seq.empty[Boolean]
        def make() = {
            val dut = new TileLinkAxi4OutstandingBridge(
                tlParams = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 5, sizeBits = bits),
                axiAddressWidth = 32, axiIdWidth = 4, maxBurstBeats = beats,
                axiCache = 0, axiProt = 0, axiQos = 0,
                axiAddressBase = BigInt("80200000", 16), axiWindowBytes = BigInt(1) << 31,
                maxOutstanding = 4, maxOutstandingWrites = 2, unorderedResponses = true,
                writeCollectionFlow = true, lineReadChannel = true,
                localPayloadWriteEnable = true, localPayloadWriteRow = local)
            flags = Seq(dut.localPayloadWriteRow) ++ dut.slots.map(_.localPayloadWriteRow)
            require(flags.size == 5 && flags.forall(_ == local))
            require(dut.localPayloadWriteEnable && dut.slots.forall(_.localPayloadWriteEnable))
            dut
        }
        ChiselStage.emitCHIRRTLFile(make(), Array("--target-dir", target.toString))
        val receipt = s"""{"manager_localPayloadWriteRow":${flags.head},"slot_localPayloadWriteRow":[${flags.tail.mkString(",")}],"localPayloadWriteEnable":true,"sourceBits":5,"sizeBits":$bits,"maxBurstBeats":$beats,"maxOutstanding":4,"maxOutstandingWrites":2}"""
        java.nio.file.Files.writeString(target.resolve("actual-constructors.json"), receipt + "\n")
    }
}
