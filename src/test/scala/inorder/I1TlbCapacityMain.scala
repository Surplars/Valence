package inorder

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.inorder._

/** Short MMU-interface trace fixture, not a full CPU program benchmark.
  * Real I/D translators use the CPU-private single-owner arbitration contract
  * from FiveStageCachedCore (coherentBandwidth=false). No cache or CPU pipeline
  * is modeled, so this measures translation/service cost, not retired IPC.
  */
class I1TlbCapacityHarness(tlb: Int = 4, banked: Boolean = false) extends Module {
    val p = FiveStageConfig(withUser = true, withSupervisor = true, withSv39 = true, pmpEntries = 4,
        fpgaTimingCuts = true, pipelineProfile = "fpga8", fastDataTranslation = true,
        directFastDataIssue = true, indexedDataProofs = tlb <= 8 || banked, tlbEntries = tlb, bankedTlbProofs = banked)
    val io = IO(new Bundle {
        val dRequest = Flipped(Decoupled(new FiveStageDataRequest(p)))
        val dResponse = Decoupled(new FiveStageDataResponse(p))
        val iRequest = Flipped(Decoupled(new FiveStageDataRequest(p)))
        val iResponse = Decoupled(new FiveStageDataResponse(p))
        val memory = new I1DataPort
        val instructionMemory = new I1DataPort
        val privilege = Input(UInt(2.W)); val dataPrivilege = Input(UInt(2.W))
        val satp = Input(UInt(64.W)); val sum = Input(Bool()); val mxr = Input(Bool())
        val pmpTop = Input(UInt(34.W)); val pmpConfig = Input(UInt(8.W)); val invalidate = Input(Bool())
        val dHit = Output(Bool()); val dMiss = Output(Bool())
        val iHit = Output(Bool()); val iMiss = Output(Bool())
        val dDemand = Output(Bool()); val dWalk = Output(Bool()); val iWalk = Output(Bool())
    })
    val it = Module(new FiveStageAddressTranslation(p, instruction = true))
    val dt = Module(new FiveStageAddressTranslation(p, instruction = false))
    it.io.request <> io.iRequest; io.iResponse <> it.io.response
    dt.io.request <> io.dRequest; io.dResponse <> dt.io.response
    for (t <- Seq(it, dt)) {
        t.io.context.privilege := io.privilege; t.io.context.dataPrivilege := io.dataPrivilege
        t.io.context.satp := io.satp; t.io.context.sum := io.sum; t.io.context.mxr := io.mxr
        t.io.context.pmpAllOff := io.pmpConfig(4, 3) === 0.U
        t.io.invalidate := io.invalidate
        t.io.entries.foreach { e => e.config := 0.U; e.address := 0.U; e.lower := 0.U; e.upper := 0.U }
        t.io.entries(0).config := io.pmpConfig; t.io.entries(0).address := io.pmpTop
        t.io.entries(0).upper := io.pmpTop << 2
    }
    def connect(request: DecoupledIO[FiveStageDataRequest], response: DecoupledIO[FiveStageDataResponse],
        port: I1DataPort): Unit = {
        port.request.valid := request.valid; request.ready := port.request.ready
        port.request.bits := 0.U.asTypeOf(new I1DataRequest)
        port.request.bits.address := request.bits.address; port.request.bits.write := request.bits.write
        port.request.bits.size := request.bits.size; port.request.bits.data := request.bits.data
        port.request.bits.mask := request.bits.mask; port.request.bits.uncached := request.bits.noAllocate
        port.request.bits.atomic := request.bits.atomic; port.request.bits.atomicOp := request.bits.atomicOperation
        response.valid := port.response.valid; port.response.ready := response.ready
        response.bits := 0.U.asTypeOf(new FiveStageDataResponse(p))
        response.bits.data := port.response.bits.data; response.bits.error := port.response.bits.error
        response.bits.pageFault := port.response.bits.pageFault
    }
    // Mirrors FiveStageCachedCore's CPU-private three-user, ONE-owner path.
    // coherentBandwidth=false: rotating grant, no response-edge replacement.
    val ports = Seq(dt.io.physical, dt.io.walk, it.io.walk)
    val physicalRequest = Wire(Decoupled(new FiveStageDataRequest(p)))
    val physicalResponse = Wire(Decoupled(new FiveStageDataResponse(p)))
    val active = RegInit(false.B); val owner = Reg(UInt(2.W))
    val offered = RegInit(false.B); val heldGrant = Reg(UInt(2.W))
    val roundRobin = RegInit(0.U(2.W))
    val available = ports.map(_.request.valid)
    val choice = MuxLookup(roundRobin, Mux(available(0), 0.U, Mux(available(1), 1.U, 2.U)))(Seq(
        1.U -> Mux(available(1), 1.U, Mux(available(2), 2.U, 0.U)),
        2.U -> Mux(available(2), 2.U, Mux(available(0), 0.U, 1.U))))
    val grant = Mux(offered, heldGrant, choice)
    physicalRequest.valid := !active && VecInit(available)(grant)
    physicalRequest.bits := Mux1H((0 until 3).map(i => (grant === i.U) -> ports(i).request.bits))
    physicalResponse.ready := active && Mux1H((0 until 3).map(i =>
        (owner === i.U) -> ports(i).response.ready))
    for (i <- 0 until 3) {
        ports(i).request.ready := !active && grant === i.U && physicalRequest.ready
        ports(i).response.valid := active && owner === i.U && physicalResponse.valid
        ports(i).response.bits := physicalResponse.bits
    }
    when(physicalRequest.valid && !physicalRequest.ready) { offered := true.B; heldGrant := grant }
    when(physicalRequest.fire) {
        active := true.B; owner := grant; offered := false.B
        roundRobin := Mux(grant === 2.U, 0.U, grant + 1.U)
    }
    when(physicalResponse.fire) { active := false.B }
    when(!reset.asBool) {
        assert(!physicalResponse.valid || active, "physical D-cache reply has no demand/PTW owner")
    }
    connect(physicalRequest, physicalResponse, io.memory)
    connect(it.io.physical.request, it.io.physical.response, io.instructionMemory)
    io.dHit := dt.io.hit; io.dMiss := dt.io.miss; io.iHit := it.io.hit; io.iMiss := it.io.miss
    io.dDemand := dt.io.physical.request.fire
    io.dWalk := dt.io.walk.request.fire; io.iWalk := it.io.walk.request.fire
}

object I1TlbCapacityMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1TlbCapacityHarness(
        args.find(_.startsWith("--tlb=")).map(_.stripPrefix("--tlb=").toInt).getOrElse(4),
        args.contains("--banked-tlb-proofs")),
        Array("--target-dir", args.head))
}
