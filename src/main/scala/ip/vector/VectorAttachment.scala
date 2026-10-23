package soc.ip.vector

import chisel3._
import chisel3.util._

/** Reserved integration shape, NOT an implemented ISA extension. Enabling execution
  * fails closed until both CPU adapters, state, memory and VPU are implemented.
  * The transport is RV64, single-command/single-element outstanding, ELEN <= 64.
  * VLEN describes future register storage, not memory bandwidth or ISA advertisement.
  */
case class VectorAttachmentConfig(
    enabled: Boolean = false,
    vlen: Int = 128,
    elen: Int = 64,
    ownerBits: Int = 16,
    epochBits: Int = 8
) {
    private def powerOfTwo(n: Int): Boolean = n > 0 && (n & (n - 1)) == 0
    require(!enabled, "VPU execution is not implemented; the reservation must remain disabled")
    require(powerOfTwo(vlen) && vlen >= 128 && vlen <= 65536, "reserved VLEN must be 128..65536")
    require(powerOfTwo(elen) && elen >= 8 && elen <= 64 && elen <= vlen, "reserved ELEN must be 8..64")
    require(ownerBits >= 2 && ownerBits <= 64)
    require(epochBits >= 2 && epochBits <= 64)
    val xlen = 64
    val maxCommands = 1
    val maxMemoryRequests = 1
    val advertisesV = false
    val vlenBytes: Int = vlen / 8

    /** Future adapters must call this before packing their full native identity.
      * Width fit is necessary, not a proof of lifetime/epoch non-reuse.
      */
    def requireIdentityCapacity(nativeOwnerBits: Int, nativeEpochBits: Int): Unit = {
        require(nativeOwnerBits > 0 && nativeOwnerBits <= ownerBits, "native owner would be truncated")
        require(nativeEpochBits > 0 && nativeEpochBits <= epochBits, "native epoch would be truncated")
    }
}

/** Echo the entire token on EVERY reply. A CPU adapter maps its full identity to
  * owner, never a truncated ROB index. No reuse/wrap before all old traffic drains.
  */
class VectorOwner(p: VectorAttachmentConfig) extends Bundle {
    val owner = UInt(p.ownerBits.W)
    val epoch = UInt(p.epochBits.W)
}

/** CPU owns architected CSRs; VPU receives a serialized snapshot. No hypervisor
  * context is supported by this reservation. FS and frm are needed by future FP.
  */
class VectorContext extends Bundle {
    val vl = UInt(64.W)
    val vtype = UInt(64.W)
    val vstart = UInt(64.W)
    val vxrm = UInt(2.W)
    val vxsat = Bool()
    val vs = UInt(2.W)
    val fs = UInt(2.W)
    val frm = UInt(3.W)
}

/** Only issue a decoded, legal oldest instruction after scalar memory drains.
  * command.fire is irrevocable authorization, not speculative dispatch. Younger
  * work and context changes remain blocked through complete.fire. Scalar operands
  * cover rs1/rs2 (vsetvl) and an IEEE/boxed FP source; the raw instruction names registers.
  */
class VectorCommand(p: VectorAttachmentConfig) extends Bundle {
    val token = new VectorOwner(p)
    val instruction = UInt(32.W)
    val pc = UInt(64.W)
    val rs1 = UInt(64.W)
    val rs2 = UInt(64.W)
    val fpSource = UInt(64.W)
    val context = new VectorContext
}

/** Complete only after all element responses and visible effects are accounted
  * for. CPU atomically accepts CSR deltas/scalar result/trap at complete.fire.
  * A fault can preserve a committed element prefix: never roll that prefix back.
  * A future adapter validates token, destination class, legality and CSR updates.
  * A fault suppresses scalarWrite, but may preserve dirty/flags/saturation from
  * the completed prefix. Success resets vstart to zero; fault-only-first success
  * may reduce vl. updateVlVtype supplies the complete pair, preserving unchanged fields.
  */
class VectorCompletion(p: VectorAttachmentConfig) extends Bundle {
    val token = new VectorOwner(p)
    val exception = Bool()
    val cause = UInt(64.W)
    val tval = UInt(64.W)
    val vstart = UInt(64.W)
    val updateVlVtype = Bool()
    val vl = UInt(64.W)
    val vtype = UInt(64.W)
    val setVxsat = Bool()
    val dirtyVs = Bool()
    val dirtyFs = Bool()
    val fpFlags = UInt(5.W)
    val scalarWrite = Bool()
    val scalarFp = Bool()
    val scalarDestination = UInt(5.W)
    val scalarValue = UInt(64.W)
}

/** Element service BEFORE translation/PMP/cache lookup; never a raw DMA port.
  * Masked-off elements generate no request. One aligned <=8-byte access at a
  * time; a future adapter must handle or fault misalignment before side effects.
  * data is right-justified, size=log2(bytes), 0..3. No atomics or implicit bursts.
  * The CPU freezes effective privilege, satp, SUM/MXR/MPRV and PMP until drain;
  * epoch identifies this frozen context and must be checked by the memory adapter.
  */
class VectorMemoryRequest(p: VectorAttachmentConfig) extends Bundle {
    val token = new VectorOwner(p)
    val element = UInt(64.W)
    val field = UInt(3.W)
    val address = UInt(64.W)
    val write = Bool()
    val size = UInt(2.W)
    val data = UInt(64.W)
}
class VectorMemoryResponse(p: VectorAttachmentConfig) extends Bundle {
    val token = new VectorOwner(p)
    val element = UInt(64.W)
    val field = UInt(3.W)
    val data = UInt(64.W)
    val exception = Bool()
    val cause = UInt(64.W)
    val tval = UInt(64.W)
}

/** CPU-facing orientation. Every producer holds valid/payload until ready.
  * quiesce stops CPU NEW command offers; an already-held offer MUST still be
  * allowed to handshake and drain. It is NOT a kill or a gate on VPU ready.
  * CPU drain also includes its held command; VPU drained alone is insufficient.
  * drained requires no accepted command, held completion, element request/reply,
  * or private effect. The CPU must not gate complete.ready on quiesce.
  * Fabric/Home/CDC drain must be combined separately before clocks/reset/context
  * change. Architectural redirects cannot erase an authorized vector instruction.
  */
class VectorAttachmentPort(p: VectorAttachmentConfig) extends Bundle {
    val command = Decoupled(new VectorCommand(p))
    val complete = Flipped(Decoupled(new VectorCompletion(p)))
    val memoryRequest = Flipped(Decoupled(new VectorMemoryRequest(p)))
    val memoryResponse = Decoupled(new VectorMemoryResponse(p))
    val quiesce = Output(Bool())
    val drained = Input(Bool())
}

/** Safe absent VPU: zero capacity and zero requests, continuously drained.
  * Deliberately NOT connected to either CPU. CPU decode must trap unsupported
  * instructions instead of issuing to this endpoint and waiting forever.
  * No state, datapath, CSR, memory client or ISA bit is added to existing tops.
  */
class DisabledVectorAttachment(p: VectorAttachmentConfig = VectorAttachmentConfig()) extends RawModule {
    val io = IO(Flipped(new VectorAttachmentPort(p)))
    io.command.ready := false.B
    io.complete.valid := false.B
    io.complete.bits := 0.U.asTypeOf(io.complete.bits)
    io.memoryRequest.valid := false.B
    io.memoryRequest.bits := 0.U.asTypeOf(io.memoryRequest.bits)
    io.memoryResponse.ready := false.B
    io.drained := true.B
}
