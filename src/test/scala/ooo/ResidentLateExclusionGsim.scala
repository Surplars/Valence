package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Compare both production head modes to the previous exclusion-before-rank
  * topology. The host independently walks ROB slots and checks the packed ports.
  * Full-token validity is deliberately qualified outside every selector, just
  * as in the actual backend; no new live-owner assumption is made by this test.
  */
class ResidentLateExclusionGsim extends Module {
    private val p = OooParams(robEntries = 16, physicalRegs = 48, tagBits = 64)
    val io = IO(new Bundle {
        val eligible = Input(UInt(16.W))
        val head = Input(UInt(4.W))
        val resident = Input(UInt(4.W))
        val savedIndex = Input(UInt(4.W))
        val savedTag = Input(UInt(64.W))
        val rowTag = Input(UInt(64.W))
        val residentPresent = Input(Bool())
        val pending = Input(Bool())
        val issued = Input(Bool())
        val candidate = Output(UInt(27.W))
        val binaryHead = Output(UInt(27.W))
        val previous = Output(UInt(27.W))
    })
    val headMask = VecInit((0 until 16).map(i => i.U >= io.head)).asUInt
    val live = io.residentPresent && io.pending && io.savedIndex === io.resident && io.savedTag === io.rowTag
    val candidate = Seq(false, true).map { predecoded =>
        val dut = Module(new ResidentMemoryPreparationSelector(p, predecodedHead = predecoded))
        dut.io.eligible := io.eligible
        dut.io.head := io.head
        dut.io.headMask.foreach(_ := headMask)
        dut.io.resident.valid := live
        dut.io.resident.bits := io.resident
        dut.io.issued := io.issued
        Cat(dut.io.selectedIndex, dut.io.selectedValid, dut.io.useResident,
            dut.io.freshIndex, dut.io.freshValid, dut.io.freshOwner)
    }
    io.binaryHead := candidate(0)
    io.candidate := candidate(1)

    // Frozen pre-change component equations; this path does not call the DUT.
    val residentOwner = Mux(live, UIntToOH(io.resident, 16), 0.U)
    val previousSelector = Module(new CircularIssueSelector(p, parallelRanks = true, predecodedHead = true))
    previousSelector.io.eligible := io.eligible & ~residentOwner
    previousSelector.io.head := io.head
    previousSelector.io.headMask.get := headMask
    val residentEligible = live && (residentOwner & io.eligible).orR
    val residentAge = io.resident - io.head
    val freshAge = previousSelector.io.firstIndex - io.head
    val reuse = residentEligible && !io.issued && (!previousSelector.io.firstValid || residentAge < freshAge)
    val selectedValid = (residentEligible && !io.issued) || previousSelector.io.firstValid
    val selectedIndex = Mux(reuse, io.resident, previousSelector.io.firstIndex)
    io.previous := Cat(selectedIndex, selectedValid, reuse, previousSelector.io.firstIndex, previousSelector.io.firstValid, previousSelector.io.first)
}

object ResidentLateExclusionGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new ResidentLateExclusionGsim, Array("--target-dir", args.head))
}
