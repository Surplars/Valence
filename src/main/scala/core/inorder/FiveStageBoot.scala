package soc.core.inorder

import chisel3._
import chisel3.util._
import chisel3.util.experimental.loadMemoryFromFileInline
import soc.bus.tilelink._
import soc.ip.bus.RegisterPort

/** Startup-only hold. Loss of lock/readiness after release latches a fault, never discards live owners.
  * Board POR must reset the entire downstream AXI/CDC endpoint too; unilateral hot reset is unsupported.
  */
class FiveStageStartup(withBootRom: Boolean, holdCycles: Int = 4) extends Module {
    require(holdCycles >= 2)
    val io = IO(new Bundle {
        val clockLocked = Input(Bool()); val ddrReady = Input(Bool())
        val held = Output(Bool()); val memoryReady = Output(Bool()); val fault = Output(Bool())
    })
    val lock = RegNext(RegNext(io.clockLocked, false.B), false.B)
    val ready = RegNext(RegNext(io.ddrReady, false.B), false.B)
    val released = RegInit(false.B)
    val count = RegInit(0.U(log2Ceil(holdCycles + 1).W))
    val good = lock && (withBootRom.B || ready)
    when(!released) {
        when(!good) { count := 0.U }.otherwise {
            when(count === (holdCycles - 1).U) { released := true.B }.otherwise { count := count + 1.U }
        }
    }
    val seenReady = RegInit(false.B); val fault = RegInit(false.B)
    when(released && ready) { seenReady := true.B }
    when(released && (!lock || (seenReady && !ready))) { fault := true.B }
    io.held := !released; io.memoryReady := ready && !fault; io.fault := fault
}

/** Read-only, synchronous 64-bit dual-port BootROM; no FF payload or runtime programming port.
  * Uncached CPU fetch/data access: one word per transaction, one-cycle read plus held D response.
  * A rejected write cannot modify the array. GSIM initializes the exact same hex into model RAM.
  */
class FiveStageRomInitialization(bytes: Int) extends Bundle {
    val index = UInt(log2Ceil(bytes / 8).W)
    val data = UInt(64.W)
}

class FiveStageBootRom(params: TLParams, base: BigInt, bytes: Int, file: String,
    simulationInit: Boolean = false) extends Module {
    require(params.dataWidth == 64 && bytes >= 1024 && isPow2(bytes) && base % bytes == 0 && file.nonEmpty)
    chisel3.experimental.annotate(this)(Seq(firrtl.AttributeAnnotation(this.toNamed, "rom_style = \"block\"")))
    val io = IO(new Bundle {
        val ports = Vec(2, Flipped(new TLBundle(params)))
        val initialize = if (simulationInit) Some(Input(Valid(new FiveStageRomInitialization(bytes)))) else None
    })
    val storage = SyncReadMem(bytes / 8, UInt(64.W))
    loadMemoryFromFileInline(storage, file)
    io.initialize.foreach { init =>
        when(init.valid) {
            assert(reset.asBool && !io.ports.map(_.a.valid).reduce(_ || _), "ROM init only under common reset")
            storage.write(init.bits.index, init.bits.data)
        }
    }
    for (port <- io.ports) {
        TLBundle.tieoffSlaveCoherence(port)
        val active = RegInit(false.B); val held = RegInit(false.B)
        val payload = Reg(UInt(64.W)); val saved = Reg(new TLBundleA(params)); val legal = Reg(Bool())
        val a = port.a.bits
        val aligned = (a.address(2, 0) & MuxLookup(a.size, 7.U)(Seq(
            0.U -> 0.U, 1.U -> 1.U, 2.U -> 3.U))) === 0.U
        val allowed = a.opcode === TLOpcode.Get && a.size <= 3.U && aligned &&
            a.address >= base.U && a.address < (base + bytes).U
        port.a.ready := !active
        val result = storage.read(((a.address - base.U) >> 3)(log2Ceil(bytes / 8) - 1, 0), port.a.fire && allowed)
        port.d.valid := active
        port.d.bits := 0.U.asTypeOf(port.d.bits)
        port.d.bits.opcode := Mux(saved.opcode === TLOpcode.Get, TLOpcode.AccessAckData, TLOpcode.AccessAck)
        port.d.bits.source := saved.source; port.d.bits.size := saved.size
        port.d.bits.data := Mux(legal, Mux(held, payload, result), 0.U)
        port.d.bits.denied := !legal; port.d.bits.corrupt := !legal && saved.opcode === TLOpcode.Get
        when(port.a.fire) { active := true.B; held := false.B; saved := a; legal := allowed }
        when(active && !port.d.ready && !held) { held := true.B; payload := result }
        when(port.d.fire) { active := false.B }
    }
}

/** ROM/local split ahead of existing DDR/MMIO route. Every input already has one owner.
  * ROM requests are single-beat uncached requests; overlarge Gets are denied by the downstream route.
  */
class FiveStageBootRoute(params: TLParams, base: BigInt, bytes: Int) extends Module {
    val io = IO(new Bundle {
        val host = Flipped(new TLBundle(params)); val rom = new TLBundle(params); val downstream = new TLBundle(params)
    })
    TLBundle.tieoffSlaveCoherence(io.host)
    TLBundle.tieoffMasterCoherence(io.rom); TLBundle.tieoffMasterCoherence(io.downstream)
    val active = RegInit(false.B); val ownerRom = Reg(Bool())
    val select = io.host.a.bits.address >= base.U && io.host.a.bits.address < (base + bytes).U &&
        io.host.a.bits.size <= 3.U
    io.rom.a.bits := io.host.a.bits; io.downstream.a.bits := io.host.a.bits
    io.rom.a.valid := io.host.a.valid && !active && select
    io.downstream.a.valid := io.host.a.valid && !active && !select
    io.host.a.ready := !active && Mux(select, io.rom.a.ready, io.downstream.a.ready)
    io.host.d.valid := active && Mux(ownerRom, io.rom.d.valid, io.downstream.d.valid)
    io.host.d.bits := Mux(ownerRom, io.rom.d.bits, io.downstream.d.bits)
    io.rom.d.ready := active && ownerRom && io.host.d.ready
    io.downstream.d.ready := active && !ownerRom && io.host.d.ready
    val remaining = Reg(UInt(TLBurst.beats(0.U(params.sizeBits.W), params).getWidth.W))
    when(io.host.a.fire) {
        active := true.B; ownerRom := select
        remaining := Mux(io.host.a.bits.opcode === TLOpcode.Get, TLBurst.beats(io.host.a.bits.size, params), 1.U)
    }
    when(io.host.d.fire) { remaining := remaining - 1.U; when(remaining === 1.U) { active := false.B } }
}

/** Boot-only 32-bit loader register port -> XLEN TL beat, true response (including AXI B) required.
  * No queues/posted stores. Narrow data/byte enables are shifted to the original DDR byte lane.
  */
class FiveStageLoaderTileLink(params: TLParams) extends Module {
    val io = IO(new Bundle { val registers = Flipped(new RegisterPort); val tl = new TLBundle(params) })
    TLBundle.tieoffMasterCoherence(io.tl)
    val active = RegInit(false.B); val lane = Reg(UInt(3.W)); val write = Reg(Bool())
    val r = io.registers.request.bits
    io.tl.a.valid := io.registers.request.valid && !active
    io.registers.request.ready := !active && io.tl.a.ready
    io.tl.a.bits := 0.U.asTypeOf(io.tl.a.bits)
    io.tl.a.bits.opcode := Mux(r.write, TLOpcode.PutPartialData, TLOpcode.Get)
    io.tl.a.bits.size := 2.U; io.tl.a.bits.address := r.address
    io.tl.a.bits.mask := (r.byteEnable << r.address(2, 0))(7, 0)
    io.tl.a.bits.data := (r.data << Cat(r.address(2, 0), 0.U(3.W)))(63, 0)
    io.registers.response.valid := active && io.tl.d.valid
    io.registers.response.bits.data := io.tl.d.bits.data >> Cat(lane, 0.U(3.W))
    io.registers.response.bits.error := io.tl.d.bits.denied || io.tl.d.bits.corrupt
    io.tl.d.ready := active && io.registers.response.ready
    when(io.tl.a.fire) {
        active := true.B; lane := r.address(2, 0); write := r.write
        assert(r.size === 2.U && r.address(1, 0) === 0.U && r.byteEnable === 15.U, "loader transfer geometry")
    }
    when(io.tl.d.fire) {
        assert(io.tl.d.bits.source === 0.U && io.tl.d.bits.size === 2.U &&
            io.tl.d.bits.opcode === Mux(write, TLOpcode.AccessAck, TLOpcode.AccessAckData), "loader reply metadata")
        active := false.B
    }
}
