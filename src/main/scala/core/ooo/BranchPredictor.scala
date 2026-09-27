package soc.core.ooo

import chisel3._
import chisel3.util._

class BranchTraining extends Bundle {
    val pc    = UInt(64.W)
    val taken = Bool()
}

class IndirectTargetTraining extends Bundle {
    val pc = UInt(64.W)
    val target = UInt(64.W)
}

/** Small commit-trained last-target table for register-indirect jumps and calls. Wrong targets recover normally. */
class IndirectTargetPredictor(p: OooParams) extends Module {
    require(p.indirectTargetEntries > 0)
    private val bits = log2Ceil(p.indirectTargetEntries)
    private val pcShift = if (p.compressedInstructions) 1 else 2
    val io = IO(new Bundle {
        val pc = Input(Vec(p.renameWidth, UInt(64.W)))
        val hit = Output(Vec(p.renameWidth, Bool()))
        val target = Output(Vec(p.renameWidth, UInt(64.W)))
        val train = Input(Vec(p.commitWidth, Valid(new IndirectTargetTraining)))
    })
    val valid = RegInit(VecInit(Seq.fill(p.indirectTargetEntries)(false.B)))
    val tags = Reg(Vec(p.indirectTargetEntries, UInt(64.W)))
    val targets = Reg(Vec(p.indirectTargetEntries, UInt(64.W)))
    for (lane <- 0 until p.renameWidth) {
        val index = io.pc(lane)(bits + pcShift - 1, pcShift)
        io.hit(lane) := valid(index) && tags(index) === io.pc(lane)
        io.target(lane) := targets(index)
    }
    // Retirement is ordered. On a same-index update, the youngest committed target wins.
    for (index <- 0 until p.indirectTargetEntries) {
        for (lane <- 0 until p.commitWidth) {
            val update = io.train(lane)
            when(update.valid && update.bits.pc(bits + pcShift - 1, pcShift) === index.U) {
                valid(index) := true.B
                tags(index) := update.bits.pc
                targets(index) := update.bits.target
            }
        }
    }
}

/** Commit-trained bimodal direction table. No speculative state to restore after recovery. */
class BranchPredictor(p: OooParams) extends Module {
    private val bits = log2Ceil(p.branchPredictorEntries)
    private val pcShift = if (p.compressedInstructions) 1 else 2
    val io           = IO(new Bundle {
        val pc    = Input(Vec(p.renameWidth, UInt(64.W)))
        val taken = Output(Vec(p.renameWidth, Bool()))
        val train = Input(Vec(p.commitWidth, Valid(new BranchTraining)))
    })
    val counters = RegInit(VecInit(Seq.fill(p.branchPredictorEntries)(1.U(2.W))))
    for (lane <- 0 until p.renameWidth) {
        io.taken(lane) := counters(io.pc(lane)(bits + pcShift - 1, pcShift))(1)
    }
    // Explicit per-entry folds preserve both updates on a same-index dual retirement.
    for (index <- 0 until p.branchPredictorEntries) {
        var next = counters(index)
        for (lane <- 0 until p.commitWidth) {
            val update    = io.train(lane)
            val increment = Mux(next === 3.U, next, next + 1.U)
            val decrement = Mux(next === 0.U, next, next - 1.U)
            next = Mux(
                update.valid && update.bits.pc(bits + pcShift - 1, pcShift) === index.U,
                Mux(update.bits.taken, increment, decrement),
                next
            )
        }
        counters(index) := next
    }
}
