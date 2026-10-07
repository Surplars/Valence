package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo.TimingArithmetic
import soc.ip.axi.RegisterAxiLite

class TimingArithmeticGsim extends Module {
    val io = IO(new Bundle {
        val a = Input(UInt(64.W))
        val b = Input(UInt(64.W))
        val sum = Output(UInt(64.W))
        val le = Output(Bool())
        val le63 = Output(Bool())
        val word0 = Output(UInt(63.W))
        val word1 = Output(UInt(63.W))
        val word2 = Output(UInt(63.W))
        val word4 = Output(UInt(63.W))
        val word255 = Output(UInt(63.W))
        val byte255 = Output(UInt(9.W))
    })
    io.sum := TimingArithmetic.add64(io.a, io.b)
    io.le := TimingArithmetic.lessOrEqual(io.a, io.b)
    io.le63 := TimingArithmetic.lessOrEqual(io.a(62, 0), io.b(62, 0))
    io.word0 := TimingArithmetic.addSmallConstantExtended(io.a(61, 0), 0)
    io.word1 := TimingArithmetic.addSmallConstantExtended(io.a(61, 0), 1)
    io.word2 := TimingArithmetic.addSmallConstantExtended(io.a(61, 0), 2)
    io.word4 := TimingArithmetic.addSmallConstantExtended(io.a(61, 0), 4)
    io.word255 := TimingArithmetic.addSmallConstantExtended(io.a(61, 0), 255)
    io.byte255 := TimingArithmetic.addSmallConstantExtended(io.a(7, 0), 255)
}
object TimingArithmeticGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new TimingArithmeticGsim, Array("--target-dir", args.head))
}
class RegisterAxiLiteGsim extends Module {
    val adapter = Module(new RegisterAxiLite(BigInt("10040000", 16), 0x40000))
    val io = IO(chiselTypeOf(adapter.io))
    io <> adapter.io
}
object RegisterAxiLiteGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new RegisterAxiLiteGsim, Array("--target-dir", args.head))
}

class EthernetResetHoldGsim extends Module {
    val io = IO(new Bundle {
        val macIrq = Input(Bool())
        val bufferIrq = Input(Bool())
        val irq = Output(Bool())
        val held = Output(Bool())
    })
    // Single-clock synchronous count/IRQ check. Async assertion is checked in xsim.
    val hold = Module(new soc.ip.bus.ResetHold(7))
    io.held := hold.io.asserted
    io.irq := RegNext(io.macIrq || io.bufferIrq, false.B)
}
object EthernetResetHoldGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new EthernetResetHoldGsim, Array("--target-dir", args.head))
}
