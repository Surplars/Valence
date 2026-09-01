package core

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.core.pipeline._
import soc.isa.{MCause, PrivilegeLevel}

class InstrFetchSpec extends AnyFunSuite with ChiselSim {
    private val V = 1 << 0
    private val R = 1 << 1
    private val X = 1 << 3
    private val A = 1 << 6

    private def pte(ppn: BigInt, flags: Int): BigInt = (ppn << 10) | BigInt(flags)
    private def ppn(pa: BigInt): BigInt = pa >> 12
    private def satp(root: BigInt): BigInt = (BigInt(8) << 60) | (root >> 12)

    private def init(dut: InstrFetch): Unit = {
        dut.io.pc.poke("h80000000".U)
        dut.io.instr_in.poke("h0000000000000013".U)
        dut.io.pred_taken_in.poke(false.B)
        dut.io.pred_target_in.poke(0.U)
        dut.io.redirect.poke(false.B)
        dut.io.trap_valid.poke(false.B)
        dut.io.stall.poke(false.B)
        dut.io.cache.req.ready.poke(false.B)
        dut.io.cache.resp.valid.poke(false.B)
        dut.io.cache.resp.bits.rdata.poke(0.U)
        dut.io.cache.resp.bits.err.poke(false.B)
        dut.io.ptw.req.ready.poke(false.B)
        dut.io.ptw.resp.valid.poke(false.B)
        dut.io.ptw.resp.bits.rdata.poke(0.U)
        dut.io.ptw.resp.bits.err.poke(false.B)
        dut.io.mem_cfg.priv.poke(PrivilegeLevel.Machine)
        dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Machine)
        dut.io.mem_cfg.mmu_en.poke(false.B)
        dut.io.mem_cfg.satp.poke(0.U)
        dut.io.mem_cfg.pmpcfg0.poke(0.U)
        for (i <- 0 until 8) {
            dut.io.mem_cfg.pmpaddr(i).poke(0.U)
        }
        dut.io.mem_cfg.mxr.poke(false.B)
        dut.io.mem_cfg.sum.poke(false.B)
        dut.io.mem_cfg.mprv.poke(false.B)
        dut.io.trap_info.valid.expect(false.B)
    }

    private def acceptCacheRead(dut: InstrFetch, data: BigInt, err: Boolean = false): Unit = {
        dut.clock.step()
        dut.io.cache.resp.valid.poke(true.B)
        dut.io.cache.resp.bits.rdata.poke(data.U)
        dut.io.cache.resp.bits.err.poke(err.B)
        dut.clock.step()
        dut.io.cache.resp.valid.poke(false.B)
        dut.io.cache.resp.bits.rdata.poke(0.U)
        dut.io.cache.resp.bits.err.poke(false.B)
    }

    private def acceptPtwRead(dut: InstrFetch, data: BigInt, err: Boolean = false): Unit = {
        dut.clock.step()
        dut.io.ptw.resp.valid.poke(true.B)
        dut.io.ptw.resp.bits.rdata.poke(data.U)
        dut.io.ptw.resp.bits.err.poke(err.B)
        dut.clock.step()
        dut.io.ptw.resp.valid.poke(false.B)
        dut.io.ptw.resp.bits.rdata.poke(0.U)
        dut.io.ptw.resp.bits.err.poke(false.B)
    }

    private def expectCacheRead(dut: InstrFetch, addr: BigInt, vaddr: Option[BigInt] = None, maxCycles: Int = 8): Unit = {
        var seen = false
        var cycles = 0
        while (!seen && cycles < maxCycles) {
            if (dut.io.cache.req.valid.peek().litToBoolean) {
                dut.io.cache.req.bits.addr.expect(addr.U)
                vaddr.foreach(expected => dut.io.cache.req.bits.vaddr.expect(expected.U))
                seen = true
            } else {
                dut.clock.step()
                cycles += 1
            }
        }
        if (!seen) {
            dut.io.cache.req.valid.expect(true.B)
        }
    }

    private def expectPtwRead(dut: InstrFetch, addr: BigInt, maxCycles: Int = 8): Unit = {
        var seen = false
        var cycles = 0
        while (!seen && cycles < maxCycles) {
            if (dut.io.ptw.req.valid.peek().litToBoolean) {
                dut.io.ptw.req.bits.addr.expect(addr.U)
                dut.io.ptw.req.bits.vaddr.expect(addr.U)
                seen = true
            } else {
                dut.clock.step()
                cycles += 1
            }
        }
        if (!seen) {
            dut.io.ptw.req.valid.expect(true.B)
        }
    }

    private def expectFetchTrap(dut: InstrFetch, cause: UInt, value: BigInt, pc: BigInt, maxCycles: Int = 8): Unit = {
        var seen = false
        var cycles = 0
        while (!seen && cycles < maxCycles) {
            if (dut.io.trap_info.valid.peek().litToBoolean) {
                dut.io.trap_info.pc.expect(pc.U)
                dut.io.trap_info.cause.expect(cause)
                dut.io.trap_info.value.expect(value.U)
                seen = true
            } else {
                dut.clock.step()
                cycles += 1
            }
        }
        if (!seen) {
            dut.io.trap_info.valid.expect(true.B)
        }
    }

    test("InstrFetch expands compressed low and high halfwords") {
        simulate(new InstrFetch(64, useCompressed = true)) { dut =>
            init(dut)

            dut.io.pc.poke("h80000000".U)
            dut.io.instr_in.poke("h0000000000850001".U) // high c.addi x1,1; low c.nop
            dut.clock.step()
            dut.io.valid.expect(true.B)
            dut.io.instr_len.expect(2.U)
            dut.io.instr_out.expect("h00000013".U)

            dut.io.pc.poke("h80000002".U)
            dut.io.instr_in.poke("h0000000000850001".U)
            dut.clock.step()
            dut.io.valid.expect(true.B)
            dut.io.instr_len.expect(2.U)
            dut.io.instr_out.expect("h00108093".U)
        }
    }

    test("InstrFetch leaves normal 32-bit instructions unchanged") {
        simulate(new InstrFetch(64, useCompressed = true)) { dut =>
            init(dut)

            dut.io.instr_in.poke("h0000000000500113".U)
            dut.clock.step()
            dut.io.valid.expect(true.B)
            dut.io.instr_len.expect(0.U)
            dut.io.instr_out.expect("h00500113".U)
        }
    }

    test("InstrFetch drains stale PTW responses after translation is cancelled") {
        simulate(new InstrFetch(64, useCache = true, useCompressed = true)) { dut =>
            init(dut)
            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.mmu_en.poke(true.B)
            dut.io.mem_cfg.satp.poke(satp(BigInt("40000000", 16)).U)

            dut.io.ptw.resp.valid.poke(true.B)
            dut.io.ptw.resp.bits.rdata.poke(0.U)
            dut.io.ptw.resp.bits.err.poke(false.B)
            dut.io.ptw.resp.ready.expect(true.B)
        }
    }

    test("InstrFetch drains an in-flight PTW walk cancelled by a trap") {
        simulate(new InstrFetch(64, useCache = true, useCompressed = true)) { dut =>
            init(dut)
            val root = BigInt("10000000", 16)
            val l1 = BigInt("10001000", 16)
            val leafPa = BigInt("80004000", 16)
            val oldVa = BigInt("40000000", 16)
            val newVa = BigInt("40001000", 16)
            val oldVpn2 = (oldVa >> 30) & 0x1ff
            val oldVpn1 = (oldVa >> 21) & 0x1ff
            val newVpn2 = (newVa >> 30) & 0x1ff

            dut.io.pc.poke(oldVa.U)
            dut.io.ptw.req.ready.poke(true.B)
            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.mmu_en.poke(true.B)
            dut.io.mem_cfg.satp.poke(satp(root).U)

            expectPtwRead(dut, root + oldVpn2 * 8)
            acceptPtwRead(dut, pte(ppn(l1), V))

            expectPtwRead(dut, l1 + oldVpn1 * 8)
            dut.io.trap_valid.poke(true.B)
            dut.io.ptw.req.valid.expect(true.B)
            dut.io.ptw.req.ready.expect(true.B)
            dut.clock.step()

            dut.io.trap_valid.poke(false.B)
            // The cancelled request still owns the shared PTW response path.
            // Keep PC stalled until that stale response has been consumed;
            // otherwise sequential PCs can be skipped without ever fetching.
            dut.io.pc.poke(newVa.U)
            dut.io.fetch_stall.expect(true.B)
            dut.io.ptw.resp.valid.poke(true.B)
            dut.io.ptw.resp.bits.rdata.poke(pte(ppn(leafPa), V | R | X | A).U)
            dut.io.ptw.resp.bits.err.poke(false.B)
            dut.io.ptw.resp.ready.expect(true.B)
            dut.clock.step()

            dut.io.ptw.resp.valid.poke(false.B)
            expectPtwRead(dut, root + newVpn2 * 8)
        }
    }

    test("InstrFetch assembles a 32-bit instruction starting at a high halfword") {
        simulate(new InstrFetch(64, useCompressed = true)) { dut =>
            init(dut)

            dut.io.pc.poke("h80000002".U)
            dut.io.instr_in.poke("h0000005001130001".U)
            dut.clock.step()
            dut.io.valid.expect(true.B)
            dut.io.instr_len.expect(0.U)
            dut.io.instr_out.expect("h00500113".U)
        }
    }

    test("InstrFetch cache path assembles a 32-bit instruction crossing a 64-bit beat") {
        simulate(new InstrFetch(64, useCache = true, useCompressed = true)) { dut =>
            init(dut)

            dut.io.pc.poke("h1000000e".U)
            dut.io.cache.req.ready.poke(true.B)

            dut.io.cache.req.valid.expect(true.B)
            dut.io.cache.req.bits.addr.expect("h1000000e".U)

            dut.clock.step()
            dut.io.cache.resp.valid.poke(true.B)
            dut.io.cache.resp.bits.rdata.poke("ha2af000000000000".U)
            dut.clock.step()

            dut.io.cache.resp.valid.poke(false.B)
            dut.io.cache.req.valid.expect(true.B)
            dut.io.cache.req.bits.addr.expect("h10000010".U)

            dut.clock.step()
            dut.io.cache.resp.valid.poke(true.B)
            dut.io.cache.resp.bits.rdata.poke("h0000000000000062".U)
            dut.io.valid.expect(true.B)
            dut.io.instr_len.expect(0.U)
            dut.io.instr_out.expect("h0062a2af".U)
            dut.clock.step()

            dut.io.cache.resp.valid.poke(false.B)
            dut.io.valid.expect(false.B)
        }
    }

    test("InstrFetch cache path reports current compressed length for PC stepping") {
        simulate(new InstrFetch(64, useCache = true, useCompressed = true)) { dut =>
            init(dut)
            dut.io.cache.req.ready.poke(true.B)

            dut.io.pc.poke("h4000f1d4".U)
            dut.clock.step()
            dut.io.cache.resp.bits.rdata.poke("h0000100ffe62c3e3".U) // previous blt; fence.i
            dut.io.cache.resp.bits.err.poke(false.B)
            dut.io.cache.resp.valid.poke(true.B)
            dut.clock.step()
            dut.io.valid.expect(true.B)
            dut.io.instr_out.expect("h0000100f".U)
            dut.io.instr_len.expect(0.U)
            dut.io.pc_step_len.expect(0.U)

            dut.io.cache.resp.valid.poke(false.B)
            dut.clock.step()
            dut.io.pc.poke("h4000f1d8".U)
            dut.clock.step()
            dut.io.cache.resp.bits.rdata.poke("h0000000000008082".U) // c.jr ra; c.unimp; c.unimp
            dut.io.cache.resp.valid.poke(true.B)
            dut.clock.step()
            dut.io.valid.expect(true.B)
            dut.io.instr_out.expect("h00008067".U) // c.jr ra expands to jalr x0, 0(ra)
            dut.io.instr_len.expect(2.U)
            dut.io.pc_step_len.expect(2.U)
        }
    }

    test("InstrFetch steps over Linux __delay mixed compressed and 32-bit sequence") {
        simulate(new InstrFetch(64, useCache = true, useCompressed = true)) { dut =>
            init(dut)
            dut.io.cache.req.ready.poke(true.B)

            val base = BigInt("ffffffff800d2ee8", 16)
            val firstBeat = BigInt("c01027f3c0102773", 16) // rdtime a4; rdtime a5
            val secondBeat = BigInt("808200a7e3638f99", 16) // c.sub; bltu; c.jr ra

            dut.io.pc.poke(base.U)
            dut.io.cache.req.valid.expect(true.B)
            dut.io.cache.req.bits.addr.expect(base.U)

            dut.clock.step()
            dut.io.cache.resp.bits.rdata.poke(firstBeat.U)
            dut.io.cache.resp.valid.poke(true.B)
            dut.io.valid.expect(true.B)
            dut.io.pc_out.expect(base.U)
            dut.io.instr_out.expect("hc0102773".U)
            dut.io.instr_len.expect(0.U)
            dut.io.pc_step_len.expect(0.U)
            dut.clock.step()

            dut.io.cache.resp.valid.poke(false.B)
            dut.io.pc.poke((base + 4).U)
            dut.io.valid.expect(true.B)
            dut.io.pc_out.expect((base + 4).U)
            dut.io.instr_out.expect("hc01027f3".U)
            dut.io.instr_len.expect(0.U)
            dut.io.pc_step_len.expect(0.U)
            dut.clock.step()

            dut.io.pc.poke((base + 8).U)
            dut.io.cache.req.valid.expect(true.B)
            dut.io.cache.req.bits.addr.expect((base + 8).U)

            dut.clock.step()
            dut.io.cache.resp.bits.rdata.poke(secondBeat.U)
            dut.io.cache.resp.valid.poke(true.B)
            dut.io.valid.expect(true.B)
            dut.io.pc_out.expect((base + 8).U)
            dut.io.instr_len.expect(2.U)
            dut.io.pc_step_len.expect(2.U)
            dut.clock.step()

            dut.io.cache.resp.valid.poke(false.B)
            dut.io.pc.poke((base + 10).U)
            dut.io.valid.expect(true.B)
            dut.io.pc_out.expect((base + 10).U)
            dut.io.instr_out.expect("h00a7e363".U)
            dut.io.instr_len.expect(0.U)
            dut.io.pc_step_len.expect(0.U)
            dut.clock.step()

            dut.io.pc.poke((base + 14).U)
            dut.io.valid.expect(true.B)
            dut.io.pc_out.expect((base + 14).U)
            dut.io.instr_out.expect("h00008067".U)
            dut.io.instr_len.expect(2.U)
            dut.io.pc_step_len.expect(2.U)
        }
    }

    test("InstrFetch cache path reuses buffered 64-bit beat for sequential PC") {
        simulate(new InstrFetch(64, useCache = true, useCompressed = true)) { dut =>
            init(dut)
            dut.io.cache.req.ready.poke(true.B)

            dut.io.pc.poke("h1000".U)
            dut.io.cache.req.valid.expect(true.B)
            dut.io.cache.req.bits.addr.expect("h1000".U)

            dut.clock.step()
            dut.io.cache.resp.bits.rdata.poke("h0071019300500113".U) // addi x2,0,5; addi x3,x2,7
            dut.io.cache.resp.valid.poke(true.B)
            dut.io.valid.expect(true.B)
            dut.io.instr_out.expect("h00500113".U)
            dut.io.pc_step_len.expect(0.U)
            dut.clock.step()

            dut.io.cache.resp.valid.poke(false.B)
            dut.io.pc.poke("h1004".U)
            dut.io.valid.expect(true.B)
            dut.io.instr_out.expect("h00710193".U)
            // Serving a buffered instruction no longer issues an untagged
            // next-beat prefetch. The old path could drive a prefetched beat as
            // the current instruction when RVC and 32-bit instructions mixed
            // around a 64-bit beat boundary.
            dut.io.cache.req.valid.expect(false.B)
            dut.io.fetch_stall.expect(false.B)
            dut.clock.step()
        }
    }

    test("InstrFetch cache path skips next-beat prefetch on taken prediction") {
        simulate(new InstrFetch(64, useCache = true, useCompressed = true)) { dut =>
            init(dut)
            dut.io.cache.req.ready.poke(true.B)

            dut.io.pc.poke("h1000".U)
            dut.clock.step()
            dut.io.cache.resp.bits.rdata.poke("h0071019300500113".U) // addi x2,0,5; addi x3,x2,7
            dut.io.cache.resp.valid.poke(true.B)
            dut.clock.step()

            dut.io.cache.resp.valid.poke(false.B)
            dut.io.pc.poke("h1004".U)
            dut.io.pred_taken_in.poke(true.B)
            dut.io.pred_target_in.poke("h2000".U)
            dut.clock.step()
            dut.io.valid.expect(true.B)
            dut.io.instr_out.expect("h00710193".U)
            dut.io.cache.req.valid.expect(false.B)
            dut.io.fetch_stall.expect(false.B)
        }
    }

    test("InstrFetch expands common compressed memory and register forms") {
        simulate(new InstrFetch(64, useCompressed = true)) { dut =>
            init(dut)

            dut.io.instr_in.poke("h0000000000004104".U) // c.lw x9, 0(x10)
            dut.clock.step()
            dut.io.instr_len.expect(2.U)
            dut.io.instr_out.expect("h00052483".U)

            dut.io.instr_in.poke("h000000000000c104".U) // c.sw x9, 0(x10)
            dut.clock.step()
            dut.io.instr_len.expect(2.U)
            dut.io.instr_out.expect("h00952023".U)

            dut.io.instr_in.poke("h000000000000908a".U) // c.add x1, x2
            dut.clock.step()
            dut.io.instr_len.expect(2.U)
            dut.io.instr_out.expect("h002080b3".U)
        }
    }

    test("InstrFetch expands compressed jump with negative offset") {
        simulate(new InstrFetch(64, useCompressed = true)) { dut =>
            init(dut)

            dut.io.pc.poke("h4000f2c8".U)
            dut.io.instr_in.poke("h000000000000bfe1".U) // c.j 0x4000f2a0
            dut.clock.step()
            dut.io.valid.expect(true.B)
            dut.io.instr_len.expect(2.U)
            dut.io.instr_out.expect("hfd9ff06f".U)
        }
    }

    test("InstrFetch expands RV64C stack and word arithmetic forms") {
        simulate(new InstrFetch(64, useCompressed = true)) { dut =>
            init(dut)

            dut.io.instr_in.poke("h00000000000064c2".U) // c.ldsp x9, 16(sp)
            dut.clock.step()
            dut.io.instr_len.expect(2.U)
            dut.io.instr_out.expect("h01013483".U)

            dut.io.instr_in.poke("h000000000000ec26".U) // c.sdsp x9, 24(sp)
            dut.clock.step()
            dut.io.instr_len.expect(2.U)
            dut.io.instr_out.expect("h00913c23".U)

            dut.io.instr_in.poke("h0000000000009ca9".U) // c.addw x9, x10
            dut.clock.step()
            dut.io.instr_len.expect(2.U)
            dut.io.instr_out.expect("h00a484bb".U)

            dut.io.instr_in.poke("h0000000000009c89".U) // c.subw x9, x10
            dut.clock.step()
            dut.io.instr_len.expect(2.U)
            dut.io.instr_out.expect("h40a484bb".U)
        }
    }

    test("InstrFetch turns illegal compressed encodings into illegal 32-bit instructions") {
        simulate(new InstrFetch(64, useCompressed = true)) { dut =>
            init(dut)

            dut.io.instr_in.poke("h0000000000000000".U) // reserved compressed encoding
            dut.clock.step()
            dut.io.instr_len.expect(2.U)
            dut.io.instr_out.expect("h00000000".U)
        }
    }

    test("InstrFetch translates supervisor cache fetches through Sv39 before issuing ICache request") {
        simulate(new InstrFetch(64, useCache = true, useCompressed = true)) { dut =>
            init(dut)
            val root = BigInt("10000000", 16)
            val l1 = BigInt("10001000", 16)
            val l0 = BigInt("10002000", 16)
            val leafPa = BigInt("80004000", 16)
            val va = BigInt("40000000", 16)
            val vpn0 = (va >> 12) & 0x1ff
            val vpn1 = (va >> 21) & 0x1ff
            val vpn2 = (va >> 30) & 0x1ff

            dut.io.pc.poke(va.U)
            dut.io.cache.req.ready.poke(true.B)
            dut.io.ptw.req.ready.poke(true.B)
            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.mmu_en.poke(true.B)
            dut.io.mem_cfg.satp.poke(satp(root).U)

            expectPtwRead(dut, root + vpn2 * 8)
            dut.io.cache.req.valid.expect(false.B)
            acceptPtwRead(dut, pte(ppn(l1), V))

            expectPtwRead(dut, l1 + vpn1 * 8)
            acceptPtwRead(dut, pte(ppn(l0), V))

            expectPtwRead(dut, l0 + vpn0 * 8)
            acceptPtwRead(dut, pte(ppn(leafPa), V | R | X | A))

            expectCacheRead(dut, leafPa, Some(va))
            acceptCacheRead(dut, BigInt("0000000000500113", 16))

            dut.io.valid.expect(true.B)
            dut.io.pc_out.expect(va.U)
            dut.io.instr_out.expect("h00500113".U)
            dut.io.trap_info.valid.expect(false.B)
        }
    }

    test("InstrFetch reports Sv39 instruction page faults without issuing ICache fetch") {
        simulate(new InstrFetch(64, useCache = true, useCompressed = true)) { dut =>
            init(dut)
            val root = BigInt("10000000", 16)
            val va = BigInt("40000000", 16)
            val vpn2 = (va >> 30) & 0x1ff

            dut.io.pc.poke(va.U)
            dut.io.cache.req.ready.poke(true.B)
            dut.io.ptw.req.ready.poke(true.B)
            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.mmu_en.poke(true.B)
            dut.io.mem_cfg.satp.poke(satp(root).U)

            expectPtwRead(dut, root + vpn2 * 8)
            acceptPtwRead(dut, pte(0x1000, V | R | A))

            expectFetchTrap(dut, MCause.InstrPageFault, va, va)
            dut.io.cache.req.valid.expect(false.B)
            dut.io.valid.expect(false.B)
        }
    }
}
