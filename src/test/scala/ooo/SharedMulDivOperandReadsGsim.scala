package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._
import scala.collection.immutable.ListMap

class EfficiencyOperandSources extends Record {
    override val elements: ListMap[String, Data] = ListMap((0 until 16).map(i => s"r$i" -> UInt(6.W)): _*)
    def at(i: Int): UInt = elements(s"r$i").asInstanceOf[UInt]
}

/** Actual production selector and PRF, comparing old four-reader preparation
  * against two selected readers. Full backend side-ticket/permission behavior
  * must be covered by the candidate CPU; this wrapper does not recreate it.
  */
class SharedMulDivOperandReadsGsim extends Module {
    val p = OooParams(robEntries = 16, physicalRegs = 48)
    val io = IO(new Bundle {
        val multiply = Input(UInt(16.W)); val divide = Input(UInt(16.W))
        val head = Input(UInt(4.W)); val multiplyReady = Input(Bool()); val divideReady = Input(Bool())
        val source1 = Input(new EfficiencyOperandSources); val source2 = Input(new EfficiencyOperandSources)
        val write0 = Input(Bool()); val address0 = Input(UInt(6.W)); val data0 = Input(UInt(64.W))
        val write1 = Input(Bool()); val address1 = Input(UInt(6.W)); val data1 = Input(UInt(64.W))
        val valid = Output(Bool()); val selectedIndex = Output(UInt(4.W)); val grant = Output(UInt(2.W))
        val multiplyIndex = Output(UInt(4.W)); val divideIndex = Output(UInt(4.W))
        val selectedSource1 = Output(UInt(6.W)); val selectedSource2 = Output(UInt(6.W))
        val oldLeft = Output(UInt(64.W)); val oldRight = Output(UInt(64.W))
        val sharedLeft = Output(UInt(64.W)); val sharedRight = Output(UInt(64.W))
    })
    val selector = Module(new SplitMulDivSelector(p, predecodedHead = true))
    selector.io.head := io.head
    selector.io.headMask.get := VecInit((0 until 16).map(i => i.U >= io.head)).asUInt
    selector.io.eligible := VecInit(Seq(io.multiply, io.divide))
    selector.io.available := VecInit(Seq(io.multiplyReady, io.divideReady))
    val sources1 = (0 until 16).map(io.source1.at)
    val sources2 = (0 until 16).map(io.source2.at)
    val oldFile = Module(new OwnerBankedPhysicalRegisterFile(48, 4))
    val sharedFile = Module(new OwnerBankedPhysicalRegisterFile(48, 2))
    for (file <- Seq(oldFile, sharedFile)) {
        file.io.write(0).valid := io.write0
        file.io.write(0).bits.address := io.address0
        file.io.write(0).bits.data := io.data0
        file.io.write(1).valid := io.write1
        file.io.write(1).bits.address := io.address1
        file.io.write(1).bits.data := io.data1
    }
    for (kind <- 0 until 2) {
        oldFile.io.address(2 * kind) := CircularIssueSelector.selectPayload(selector.io.owner(kind), sources1)
        oldFile.io.address(2 * kind + 1) := CircularIssueSelector.selectPayload(selector.io.owner(kind), sources2)
    }
    val selectedOwner = Mux1H(selector.io.grant.zip(selector.io.owner))
    val leftId = Mux(selector.io.selectedValid, CircularIssueSelector.selectPayload(selectedOwner, sources1), 0.U)
    val rightId = Mux(selector.io.selectedValid, CircularIssueSelector.selectPayload(selectedOwner, sources2), 0.U)
    sharedFile.io.address(0) := leftId
    sharedFile.io.address(1) := rightId
    io.valid := selector.io.selectedValid
    io.selectedIndex := selector.io.selectedIndex
    io.grant := selector.io.grant.asUInt
    io.multiplyIndex := selector.io.index(0)
    io.divideIndex := selector.io.index(1)
    io.selectedSource1 := leftId
    io.selectedSource2 := rightId
    io.oldLeft := Mux1H(selector.io.grant.zip(Seq(oldFile.io.data(0), oldFile.io.data(2))))
    io.oldRight := Mux1H(selector.io.grant.zip(Seq(oldFile.io.data(1), oldFile.io.data(3))))
    io.sharedLeft := sharedFile.io.data(0)
    io.sharedRight := sharedFile.io.data(1)
}

object SharedMulDivOperandReadsGsimMain extends App {
    require(args.length == 1)
    ChiselStage.emitCHIRRTLFile(new SharedMulDivOperandReadsGsim, Array("--target-dir", args.head))
}
