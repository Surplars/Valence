package core

import chisel3._
import chisel3.simulator.scalatest.ChiselSim
import org.scalatest.funsuite.AnyFunSuite
import soc.core.pipeline._
import soc.isa.{MCause, PrivilegeLevel}
import soc.memory.cache.CacheCmd

class LSUSpec extends AnyFunSuite with ChiselSim {
    private val pmpNapotRwx = 0x1f
    private val V = 1 << 0
    private val R = 1 << 1
    private val W = 1 << 2
    private val A = 1 << 6
    private val D = 1 << 7

    private def pte(ppn: BigInt, flags: Int): BigInt = (ppn << 10) | BigInt(flags)
    private def ppn(pa: BigInt): BigInt = pa >> 12
    private def satp(root: BigInt): BigInt = (BigInt(8) << 60) | (root >> 12)

    private def init(dut: LSU): Unit = {
        dut.io.pc_in.poke("h80000000".U)
        dut.io.valid_in.poke(false.B)
        dut.io.trap_valid.poke(false.B)
        dut.io.trap_info_in.valid.poke(false.B)
        dut.io.trap_info_in.pc.poke(0.U)
        dut.io.trap_info_in.cause.poke(0.U)
        dut.io.trap_info_in.value.poke(0.U)
        dut.io.trap_info_in.is_ret.poke(false.B)
        dut.io.trap_info_in.ret_type.poke(TrapReturnType.None)

        dut.io.alu_out.result.poke(0.U)
        dut.io.alu_out.instr.poke(0.U)
        dut.io.alu_out.instr_len.poke(0.U)
        dut.io.alu_out.funct3.poke(0.U)
        dut.io.alu_out.rd.poke(0.U)
        dut.io.alu_out.reg_write.poke(false.B)
        dut.io.alu_out.mem_read.poke(false.B)
        dut.io.alu_out.mem_write.poke(false.B)
        dut.io.alu_out.mem_addr.poke(0.U)
        dut.io.alu_out.mem.valid.poke(false.B)
        dut.io.alu_out.mem.op.poke(MemOpType.None)
        dut.io.alu_out.mem.vaddr.poke(0.U)
        dut.io.alu_out.mem.paddr.poke(0.U)
        dut.io.alu_out.mem.size.poke(3.U)
        dut.io.alu_out.mem.signed.poke(false.B)
        dut.io.alu_out.mem.mask.poke(0.U)
        dut.io.alu_out.mem.wdata.poke(0.U)
        dut.io.alu_out.mem.atomic.poke(AtomicOpType.None)
        dut.io.alu_out.mem.aq.poke(false.B)
        dut.io.alu_out.mem.rl.poke(false.B)
        dut.io.alu_out.mem.attrs.cacheable.poke(false.B)
        dut.io.alu_out.mem.attrs.device.poke(false.B)
        dut.io.alu_out.mem.attrs.bufferable.poke(false.B)
        dut.io.alu_out.mem.attrs.allocate.poke(false.B)
        dut.io.alu_out.mem.attrs.translate.poke(false.B)
        dut.io.alu_out.mem.attrs.executable.poke(false.B)

        dut.io.mem_cfg.priv.poke(3.U)
        dut.io.mem_cfg.data_priv.poke(3.U)
        dut.io.mem_cfg.mmu_en.poke(false.B)
        dut.io.mem_cfg.satp.poke(0.U)
        dut.io.mem_cfg.pmpcfg0.poke(0.U)
        for (i <- 0 until 8) {
            dut.io.mem_cfg.pmpaddr(i).poke(0.U)
        }
        dut.io.mem_cfg.mxr.poke(false.B)
        dut.io.mem_cfg.sum.poke(false.B)
        dut.io.mem_cfg.mprv.poke(false.B)

        dut.io.dcache.req.ready.poke(true.B)
        dut.io.dcache.resp.valid.poke(false.B)
        dut.io.dcache.resp.bits.rdata.poke(0.U)
        dut.io.dcache.resp.bits.err.poke(false.B)

        dut.io.mmio.req_ready.poke(true.B)
        dut.io.mmio.resp_valid.poke(false.B)
        dut.io.mmio.resp_data.poke(0.U)
        dut.io.mmio.resp_cmd.poke(0.U)
        dut.io.mmio.resp_source.poke(0.U)
        dut.io.mmio.resp_err.poke(false.B)
    }

    private def driveStore(dut: LSU, addr: BigInt, data: BigInt): Unit = {
        dut.io.valid_in.poke(true.B)
        dut.io.alu_out.result.poke(data.U)
        dut.io.alu_out.mem.valid.poke(true.B)
        dut.io.alu_out.mem.op.poke(MemOpType.Store)
        dut.io.alu_out.mem.vaddr.poke(addr.U)
        dut.io.alu_out.mem.paddr.poke(addr.U)
        dut.io.alu_out.mem.size.poke(3.U)
        dut.io.alu_out.mem.mask.poke("hff".U)
        dut.io.alu_out.mem.wdata.poke(data.U)
    }

    private def driveLoad(dut: LSU, addr: BigInt): Unit = {
        dut.io.valid_in.poke(true.B)
        dut.io.alu_out.mem.valid.poke(true.B)
        dut.io.alu_out.mem.op.poke(MemOpType.Load)
        dut.io.alu_out.mem.vaddr.poke(addr.U)
        dut.io.alu_out.mem.paddr.poke(addr.U)
        dut.io.alu_out.mem.size.poke(3.U)
        dut.io.alu_out.mem.mask.poke("hff".U)
        dut.io.alu_out.mem.signed.poke(false.B)
    }

    private def driveFence(dut: LSU, instr: BigInt = 0x0000000fL): Unit = {
        dut.io.valid_in.poke(true.B)
        dut.io.alu_out.instr.poke(instr.U)
        dut.io.alu_out.mem.valid.poke(true.B)
        dut.io.alu_out.mem.op.poke(MemOpType.Fence)
        dut.io.alu_out.mem.vaddr.poke(0.U)
        dut.io.alu_out.mem.paddr.poke(0.U)
        dut.io.alu_out.mem.size.poke(0.U)
        dut.io.alu_out.mem.mask.poke(0.U)
        dut.io.alu_out.mem.wdata.poke(0.U)
    }

    private def driveAtomic(dut: LSU, op: MemOpType.Type, atomic: AtomicOpType.Type, addr: BigInt, data: BigInt = 0, size: Int = 3): Unit = {
        val mask = if (size == 2) 0x0f else 0xff
        dut.io.valid_in.poke(true.B)
        dut.io.alu_out.reg_write.poke(true.B)
        dut.io.alu_out.mem.valid.poke(true.B)
        dut.io.alu_out.mem.op.poke(op)
        dut.io.alu_out.mem.atomic.poke(atomic)
        dut.io.alu_out.mem.vaddr.poke(addr.U)
        dut.io.alu_out.mem.paddr.poke(addr.U)
        dut.io.alu_out.mem.size.poke(size.U)
        dut.io.alu_out.mem.mask.poke(mask.U)
        dut.io.alu_out.mem.wdata.poke(data.U)
    }

    private def driveNoMem(dut: LSU): Unit = {
        dut.io.valid_in.poke(false.B)
        dut.io.alu_out.mem.valid.poke(false.B)
        dut.io.alu_out.mem.op.poke(MemOpType.None)
        dut.io.alu_out.mem.mask.poke(0.U)
        dut.io.alu_out.mem.wdata.poke(0.U)
    }

    private def expectDCacheRead(dut: LSU, addr: BigInt, maxCycles: Int = 8): Unit = {
        var seen = false
        var cycles = 0
        while (!seen && cycles < maxCycles) {
            if (dut.io.dcache.req.valid.peek().litToBoolean) {
                dut.io.dcache.req.bits.cmd.expect(CacheCmd.Read)
                dut.io.dcache.req.bits.addr.expect(addr.U)
                seen = true
            } else {
                dut.clock.step()
                cycles += 1
            }
        }
        if (!seen) {
            dut.io.dcache.req.valid.expect(true.B)
        }
    }

    private def acceptDCacheRead(dut: LSU, data: BigInt, err: Boolean = false): Unit = {
        dut.clock.step()
        dut.io.dcache.resp.valid.poke(true.B)
        dut.io.dcache.resp.bits.rdata.poke(data.U)
        dut.io.dcache.resp.bits.err.poke(err.B)
        dut.clock.step()
        dut.io.dcache.resp.valid.poke(false.B)
        dut.io.dcache.resp.bits.rdata.poke(0.U)
        dut.io.dcache.resp.bits.err.poke(false.B)
    }

    private def expectDCacheWrite(dut: LSU, addr: BigInt, data: BigInt, maxCycles: Int = 8): Unit = {
        var seen = false
        var cycles = 0
        while (!seen && cycles < maxCycles) {
            if (dut.io.dcache.req.valid.peek().litToBoolean) {
                dut.io.dcache.req.bits.cmd.expect(CacheCmd.Write)
                dut.io.dcache.req.bits.addr.expect(addr.U)
                dut.io.dcache.req.bits.wdata.expect(data.U)
                seen = true
            } else {
                dut.clock.step()
                cycles += 1
            }
        }
        if (!seen) {
            dut.io.dcache.req.valid.expect(true.B)
        }
    }

    private def expectDCacheFence(dut: LSU, maxCycles: Int = 8): Unit = {
        var seen = false
        var cycles = 0
        while (!seen && cycles < maxCycles) {
            if (dut.io.dcache.req.valid.peek().litToBoolean) {
                dut.io.dcache.req.bits.fence.expect(true.B)
                dut.io.dcache.req.bits.fencei.expect(false.B)
                seen = true
            } else {
                dut.clock.step()
                cycles += 1
            }
        }
        if (!seen) {
            dut.io.dcache.req.valid.expect(true.B)
        }
    }

    private def expectTrap(dut: LSU, cause: UInt, value: BigInt, pc: BigInt, maxCycles: Int = 8): Unit = {
        var seen = false
        var cycles = 0
        while (!seen && cycles < maxCycles) {
            if (dut.io.trap_info_out.valid.peek().litToBoolean) {
                dut.io.trap_info_out.pc.expect(pc.U)
                dut.io.trap_info_out.cause.expect(cause)
                dut.io.trap_info_out.value.expect(value.U)
                seen = true
            } else {
                dut.clock.step()
                cycles += 1
            }
        }
        if (!seen) {
            dut.io.trap_info_out.valid.expect(true.B)
        }
    }

    test("LSU forwards a load from the newest store buffer entry without DCache access") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            driveStore(dut, BigInt("10000000", 16), BigInt("1111111111111111", 16))
            dut.clock.step()

            driveStore(dut, BigInt("10000000", 16), BigInt("2222222222222222", 16))
            dut.clock.step()

            driveLoad(dut, BigInt("10000000", 16))
            dut.io.load_data_valid.expect(true.B)
            dut.io.load_data.expect(BigInt("2222222222222222", 16))
            dut.io.dcache.req.valid.expect(false.B)
        }
    }

    test("LSU reports store drain cache errors as StoreAccessFault") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            dut.io.pc_in.poke("h80000040".U)
            driveStore(dut, BigInt("10000008", 16), BigInt("abcdef0123456789", 16))
            dut.clock.step()

            driveNoMem(dut)
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Write)
            dut.io.dcache.req.bits.addr.expect(BigInt("10000008", 16))
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.io.dcache.resp.bits.err.poke(true.B)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)
            dut.io.dcache.resp.bits.err.poke(false.B)

            dut.clock.step()
            dut.io.trap_info_out.valid.expect(true.B)
            dut.io.trap_info_out.pc.expect(BigInt("80000040", 16))
            dut.io.trap_info_out.cause.expect(MCause.StoreAccessFault)
            dut.io.trap_info_out.value.expect(BigInt("10000008", 16))
        }
    }

    test("LSU reports cache load errors with the original load PC") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            dut.io.pc_in.poke("h80000080".U)
            driveLoad(dut, BigInt("10000010", 16))
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Read)
            dut.io.dcache.req.bits.addr.expect(BigInt("10000010", 16))
            dut.clock.step()

            dut.io.pc_in.poke("h80000088".U)
            dut.io.dcache.resp.valid.poke(true.B)
            dut.io.dcache.resp.bits.err.poke(true.B)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)
            dut.io.dcache.resp.bits.err.poke(false.B)

            dut.clock.step()
            dut.io.trap_info_out.valid.expect(true.B)
            dut.io.trap_info_out.pc.expect(BigInt("80000080", 16))
            dut.io.trap_info_out.cause.expect(MCause.LoadAccessFault)
            dut.io.trap_info_out.value.expect(BigInt("10000010", 16))
        }
    }

    test("LSU releases cache load stall on response and retires the load once") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            dut.io.alu_out.rd.poke(5.U)
            dut.io.alu_out.reg_write.poke(true.B)
            driveLoad(dut, BigInt("10000018", 16))
            dut.io.dcache.req.valid.expect(true.B)
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.io.dcache.resp.bits.rdata.poke(BigInt("1122334455667788", 16).U)
            dut.io.stall_req.expect(false.B)
            dut.io.load_data_valid.expect(true.B)
            dut.io.valid_out.expect(false.B)
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(false.B)
            // The upstream ALU register is still presenting the completed load
            // until the just-released pipeline advances. LSU must retire the
            // load from its completion slot, not by accepting it again.
            driveLoad(dut, BigInt("10000018", 16))
            dut.io.valid_out.expect(true.B)
            dut.io.mem_out.rd.expect(5.U)
            dut.io.mem_out.reg_write.expect(true.B)
            dut.io.mem_out.result.expect(BigInt("1122334455667788", 16).U)
            dut.io.dcache.req.valid.expect(false.B)
            dut.clock.step()

            driveNoMem(dut)
            dut.io.valid_out.expect(false.B)
        }
    }

    test("LSU holds cache loads behind an outstanding store drain") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            driveStore(dut, BigInt("10000018", 16), BigInt("123456789abcdef0", 16))
            dut.clock.step()

            driveNoMem(dut)
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Write)
            dut.clock.step()

            driveLoad(dut, BigInt("10000020", 16))
            dut.io.stall_req.expect(true.B)
            dut.io.dcache.req.valid.expect(false.B)

            dut.io.dcache.resp.valid.poke(true.B)
            dut.io.dcache.resp.bits.err.poke(false.B)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)

            dut.io.stall_req.expect(true.B)
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Read)
            dut.io.dcache.req.bits.addr.expect(BigInt("10000020", 16))
            dut.clock.step()
        }
    }

    test("LSU drains stores before retiring a memory fence") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            driveStore(dut, BigInt("10000030", 16), BigInt("1122334455667788", 16))
            dut.clock.step()

            driveFence(dut)
            dut.io.stall_req.expect(true.B)
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Write)
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)

            dut.io.stall_req.expect(true.B)
            dut.io.dcache.req.valid.expect(false.B)
            dut.clock.step()

            dut.io.dcache.req.valid.expect(false.B)
            dut.io.valid_out.expect(true.B)
            dut.io.mem_out.reg_write.expect(false.B)
            dut.clock.step()

            dut.io.stall_req.expect(false.B)
            dut.io.valid_out.expect(false.B)
        }
    }

    test("LSU drains stores before retiring SFENCE.VMA without a full DCache flush") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            driveStore(dut, BigInt("10000038", 16), BigInt("8877665544332211", 16))
            dut.clock.step()

            driveFence(dut, instr = 0x12000073L) // sfence.vma x0, x0
            dut.io.stall_req.expect(true.B)
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Write)
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)

            dut.io.stall_req.expect(true.B)
            dut.io.dcache.req.valid.expect(false.B)
            dut.clock.step()

            dut.io.dcache.req.valid.expect(false.B)
            dut.io.valid_out.expect(true.B)
            dut.io.mem_out.reg_write.expect(false.B)
        }
    }

    test("LSU keeps store retire packet coherent when following load hits store buffer") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            dut.io.pc_in.poke(BigInt("80000056", 16).U)
            dut.io.alu_out.instr.poke(BigInt("0062b023", 16).U) // sd t1, 0(t0)
            dut.io.alu_out.instr_len.poke(0.U)
            dut.io.alu_out.rd.poke(0.U)
            dut.io.alu_out.reg_write.poke(false.B)
            driveStore(dut, BigInt("10000000", 16), BigInt("1122334455667788", 16))
            dut.clock.step()

            dut.io.pc_in.poke(BigInt("8000005a", 16).U)
            dut.io.alu_out.instr.poke(BigInt("0002b383", 16).U) // ld t2, 0(t0)
            dut.io.alu_out.instr_len.poke(0.U)
            dut.io.alu_out.rd.poke(7.U)
            dut.io.alu_out.reg_write.poke(true.B)
            driveLoad(dut, BigInt("10000000", 16))

            dut.io.valid_out.expect(true.B)
            dut.io.pc_out.expect(BigInt("80000056", 16).U)
            dut.io.mem_out.instr.expect(BigInt("0062b023", 16).U)
            dut.io.mem_out.reg_write.expect(false.B)
            dut.io.load_data_valid.expect(true.B)
            dut.io.load_data_rd.expect(7.U)
            dut.io.load_data.expect(BigInt("1122334455667788", 16).U)
        }
    }

    test("LSU handles cacheable misaligned halfword loads within one beat") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            dut.io.pc_in.poke(BigInt("80000060", 16).U)
            dut.io.alu_out.rd.poke(7.U)
            dut.io.alu_out.reg_write.poke(true.B)
            driveLoad(dut, BigInt("10000001", 16))
            dut.io.alu_out.mem.size.poke(1.U)
            dut.io.alu_out.mem.mask.poke("h06".U)
            dut.io.alu_out.mem.signed.poke(false.B)

            expectDCacheRead(dut, BigInt("10000001", 16))
            acceptDCacheRead(dut, BigInt("0706050403020100", 16))

            dut.io.trap_info_out.valid.expect(false.B)
            dut.io.load_data_valid.expect(true.B)
            dut.io.load_data_rd.expect(7.U)
            dut.io.load_data.expect(BigInt("0201", 16).U)
        }
    }

    test("LSU handles cacheable misaligned word loads across two beats") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            dut.io.pc_in.poke(BigInt("80000064", 16).U)
            dut.io.alu_out.rd.poke(7.U)
            dut.io.alu_out.reg_write.poke(true.B)
            driveLoad(dut, BigInt("10000006", 16))
            dut.io.alu_out.mem.size.poke(2.U)
            dut.io.alu_out.mem.mask.poke("hc0".U)
            dut.io.alu_out.mem.signed.poke(false.B)

            expectDCacheRead(dut, BigInt("10000000", 16))
            acceptDCacheRead(dut, BigInt("0706050403020100", 16))
            expectDCacheRead(dut, BigInt("10000008", 16))
            acceptDCacheRead(dut, BigInt("0f0e0d0c0b0a0908", 16))

            dut.io.trap_info_out.valid.expect(false.B)
            dut.io.load_data_valid.expect(true.B)
            dut.io.load_data_rd.expect(7.U)
            dut.io.load_data.expect(BigInt("09080706", 16).U)
        }
    }

    test("LSU handles cacheable misaligned halfword stores within one beat") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            dut.io.pc_in.poke(BigInt("80000068", 16).U)
            driveStore(dut, BigInt("10000001", 16), BigInt("8180", 16))
            dut.io.alu_out.mem.size.poke(1.U)
            dut.io.alu_out.mem.mask.poke("h06".U)

            dut.clock.step()
            driveNoMem(dut)

            expectDCacheWrite(dut, BigInt("10000001", 16), BigInt("818000", 16))
            dut.io.dcache.req.bits.mask.expect("h06".U)
            dut.io.trap_info_out.valid.expect(false.B)
        }
    }

    test("LSU splits cacheable misaligned word stores across two beats") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            dut.io.pc_in.poke(BigInt("8000006c", 16).U)
            driveStore(dut, BigInt("10000006", 16), BigInt("83828180", 16))
            dut.io.alu_out.mem.size.poke(2.U)
            dut.io.alu_out.mem.mask.poke("hc0".U)

            dut.io.stall_req.expect(true.B)
            dut.clock.step()
            driveNoMem(dut)

            expectDCacheWrite(dut, BigInt("10000000", 16), BigInt("8180000000000000", 16))
            dut.io.dcache.req.bits.mask.expect("hc0".U)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(true.B)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)

            expectDCacheWrite(dut, BigInt("10000008", 16), BigInt("8382", 16))
            dut.io.dcache.req.bits.mask.expect("h03".U)
            dut.io.trap_info_out.valid.expect(false.B)
        }
    }

    test("LSU retires cacheable split stores after both beats are queued") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            val pc = BigInt("80000070", 16)
            val instr = BigInt("006430a3", 16) // sd t1, 1(s0)
            val data = BigInt("a3a2a1a09f9e9d9c", 16)

            dut.io.pc_in.poke(pc.U)
            dut.io.alu_out.instr.poke(instr.U)
            dut.io.alu_out.instr_len.poke(0.U)
            driveStore(dut, BigInt("10000001", 16), data)
            dut.io.stall_req.expect(true.B)

            dut.clock.step()
            dut.io.pc_in.poke(pc.U)
            dut.io.alu_out.instr.poke(instr.U)
            dut.io.alu_out.instr_len.poke(0.U)
            driveStore(dut, BigInt("10000001", 16), data)
            dut.io.stall_req.expect(true.B)

            dut.clock.step()
            dut.io.pc_in.poke(pc.U)
            dut.io.alu_out.instr.poke(instr.U)
            dut.io.alu_out.instr_len.poke(0.U)
            driveStore(dut, BigInt("10000001", 16), data)

            dut.io.valid_out.expect(true.B)
            dut.io.pc_out.expect(pc.U)
            dut.io.mem_out.instr.expect(instr.U)
            dut.io.mem_out.reg_write.expect(false.B)
        }
    }

    test("LSU forwards narrow loads from a queued cacheable split store") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            val storePc = BigInt("80000074", 16)
            val loadPc = BigInt("80000078", 16)
            val storeInstr = BigInt("006430a3", 16) // sd t1, 1(s0)
            val loadInstr = BigInt("00740e03", 16) // lb t3, 7(s0)
            val data = BigInt("b7b6b5b4b3b2b1b0", 16)
            val loadAddr = BigInt("10000007", 16)

            dut.io.dcache.req.ready.poke(false.B)
            dut.io.pc_in.poke(storePc.U)
            dut.io.alu_out.instr.poke(storeInstr.U)
            dut.io.alu_out.instr_len.poke(0.U)
            driveStore(dut, BigInt("10000001", 16), data)
            dut.clock.step()

            dut.io.pc_in.poke(storePc.U)
            dut.io.alu_out.instr.poke(storeInstr.U)
            dut.io.alu_out.instr_len.poke(0.U)
            driveStore(dut, BigInt("10000001", 16), data)
            dut.clock.step()

            dut.io.valid_out.expect(true.B)
            dut.io.pc_out.expect(storePc.U)

            dut.io.pc_in.poke(loadPc.U)
            dut.io.alu_out.instr.poke(loadInstr.U)
            dut.io.alu_out.instr_len.poke(0.U)
            dut.io.alu_out.rd.poke(28.U)
            dut.io.alu_out.reg_write.poke(true.B)
            driveLoad(dut, loadAddr)
            dut.io.alu_out.result.poke(loadAddr.U)
            dut.io.alu_out.mem.size.poke(0.U)
            dut.io.alu_out.mem.mask.poke("h80".U)
            dut.io.alu_out.mem.signed.poke(true.B)
            dut.clock.step()

            dut.io.valid_out.expect(true.B)
            dut.io.pc_out.expect(loadPc.U)
            dut.io.mem_out.rd.expect(28.U)
            dut.io.mem_out.reg_write.expect(true.B)
            dut.io.mem_out.result.expect(BigInt("ffffffffffffffb6", 16).U)
        }
    }

    test("LSU forwards narrow loads while a split store starts draining") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            val storePc = BigInt("80000084", 16)
            val loadPc = BigInt("80000088", 16)
            val storeInstr = BigInt("006430a3", 16) // sd t1, 1(s0)
            val loadInstr = BigInt("00740e03", 16) // lb t3, 7(s0)
            val data = BigInt("b7b6b5b4b3b2b1b0", 16)
            val loadAddr = BigInt("10000007", 16)

            dut.io.pc_in.poke(storePc.U)
            dut.io.alu_out.instr.poke(storeInstr.U)
            dut.io.alu_out.instr_len.poke(0.U)
            driveStore(dut, BigInt("10000001", 16), data)
            dut.clock.step()

            dut.io.pc_in.poke(storePc.U)
            dut.io.alu_out.instr.poke(storeInstr.U)
            dut.io.alu_out.instr_len.poke(0.U)
            driveStore(dut, BigInt("10000001", 16), data)
            dut.clock.step()

            dut.io.valid_out.expect(true.B)
            dut.io.pc_out.expect(storePc.U)
            dut.io.pc_in.poke(loadPc.U)
            dut.io.alu_out.instr.poke(loadInstr.U)
            dut.io.alu_out.instr_len.poke(0.U)
            dut.io.alu_out.rd.poke(28.U)
            dut.io.alu_out.reg_write.poke(true.B)
            driveLoad(dut, loadAddr)
            dut.io.alu_out.result.poke(loadAddr.U)
            dut.io.alu_out.mem.size.poke(0.U)
            dut.io.alu_out.mem.mask.poke("h80".U)
            dut.io.alu_out.mem.signed.poke(true.B)
            dut.clock.step()

            dut.io.valid_out.expect(true.B)
            dut.io.pc_out.expect(loadPc.U)
            dut.io.mem_out.rd.expect(28.U)
            dut.io.mem_out.reg_write.expect(true.B)
            dut.io.mem_out.result.expect(BigInt("ffffffffffffffb6", 16).U)
        }
    }

    test("LSU does not retire a stalled load with its address after split store drain") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            val storePc = BigInt("8000007c", 16)
            val loadPc = BigInt("80000080", 16)
            val storeInstr = BigInt("006430a3", 16) // sd t1, 1(s0)
            val loadInstr = BigInt("00740e03", 16) // lb t3, 7(s0)
            val data = BigInt("b7b6b5b4b3b2b1b0", 16)
            val loadAddr = BigInt("10000007", 16)

            dut.io.pc_in.poke(storePc.U)
            dut.io.alu_out.instr.poke(storeInstr.U)
            dut.io.alu_out.instr_len.poke(0.U)
            driveStore(dut, BigInt("10000001", 16), data)
            dut.clock.step()

            dut.io.pc_in.poke(storePc.U)
            dut.io.alu_out.instr.poke(storeInstr.U)
            dut.io.alu_out.instr_len.poke(0.U)
            driveStore(dut, BigInt("10000001", 16), data)
            dut.clock.step()

            driveNoMem(dut)
            dut.clock.step()

            dut.io.pc_in.poke(loadPc.U)
            dut.io.alu_out.instr.poke(loadInstr.U)
            dut.io.alu_out.instr_len.poke(0.U)
            dut.io.alu_out.rd.poke(28.U)
            dut.io.alu_out.reg_write.poke(true.B)
            driveLoad(dut, loadAddr)
            dut.io.alu_out.result.poke(loadAddr.U)
            dut.io.alu_out.mem.size.poke(0.U)
            dut.io.alu_out.mem.mask.poke("h80".U)
            dut.io.alu_out.mem.signed.poke(true.B)
            dut.io.stall_req.expect(true.B)
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)

            dut.io.pc_in.poke(loadPc.U)
            dut.io.alu_out.instr.poke(loadInstr.U)
            dut.io.alu_out.instr_len.poke(0.U)
            dut.io.alu_out.rd.poke(28.U)
            dut.io.alu_out.reg_write.poke(true.B)
            driveLoad(dut, loadAddr)
            dut.io.alu_out.result.poke(loadAddr.U)
            dut.io.alu_out.mem.size.poke(0.U)
            dut.io.alu_out.mem.mask.poke("h80".U)
            dut.io.alu_out.mem.signed.poke(true.B)

            var sawRead = false
            var cycles = 0
            while (!sawRead && cycles < 8) {
                dut.io.valid_out.expect(false.B)
                if (dut.io.dcache.req.valid.peek().litToBoolean) {
                    val isWrite = dut.io.dcache.req.bits.cmd.peek().litValue == CacheCmd.Write.litValue
                    if (isWrite) {
                        dut.clock.step()
                        dut.io.dcache.resp.valid.poke(true.B)
                        dut.clock.step()
                        dut.io.dcache.resp.valid.poke(false.B)
                    } else {
                        dut.io.dcache.req.bits.cmd.expect(CacheCmd.Read)
                        dut.io.dcache.req.bits.addr.expect(loadAddr.U)
                        sawRead = true
                    }
                } else {
                    dut.clock.step()
                }
                cycles += 1
            }
            assert(sawRead, "expected stalled load to issue a DCache read after split store drains")
        }
    }

    test("LSU does not retire a load with its address after waiting for store drain") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            val storePc = BigInt("8000008c", 16)
            val loadPc = BigInt("80000090", 16)
            val loadAddr = BigInt("10000008", 16)

            dut.io.pc_in.poke(storePc.U)
            driveStore(dut, BigInt("10000000", 16), BigInt("1122334455667788", 16))
            dut.clock.step()

            driveNoMem(dut)
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Write)
            dut.clock.step()

            dut.io.pc_in.poke(loadPc.U)
            dut.io.alu_out.rd.poke(7.U)
            dut.io.alu_out.reg_write.poke(true.B)
            driveLoad(dut, loadAddr)
            dut.io.alu_out.result.poke(loadAddr.U)
            dut.io.stall_req.expect(true.B)
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)

            dut.io.pc_in.poke(loadPc.U)
            dut.io.alu_out.rd.poke(7.U)
            dut.io.alu_out.reg_write.poke(true.B)
            driveLoad(dut, loadAddr)
            dut.io.alu_out.result.poke(loadAddr.U)

            dut.io.valid_out.expect(false.B)
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Read)
            dut.io.dcache.req.bits.addr.expect(loadAddr.U)
        }
    }

    test("LSU stalls cache loads while an unrelated store remains queued") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            dut.io.dcache.req.ready.poke(false.B)
            driveStore(dut, BigInt("10000000", 16), BigInt("1122334455667788", 16))
            dut.clock.step()

            dut.io.pc_in.poke(BigInt("80000094", 16).U)
            dut.io.alu_out.rd.poke(7.U)
            dut.io.alu_out.reg_write.poke(true.B)
            driveLoad(dut, BigInt("10000008", 16))
            dut.io.alu_out.result.poke(BigInt("10000008", 16).U)

            dut.io.stall_req.expect(true.B)
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Write)
        }
    }

    test("LSU blocks supervisor memory access without a matching PMP entry") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.pc_in.poke("h80000100".U)
            driveLoad(dut, BigInt("10000000", 16))
            dut.io.dcache.req.valid.expect(false.B)
            dut.io.mmio.req_valid.expect(false.B)

            dut.clock.step()
            dut.io.trap_info_out.valid.expect(true.B)
            dut.io.trap_info_out.pc.expect(BigInt("80000100", 16))
            dut.io.trap_info_out.cause.expect(MCause.LoadAccessFault)
            dut.io.trap_info_out.value.expect(BigInt("10000000", 16))
        }
    }

    test("LSU permits supervisor memory access through an all-address NAPOT PMP entry") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.pmpcfg0.poke(pmpNapotRwx.U)
            dut.io.mem_cfg.pmpaddr(0).poke(BigInt("ffffffffffffffff", 16).U)
            driveLoad(dut, BigInt("10000008", 16))
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Read)
            dut.io.dcache.req.bits.addr.expect(BigInt("10000008", 16))
            dut.clock.step()

            dut.io.trap_info_out.valid.expect(false.B)
        }
    }

    test("LSU translates supervisor cache loads through Sv39 before issuing the data request") {
        simulate(new LSU(64)) { dut =>
            init(dut)
            val root = BigInt("40000000", 16)
            val l1 = BigInt("40001000", 16)
            val l0 = BigInt("40002000", 16)
            val leafPa = BigInt("40003000", 16)
            val va = BigInt("0000000012345678", 16)
            val vpn0 = (va >> 12) & 0x1ff
            val vpn1 = (va >> 21) & 0x1ff
            val vpn2 = (va >> 30) & 0x1ff
            val expectedPa = leafPa | (va & 0xfff)

            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.mmu_en.poke(true.B)
            dut.io.mem_cfg.satp.poke(satp(root).U)
            dut.io.mem_cfg.pmpcfg0.poke(pmpNapotRwx.U)
            dut.io.mem_cfg.pmpaddr(0).poke(BigInt("ffffffffffffffff", 16).U)
            dut.io.pc_in.poke("h80000300".U)
            dut.io.alu_out.rd.poke(6.U)
            dut.io.alu_out.reg_write.poke(true.B)
            driveLoad(dut, va)

            expectDCacheRead(dut, root + vpn2 * 8)
            acceptDCacheRead(dut, pte(ppn(l1), V))
            expectDCacheRead(dut, l1 + vpn1 * 8)
            acceptDCacheRead(dut, pte(ppn(l0), V))
            expectDCacheRead(dut, l0 + vpn0 * 8)
            acceptDCacheRead(dut, pte(ppn(leafPa), V | R | W | A | D))

            expectDCacheRead(dut, expectedPa)
            dut.io.dcache.req.bits.vaddr.expect(va.U)
            acceptDCacheRead(dut, BigInt("1122334455667788", 16))

            dut.io.load_data_valid.expect(true.B)
            dut.io.load_data_rd.expect(6.U)
            dut.io.load_data.expect(BigInt("1122334455667788", 16))
            dut.io.valid_out.expect(true.B)
            dut.io.mem_out.rd.expect(6.U)
            dut.io.mem_out.reg_write.expect(true.B)
            dut.io.mem_out.result.expect(BigInt("1122334455667788", 16).U)
        }
    }

    test("LSU reclassifies translated UART loads as MMIO instead of DCache requests") {
        simulate(new LSU(64)) { dut =>
            init(dut)
            val root = BigInt("40000000", 16)
            val l1 = BigInt("40001000", 16)
            val l0 = BigInt("40002000", 16)
            val uartPa = BigInt("10010005", 16)
            val va = BigInt("ffffffc4febf9005", 16)
            val vpn0 = (va >> 12) & 0x1ff
            val vpn1 = (va >> 21) & 0x1ff
            val vpn2 = (va >> 30) & 0x1ff

            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.mmu_en.poke(true.B)
            dut.io.mem_cfg.satp.poke(satp(root).U)
            dut.io.mem_cfg.pmpcfg0.poke(pmpNapotRwx.U)
            dut.io.mem_cfg.pmpaddr(0).poke(BigInt("ffffffffffffffff", 16).U)
            dut.io.pc_in.poke("h80000320".U)
            dut.io.alu_out.rd.poke(15.U)
            dut.io.alu_out.reg_write.poke(true.B)
            driveLoad(dut, va)
            dut.io.alu_out.mem.size.poke(0.U)
            dut.io.alu_out.mem.mask.poke(1.U)

            expectDCacheRead(dut, root + vpn2 * 8)
            acceptDCacheRead(dut, pte(ppn(l1), V))
            expectDCacheRead(dut, l1 + vpn1 * 8)
            acceptDCacheRead(dut, pte(ppn(l0), V))
            expectDCacheRead(dut, l0 + vpn0 * 8)
            acceptDCacheRead(dut, pte(ppn(uartPa & ~BigInt("fff", 16)), V | R | W | A | D))

            var sawMmio = false
            for (_ <- 0 until 4 if !sawMmio) {
                dut.io.dcache.req.valid.expect(false.B)
                if (dut.io.mmio.req_valid.peek().litToBoolean) {
                    sawMmio = true
                } else {
                    dut.clock.step()
                }
            }
            if (!sawMmio) {
                dut.io.mmio.req_valid.expect(true.B)
            }
            dut.io.mmio.req_addr.expect(uartPa.U)
            dut.io.mmio.req_cmd.expect(4.U) // TL Get
            dut.io.mmio.req_size.expect(0.U)
        }
    }

    test("LSU bypasses Sv39 translation for machine-mode cache loads even when satp is active") {
        simulate(new LSU(64)) { dut =>
            init(dut)
            val root = BigInt("40000000", 16)
            val addr = BigInt("10000048", 16)

            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Machine)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Machine)
            dut.io.mem_cfg.mmu_en.poke(true.B)
            dut.io.mem_cfg.satp.poke(satp(root).U)
            dut.io.pc_in.poke("h80000340".U)
            driveLoad(dut, addr)

            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Read)
            dut.io.dcache.req.bits.addr.expect(addr.U)
        }
    }

    test("LSU translates MPRV machine-mode loads with supervisor data privilege") {
        simulate(new LSU(64)) { dut =>
            init(dut)
            val root = BigInt("40000000", 16)
            val l1 = BigInt("40001000", 16)
            val l0 = BigInt("40002000", 16)
            val leafPa = BigInt("10005000", 16)
            val va = BigInt("0000000040005000", 16)
            val vpn0 = (va >> 12) & 0x1ff
            val vpn1 = (va >> 21) & 0x1ff
            val vpn2 = (va >> 30) & 0x1ff
            val data = BigInt("0102030405060708", 16)

            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Machine)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.mprv.poke(true.B)
            dut.io.mem_cfg.mmu_en.poke(true.B)
            dut.io.mem_cfg.satp.poke(satp(root).U)
            dut.io.mem_cfg.pmpcfg0.poke(pmpNapotRwx.U)
            dut.io.mem_cfg.pmpaddr(0).poke(BigInt("ffffffffffffffff", 16).U)
            dut.io.pc_in.poke("h80000360".U)
            dut.io.alu_out.rd.poke(8.U)
            dut.io.alu_out.reg_write.poke(true.B)
            driveLoad(dut, va)

            expectDCacheRead(dut, root + vpn2 * 8)
            acceptDCacheRead(dut, pte(ppn(l1), V))
            expectDCacheRead(dut, l1 + vpn1 * 8)
            acceptDCacheRead(dut, pte(ppn(l0), V))
            expectDCacheRead(dut, l0 + vpn0 * 8)
            acceptDCacheRead(dut, pte(ppn(leafPa), V | R | W | A | D))

            expectDCacheRead(dut, leafPa)
            dut.io.dcache.req.bits.vaddr.expect(va.U)
            acceptDCacheRead(dut, data)

            dut.io.valid_out.expect(true.B)
            dut.io.mem_out.rd.expect(8.U)
            dut.io.mem_out.reg_write.expect(true.B)
            dut.io.mem_out.result.expect(data.U)
        }
    }

    test("LSU translates supervisor cache stores through Sv39 before draining to DCache") {
        simulate(new LSU(64)) { dut =>
            init(dut)
            val root = BigInt("40000000", 16)
            val l1 = BigInt("40001000", 16)
            val l0 = BigInt("40002000", 16)
            val leafPa = BigInt("41188000", 16)
            val va = BigInt("ffffffff81188110", 16)
            val vpn0 = (va >> 12) & 0x1ff
            val vpn1 = (va >> 21) & 0x1ff
            val vpn2 = (va >> 30) & 0x1ff
            val expectedPa = leafPa | (va & 0xfff)
            val data = BigInt("cafebabedeadbeef", 16)

            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.mmu_en.poke(true.B)
            dut.io.mem_cfg.satp.poke(satp(root).U)
            dut.io.mem_cfg.pmpcfg0.poke(pmpNapotRwx.U)
            // 128 MiB NAPOT window at physical 0x40000000. It permits the
            // translated PA but intentionally does not match the high VA.
            dut.io.mem_cfg.pmpaddr(0).poke(BigInt("10ffffff", 16).U)
            dut.io.pc_in.poke("h80000380".U)
            driveStore(dut, va, data)

            expectDCacheRead(dut, root + vpn2 * 8)
            acceptDCacheRead(dut, pte(ppn(l1), V))
            expectDCacheRead(dut, l1 + vpn1 * 8)
            acceptDCacheRead(dut, pte(ppn(l0), V))
            expectDCacheRead(dut, l0 + vpn0 * 8)
            acceptDCacheRead(dut, pte(ppn(leafPa), V | R | W | A | D))

            expectDCacheWrite(dut, expectedPa, data)
            dut.io.dcache.req.bits.vaddr.expect(va.U)
        }
    }

    test("LSU commits a translated load after a translated store with response data") {
        simulate(new LSU(64)) { dut =>
            init(dut)
            val root = BigInt("40000000", 16)
            val l1 = BigInt("40001000", 16)
            val l0 = BigInt("40002000", 16)
            val leafPa = BigInt("10004000", 16)
            val va = BigInt("0000000040004000", 16)
            val vpn0 = (va >> 12) & 0x1ff
            val vpn1 = (va >> 21) & 0x1ff
            val vpn2 = (va >> 30) & 0x1ff
            val data = BigInt("8877665544332211", 16)

            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.mmu_en.poke(true.B)
            dut.io.mem_cfg.satp.poke(satp(root).U)
            dut.io.mem_cfg.pmpcfg0.poke(pmpNapotRwx.U)
            dut.io.mem_cfg.pmpaddr(0).poke(BigInt("ffffffffffffffff", 16).U)

            dut.io.pc_in.poke("h0000200160".U)
            driveStore(dut, va, data)
            expectDCacheRead(dut, root + vpn2 * 8)
            acceptDCacheRead(dut, pte(ppn(l1), V))
            expectDCacheRead(dut, l1 + vpn1 * 8)
            acceptDCacheRead(dut, pte(ppn(l0), V))
            expectDCacheRead(dut, l0 + vpn0 * 8)
            acceptDCacheRead(dut, pte(ppn(leafPa), V | R | W | A | D))
            expectDCacheWrite(dut, leafPa, data)
            driveNoMem(dut)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(true.B)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)

            dut.io.pc_in.poke("h0000200164".U)
            dut.io.alu_out.rd.poke(29.U)
            dut.io.alu_out.reg_write.poke(true.B)
            driveLoad(dut, va)
            expectDCacheRead(dut, root + vpn2 * 8)
            acceptDCacheRead(dut, pte(ppn(l1), V))
            expectDCacheRead(dut, l1 + vpn1 * 8)
            acceptDCacheRead(dut, pte(ppn(l0), V))
            expectDCacheRead(dut, l0 + vpn0 * 8)
            acceptDCacheRead(dut, pte(ppn(leafPa), V | R | W | A | D))
            expectDCacheRead(dut, leafPa)
            acceptDCacheRead(dut, data)

            dut.io.valid_out.expect(true.B)
            dut.io.mem_out.rd.expect(29.U)
            dut.io.mem_out.reg_write.expect(true.B)
            dut.io.mem_out.result.expect(data.U)
        }
    }

    test("LSU executes consecutive translated supervisor AMOADD operations on adjacent cache beats") {
        simulate(new LSU(64)) { dut =>
            init(dut)
            val root = BigInt("40000000", 16)
            val l1 = BigInt("40001000", 16)
            val l0 = BigInt("40002000", 16)
            val leafPa = BigInt("411bb000", 16)
            val virtualAddresses = Seq(
                BigInt("ffffffff8115faf8", 16),
                BigInt("ffffffff811bbe88", 16),
                BigInt("ffffffff8115faf0", 16),
                BigInt("ffffffff811bbe80", 16)
            )

            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.mmu_en.poke(true.B)
            dut.io.mem_cfg.satp.poke(satp(root).U)
            dut.io.mem_cfg.pmpcfg0.poke(pmpNapotRwx.U)
            dut.io.mem_cfg.pmpaddr(0).poke(BigInt("10ffffff", 16).U)

            for ((va, index) <- virtualAddresses.zipWithIndex) {
                val mappedPage =
                    if ((va >> 12) == (BigInt("ffffffff811bb000", 16) >> 12)) leafPa else BigInt("4115f000", 16)
                val expectedPa = mappedPage | (va & 0xfff)
                val vpn0 = (va >> 12) & 0x1ff
                val vpn1 = (va >> 21) & 0x1ff
                val vpn2 = (va >> 30) & 0x1ff
                val oldValue = BigInt(100 + index)
                val delta = BigInt(-1) & ((BigInt(1) << 64) - 1)

                dut.io.pc_in.poke((BigInt("ffffffff8015cf40", 16) + index * 8).U)
                dut.io.alu_out.rd.poke(0.U)
                driveAtomic(dut, MemOpType.AMO, AtomicOpType.Add, va, delta)

                expectDCacheRead(dut, root + vpn2 * 8)
                acceptDCacheRead(dut, pte(ppn(l1), V))
                expectDCacheRead(dut, l1 + vpn1 * 8)
                acceptDCacheRead(dut, pte(ppn(l0), V))
                expectDCacheRead(dut, l0 + vpn0 * 8)
                acceptDCacheRead(dut, pte(ppn(mappedPage), V | R | W | A | D))

                expectDCacheRead(dut, expectedPa)
                acceptDCacheRead(dut, oldValue)
                expectDCacheWrite(dut, expectedPa, oldValue - 1)
                dut.clock.step()
                dut.io.dcache.resp.valid.poke(true.B)
                dut.clock.step()
                dut.io.dcache.resp.valid.poke(false.B)
                dut.io.trap_info_out.valid.expect(false.B)

                // Present the next translated AMO without an idle bubble. The
                // prior translation result remains live for one cleanup cycle;
                // the next request must not issue its untranslated high VA.
                if (index == virtualAddresses.size - 1) {
                    driveNoMem(dut)
                    dut.clock.step(2)
                }
            }
        }
    }

    test("LSU reports Sv39 load page faults without issuing the data cache request") {
        simulate(new LSU(64)) { dut =>
            init(dut)
            val root = BigInt("40000000", 16)
            val va = BigInt("0000000012345678", 16)
            val vpn2 = (va >> 30) & 0x1ff

            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.mmu_en.poke(true.B)
            dut.io.mem_cfg.satp.poke(satp(root).U)
            dut.io.mem_cfg.pmpcfg0.poke(pmpNapotRwx.U)
            dut.io.mem_cfg.pmpaddr(0).poke(BigInt("ffffffffffffffff", 16).U)
            dut.io.pc_in.poke("h800003c0".U)
            driveLoad(dut, va)

            expectDCacheRead(dut, root + vpn2 * 8)
            acceptDCacheRead(dut, pte(0x1000, V | W | A | D))

            dut.io.dcache.req.valid.expect(false.B)
            expectTrap(dut, MCause.LoadPageFault, va, BigInt("800003c0", 16))
        }
    }

    test("LSU holds Sv39 translation behind an outstanding store drain") {
        simulate(new LSU(64)) { dut =>
            init(dut)
            val root = BigInt("40000000", 16)
            val va = BigInt("0000000012345678", 16)
            val vpn2 = (va >> 30) & 0x1ff

            driveStore(dut, BigInt("10000040", 16), BigInt("abcdef0123456789", 16))
            dut.clock.step()

            driveNoMem(dut)
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Write)
            dut.clock.step()

            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.mmu_en.poke(true.B)
            dut.io.mem_cfg.satp.poke(satp(root).U)
            dut.io.mem_cfg.pmpcfg0.poke(pmpNapotRwx.U)
            dut.io.mem_cfg.pmpaddr(0).poke(BigInt("ffffffffffffffff", 16).U)
            driveLoad(dut, va)
            dut.clock.step()

            dut.io.dcache.req.valid.expect(false.B)
            dut.io.stall_req.expect(true.B)
            dut.io.stall_load.expect(true.B)
            dut.io.dcache.resp.valid.poke(true.B)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)

            expectDCacheRead(dut, root + vpn2 * 8)
        }
    }

    test("LSU stalls translated loads while a store is queued but not yet draining") {
        simulate(new LSU(64)) { dut =>
            init(dut)
            val root = BigInt("40000000", 16)
            val va = BigInt("0000000040004000", 16)

            driveStore(dut, BigInt("10000040", 16), BigInt("abcdef0123456789", 16))
            dut.clock.step()

            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.mmu_en.poke(true.B)
            dut.io.mem_cfg.satp.poke(satp(root).U)
            dut.io.mem_cfg.pmpcfg0.poke(pmpNapotRwx.U)
            dut.io.mem_cfg.pmpaddr(0).poke(BigInt("ffffffffffffffff", 16).U)
            driveLoad(dut, va)

            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Write)
            dut.io.stall_req.expect(true.B)
            dut.io.stall_load.expect(true.B)
        }
    }

    test("LSU reports supervisor store PMP denials as StoreAccessFault without enqueuing") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.pmpcfg0.poke(0x19.U) // NAPOT, read-only
            dut.io.mem_cfg.pmpaddr(0).poke(BigInt("ffffffffffffffff", 16).U)
            dut.io.pc_in.poke("h80000140".U)
            driveStore(dut, BigInt("10000010", 16), BigInt("feedfacecafebeef", 16))
            dut.io.dcache.req.valid.expect(false.B)

            dut.clock.step()
            dut.io.trap_info_out.valid.expect(true.B)
            dut.io.trap_info_out.pc.expect(BigInt("80000140", 16))
            dut.io.trap_info_out.cause.expect(MCause.StoreAccessFault)
            dut.io.trap_info_out.value.expect(BigInt("10000010", 16))

            driveNoMem(dut)
            dut.clock.step()
            dut.io.dcache.req.valid.expect(false.B)
        }
    }

    test("LSU uses the first matching TOR PMP entry") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            dut.io.mem_cfg.priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.data_priv.poke(PrivilegeLevel.Supervisor)
            dut.io.mem_cfg.pmpcfg0.poke(BigInt("090f00", 16).U) // entry1 RWX TOR, entry2 R-only TOR
            dut.io.mem_cfg.pmpaddr(1).poke((BigInt("40000000", 16) >> 2).U)
            dut.io.mem_cfg.pmpaddr(2).poke((BigInt("40010000", 16) >> 2).U)
            driveStore(dut, BigInt("40000008", 16), BigInt("12345678", 16))
            dut.io.dcache.req.valid.expect(false.B)

            dut.clock.step()
            dut.io.trap_info_out.valid.expect(true.B)
            dut.io.trap_info_out.cause.expect(MCause.StoreAccessFault)
            dut.io.trap_info_out.value.expect(BigInt("40000008", 16))
        }
    }

    test("LSU completes LR/SC reservation success and writes store data") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            driveAtomic(dut, MemOpType.LR, AtomicOpType.LR, BigInt("10000000", 16))
            dut.clock.step()
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Read)
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.io.dcache.resp.bits.rdata.poke(BigInt("1122334455667788", 16).U)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)
            dut.io.load_data_valid.expect(true.B)
            dut.io.load_data.expect(BigInt("1122334455667788", 16))

            driveAtomic(dut, MemOpType.SC, AtomicOpType.SC, BigInt("10000000", 16), BigInt("aaaabbbbccccdddd", 16))
            dut.clock.step()
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Read)
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.io.dcache.resp.bits.rdata.poke(BigInt("1122334455667788", 16).U)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Write)
            dut.io.dcache.req.bits.wdata.expect(BigInt("aaaabbbbccccdddd", 16))
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)
            dut.io.load_data_valid.expect(true.B)
            dut.io.load_data.expect(0.U)
        }
    }

    test("LSU fails SC without a matching reservation") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            driveAtomic(dut, MemOpType.SC, AtomicOpType.SC, BigInt("10000008", 16), BigInt("1234", 16))
            dut.clock.step()
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Read)
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.io.dcache.resp.bits.rdata.poke(BigInt("feedfacecafebeef", 16).U)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)
            dut.io.dcache.req.valid.expect(false.B)
            dut.io.load_data_valid.expect(true.B)
            dut.io.load_data.expect(1.U)
        }
    }

    test("LSU performs AMOADD.D and returns the old value") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            driveAtomic(dut, MemOpType.AMO, AtomicOpType.Add, BigInt("10000010", 16), 5)
            dut.clock.step()
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Read)
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.io.dcache.resp.bits.rdata.poke(7.U)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Write)
            dut.io.dcache.req.bits.wdata.expect(12.U)
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)
            dut.io.load_data_valid.expect(true.B)
            dut.io.load_data.expect(7.U)
        }
    }

    test("LSU performs AMOXOR.D and returns the old value") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            driveAtomic(
                dut,
                MemOpType.AMO,
                AtomicOpType.Xor,
                BigInt("10000010", 16),
                BigInt("0000000000000001", 16)
            )
            dut.clock.step()
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Read)
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.io.dcache.resp.bits.rdata.poke(BigInt("0000000000000005", 16).U)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Write)
            dut.io.dcache.req.bits.wdata.expect(BigInt("0000000000000004", 16).U)
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)
            dut.io.load_data_valid.expect(true.B)
            dut.io.load_data.expect(BigInt("0000000000000005", 16).U)
        }
    }

    test("LSU performs AMOSWAP.W with sign-extended old value") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            driveAtomic(dut, MemOpType.AMO, AtomicOpType.Swap, BigInt("10000018", 16), BigInt("0000000012345678", 16), size = 2)
            dut.clock.step()
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.io.dcache.resp.bits.rdata.poke(BigInt("0000000080000001", 16).U)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Write)
            dut.io.dcache.req.bits.mask.expect("h0f".U)
            dut.io.dcache.req.bits.wdata.expect(BigInt("1234567812345678", 16))
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)
            dut.io.load_data_valid.expect(true.B)
            dut.io.load_data.expect(BigInt("ffffffff80000001", 16))
        }
    }

    test("LSU reports atomic misalignment with load/store-specific causes") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            dut.io.pc_in.poke("h80000200".U)
            driveAtomic(dut, MemOpType.LR, AtomicOpType.LR, BigInt("10000004", 16))
            dut.clock.step()
            dut.io.trap_info_out.valid.expect(true.B)
            dut.io.trap_info_out.pc.expect(BigInt("80000200", 16))
            dut.io.trap_info_out.cause.expect(MCause.LoadAddrMisaligned)
            dut.io.trap_info_out.value.expect(BigInt("10000004", 16))

            init(dut)
            dut.io.pc_in.poke("h80000208".U)
            driveAtomic(dut, MemOpType.SC, AtomicOpType.SC, BigInt("10000004", 16), 1)
            dut.clock.step()
            dut.io.trap_info_out.valid.expect(true.B)
            dut.io.trap_info_out.pc.expect(BigInt("80000208", 16))
            dut.io.trap_info_out.cause.expect(MCause.StoreAddrMisaligned)
            dut.io.trap_info_out.value.expect(BigInt("10000004", 16))
        }
    }

    test("LSU rejects atomics to device regions") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            dut.io.pc_in.poke("h80000240".U)
            driveAtomic(dut, MemOpType.AMO, AtomicOpType.Add, BigInt("10010000", 16), 1)
            dut.clock.step()
            dut.io.dcache.req.valid.expect(false.B)
            dut.io.mmio.req_valid.expect(false.B)
            dut.io.trap_info_out.valid.expect(true.B)
            dut.io.trap_info_out.pc.expect(BigInt("80000240", 16))
            dut.io.trap_info_out.cause.expect(MCause.StoreAccessFault)
            dut.io.trap_info_out.value.expect(BigInt("10010000", 16))
        }
    }

    test("LSU clears LR reservation after an intervening store drain") {
        simulate(new LSU(64)) { dut =>
            init(dut)

            driveAtomic(dut, MemOpType.LR, AtomicOpType.LR, BigInt("10000020", 16))
            dut.clock.step()
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(true.B)
            dut.io.dcache.resp.bits.rdata.poke(BigInt("1111222233334444", 16).U)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)
            dut.io.load_data_valid.expect(true.B)

            driveStore(dut, BigInt("10000028", 16), BigInt("aaaabbbbccccdddd", 16))
            dut.clock.step()

            driveNoMem(dut)
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Write)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(true.B)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)

            driveAtomic(dut, MemOpType.SC, AtomicOpType.SC, BigInt("10000020", 16), BigInt("5555666677778888", 16))
            dut.clock.step()
            dut.io.dcache.req.valid.expect(true.B)
            dut.io.dcache.req.bits.cmd.expect(CacheCmd.Read)
            dut.clock.step()

            dut.io.dcache.resp.valid.poke(true.B)
            dut.io.dcache.resp.bits.rdata.poke(BigInt("1111222233334444", 16).U)
            dut.clock.step()
            dut.io.dcache.resp.valid.poke(false.B)
            dut.io.dcache.req.valid.expect(false.B)
            dut.io.load_data_valid.expect(true.B)
            dut.io.load_data.expect(1.U)
        }
    }
}
