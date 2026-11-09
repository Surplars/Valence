package soc.integration.spinor

import chisel3._
import chisel3.util._
import soc.core.inorder._
import vpu._

/** Single-beat TL A/D element service through the CPU's ordinary D-cache.
  * One accepted A owns source/size until D.fire. Byte lanes are unchanged.
  * H configurations use the CPU translator and retain precise fault metadata
  * locally; the native CDC still transports the original TL response.
  */
class I1SpinorMemoryBridge(p: FiveStageConfig) extends Module {
    val io = IO(new Bundle {
        val tl = Flipped(new VpuTileLinkMaster(VpuTLParams()))
        val memory = new I1SpinorMemoryPort(p)
        val begin = if (p.withH) Some(Flipped(Valid(UInt(80.W)))) else None
        val fault = if (p.withH) Some(Valid(new I1SpinorMemoryFault)) else None
    })
    val pending = RegInit(false.B)
    val source = Reg(UInt(4.W)); val size = Reg(UInt(3.W)); val write = Reg(Bool())
    val a = io.tl.a.bits
    io.memory.request.valid := !pending && io.tl.a.valid
    io.memory.request.bits := 0.U.asTypeOf(new FiveStageDataRequest(p))
    io.memory.request.bits.guest.foreach(_.vector := true.B)
    io.memory.request.bits.address := a.address
    io.memory.request.bits.write := a.opcode =/= 4.U
    io.memory.request.bits.size := a.size(1, 0)
    io.memory.request.bits.data := a.data; io.memory.request.bits.mask := a.mask
    io.tl.a.ready := !pending && io.memory.request.ready
    io.tl.d.valid := pending && io.memory.response.valid
    io.tl.d.bits := 0.U.asTypeOf(new VpuTLD(VpuTLParams()))
    io.tl.d.bits.opcode := Mux(write, 0.U, 1.U)
    io.tl.d.bits.source := source; io.tl.d.bits.size := size
    io.tl.d.bits.data := io.memory.response.bits.data
    io.tl.d.bits.denied := io.memory.response.bits.error || io.memory.response.bits.pageFault
    io.memory.response.ready := pending && io.tl.d.ready
    when(io.tl.a.fire) {
        assert((a.opcode === 0.U || a.opcode === 1.U || a.opcode === 4.U) && a.size <= 3.U &&
            a.param === 0.U && !a.corrupt, "unsupported Spinor physical A beat")
        pending := true.B; source := a.source; size := a.size; write := a.opcode =/= 4.U
    }
    when(io.tl.d.fire) { pending := false.B }
    if (p.withH) {
        val faultValid = RegInit(false.B)
        val fault = Reg(new I1SpinorMemoryFault)
        val token = Reg(UInt(80.W)); val address = Reg(UInt(64.W))
        io.fault.get.valid := faultValid; io.fault.get.bits := fault
        when(io.begin.get.valid) {
            assert(!pending, "new vector command overlaps an old element response")
            token := io.begin.get.bits; faultValid := false.B
        }
        when(io.memory.request.fire) { address := a.address }
        when(io.memory.response.fire && io.memory.response.bits.error && !faultValid) {
            val response = io.memory.response.bits
            faultValid := true.B; fault.token := token; fault.tval := address
            fault.guest := response.guest.get
            fault.cause := Mux(response.guest.get.pageFault, Mux(write, 23.U, 21.U),
                Mux(response.pageFault, Mux(write, 15.U, 13.U), Mux(write, 7.U, 5.U)))
        }
    }

}
