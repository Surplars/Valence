package core

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.core.LoadUseScoreboard
import soc.core.pipeline.MemOpType

class LoadUseScoreboardSpec extends AnyFunSuite with ChiselSim {
    private def init(dut: LoadUseScoreboard): Unit = {
        dut.io.flush.poke(false.B)
        dut.io.aluValid.poke(false.B)
        dut.io.aluRegWrite.poke(false.B)
        dut.io.aluRd.poke(0.U)
        dut.io.aluPc.poke(0.U)
        dut.io.aluMemOp.poke(MemOpType.None)
        dut.io.lsuLoadDataValid.poke(false.B)
        dut.io.lsuLoadDataRd.poke(0.U)
        dut.io.wbRegWrite.poke(false.B)
        dut.io.wbRd.poke(0.U)
        dut.io.decodeValid.poke(false.B)
        dut.io.decodeRs1.poke(0.U)
        dut.io.decodeRs2.poke(0.U)
    }

    test("clears a stale load dependency on pipeline flush") {
        simulate(new LoadUseScoreboard(64)) { dut =>
            init(dut)

            dut.io.aluValid.poke(true.B)
            dut.io.aluRegWrite.poke(true.B)
            dut.io.aluRd.poke(12.U)
            dut.io.aluPc.poke("h100".U)
            dut.io.aluMemOp.poke(MemOpType.Load)
            dut.clock.step()

            dut.io.aluValid.poke(false.B)
            dut.io.decodeValid.poke(true.B)
            dut.io.decodeRs1.poke(12.U)
            dut.io.decodeUsesPending.expect(true.B)

            dut.io.flush.poke(true.B)
            dut.clock.step()

            dut.io.flush.poke(false.B)
            dut.io.decodeUsesPending.expect(false.B)
            dut.io.pending.expect(false.B)
            dut.io.pendingRd.expect(0.U)
        }
    }

    test("preserves a new load dependency when an older one completes in the same cycle") {
        simulate(new LoadUseScoreboard(64)) { dut =>
            init(dut)

            dut.io.aluValid.poke(true.B)
            dut.io.aluRegWrite.poke(true.B)
            dut.io.aluRd.poke(5.U)
            dut.io.aluPc.poke("h100".U)
            dut.io.aluMemOp.poke(MemOpType.Load)
            dut.clock.step()

            dut.io.aluRd.poke(6.U)
            dut.io.aluPc.poke("h104".U)
            dut.io.lsuLoadDataValid.poke(true.B)
            dut.io.lsuLoadDataRd.poke(5.U)
            dut.clock.step()

            dut.io.aluValid.poke(false.B)
            dut.io.lsuLoadDataValid.poke(false.B)
            dut.io.decodeValid.poke(true.B)
            dut.io.decodeRs1.poke(6.U)
            dut.io.decodeUsesPending.expect(true.B)
            dut.io.pending.expect(true.B)
            dut.io.pendingRd.expect(6.U)
        }
    }
}
