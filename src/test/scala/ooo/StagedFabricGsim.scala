package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._
import soc.ip.bus.RegisterPort

class StagedFabricGsim(bypassMemoryShift: Boolean = false, registerHead: Boolean = false) extends Module {
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val reg0 = new RegisterPort
        val reg1 = new RegisterPort
        val reg2 = new RegisterPort
        val memory = new DataPort
        val requestCpu = Input(Bool())
        val memoryCpu = Output(Bool())
    })
    val router = Module(new ParallelRegisterRouter(Seq(
        (BigInt("02000000", 16), BigInt(65536)),
        (BigInt("10000000", 16), BigInt(8)),
        (BigInt("10001000", 16), BigInt(40))
    ), bypassMemoryShift = bypassMemoryShift))
    val buffer = Module(new DataRequestBuffer(registerHead = registerHead))
    router.io.upstream <> io.upstream
    io.reg0 <> router.io.registers(0)
    io.reg1 <> router.io.registers(1)
    io.reg2 <> router.io.registers(2)
    buffer.io.upstream <> router.io.memory
    io.memory <> buffer.io.downstream
    buffer.io.requestCpu := io.requestCpu
    io.memoryCpu := buffer.io.downstreamRequestCpu
}

object StagedFabricGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new StagedFabricGsim(args.drop(1).contains("direct-memory-response"),
        args.drop(1).contains("register-head")),
        Array("--target-dir", args.head))
}
