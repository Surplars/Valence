package inorder

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.inorder.I1ExecuteDatapath

/** Direct production-helper coverage. Legacy outputs are test-only negative controls. */
class I1OperandSingletonFixture extends Module {
    val io = IO(new Bundle {
        val masks = Input(UInt(20.W))
        val value0 = Input(UInt(64.W))
        val value1 = Input(UInt(64.W))
        val value2 = Input(UInt(64.W))
        val value3 = Input(UInt(64.W))
        val value4 = Input(UInt(64.W))
        val value5 = Input(UInt(64.W))
        val value6 = Input(UInt(64.W))
        val value7 = Input(UInt(64.W))
        val value8 = Input(UInt(64.W))
        val value9 = Input(UInt(64.W))
        val value10 = Input(UInt(64.W))
        val value11 = Input(UInt(64.W))
        val value12 = Input(UInt(64.W))
        val value13 = Input(UInt(64.W))
        val value14 = Input(UInt(64.W))
        val value15 = Input(UInt(64.W))
        val value16 = Input(UInt(64.W))
        val value17 = Input(UInt(64.W))
        val value18 = Input(UInt(64.W))
        val value19 = Input(UInt(64.W))
        val overrideEnable = Input(Bool())
        val registerEnable = Input(Bool())
        val overrideValue = Input(UInt(64.W))
        val result1 = Output(UInt(64.W))
        val legacyResult1 = Output(UInt(64.W))
        val result2 = Output(UInt(64.W))
        val legacyResult2 = Output(UInt(64.W))
        val result3 = Output(UInt(64.W))
        val legacyResult3 = Output(UInt(64.W))
        val result4 = Output(UInt(64.W))
        val legacyResult4 = Output(UInt(64.W))
        val result5 = Output(UInt(64.W))
        val legacyResult5 = Output(UInt(64.W))
        val result6 = Output(UInt(64.W))
        val legacyResult6 = Output(UInt(64.W))
        val result7 = Output(UInt(64.W))
        val legacyResult7 = Output(UInt(64.W))
        val result8 = Output(UInt(64.W))
        val legacyResult8 = Output(UInt(64.W))
        val result9 = Output(UInt(64.W))
        val legacyResult9 = Output(UInt(64.W))
        val result10 = Output(UInt(64.W))
        val legacyResult10 = Output(UInt(64.W))
        val result20 = Output(UInt(64.W))
        val legacyResult20 = Output(UInt(64.W))
        val overridden = Output(UInt(64.W))
        val legacyOverridden = Output(UInt(64.W))
    })

    // Exact pre-fix grouping, deliberately confined to this negative-control fixture.
    // Chisel's one-element Mux1H ignores the mask, leaking the final singleton payload.
    private def legacyOperand(masks: Seq[Bool], values: Seq[UInt]): UInt =
        masks.zip(values).grouped(3).map(group => Mux1H(group)).reduce(_ | _)

    // Explicit scalar ports avoid GSIM's aggregate input setter limitation.
    private val values = Seq(
        io.value0, io.value1, io.value2, io.value3, io.value4,
        io.value5, io.value6, io.value7, io.value8, io.value9,
        io.value10, io.value11, io.value12, io.value13, io.value14,
        io.value15, io.value16, io.value17, io.value18, io.value19)
    private def connect(count: Int, result: UInt, legacyResult: UInt): Unit = {
        val masks = (0 until count).map(io.masks(_))
        result := I1ExecuteDatapath.operand(masks, values.take(count))
        legacyResult := legacyOperand(masks, values.take(count))
    }
    connect(1, io.result1, io.legacyResult1)
    connect(2, io.result2, io.legacyResult2)
    connect(3, io.result3, io.legacyResult3)
    connect(4, io.result4, io.legacyResult4)
    connect(5, io.result5, io.legacyResult5)
    connect(6, io.result6, io.legacyResult6)
    connect(7, io.result7, io.legacyResult7)
    connect(8, io.result8, io.legacyResult8)
    connect(9, io.result9, io.legacyResult9)
    connect(10, io.result10, io.legacyResult10)
    connect(20, io.result20, io.legacyResult20)
    private val overrideMasks = (0 until 4).map(io.masks(_))
    private val overrideValues = values.take(4)
    io.overridden := I1ExecuteDatapath.overrideOperand(overrideMasks, overrideValues,
        io.overrideEnable, io.overrideValue, io.registerEnable)
    io.legacyOverridden := legacyOperand(
        overrideMasks.map(_ && !io.overrideEnable && io.registerEnable), overrideValues) |
        Mux(io.overrideEnable, io.overrideValue, 0.U)
}

object I1OperandSingletonMain extends App {
    require(args.length == 1, "expected output directory")
    ChiselStage.emitCHIRRTLFile(new I1OperandSingletonFixture, Array("--target-dir", args.head))
}
