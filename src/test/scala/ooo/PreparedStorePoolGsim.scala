package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

class PreparedStorePoolInputs extends Bundle {
    val original = UInt(16.W)
    val prepared = UInt(16.W)
    val bare = Bool()
    val postedWindow = Bool()
    val head = UInt(4.W)
    val resident = UInt(4.W)
    val savedIndex = UInt(4.W)
    val savedTag = UInt(64.W)
    val rowTag = UInt(64.W)
    val present = Bool()
    val pending = Bool()
    val issued = Bool()
}

/** Actual production pool helper and actual resident selector; no copied ranking logic. */
class PreparedStorePoolSelector(candidate: Boolean, postedPriority: Boolean, predecoded: Boolean = true)
    extends Module {
    private val p = OooParams(robEntries = 16, physicalRegs = 48, tagBits = 64)
    val io = IO(new Bundle {
        val in = Input(new PreparedStorePoolInputs)
        val result = Output(UInt(27.W))
    })
    val lateEnable = candidate && !postedPriority
    val fallback = PreparedStorePool.fallback(io.in.original, io.in.prepared, io.in.bare, lateEnable)
    val eligible = if (postedPriority) {
        val prepared = io.in.prepared & Fill(16, io.in.bare)
        val base = Mux(io.in.original.orR, io.in.original, prepared)
        Mux(io.in.postedWindow && io.in.bare && io.in.original.orR, io.in.original | prepared, base)
    } else fallback._1
    val planner = Module(new ResidentMemoryPreparationSelector(p, predecodedHead = predecoded,
        latePoolEnable = lateEnable, directSelectedRank = lateEnable))
    planner.io.eligible := eligible
    planner.io.poolEnabled.foreach(_ := fallback._2)
    planner.io.head := io.in.head
    planner.io.headMask.foreach(_ := VecInit((0 until 16).map(i => i.U >= io.in.head)).asUInt)
    planner.io.resident.valid := io.in.present && io.in.pending && io.in.savedIndex === io.in.resident &&
        io.in.savedTag === io.in.rowTag
    planner.io.resident.bits := io.in.resident
    planner.io.issued := io.in.issued
    io.result := Cat(planner.io.selectedIndex, planner.io.selectedValid, planner.io.useResident,
        planner.io.freshIndex, planner.io.freshValid, planner.io.freshOwner)
}

class PreparedStorePoolGsim extends Module {
    val io = IO(new Bundle {
        val in = Input(new PreparedStorePoolInputs)
        val original = Output(UInt(27.W))
        val candidate = Output(UInt(27.W))
        val postedOriginal = Output(UInt(27.W))
        val postedCandidate = Output(UInt(27.W))
        val binaryCandidate = Output(UInt(27.W))
        val equivalent = Output(Bool())
    })
    val variants = Seq((false, false, true), (true, false, true), (false, true, true),
        (true, true, true), (true, false, false)).map { case (candidate, posted, predecoded) =>
        val dut = Module(new PreparedStorePoolSelector(candidate, posted, predecoded))
        dut.io.in := io.in
        dut.io.result
    }
    io.original := variants(0)
    io.candidate := variants(1)
    io.postedOriginal := variants(2)
    io.postedCandidate := variants(3)
    io.binaryCandidate := variants(4)
    io.equivalent := variants(0) === variants(1) && variants(2) === variants(3) &&
        variants(0) === variants(4)
}

object PreparedStorePoolGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PreparedStorePoolGsim, Array("--target-dir", args.head))
}

object PreparedStorePoolAreaMain extends App {
    ChiselStage.emitSystemVerilogFile(new PreparedStorePoolSelector(args(1).toBoolean, postedPriority = false),
        Array("--target-dir", args.head), firtoolOpts = Array("--disable-all-randomization", "--strip-debug-info"))
}
