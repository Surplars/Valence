package core

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.core.pipeline.StoreBuffer

class StoreBufferSpec extends AnyFunSuite with ChiselSim {
    private def init(dut: StoreBuffer): Unit = {
        dut.io.enq_valid.poke(false.B)
        dut.io.enq_pc.poke(0.U)
        dut.io.enq_vaddr.poke(0.U)
        dut.io.enq_addr.poke(0.U)
        dut.io.enq_data.poke(0.U)
        dut.io.enq_mask.poke(0.U)
        dut.io.enq_size.poke(3.U)
        dut.io.search_addr.poke(0.U)
        dut.io.search_mask.poke(0.U)
        dut.io.deq_ready.poke(false.B)
    }

    test("StoreBuffer forwards the newest matching store for duplicate addresses") {
        simulate(new StoreBuffer(entries = 4, AW = 64, DW = 64)) { dut =>
            init(dut)

            dut.io.enq_addr.poke("h1000".U)
            dut.io.enq_mask.poke("hff".U)

            dut.io.enq_data.poke("h1111111111111111".U)
            dut.io.enq_valid.poke(true.B)
            dut.io.enq_ready.expect(true.B)
            dut.clock.step()

            dut.io.enq_data.poke("h2222222222222222".U)
            dut.io.enq_ready.expect(true.B)
            dut.clock.step()
            dut.io.enq_valid.poke(false.B)

            dut.io.search_addr.poke("h1000".U)
            dut.io.search_mask.poke("hff".U)
            dut.io.search_hit.expect(true.B)
            dut.io.search_data.expect(BigInt("2222222222222222", 16))
        }
    }

    test("StoreBuffer forwards covered byte lanes within the same beat") {
        simulate(new StoreBuffer(entries = 4, AW = 64, DW = 64)) { dut =>
            init(dut)

            dut.io.enq_valid.poke(true.B)
            dut.io.enq_addr.poke("h1000".U)
            dut.io.enq_data.poke(BigInt("1122334455667788", 16).U)
            dut.io.enq_mask.poke("hff".U)
            dut.clock.step()
            dut.io.enq_valid.poke(false.B)

            dut.io.search_addr.poke("h1003".U)
            dut.io.search_mask.poke("h08".U)
            dut.io.search_hit.expect(true.B)
            dut.io.search_conflict.expect(false.B)
            dut.io.search_data.expect(BigInt("1122334455667788", 16))
        }
    }

    test("StoreBuffer reports partial overlap conflicts") {
        simulate(new StoreBuffer(entries = 4, AW = 64, DW = 64)) { dut =>
            init(dut)

            dut.io.enq_valid.poke(true.B)
            dut.io.enq_addr.poke("h1000".U)
            dut.io.enq_data.poke(BigInt("00000000aa000000", 16).U)
            dut.io.enq_mask.poke("h08".U)
            dut.clock.step()
            dut.io.enq_valid.poke(false.B)

            dut.io.search_addr.poke("h1002".U)
            dut.io.search_mask.poke("h0c".U)
            dut.io.search_hit.expect(false.B)
            dut.io.search_conflict.expect(true.B)
        }
    }

    test("StoreBuffer accepts enqueue while full when dequeue also fires") {
        simulate(new StoreBuffer(entries = 2, AW = 64, DW = 64)) { dut =>
            init(dut)

            dut.io.enq_valid.poke(true.B)
            dut.io.enq_addr.poke("h1000".U)
            dut.io.enq_data.poke("h1111".U)
            dut.io.enq_mask.poke("hff".U)
            dut.io.enq_ready.expect(true.B)
            dut.clock.step()

            dut.io.enq_addr.poke("h1008".U)
            dut.io.enq_data.poke("h2222".U)
            dut.io.enq_ready.expect(true.B)
            dut.clock.step()
            dut.io.enq_ready.expect(false.B)

            dut.io.deq_ready.poke(true.B)
            dut.io.enq_addr.poke("h1010".U)
            dut.io.enq_data.poke("h3333".U)
            dut.io.enq_ready.expect(true.B)
            dut.io.deq_addr.expect("h1000".U)
            dut.clock.step()

            dut.io.enq_valid.poke(false.B)
            dut.io.deq_addr.expect("h1008".U)
            dut.clock.step()
            dut.io.deq_addr.expect("h1010".U)
        }
    }
}
