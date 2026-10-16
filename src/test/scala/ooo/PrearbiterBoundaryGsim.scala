package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.bus.tilelink.{TLBundle, TLParams}
import soc.ip.tilelink.{TileLinkLineTransfer, TileLinkLineWriteEngine}

class PrearbiterBoundaryGsim(dispatchFlow: Boolean = false, registerRequests: Boolean = false) extends Module {
    private val params = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 3)
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new Bundle {
            val address = UInt(64.W)
            val tag = UInt(8.W)
        }))
        val word0 = Input(UInt(64.W))
        val word1 = Input(UInt(64.W))
        val word2 = Input(UInt(64.W))
        val word3 = Input(UInt(64.W))
        val word4 = Input(UInt(64.W))
        val word5 = Input(UInt(64.W))
        val word6 = Input(UInt(64.W))
        val word7 = Input(UInt(64.W))
        val response = Decoupled(new Bundle {
            val tag = UInt(8.W)
            val error = Bool()
        })
        val tl = new TLBundle(params.copy(sourceBits = 4))
        val contender = Flipped(Decoupled(new soc.bus.tilelink.TLBundleA(params)))
        val contenderReply = Decoupled(new soc.bus.tilelink.TLBundleD(params))
        val writerReady = Output(Bool())
    })
    val write = Module(new TileLinkLineWriteEngine(params, entries = 4, dispatchFlow = dispatchFlow))
    write.io.request.valid := io.request.valid
    write.io.request.bits.address := io.request.bits.address
    write.io.request.bits.tag := io.request.bits.tag
    write.io.request.bits.data := Cat(io.word7, io.word6, io.word5, io.word4,
        io.word3, io.word2, io.word1, io.word0)
    io.request.ready := write.io.request.ready
    io.response <> write.io.response
    val arbiter = Module(new soc.ip.tilelink.TwoMasterTileLinkArbiter(params,
        rawResponseMetadata = true, rawRequestMetadata = true))
    soc.core.ooo.CoherentHomeUlBoundary.connect(write.io.tl, arbiter.io.masters(1), registerRequests)
    arbiter.io.masters(0).a <> io.contender
    io.contenderReply <> arbiter.io.masters(0).d
    arbiter.io.masters(0).b.ready := false.B
    arbiter.io.masters(0).c.valid := false.B
    arbiter.io.masters(0).c.bits := 0.U.asTypeOf(arbiter.io.masters(0).c.bits)
    arbiter.io.masters(0).e.valid := false.B
    arbiter.io.masters(0).e.bits := 0.U.asTypeOf(arbiter.io.masters(0).e.bits)
    io.tl <> arbiter.io.manager
    io.writerReady := write.io.tl.a.ready
}

object PrearbiterBoundaryGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PrearbiterBoundaryGsim(args.lift(1).contains("1"), args.lift(2).contains("1")),
        Array("--target-dir", args.head))
}
