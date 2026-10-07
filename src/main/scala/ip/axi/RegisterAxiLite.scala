package soc.ip.axi

import chisel3._
import chisel3.util._
import soc.ip.bus.{RegisterPort, RegisterRequest}

class AxiLiteAddress extends Bundle {
    val addr = UInt(32.W)
    val prot = UInt(3.W)
}
class AxiLiteWriteData extends Bundle {
    val data = UInt(32.W)
    val strb = UInt(4.W)
}
class AxiLiteReadData extends Bundle {
    val data = UInt(32.W)
    val resp = UInt(2.W)
}
class AxiLitePort extends Bundle {
    val aw = Decoupled(new AxiLiteAddress)
    val w = Decoupled(new AxiLiteWriteData)
    val b = Flipped(Decoupled(UInt(2.W)))
    val ar = Decoupled(new AxiLiteAddress)
    val r = Flipped(Decoupled(new AxiLiteReadData))
}

/** One ordered register transaction; AW and W advance independently.
  * Latency: registered request and registered response; no combinational ready/valid bypass.
  * Capacity: one, held until the upstream reply is consumed. Byte/half/word accesses
  * within one aligned word are supported; wider, crossing and out-of-window accesses
  * return error without AXI side effects. Reset must be coordinated with the AXI slave.
  * RegisterPort payload is byte-addressed/right-justified; AXI payload is word-lane aligned.
  */
class RegisterAxiLite(base: BigInt, bytes: BigInt) extends Module {
    require(base >= 0 && bytes >= 4 && base % 4 == 0 && bytes % 4 == 0)
    val io = IO(new Bundle {
        val registers = Flipped(new RegisterPort)
        val axi = new AxiLitePort
    })
    val idle :: issue :: reply :: Nil = Enum(3)
    val state = RegInit(idle)
    val request = RegInit(0.U.asTypeOf(new RegisterRequest))
    val addressDone = RegInit(false.B)
    val dataDone = RegInit(false.B)
    val replyData = RegInit(0.U(64.W))
    val replyError = RegInit(false.B)
    val offset = request.address(1, 0)
    val shift = Cat(offset, 0.U(3.W))
    io.registers.request.ready := state === idle
    io.registers.response.valid := state === reply
    io.registers.response.bits.data := replyData
    io.registers.response.bits.error := replyError
    val local = request.address - base.U(64.W)
    val aligned = Cat(local(31, 2), 0.U(2.W))
    io.axi.aw.valid := state === issue && request.write && !addressDone
    io.axi.aw.bits.addr := aligned
    io.axi.aw.bits.prot := 0.U
    io.axi.w.valid := state === issue && request.write && !dataDone
    io.axi.w.bits.data := (request.data << shift)(31, 0)
    io.axi.w.bits.strb := (request.byteEnable << offset)(3, 0)
    io.axi.ar.valid := state === issue && !request.write && !addressDone
    io.axi.ar.bits.addr := aligned
    io.axi.ar.bits.prot := 0.U
    io.axi.b.ready := state === issue && request.write && addressDone && dataDone
    io.axi.r.ready := state === issue && !request.write && addressDone
    when(io.registers.request.fire) {
        val offered = io.registers.request.bits
        val sizeBytes = (1.U(4.W) << offered.size)(3, 0)
        val inWindow = offered.address >= base.U && offered.address < (base + bytes).U
        val fits = offered.size <= 2.U && (offered.address(1, 0) +& sizeBytes) <= 4.U
        request := offered
        addressDone := false.B
        dataDone := false.B
        replyData := 0.U
        replyError := !inWindow || !fits
        state := Mux(inWindow && fits, issue, reply)
    }
    when(io.axi.aw.fire || io.axi.ar.fire) { addressDone := true.B }
    when(io.axi.w.fire) { dataDone := true.B }
    when(io.axi.b.fire) {
        replyError := io.axi.b.bits =/= 0.U
        replyData := 0.U
        state := reply
    }
    when(io.axi.r.fire) {
        replyError := io.axi.r.bits.resp =/= 0.U
        replyData := io.axi.r.bits.data >> shift
        state := reply
    }
    when(io.registers.response.fire) { state := idle }
}
