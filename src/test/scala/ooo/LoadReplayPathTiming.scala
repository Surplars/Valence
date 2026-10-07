package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Identical registered boundaries around the old/new combinational replay path.
  * Registers are measurement fixtures, not extra stages in the production CPU.
  * OOC placement is a module comparison, NOT a full-board Fmax claim.
  */
class LoadReplayPathTimingTop(candidate: Boolean, oneHotPayload: Boolean = true) extends Module {
    private val p = OooParams(robEntries = 16, physicalRegs = 48)
    val io = IO(new Bundle {
        val request = Input(new Bundle {
            val head = UInt(4.W)
            val checkedValid = Bool()
            val checkedIndex = UInt(4.W)
            val checkedBeat = UInt(61.W)
            val checkedLanes = UInt(8.W)
            val eligible = UInt(16.W)
            val beats = Vec(16, UInt(61.W))
            val lanes = Vec(16, UInt(8.W))
            val pcs = Vec(16, UInt(64.W))
            val tags = Vec(16, UInt(64.W))
        })
        val response = Output(new Bundle {
            val valid = Bool()
            val index = UInt(4.W)
            val pc = UInt(64.W)
            val tag = UInt(64.W)
        })
    })
    val request = RegNext(io.request)
    val result = Wire(chiselTypeOf(io.response))
    if (candidate) {
        val selector = Module(new LoadReplaySelector(p))
        selector.io.head := request.head
        selector.io.checkedValid := request.checkedValid
        selector.io.checkedIndex := request.checkedIndex
        selector.io.checkedBeat := request.checkedBeat
        selector.io.checkedLanes := request.checkedLanes
        selector.io.eligible := request.eligible
        selector.io.beats := request.beats
        selector.io.lanes := request.lanes
        result.valid := selector.io.valid
        result.index := selector.io.index
        result.pc := (if (oneHotPayload)
            Mux1H((0 until 16).map(i => selector.io.oneHot(i) -> request.pcs(i)))
        else request.pcs(selector.io.index))
        result.tag := (if (oneHotPayload)
            Mux1H((0 until 16).map(i => selector.io.oneHot(i) -> request.tags(i)))
        else request.tags(selector.io.index))
    } else {
        class Candidate extends Bundle {
            val valid = Bool()
            val index = UInt(4.W)
            val age = UInt(4.W)
        }
        def tournament(items: Seq[Candidate]): Candidate = {
            if (items.size == 1) items.head
            else tournament(items.grouped(2).map {
                case Seq(a, b) => Mux(a.valid && (!b.valid || a.age < b.age), a, b)
                case Seq(a) => a
            }.toSeq)
        }
        val winner = tournament((0 until 16).map { i =>
            val entry = Wire(new Candidate)
            val age = i.U(4.W) - request.head
            val checkedAge = request.checkedIndex - request.head
            entry.valid := request.checkedValid && request.eligible(i) && age > checkedAge &&
                request.beats(i) === request.checkedBeat && (request.lanes(i) & request.checkedLanes).orR
            entry.index := i.U
            entry.age := age
            entry
        })
        result.valid := winner.valid
        result.index := winner.index
        result.pc := request.pcs(winner.index)
        result.tag := request.tags(winner.index)
    }
    io.response := RegNext(result)
}

object LoadReplayPathTimingMain extends App {
    require(args.length == 2 && Set("baseline", "candidate", "indexed").contains(args(1)),
        "usage: LoadReplayPathTimingMain output-directory baseline|candidate|indexed")
    ChiselStage.emitSystemVerilogFile(new LoadReplayPathTimingTop(args(1) != "baseline",
        oneHotPayload = args(1) != "indexed"),
        Array("--target-dir", args(0)),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable"))
}
