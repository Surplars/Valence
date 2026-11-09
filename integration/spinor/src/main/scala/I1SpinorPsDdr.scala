package soc.integration.spinor

import chisel3._
import chisel3.util._
import soc.core.inorder.FiveStageConfig
import soc.ip.axi.{Axi4Address, Axi4MemoryPort}
import soc.ip.bus.{CdcLevel, CdcResetRelease}

/** Noncoherent PS DDR window. Native fabric addresses are offsets, not RV addresses.
  * A dedicated 64-bit S_AXI_HP port preserves the existing outstanding owners.
  * Aligned power-of-two relocation is wiring: no address adder or extra cycle.
  */
class I1PsDdrWindow(base: BigInt = BigInt("40000000", 16), bytes: BigInt = BigInt(1) << 28) extends Module {
    require(bytes >= 4096 && bytes <= (BigInt(1) << 31) && bytes.bitCount == 1)
    require(base >= 0 && base % bytes == 0 && base + bytes <= (BigInt(1) << 31))
    private val offsetBits = bytes.bitLength - 1
    val io = IO(new Bundle {
        val offset = Flipped(new Axi4MemoryPort(32, 4))
        val hp = new Axi4MemoryPort(49, 6)
    })
    def address(source: DecoupledIO[Axi4Address], target: DecoupledIO[Axi4Address]): Unit = {
        target.valid := source.valid; source.ready := target.ready
        target.bits := source.bits
        target.bits.addr := Cat((base >> offsetBits).U((49 - offsetBits).W), source.bits.addr(offsetBits - 1, 0))
        target.bits.id := source.bits.id.pad(6)
        // Contracts of the connected burst bridge, checked without a second datapath.
        when(source.valid) {
            val span = (source.bits.len +& 1.U) << source.bits.size
            assert(source.bits.addr +& span <= bytes.U, "AXI burst exceeds reserved PS DDR window")
            assert(source.bits.burst === 1.U && source.bits.size <= 3.U && source.bits.len < 16.U,
                "PS HP interface requires supported INCR bursts")
        }
    }
    address(io.offset.ar, io.hp.ar); address(io.offset.aw, io.hp.aw)
    io.hp.w <> io.offset.w
    io.offset.r.valid := io.hp.r.valid; io.hp.r.ready := io.offset.r.ready
    io.offset.r.bits := io.hp.r.bits
    io.offset.b.valid := io.hp.b.valid; io.hp.b.ready := io.offset.b.ready
    io.offset.b.bits := io.hp.b.bits
    when(io.hp.r.valid) { assert(io.hp.r.bits.id(5, 4) === 0.U, "unowned PS HP read ID") }
    when(io.hp.b.valid) { assert(io.hp.b.bits.id(5, 4) === 0.U, "unowned PS HP write ID") }
}

/** One cold launch per board reset. RPU GPIO changes after launch cannot discard
  * outstanding AXI work. Re-loading a running system requires a drained common
  * reset epoch including the PS AFI; a CPU-only reset is deliberately not exposed.
  */
class I1PsBootRelease extends RawModule {
    val systemClock = IO(Input(Clock())); val boardColdReset = IO(Input(AsyncReset()))
    val io = IO(new Bundle {
        val start = Input(Bool()); val ddrReady = Input(Bool()) // persistent PS GPIO levels
        val started = Output(Bool()); val memoryReady = Output(Bool())
        val subsystemColdReset = Output(AsyncReset())
    })
    val release = Module(new CdcResetRelease)
    release.clockIn := systemClock; release.asyncReset := boardColdReset
    def level(name: String, input: Bool): Bool = {
        val sync = Module(new CdcLevel); sync.suggestName(name)
        sync.clockIn := systemClock; sync.resetIn := release.resetOut; sync.levelIn := input
        sync.levelOut
    }
    val start = level("startSync", io.start); val ready = level("ddrReadySync", io.ddrReady)
    val started = withClockAndReset(systemClock, release.resetOut) {
        val active = RegInit(false.B)
        when(start && ready) { active := true.B }
        active
    }
    io.started := started; io.memoryReady := started
    io.subsystemColdReset := (boardColdReset.asBool || !started).asAsyncReset
}

/** PS-facing PL assembly. The PS block itself and DDR pins remain in the board BD.
  * Connect hp to a dedicated 64-bit S_AXI_HP port at systemClock. CPU and VPU keep
  * their independent raw clocks and existing CMU/BUFGCE management.
  */
class I1SpinorPsFpga(p: FiveStageConfig, systemHz: Int = 300000000,
    cpuHz: Long = 300000000L, vpuHz: Long = 300000000L) extends RawModule {
    require(p.cacheableBytes == (BigInt(1) << 28))
    val rawCpuClock = IO(Input(Clock())); val rawVpuClock = IO(Input(Clock()))
    val systemClock = IO(Input(Clock())); val boardColdReset = IO(Input(AsyncReset()))
    val io = IO(new Bundle {
        val hp = new Axi4MemoryPort(49, 6)
        val start = Input(Bool()); val ddrReady = Input(Bool()); val started = Output(Bool())
        val uartRx = Input(Bool()); val uartTx = Output(Bool())
        val externalIrq = Input(Bool()); val wakeCpu = Input(Bool()); val wakeVpu = Input(Bool())
        val cpuStopAck = Output(Bool()); val vpuStopAck = Output(Bool())
        val fabricIdle = Output(Bool()); val protocolError = Output(Bool())
    })
    val boot = Module(new I1PsBootRelease)
    boot.systemClock := systemClock; boot.boardColdReset := boardColdReset
    boot.io.start := io.start; boot.io.ddrReady := io.ddrReady; io.started := boot.io.started
    val unit = Module(new I1SpinorManagedFpga(p, systemHz, cpuHz, vpuHz))
    unit.rawCpuClock := rawCpuClock; unit.rawVpuClock := rawVpuClock; unit.systemClock := systemClock
    unit.commonColdReset := boot.io.subsystemColdReset; unit.io.memoryReady := boot.io.memoryReady
    unit.io.uartRx := io.uartRx; io.uartTx := unit.io.uartTx
    unit.io.externalIrq := io.externalIrq; unit.io.wakeCpu := io.wakeCpu; unit.io.wakeVpu := io.wakeVpu
    io.cpuStopAck := unit.io.cpuStopAck; io.vpuStopAck := unit.io.vpuStopAck
    io.fabricIdle := unit.io.fabricIdle; io.protocolError := unit.io.protocolError
    val window = withClockAndReset(systemClock, boot.io.subsystemColdReset) { Module(new I1PsDdrWindow) }
    window.io.offset <> unit.io.memory; io.hp <> window.io.hp
}
