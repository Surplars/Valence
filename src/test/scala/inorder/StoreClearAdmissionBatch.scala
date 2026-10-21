package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.inorder._
import soc.platform.CommonCpuProfile

/** Actual production-profile DT, with an independently scheduled native memory server. */
class StoreClearAdmissionBatch extends Module {
    private val p = CommonCpuProfile.I1.i1
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new FiveStageDataRequest(p)))
        val response = Decoupled(new FiveStageDataResponse(p))
        val readAhead = Input(Bool())
        val early = Input(Bool())
        val invalidate = Input(Bool())
        val privilege = Input(UInt(2.W))
        val storeAccepted = Output(Bool())
        val nativeReady = Input(Bool())
        val nativeValid = Output(Bool())
        val nativeAddress = Output(UInt(64.W))
        val nativeWrite = Output(Bool())
        val nativeAtomic = Output(Bool())
        val nativeResponseValid = Input(Bool())
        val nativeResponseReady = Output(Bool())
        val nativeResponseData = Input(UInt(64.W))
        val nativeResponseError = Input(Bool())
    })
    val dt = Module(new FiveStageAddressTranslation(p, instruction = false,
        parallelDataCandidates = p.fastDataTranslation && p.preparedTranslationProofs))
    dt.io.request <> io.request
    io.response <> dt.io.response
    dt.io.readAhead.get := io.readAhead
    io.storeAccepted := dt.io.ordinaryStoreAccepted.get
    dt.io.invalidate := io.invalidate
    dt.io.context := 0.U.asTypeOf(new FiveStageTranslationContext(p))
    dt.io.context.privilege := io.privilege
    dt.io.context.dataPrivilege := io.privilege
    dt.io.context.pmpAllOff := true.B
    dt.io.entries := 0.U.asTypeOf(dt.io.entries)
    dt.io.dataCandidates.foreach { candidates =>
        candidates(0) := io.request.bits
        candidates(1) := io.request.bits
        when(io.early) { candidates(0).address := io.request.bits.address ^ 4096.U }
            .otherwise { candidates(1).address := io.request.bits.address ^ 4096.U }
    }
    dt.io.dataCandidateEarly.foreach(_ := io.early)
    dt.io.physical.request.ready := io.nativeReady
    io.nativeValid := dt.io.physical.request.valid
    io.nativeAddress := dt.io.physical.request.bits.address
    io.nativeWrite := dt.io.physical.request.bits.write
    io.nativeAtomic := dt.io.physical.request.bits.atomic
    dt.io.physical.response.valid := io.nativeResponseValid
    dt.io.physical.response.bits := 0.U.asTypeOf(new FiveStageDataResponse(p))
    dt.io.physical.response.bits.data := io.nativeResponseData
    dt.io.physical.response.bits.error := io.nativeResponseError
    io.nativeResponseReady := dt.io.physical.response.ready
    dt.io.walk.request.ready := false.B
    dt.io.walk.response.valid := false.B
    dt.io.walk.response.bits := 0.U.asTypeOf(new FiveStageDataResponse(p))
    when(!reset.asBool) {
        assert(!dt.io.walk.request.valid, "Bare-address admission fixture unexpectedly walked a page table")
    }
}

object StoreClearAdmissionBatchMain extends App {
    require(args.length == 1 || (args.length == 2 && Set("--production-lowering", "--default-lowering")(args(1))))
    // Match the native production exporter; retain the old mode only to reproduce its X regression.
    val lowering = if (args.length == 2 && args(1) == "--default-lowering") Array.empty[String]
        else Array("--lowering-options=disallowLocalVariables,disallowPackedArrays")
    ChiselStage.emitSystemVerilogFile(new StoreClearAdmissionBatch,
        Array("--target-dir", args.head),
        firtoolOpts = Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable") ++ lowering)
}
