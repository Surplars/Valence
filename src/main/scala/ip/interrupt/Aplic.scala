package soc.ip.interrupt

import chisel3._
import chisel3.util._
import soc.ip.bus._

case class AplicParams(
    sources: Int = 31,
    identities: Int = 127,
    base: BigInt = BigInt("0c000000", 16),
    msiBase: BigInt = BigInt("24000000", 16)
) {
    require(sources >= 1 && sources <= 1023)
    require(identities >= 63 && identities <= 2047 && (identities + 1) % 64 == 0)
    require(base >= 0 && base                                          % 4096 == 0 && base + 16384 <= (BigInt(1) << 64))
    require(msiBase >= 0 && msiBase % 4096 == 0 && msiBase + 4096 <= (BigInt(1) << 56))
    require(base + 16384 <= msiBase || msiBase + 4096 <= base)
    val eiidBits = log2Ceil(identities + 1)
}

/** Single-hart MSI domain. Optional root delegation and parent mask compose an M root with one S child. */
class Aplic(val p: AplicParams = AplicParams(), hasChild: Boolean = false,
    hasParent: Boolean = false, childMsiBase: BigInt = 0) extends Module {
    require(!hasChild || (childMsiBase >= 0 && childMsiBase % 4096 == 0))
    val io = IO(new Bundle {
        val sources  = Input(UInt(p.sources.W))
        val parentEnabled = if (hasParent) Some(Input(UInt(p.sources.W))) else None
        val childSources = Output(UInt(p.sources.W))
        val childEnabled = Output(UInt(p.sources.W))
        val mmio     = Flipped(new RegisterPort)
        val msi      = new RegisterPort
        val msiError = Output(Bool())
    })
    val modes       = RegInit(VecInit(Seq.fill(p.sources)(0.U(3.W))))
    val delegated   = RegInit(VecInit(Seq.fill(p.sources)(false.B)))
    val targets     = RegInit(VecInit(Seq.fill(p.sources)(0.U(p.eiidBits.W))))
    val pending     = RegInit(VecInit(Seq.fill(p.sources)(false.B)))
    val enabled     = RegInit(VecInit(Seq.fill(p.sources)(false.B)))
    val previous    = RegInit(VecInit(Seq.fill(p.sources)(false.B)))
    val delivery    = RegInit(false.B)
    val genBusy     = RegInit(false.B)
    val genPending  = RegInit(false.B)
    val genIdentity = RegInit(0.U(p.eiidBits.W))
    val responses   = Module(new Queue(new RegisterResponse, 2, pipe = false, flow = false))
    io.mmio.response <> responses.io.deq
    io.mmio.request.ready  := responses.io.enq.ready
    responses.io.enq.valid := io.mmio.request.valid
    val bus    = io.mmio.request.bits
    val offset = bus.address - p.base.U
    val error  = bus.address < p.base.U || bus.address >= (p.base + 16384).U(65.W) ||
        bus.size =/= 2.U || bus.address(1, 0) =/= 0.U || (bus.write && bus.byteEnable =/= 15.U)
    val write  = io.mmio.request.fire && bus.write && !error
    val data   = bus.data(31, 0)
    val number = Mux(offset === "h2004".U, Cat((0 until 4).map(i => data(8 * i + 7, 8 * i))), data)
    val read   = WireDefault(0.U(32.W))
    responses.io.enq.bits.data  := Mux(error || bus.write, 0.U, read)
    responses.io.enq.bits.error := error
    when(offset === 0.U) { read := "h80000004".U | (delivery.asUInt << 8) }
    when(offset === "h1bc0".U) { read := ((p.msiBase >> 12) & BigInt("ffffffff", 16)).U }
    when(offset === "h1bc4".U) { read := (BigInt("80000000", 16) | (p.msiBase >> 44)).U }
    if (hasChild) {
        when(offset === "h1bc8".U) { read := ((childMsiBase >> 12) & BigInt("ffffffff", 16)).U }
        when(offset === "h1bcc".U) { read := (BigInt("80000000", 16) | (childMsiBase >> 44)).U }
    }
    when(offset === "h3000".U) { read := (genBusy.asUInt << 12) | genIdentity }
    when(write && offset === 0.U) { delivery := data(8) }
    when(write && offset === "h3000".U && !genBusy) {
        genBusy     := true.B
        genPending  := true.B
        genIdentity := data(p.eiidBits - 1, 0)
    }
    val rectified  = Wire(Vec(p.sources, Bool()))
    val candidates = Wire(Vec(p.sources, Bool()))
    io.childEnabled := Mux(hasChild.B, delegated.asUInt, 0.U)
    io.childSources := io.sources & io.childEnabled
    for (i <- 0 until p.sources) {
        val parentAllows = io.parentEnabled.map(_(i)).getOrElse(true.B)
        rectified(i)  := parentAllows && !delegated(i) && modes(i) >= 4.U &&
            (io.sources(i) ^ modes(i)(0))
        candidates(i) := parentAllows && !delegated(i) && delivery && pending(i) && enabled(i) &&
            (modes(i) < 6.U || rectified(i))
    }
    class Message extends Bundle {
        val identity  = UInt(p.eiidBits.W)
        val generated = Bool()
    }
    val outgoing = Module(new Queue(new Message, 2, pipe = false, flow = false))
    val selected = PriorityEncoder(candidates.asUInt)
    outgoing.io.enq.valid          := genPending || candidates.asUInt.orR
    outgoing.io.enq.bits.identity  := Mux(genPending, genIdentity, targets(selected))
    outgoing.io.enq.bits.generated := genPending
    when(outgoing.io.enq.fire && genPending) { genPending := false.B }
    val outstanding = RegInit(0.U(3.W))
    io.msi.request.valid           := outgoing.io.deq.valid && outstanding < 4.U
    outgoing.io.deq.ready          := io.msi.request.ready && outstanding < 4.U
    io.msi.request.bits.address    := p.msiBase.U
    io.msi.request.bits.write      := true.B
    io.msi.request.bits.size       := 2.U
    io.msi.request.bits.byteEnable := 15.U
    io.msi.request.bits.data       := outgoing.io.deq.bits.identity
    io.msi.response.ready          := outstanding =/= 0.U || io.msi.request.fire
    outstanding                    := outstanding + io.msi.request.fire - io.msi.response.fire
    val failed = RegInit(false.B)
    when(io.msi.response.fire && io.msi.response.bits.error) { failed := true.B }
    io.msiError := failed
    when(io.msi.request.fire && outgoing.io.deq.bits.generated) { genBusy := false.B }
    for (i <- 0 until p.sources) {
        val id            = i + 1
        val parentAllows  = io.parentEnabled.map(_(i)).getOrElse(true.B)
        val group         = id / 32
        val bit           = id % 32
        val cfgWrite      = write && offset === (id * 4).U
        val newDelegation = if (hasChild) data(10) && data(9, 0) === 0.U else false.B
        val newMode       = Mux(data(10) || data(2, 1) === 1.U, 0.U, data(2, 0))
        val effectiveMode = Mux(cfgWrite, newMode, modes(i))
        val input         = parentAllows && !Mux(cfgWrite, newDelegation, delegated(i)) &&
            effectiveMode >= 4.U && (io.sources(i) ^ effectiveMode(0))
        val set           = write && ((offset === (0x1c00 + 4 * group).U && data(bit)) ||
            ((offset === "h1cdc".U || offset === "h2000".U || offset === "h2004".U) && number === id.U))
        val clear = write && ((offset === (0x1d00 + 4 * group).U && data(bit)) ||
            (offset === "h1ddc".U && data === id.U))
        val setEnable = write && ((offset === (0x1e00 + 4 * group).U && data(bit)) ||
            (offset === "h1edc".U && data === id.U))
        val clearEnable = write && ((offset === (0x1f00 + 4 * group).U && data(bit)) ||
            (offset === "h1fdc".U && data === id.U))
        val forwarded = outgoing.io.enq.fire && !genPending && selected === i.U
        when(clear || forwarded) { pending(i) := false.B }
        when((input && (!previous(i) || cfgWrite)) || (set && (effectiveMode < 6.U || input))) {
            pending(i) := true.B
        }
        when(clearEnable) { enabled(i) := false.B }
        when(setEnable) { enabled(i) := true.B }
        when(write && offset === (0x3000 + id * 4).U) { targets(i) := data(p.eiidBits - 1, 0) }
        when(cfgWrite) {
            modes(i) := newMode
            delegated(i) := newDelegation
        }
        when(effectiveMode === 0.U) {
            pending(i) := false.B
            enabled(i) := false.B
            targets(i) := 0.U
        }.elsewhen(effectiveMode >= 6.U && !input) { pending(i) := false.B }
        when(!parentAllows) { pending(i) := false.B }
        previous(i) := input
        when(offset === (id * 4).U) { read := Mux(delegated(i), "h400".U, modes(i)) }
        when(offset === (0x3000 + id * 4).U) { read := targets(i) }
    }
    for (g <- 0 until (p.sources + 32) / 32) {
        def word(values: Vec[Bool]): UInt = VecInit((0 until 32).map { b =>
            val id = g * 32 + b
            if (id >= 1 && id <= p.sources) values(id - 1) else false.B
        }).asUInt
        when(offset === (0x1c00 + g * 4).U) { read := word(pending) }
        when(offset === (0x1d00 + g * 4).U) { read := word(rectified) }
        when(offset === (0x1e00 + g * 4).U) { read := word(enabled) }
    }
}
