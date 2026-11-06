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
class IndirectTargetPredictor(p: OooParams, bankedStorage: Boolean = false) extends Module {
    require(!bankedStorage || (p.indirectTargetEntries == 16 && p.renameWidth == 2 && p.commitWidth == 2 &&
        p.compressedInstructions && p.registeredPredictionTraining),
        "banked indirect storage is qualified only for 16 entries, two lookups/commits, RVC and registered training")
    require(p.indirectTargetEntries > 0)
    private val bits = log2Ceil(p.indirectTargetEntries)
    private val pcShift = if (p.compressedInstructions) 1 else 2
    val io = IO(new Bundle {
        val pc = Input(Vec(p.renameWidth, UInt(64.W)))
        val hit = Output(Vec(p.renameWidth, Bool()))
        val target = Output(Vec(p.renameWidth, UInt(64.W)))
        val train = Input(Vec(p.commitWidth, Valid(new IndirectTargetTraining)))
    })
    // Storage-only experiment: two asynchronous lookups and two ordered writes per cycle,
    // II=1, no backpressure or extra pipeline/bypass. Training latency is unchanged.
    if (bankedStorage) {
        val valid = RegInit(VecInit(Seq.fill(p.indirectTargetEntries)(false.B)))
        val ownerBits = log2Ceil(p.commitWidth).max(1)
        val owner = Reg(Vec(p.indirectTargetEntries, UInt(ownerBits.W)))
        // One writer per bank. Split PC/target into the existing 64-bit Mem shape;
        // each pair shares its write enable, address and clock, without payload reset.
        val banks = (0 until p.commitWidth).map { lane =>
            val tags = Mem(p.indirectTargetEntries, UInt(64.W)).suggestName(s"tagBank$lane")
            val targets = Mem(p.indirectTargetEntries, UInt(64.W)).suggestName(s"targetBank$lane")
            val update = io.train(lane)
            val index = update.bits.pc(bits + pcShift - 1, pcShift)
            when(update.valid) {
                tags.write(index, update.bits.pc)
                targets.write(index, update.bits.target)
            }
            (tags, targets)
        }
        for (lane <- 0 until p.renameWidth) {
            val index = io.pc(lane)(bits + pcShift - 1, pcShift)
            // Gate only the uninitialized owner. A stale, unselected bank must never hit.
            val selected = Mux(valid(index), owner(index), 0.U)
            val payloads = VecInit(banks.map { case (tags, targets) =>
                Cat(tags.read(index), targets.read(index))
            })
            val payload = if (p.commitWidth == 1) payloads(0) else payloads(selected)
            io.hit(lane) := valid(index) && payload(127, 64) === io.pc(lane)
            io.target(lane) := payload(63, 0)
        }
        // Retirement is ordered. On a same-index update, the youngest committed target wins.
        for (index <- 0 until p.indirectTargetEntries) {
            for (lane <- 0 until p.commitWidth) {
                val update = io.train(lane)
                when(update.valid && update.bits.pc(bits + pcShift - 1, pcShift) === index.U) {
                    valid(index) := true.B
                    owner(index) := lane.U
                }
            }
        }
    } else {
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
