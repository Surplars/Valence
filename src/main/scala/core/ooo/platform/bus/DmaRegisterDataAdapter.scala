package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.bus.RegisterPort

/** Right-justified IP requests to DataPort byte lanes, four ordered owners.
  * No zero-cycle bypass; exact naturally aligned masks are checked downstream.
  * Neither atomics nor virtual addresses can originate from this ordinary DMA port.
  */
class DmaRegisterDataAdapter extends Module {
    val io = IO(new Bundle {
        val registers = Flipped(new RegisterPort)
        val data = new DataPort
    })
    val lanes = Module(new Queue(UInt(3.W), 4, pipe = false, flow = false))
    val r = io.registers.request.bits
    val shift = Cat(r.address(2, 0), 0.U(3.W))
    io.data.request.valid := io.registers.request.valid && lanes.io.enq.ready
    io.data.request.bits := 0.U.asTypeOf(new DataRequest)
    io.data.request.bits.address := r.address
    io.data.request.bits.write := r.write
    io.data.request.bits.size := r.size
    io.data.request.bits.data := r.data << shift
    io.data.request.bits.mask := (r.byteEnable << r.address(2, 0))(7, 0)
    io.registers.request.ready := io.data.request.ready && lanes.io.enq.ready
    lanes.io.enq.valid := io.data.request.fire
    lanes.io.enq.bits := r.address(2, 0)
    io.registers.response.valid := io.data.response.valid && lanes.io.deq.valid
    io.registers.response.bits.data := io.data.response.bits.data >> Cat(lanes.io.deq.bits, 0.U(3.W))
    io.registers.response.bits.error := io.data.response.bits.error || io.data.response.bits.pageFault
    io.data.response.ready := io.registers.response.ready && lanes.io.deq.valid
    lanes.io.deq.ready := io.data.response.fire
}
