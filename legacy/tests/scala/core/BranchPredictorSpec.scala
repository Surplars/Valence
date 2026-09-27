package core

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.core.pipeline.BranchPredictor

class BranchPredictorSpec extends AnyFunSuite with ChiselSim {
    private def init(dut: BranchPredictor): Unit = {
        dut.io.req_pc.poke("h1000".U)
        dut.io.update_valid.poke(false.B)
        dut.io.update_pc.poke(0.U)
        dut.io.update_target.poke(0.U)
        dut.io.update_taken.poke(false.B)
        dut.io.update_is_br.poke(false.B)
    }

    private def update(
        dut: BranchPredictor,
        pc: BigInt,
        target: BigInt,
        taken: Boolean,
        isBranch: Boolean
    ): Unit = {
        dut.io.update_pc.poke(pc.U)
        dut.io.update_target.poke(target.U)
        dut.io.update_taken.poke(taken.B)
        dut.io.update_is_br.poke(isBranch.B)
        dut.io.update_valid.poke(true.B)
        dut.clock.step()
        dut.io.update_valid.poke(false.B)
    }

    test("BTB allocation, counter update, compressed PC indexing, and tag checks") {
        simulate(new BranchPredictor(entries = 8)) { dut =>
            init(dut)

            // Cold miss.
            dut.io.pred_valid.expect(false.B)
            dut.io.pred_taken.expect(false.B)

            // Not-taken conditional miss is not allocated.
            update(dut, pc = 0x1020, target = 0x1060, taken = false, isBranch = true)
            dut.io.req_pc.poke("h1020".U)
            dut.io.pred_valid.expect(false.B)
            dut.io.pred_taken.expect(false.B)

            // Taken conditional branch allocates and predicts taken.
            update(dut, pc = 0x1000, target = 0x1040, taken = true, isBranch = true)
            dut.io.req_pc.poke("h1000".U)
            dut.io.pred_valid.expect(true.B)
            dut.io.pred_taken.expect(true.B)
            dut.io.pred_target.expect("h1040".U)

            // Existing entry remains allocated while the counter decays.
            update(dut, pc = 0x1000, target = 0x1040, taken = false, isBranch = true)
            dut.io.req_pc.poke("h1000".U)
            dut.io.pred_valid.expect(true.B)
            dut.io.pred_taken.expect(true.B)

            update(dut, pc = 0x1000, target = 0x1040, taken = false, isBranch = true)
            dut.io.req_pc.poke("h1000".U)
            dut.io.pred_valid.expect(true.B)
            dut.io.pred_taken.expect(false.B)

            // Unconditional jumps are always strongly taken.
            update(dut, pc = 0x1004, target = 0x2000, taken = true, isBranch = false)
            dut.io.req_pc.poke("h1004".U)
            dut.io.pred_valid.expect(true.B)
            dut.io.pred_taken.expect(true.B)
            dut.io.pred_target.expect("h2000".U)

            // Halfword index separates adjacent compressed branch PCs.
            dut.io.req_pc.poke("h1002".U)
            dut.io.pred_valid.expect(false.B)

            update(dut, pc = 0x1002, target = 0x1080, taken = true, isBranch = true)
            dut.io.req_pc.poke("h1000".U)
            dut.io.pred_valid.expect(true.B)
            dut.io.pred_target.expect("h1040".U)
            dut.io.req_pc.poke("h1002".U)
            dut.io.pred_valid.expect(true.B)
            dut.io.pred_target.expect("h1080".U)

            // Same direct-mapped index but different tag must miss.
            dut.io.req_pc.poke("h1010".U)
            dut.io.pred_valid.expect(false.B)
            dut.io.pred_taken.expect(false.B)
        }
    }
}
