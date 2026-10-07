package soc.ip.ethernet

import chisel3._
import chisel3.util._

class MdioCommand extends Bundle {
    val phy = UInt(5.W)
    val register = UInt(5.W)
    val write = Bool()
    val data = UInt(16.W)
}
class MdioResponse extends Bundle {
    val data = UInt(16.W)
    val noAck = Bool()
}

/** One outstanding Clause 22 transaction; full 32-one preamble, no suppression.
  * MDC is idle-low. Output changes on falling edges; read data is sampled on
  * rising edges, with both turnaround bits released. Read TA0=1 reports noAck.
  * Response remains stable under backpressure. Reset cancels the transaction.
  * A command takes 128*divider control cycles; response blocks the next command.
  */
class MdioClause22(clockHz: Int = 100000000, mdcHz: Int = 2500000) extends Module {
    require(clockHz > 0 && mdcHz > 0 && mdcHz <= 2500000 && clockHz.toLong >= 4L * mdcHz)
    private val divider = ((clockHz.toLong + 2L * mdcHz - 1) / (2L * mdcHz)).toInt
    require(divider <= 65536)
    val io = IO(new Bundle {
        val command = Flipped(Decoupled(new MdioCommand))
        val response = Decoupled(new MdioResponse)
        val mdc = Output(Bool())
        val mdioIn = Input(Bool())
        val mdioOut = Output(Bool())
        val mdioOe = Output(Bool())
        val busy = Output(Bool())
    })
    val active = RegInit(false.B)
    val mdc = RegInit(false.B)
    val remaining = RegInit(0.U(log2Ceil(divider).W))
    val index = RegInit(0.U(6.W))
    val frame = RegInit(0.U(64.W))
    val write = RegInit(false.B)
    val result = RegInit(0.U(16.W))
    val noAck = RegInit(false.B)
    val reply = RegInit(false.B)
    io.command.ready := !active && !reply
    io.response.valid := reply
    io.response.bits.data := result
    io.response.bits.noAck := noAck
    io.busy := active || reply
    io.mdc := mdc
    io.mdioOe := active && (write || index < 46.U)
    // Physical MDIO data is a serializer FF, not a 64-to-1 indexed mux.
    // Advance only on MDC falling edges, retaining the complete TA/preamble.
    io.mdioOut := Mux(active, frame(63), true.B)
    when(io.response.fire) { reply := false.B }
    when(io.command.fire) {
        frame := Cat("hffffffff".U(32.W), 1.U(2.W),
            Mux(io.command.bits.write, 1.U(2.W), 2.U(2.W)),
            io.command.bits.phy, io.command.bits.register, 2.U(2.W), io.command.bits.data)
        active := true.B
        mdc := false.B
        remaining := 0.U
        index := 0.U
        write := io.command.bits.write
        result := Mux(io.command.bits.write, io.command.bits.data, 0.U)
        noAck := false.B
    }
    when(active) {
        when(remaining === (divider - 1).U) {
            remaining := 0.U
            mdc := !mdc
            when(!mdc) {
                when(!write && index === 47.U) { noAck := io.mdioIn }
                when(!write && index >= 48.U) { result := Cat(result(14, 0), io.mdioIn) }
            }.otherwise {
                when(index === 63.U) { active := false.B; reply := true.B }
                    .otherwise { index := index + 1.U; frame := Cat(frame(62, 0), true.B) }
            }
        }.otherwise { remaining := remaining + 1.U }
    }
}
