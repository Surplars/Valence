package soc.core.inorder

import chisel3._
import chisel3.util._
import soc.bus.tilelink._
import soc.ip.bus.RegisterPort

/** One existing cache owner, one TL source, no payload FIFO or posted write acknowledgement.
  * One A Get requests an entire power-of-two line; D transfers one XLEN beat/cycle.
  * All offered fields are independent of READY. Retain ownership through the final D handshake.
  */
class FiveStageTileLink(val p: FiveStageConfig) extends Module {
    require(p.cacheLineBytes <= 128, "reused SoC fabric encodes at most 128-byte messages")
    val params = TLParams(addrWidth = p.xlen, dataWidth = p.xlen, sourceBits = 1, sizeBits = 3)
    val io = IO(new Bundle {
        val native = Flipped(new FiveStageBurstPort(p))
        val tl = new TLBundle(params)
    })
    TLBundle.tieoffMasterCoherence(io.tl)
    val active = RegInit(false.B)
    val write = Reg(Bool())
    val size = Reg(UInt(params.sizeBits.W))
    val remaining = Reg(UInt(io.native.request.bits.beats.getWidth.W))
    val r = io.native.request.bits
    val beatLog = log2Ceil(p.xlen / 8)
    val burstSize = MuxLookup(r.beats, beatLog.U(3.W))(
        (0 to log2Ceil(p.cacheLineBytes / (p.xlen / 8))).map(n => (1 << n).U -> (n + beatLog).U(3.W)))
    val requestedSize = Mux(!r.write && r.beats > 1.U, burstSize, r.size)
    val address = r.address | r.byteOffset
    val mask = MuxLookup(r.size, ((BigInt(1) << (p.xlen / 8)) - 1).U((p.xlen / 8).W))(
        (0 until beatLog).map(n => n.U -> (((BigInt(1) << (1 << n)) - 1).U << r.byteOffset)))
    io.tl.a.valid := io.native.request.valid && !active
    io.native.request.ready := !active && io.tl.a.ready
    io.tl.a.bits := 0.U.asTypeOf(io.tl.a.bits)
    io.tl.a.bits.opcode := Mux(r.write, TLOpcode.PutPartialData, TLOpcode.Get)
    io.tl.a.bits.size := requestedSize
    io.tl.a.bits.address := address
    io.tl.a.bits.mask := Mux(r.write, r.mask, mask)
    io.tl.a.bits.data := r.data
    io.native.response.valid := active && io.tl.d.valid
    io.native.response.bits.data := io.tl.d.bits.data
    io.native.response.bits.error := io.tl.d.bits.denied || io.tl.d.bits.corrupt
    io.native.response.bits.last := remaining === 1.U
    io.tl.d.ready := active && io.native.response.ready
    when(io.tl.a.fire) {
        active := true.B; write := r.write; size := requestedSize; remaining := r.beats
        assert(r.beats =/= 0.U && (r.beats & (r.beats - 1.U)) === 0.U, "non-power-of-two native burst")
        assert(!r.write || r.beats === 1.U, "native stores are single-beat, acknowledged transactions")
        assert(r.size <= beatLog.U && r.address(beatLog - 1, 0) === 0.U, "native lane geometry")
        assert((address & ((1.U(p.xlen.W) << requestedSize) - 1.U)) === 0.U, "TL natural alignment")
    }
    when(io.tl.d.valid && !reset.asBool) {
        assert(active, "unowned TileLink response")
        assert(io.tl.d.bits.source === 0.U && io.tl.d.bits.size === size &&
            io.tl.d.bits.opcode === Mux(write, TLOpcode.AccessAck, TLOpcode.AccessAckData),
            "TileLink response metadata mismatch")
    }
    when(io.tl.d.fire) {
        remaining := remaining - 1.U
        when(remaining === 1.U) { active := false.B }
    }
    when(io.tl.b.valid && !reset.asBool) { assert(false.B, "I1 caches do not hold TL-C permissions") }
}

/** Single-source physical route. DDR and register replies cannot borrow one another's owner.
  * DDR A/D are not copied into extra queues. Subword register data/strobes are right justified.
  * Unmapped and oversized MMIO reads return the exact denied D beat count without IP side effects.
  */
class FiveStageTileLinkRoute(params: TLParams, base: BigInt, bytes: BigInt, allowRegisters: Boolean,
    registeredAdmission: Boolean = false) extends Module {
    require(params.dataWidth == 64 && params.addrWidth == 64)
    private val largest = BigInt(1) << ((1 << params.sizeBits) - 1)
    require(base >= 0 && bytes > 0 && base % largest == 0 && bytes % largest == 0 &&
        base + bytes <= (BigInt(1) << params.addrWidth), "bounded route requires aligned message windows")
    val io = IO(new Bundle {
        val host = Flipped(new TLBundle(params))
        val memory = new TLBundle(params)
        val registers = new RegisterPort
    })
    TLBundle.tieoffSlaveCoherence(io.host); TLBundle.tieoffMasterCoherence(io.memory)
    val active = RegInit(false.B)
    val memoryOwner = Reg(Bool())
    val registerOwner = Reg(Bool())
    val saved = Reg(new TLBundleA(params))
    val offering = if (registeredAdmission) Some(RegInit(false.B)) else None
    val remaining = Reg(UInt(TLBurst.beats(0.U(params.sizeBits.W), params).getWidth.W))
    val a = io.host.a.bits
    // Natural TL alignment plus aligned window boundaries prove the whole beat/burst fits.
    // No XLEN add -> XLEN compare -> READY path; malformed alignment is denied before any IP side effect.
    val aligned = MuxLookup(a.size, true.B)((1 until (1 << params.sizeBits)).map(n =>
        n.U -> (a.address(n - 1, 0) === 0.U)))
    val memory = (if (registeredAdmission) I1AddressWindow.contains(a.address, base, bytes)
        else a.address >= base.U && a.address < (base + bytes).U(65.W)) && aligned
    val registerSelected = allowRegisters.B && aligned && a.size <= 3.U &&
        (a.opcode === TLOpcode.Get || a.opcode === TLOpcode.PutPartialData || a.opcode === TLOpcode.PutFullData)
    // Reuse the existing saved packet/one-owner capacity. Admission captures
    // it before arbitration, breaking downstream AXI range/hazard -> cache
    // READY feedback without adding a transaction slot or posting a store.
    val forwarded = if (registeredAdmission) saved else a
    val forwardValid = if (registeredAdmission) active && offering.get else io.host.a.valid && !active
    val forwardMemory = if (registeredAdmission) memoryOwner else memory
    val forwardRegister = if (registeredAdmission) registerOwner else !memory && registerSelected
    val awaitingReply = if (registeredAdmission) active && !offering.get else active
    io.memory.a.valid := forwardValid && forwardMemory
    io.memory.a.bits := forwarded
    io.registers.request.valid := forwardValid && forwardRegister
    io.registers.request.bits.address := forwarded.address
    io.registers.request.bits.write := forwarded.opcode =/= TLOpcode.Get
    io.registers.request.bits.size := forwarded.size
    io.registers.request.bits.data := forwarded.data >> Cat(forwarded.address(2, 0), 0.U(3.W))
    io.registers.request.bits.byteEnable := forwarded.mask >> forwarded.address(2, 0)
    io.host.a.ready := (if (registeredAdmission) !active else !active && Mux(memory, io.memory.a.ready,
        Mux(registerSelected, io.registers.request.ready, true.B)))
    io.host.d.valid := awaitingReply && Mux(memoryOwner, io.memory.d.valid,
        Mux(registerOwner, io.registers.response.valid, true.B))
    io.host.d.bits := 0.U.asTypeOf(io.host.d.bits)
    io.host.d.bits.opcode := Mux(saved.opcode === TLOpcode.Get, TLOpcode.AccessAckData, TLOpcode.AccessAck)
    io.host.d.bits.size := saved.size; io.host.d.bits.source := saved.source
    io.host.d.bits.denied := !registerOwner || io.registers.response.bits.error
    io.host.d.bits.corrupt := saved.opcode === TLOpcode.Get && io.host.d.bits.denied
    io.host.d.bits.data := (io.registers.response.bits.data << Cat(saved.address(2, 0), 0.U(3.W)))(63, 0)
    when(memoryOwner) { io.host.d.bits := io.memory.d.bits }
    io.memory.d.ready := awaitingReply && memoryOwner && io.host.d.ready
    io.registers.response.ready := awaitingReply && !memoryOwner && registerOwner && io.host.d.ready
    when(io.host.a.fire) {
        active := true.B; memoryOwner := memory; registerOwner := !memory && registerSelected; saved := a
        offering.foreach(_ := true.B)
        remaining := Mux(a.opcode === TLOpcode.Get, TLBurst.beats(a.size, params), 1.U)
    }
    offering.foreach { pending =>
        when(active && pending && (io.memory.a.fire || io.registers.request.fire ||
            (!memoryOwner && !registerOwner))) { pending := false.B }
    }
    when(io.host.d.fire) {
        remaining := remaining - 1.U
        when(remaining === 1.U) { active := false.B }
    }
}
