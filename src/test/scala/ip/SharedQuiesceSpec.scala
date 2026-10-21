package ip

import _root_.circt.stage.ChiselStage
import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.bus.{CdcResetRelease, PeripheralQuiesceAck}
import soc.ip.clock.{ManagedPeripheralSupport, PeripheralWakeDelay}

/** Actual production components, with a raw parent and independently stoppable
  * managed clock supplied by the native FPGA testbench. No modeled synchronizer.
  */
class SharedQuiesceFixture extends RawModule {
    val rawClock = IO(Input(Clock()))
    val managedClock = IO(Input(Clock()))
    val commonReset = IO(Input(AsyncReset()))
    val quiesce = IO(Input(Bool()))
    val isolate = IO(Input(Bool()))
    val active = IO(Input(Bool()))
    val payload = IO(Input(UInt(8.W)))
    val delayed = IO(Output(UInt(8.W)))
    val wake = IO(Output(Bool()))
    val empty = IO(Output(Bool()))
    val ack = IO(Output(Bool()))
    val sharedQuiesce = IO(Output(Bool()))
    val managedRequest = IO(Output(Bool()))
    val release = Module(new CdcResetRelease)
    release.clockIn := rawClock
    release.asyncReset := commonReset
    val shared = ManagedPeripheralSupport.level(quiesce, rawClock, release.resetOut)
    val ingress = Module(new PeripheralWakeDelay(8, 64, synchronousQuiesce = true))
    ingress.rawClock := rawClock
    ingress.commonReset := commonReset
    ingress.payload := payload
    ingress.active := active
    ingress.quiesce := shared
    ingress.isolate := isolate
    val agent = Module(new PeripheralQuiesceAck(synchronousQuiesce = true))
    agent.domainClock := managedClock
    agent.commonReset := commonReset
    agent.quiesce := shared
    agent.idle := ingress.empty
    delayed := ingress.delayed
    wake := ingress.wake
    empty := ingress.empty
    ack := agent.ack
    sharedQuiesce := shared
    managedRequest := agent.stopAdmission
}

class SharedQuiesceSpec extends AnyFunSuite {
    private def moduleBody(fir: String, name: String): String = {
        val modules = "(?m)^[ \\t]*(?:public )?module (\\w+)\\s*:".r.findAllMatchIn(fir).toVector
        val index = modules.indexWhere(_.group(1) == name)
        require(index >= 0, s"missing actual module $name")
        fir.substring(modules(index).end, modules.lift(index + 1).map(_.start).getOrElse(fir.length))
    }

    test("shared raw synchronizer feeds wake and a locally clocked managed pipeline") {
        val fir = ChiselStage.emitCHIRRTL(new SharedQuiesceFixture)
        val agent = moduleBody(fir, "PeripheralQuiesceAck")
        assert(!agent.contains("of CdcLevel"))
        assert(agent.linesIterator.count(_.trim.startsWith("regreset ")) == 3)
        assert(agent.contains("domainClock"))
        val ingress = moduleBody(fir, "PeripheralWakeDelay")
        assert(ingress.linesIterator.count(_.contains("of CdcLevel")) == 1) // isolate only
        assert(fir.contains("agent.quiesce, shared") && fir.contains("ingress.quiesce, shared"))
    }

    test("default asynchronous agent retains its explicit two-stage crossing") {
        val fir = ChiselStage.emitCHIRRTL(new PeripheralQuiesceAck)
        assert(fir.contains("of CdcLevel"))
    }
}

object SharedQuiesceMain extends App {
    require(args.length == 1 && !java.nio.file.Files.exists(java.nio.file.Paths.get(args(0))))
    ChiselStage.emitSystemVerilogFile(new SharedQuiesceFixture,
        Array("--target-dir", args(0)),
        Array("--split-verilog", "--strip-debug-info", "--disable-all-randomization",
            "--lowering-options=disallowLocalVariables,disallowPackedArrays",
            "--default-layer-specialization=enable", "--verification-flavor=if-else-fatal"))
}
