package inorder

import chisel3._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.core.inorder._
import soc.ip.tilelink.LineReadMemoryPort

/** Same two DDR slots /one write owner as the selected I1 fabric. */
class LineReadChannelGsim(burstBeats: Int = 8, writeFlow: Boolean = false,
    parallelAdmission: Boolean = false, registeredPreflight: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val tl = Flipped(new TLBundle(TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4)))
        val lineRead = Flipped(new LineReadMemoryPort())
        val ddrAxi = new soc.ip.axi.Axi4MemoryPort(32, 4)
    })
    val bridge = Module(new I1TileLinkAxi4OutstandingBridge(
        TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4), 32, 4, burstBeats, 0, 0, 0,
        BigInt("80200000", 16), BigInt(2147483648L), 2, maxOutstandingWrites = 1,
        unorderedResponses = true, writeCollectionFlow = writeFlow, lineReadChannel = true,
        parallelAdmission = parallelAdmission, registeredPreflight = registeredPreflight))
    if (registeredPreflight) {
        val a = Module(new I1RegisteredAxiRequestBoundary(
            TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4), 32,
            BigInt("80200000", 16), BigInt(2147483648L), burstBeats))
        val line = Module(new I1RegisteredAxiLineRequestBoundary(32,
            BigInt("80200000", 16), BigInt(2147483648L), burstBeats))
        a.io.upstream <> io.tl; bridge.io.tl <> a.io.downstream
        line.io.upstream <> io.lineRead; bridge.io.lineRead.get <> line.io.downstream
        bridge.io.ordinaryPreflight.get := a.io.preflight
        bridge.io.linePreflight.get := line.io.preflight
    } else {
        io.tl <> bridge.io.tl
        io.lineRead <> bridge.io.lineRead.get
    }
    io.ddrAxi <> bridge.io.axi
    if (registeredPreflight) {
        // Interface-only cycle equivalence: constant proofs prepared in the
        // old queue edge must equal a direct computation from the SAME head.
        // The reference owns its own bridge state and buffers, and never
        // supplies expected memory bytes to the independent C++ model.
        val reference = Module(new I1TileLinkAxi4OutstandingBridge(
            TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 4), 32, 4, burstBeats, 0, 0, 0,
            BigInt("80200000", 16), BigInt(2147483648L), 2, maxOutstandingWrites = 1,
            unorderedResponses = true, writeCollectionFlow = writeFlow,
            lineReadChannel = true, parallelAdmission = true))
        reference.io.tl.a.valid := bridge.io.tl.a.valid
        reference.io.tl.a.bits := bridge.io.tl.a.bits
        reference.io.tl.d.ready := bridge.io.tl.d.ready
        reference.io.tl.b.ready := false.B
        reference.io.tl.c.valid := false.B
        reference.io.tl.c.bits := 0.U.asTypeOf(reference.io.tl.c.bits)
        reference.io.tl.e.valid := false.B
        reference.io.tl.e.bits := 0.U.asTypeOf(reference.io.tl.e.bits)
        reference.io.lineRead.get.request.valid := bridge.io.lineRead.get.request.valid
        reference.io.lineRead.get.request.bits := bridge.io.lineRead.get.request.bits
        reference.io.lineRead.get.response.ready := bridge.io.lineRead.get.response.ready
        reference.io.axi.ar.ready := io.ddrAxi.ar.ready
        reference.io.axi.aw.ready := io.ddrAxi.aw.ready
        reference.io.axi.w.ready := io.ddrAxi.w.ready
        reference.io.axi.r.valid := io.ddrAxi.r.valid
        reference.io.axi.r.bits := io.ddrAxi.r.bits
        reference.io.axi.b.valid := io.ddrAxi.b.valid
        reference.io.axi.b.bits := io.ddrAxi.b.bits
        when(!reset.asBool) {
            assert(reference.io.tl.a.ready === bridge.io.tl.a.ready &&
                reference.io.tl.d.valid === bridge.io.tl.d.valid,
                "registered preflight changed exact ordinary admission/retirement cycle")
            when(bridge.io.tl.d.valid) { assert(reference.io.tl.d.bits.asUInt === bridge.io.tl.d.bits.asUInt) }
            assert(reference.io.lineRead.get.request.ready === bridge.io.lineRead.get.request.ready &&
                reference.io.lineRead.get.response.valid === bridge.io.lineRead.get.response.valid,
                "registered preflight changed exact line admission/retirement cycle")
            when(bridge.io.lineRead.get.response.valid) {
                assert(reference.io.lineRead.get.response.bits.asUInt === bridge.io.lineRead.get.response.bits.asUInt)
            }
            for ((old, current) <- Seq((reference.io.axi.ar, bridge.io.axi.ar),
                (reference.io.axi.aw, bridge.io.axi.aw))) {
                assert(old.valid === current.valid)
                when(current.valid) { assert(old.bits.asUInt === current.bits.asUInt) }
            }
            assert(reference.io.axi.w.valid === bridge.io.axi.w.valid &&
                reference.io.axi.r.ready === bridge.io.axi.r.ready &&
                reference.io.axi.b.ready === bridge.io.axi.b.ready)
            when(bridge.io.axi.w.valid) { assert(reference.io.axi.w.bits.asUInt === bridge.io.axi.w.bits.asUInt) }
        }
    }
}

object I1LineReadChannelMain extends App {
    ChiselStage.emitCHIRRTLFile(new LineReadChannelGsim(
        if (args.contains("--burst16")) 16 else 8, args.contains("--write-flow"),
        args.contains("--parallel-admission"), args.contains("--registered-preflight")), Array("--target-dir", args.head))
}
