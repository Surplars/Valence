package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Exact aligned-token caller, with a frozen pre-change peer. The host owns an
  * independent token/reservoir/permission event model; neither DUT feeds it.
  */
class FetchTokenReadyCaptureGsim extends Module {
    val io = IO(new Bundle {
        val present = Input(UInt(2.W))
        val instruction0 = Input(UInt(32.W))
        val instruction1 = Input(UInt(32.W))
        val access = Input(UInt(2.W))
        val page = Input(UInt(2.W))
        val denied = Input(UInt(4.W))
        val faultOffset0 = Input(UInt(5.W))
        val faultOffset1 = Input(UInt(5.W))
        val pause = Input(Bool())
        val consumed = Input(UInt(2.W))
        val flush = Input(Bool())
        val flushTarget = Input(UInt(64.W))
        val expected = Input(UInt(64.W))
        val invalidate = Input(Bool())
        val out0 = Output(Valid(new RawFetchInstruction))
        val out1 = Output(Valid(new RawFetchInstruction))
        val pc = Output(UInt(64.W))
        val nextPc = Output(UInt(64.W))
        val occupancy = Output(UInt(3.W))
        val captured = Output(UInt(2.W))
        val accepted = Output(UInt(2.W))
        val transferred = Output(Bool())
        val tokenValid = Output(Bool())
        val tokenPresent = Output(UInt(2.W))
        val tokenPc = Output(UInt(64.W))
        val frontier = Output(UInt(64.W))
        val suppress = Output(Bool())
    })
    val dut = Module(new RegisteredFetchPacket(2, true, BigInt("80000000", 16),
        parallelValidation = true, hintEntries = 8, splitCursor = true, bankedHints = true,
        alignedPermissionStage = true, eagerPrefixSelect = false, acceptedPrefixValidation = true))
    val reference = Module(new FrozenFetchPacketBeforeReadyCapture(2, true, BigInt("80000000", 16),
        parallelValidation = true, hintEntries = 8, splitCursor = true, bankedHints = true,
        alignedPermissionStage = true, eagerPrefixSelect = false, acceptedPrefixValidation = true))
    for (lane <- 0 until 2) {
        dut.io.supply(lane).valid := io.present(lane)
        dut.io.supply(lane).bits := 0.U.asTypeOf(new RawFetchInstruction)
        dut.io.supply(lane).bits.instruction := (if (lane == 0) io.instruction0 else io.instruction1)
        dut.io.supply(lane).bits.accessFault := io.access(lane)
        dut.io.supply(lane).bits.pageFault := io.page(lane)
        dut.io.phaseInput.get.faultOffsets(lane) := (if (lane == 0) io.faultOffset0 else io.faultOffset1)
        dut.io.consume(lane) := io.consumed > lane.U
        dut.io.validation.get(lane).sequentialPc := io.expected
        dut.io.validation.get(lane).predictedPc := ~io.expected
        dut.io.validation.get(lane).predicts := false.B
    }
    dut.io.phaseInput.get.denied := VecInit((0 until 4).map(io.denied(_)))
    dut.io.pause := io.pause
    dut.io.flush.valid := io.flush
    dut.io.flush.bits := io.flushTarget
    dut.io.expectedNext.valid := io.consumed =/= 0.U
    dut.io.expectedNext.bits := io.expected
    dut.io.train := 0.U.asTypeOf(dut.io.train)
    dut.io.invalidate := io.invalidate
    reference.io.supply := dut.io.supply
    reference.io.phaseInput.get := dut.io.phaseInput.get
    reference.io.pause := dut.io.pause
    reference.io.consume := dut.io.consume
    reference.io.flush := dut.io.flush
    reference.io.expectedNext := dut.io.expectedNext
    reference.io.validation.get := dut.io.validation.get
    reference.io.train := dut.io.train
    reference.io.invalidate := dut.io.invalidate

    assert(dut.io.fetchPc === reference.io.fetchPc && dut.io.nextFetchPc === reference.io.nextFetchPc &&
        dut.io.occupancy === reference.io.occupancy && dut.io.captured.asUInt === reference.io.captured.asUInt,
        "token ready capture changed cursor, occupancy or architectural capture")
    assert(dut.io.requestFrontier.get === reference.io.requestFrontier.get &&
        dut.io.suppressRequest.get === reference.io.suppressRequest.get,
        "token ready capture changed fetch authority")
    val status = dut.io.phaseStatus.get
    val expectedStatus = reference.io.phaseStatus.get
    assert(status.tokenValid === expectedStatus.tokenValid && status.tokenPresent === expectedStatus.tokenPresent &&
        status.accepted === expectedStatus.accepted && status.transferred === expectedStatus.transferred,
        "token ready capture changed token lifecycle")
    when(status.tokenValid) {
        assert(status.tokenPc === expectedStatus.tokenPc, "token ready capture changed live token PC")
    }
    for (lane <- 0 until 2) {
        assert(dut.io.instructions(lane).valid === reference.io.instructions(lane).valid,
            "token ready capture changed output validity")
        when(dut.io.instructions(lane).valid) {
            assert(dut.io.instructions(lane).bits.asUInt === reference.io.instructions(lane).bits.asUInt,
                "token ready capture changed valid instruction/fault tuple")
        }
    }
    io.out0 := dut.io.instructions(0)
    io.out1 := dut.io.instructions(1)
    io.pc := dut.io.fetchPc
    io.nextPc := dut.io.nextFetchPc
    io.occupancy := dut.io.occupancy
    io.captured := dut.io.captured.asUInt
    io.accepted := status.accepted
    io.transferred := status.transferred
    io.tokenValid := status.tokenValid
    io.tokenPresent := status.tokenPresent
    io.tokenPc := status.tokenPc
    io.frontier := dut.io.requestFrontier.get
    io.suppress := dut.io.suppressRequest.get
}
object FetchTokenReadyCaptureGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FetchTokenReadyCaptureGsim, Array("--target-dir", args.head))
}
