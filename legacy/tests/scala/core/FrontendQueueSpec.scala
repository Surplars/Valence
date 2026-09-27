package core

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.core.pipeline.FrontendQueue

class FrontendQueueSpec extends AnyFunSuite with ChiselSim {
    private def init(dut: FrontendQueue): Unit = {
        dut.io.flush.poke(false.B)
        dut.io.enq.valid.poke(false.B)
        dut.io.enq.bits.pc.poke(0.U)
        dut.io.enq.bits.instr.poke(0.U)
        dut.io.enq.bits.instrLen.poke(0.U)
        dut.io.enq.bits.predTaken.poke(false.B)
        dut.io.enq.bits.predTarget.poke(0.U)
        dut.io.deq.ready.poke(false.B)
    }

    private def driveEntry(dut: FrontendQueue, pc: BigInt, instr: BigInt): Unit = {
        dut.io.enq.valid.poke(true.B)
        dut.io.enq.bits.pc.poke(pc.U)
        dut.io.enq.bits.instr.poke(instr.U)
        dut.io.enq.bits.instrLen.poke(0.U)
        dut.io.enq.bits.predTaken.poke(false.B)
        dut.io.enq.bits.predTarget.poke(0.U)
    }

    test("FrontendQueue preserves order and allows enqueue into a freed full slot") {
        simulate(new FrontendQueue(64, entries = 2)) { dut =>
            init(dut)

            driveEntry(dut, pc = 0x1000, instr = 0x13)
            dut.io.enq.ready.expect(true.B)
            dut.clock.step()

            driveEntry(dut, pc = 0x1004, instr = 0x93)
            dut.io.enq.ready.expect(true.B)
            dut.clock.step()
            dut.io.full.expect(true.B)

            driveEntry(dut, pc = 0x1008, instr = 0x113)
            dut.io.deq.ready.poke(true.B)
            dut.io.enq.ready.expect(true.B)
            dut.io.deq.valid.expect(true.B)
            dut.io.deq.bits.pc.expect("h1000".U)
            dut.clock.step()

            dut.io.enq.valid.poke(false.B)
            dut.io.deq.bits.pc.expect("h1004".U)
            dut.clock.step()
            dut.io.deq.bits.pc.expect("h1008".U)
        }
    }

    test("FrontendQueue flush drops queued entries") {
        simulate(new FrontendQueue(64, entries = 2)) { dut =>
            init(dut)

            driveEntry(dut, pc = 0x2000, instr = 0x13)
            dut.clock.step()
            dut.io.empty.expect(false.B)

            dut.io.enq.valid.poke(false.B)
            dut.io.flush.poke(true.B)
            dut.clock.step()
            dut.io.flush.poke(false.B)
            dut.io.empty.expect(true.B)
            dut.io.deq.valid.expect(false.B)
        }
    }
}
