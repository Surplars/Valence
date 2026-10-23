package ip.vector

import _root_.circt.stage.ChiselStage
import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import soc.ip.vector._

class VectorAttachmentWireFixture(p: VectorAttachmentConfig) extends RawModule {
    val cpu = IO(Flipped(new VectorAttachmentPort(p)))
    val vpu = IO(new VectorAttachmentPort(p))
    vpu <> cpu
    require(cpu.command.bits.token.getWidth == p.ownerBits + p.epochBits)
    require(cpu.memoryRequest.bits.token.getWidth == cpu.command.bits.token.getWidth)
    require(cpu.complete.bits.token.getWidth == cpu.command.bits.token.getWidth)
}

/** Independent executable contract examples, NOT a model of implemented RTL.
  * No vector datapath is implemented. These cases pin the future adapter rules.
  */
private class SerialVectorContract {
    private var offered = Option.empty[(Int, Int)]
    private var active = Option.empty[(Int, Int)]
    private var memoryPending = false
    private var completionHeld = false
    var quiesce = false
    def drained: Boolean = offered.isEmpty && active.isEmpty && !memoryPending && !completionHeld
    def offer(token: (Int, Int)): Unit = {
        require(!quiesce && drained)
        offered = Some(token)
    }
    def accept(): Unit = {
        require(offered.nonEmpty && active.isEmpty)
        active = offered
        offered = None
    }
    def memoryIssue(): Unit = {
        require(active.nonEmpty && !memoryPending && !completionHeld)
        memoryPending = true
    }
    def memoryReply(token: (Int, Int)): Unit = {
        require(active.contains(token) && memoryPending)
        memoryPending = false
    }
    def complete(token: (Int, Int), exception: Boolean = false,
        scalarWrite: Boolean = false, vstart: Int = 0): Unit = {
        require(active.contains(token) && !memoryPending && !completionHeld)
        require(!exception || !scalarWrite)
        require(exception || vstart == 0)
        completionHeld = true
    }
    def retire(): Unit = {
        require(completionHeld)
        completionHeld = false
        active = None
    }
}

class VectorAttachmentSpec extends AnyFunSuite {
    test("reservation is disabled and cannot advertise or enable V") {
        val p = VectorAttachmentConfig()
        assert(!p.enabled && !p.advertisesV)
        assert(p.vlenBytes == 16 && p.xlen == 64)
        assert(p.maxCommands == 1 && p.maxMemoryRequests == 1)
        intercept[IllegalArgumentException] { VectorAttachmentConfig(enabled = true) }
    }
    test("reject invalid storage, transport and ownership dimensions") {
        Seq(0, 64, 192, 131072).foreach { n =>
            intercept[IllegalArgumentException] { VectorAttachmentConfig(vlen = n) }
        }
        Seq(0, 4, 24, 128).foreach { n =>
            intercept[IllegalArgumentException] { VectorAttachmentConfig(elen = n) }
        }
        intercept[IllegalArgumentException] { VectorAttachmentConfig(ownerBits = 1) }
        intercept[IllegalArgumentException] { VectorAttachmentConfig(epochBits = 1) }
        intercept[IllegalArgumentException] { VectorAttachmentConfig(ownerBits = 65) }
        intercept[IllegalArgumentException] { VectorAttachmentConfig(epochBits = 65) }
    }
    test("boundary elaborates with complete identities, precise faults and drain") {
        Seq(VectorAttachmentConfig(), VectorAttachmentConfig(vlen = 65536, ownerBits = 32, epochBits = 16))
            .foreach { p =>
                val fir = ChiselStage.emitCHIRRTL(new VectorAttachmentWireFixture(p))
                Seq("token", "epoch", "vstart", "vtype", "fpFlags", "exception", "tval", "quiesce", "drained")
                    .foreach(name => assert(fir.contains(name)))
                assert(!fir.contains("reg ") && !fir.contains("mem "))
            }
    }
    test("absent endpoint has no state and never accepts or emits work") {
        val fir = ChiselStage.emitCHIRRTL(new DisabledVectorAttachment())
        Seq("command.ready", "complete.valid", "memoryRequest.valid", "memoryResponse.ready").foreach { name =>
            assert(fir.contains(s"connect io.$name, UInt<1>(0h0)"))
        }
        assert(fir.contains("connect io.drained, UInt<1>(0h1)"))
        assert(!fir.contains("reg ") && !fir.contains("mem "))
    }
    test("native owner and epoch mappings must not truncate identity") {
        val p = VectorAttachmentConfig()
        p.requireIdentityCapacity(16, 8)
        intercept[IllegalArgumentException] { p.requireIdentityCapacity(17, 8) }
        intercept[IllegalArgumentException] { p.requireIdentityCapacity(16, 9) }
        intercept[IllegalArgumentException] { p.requireIdentityCapacity(0, 8) }
    }
    test("contract rejects stale completions, premature drain and active owner reuse") {
        val m = new SerialVectorContract
        val token = (7, 3)
        m.offer(token)
        m.accept()
        m.memoryIssue()
        intercept[IllegalArgumentException] { m.offer(token) }
        intercept[IllegalArgumentException] { m.complete(token) }
        intercept[IllegalArgumentException] { m.memoryReply((7, 2)) }
        assert(!m.drained)
        m.memoryReply(token)
        intercept[IllegalArgumentException] { m.complete((6, 3)) }
        intercept[IllegalArgumentException] { m.complete((7, 2)) }
        m.complete(token)
        assert(!m.drained) // a held completion remains an owner
        intercept[IllegalArgumentException] { m.complete(token) }
        m.retire()
        assert(m.drained)
        intercept[IllegalArgumentException] { m.complete(token) }
    }
    test("quiesce preserves a held offer and permits completion drain without deadlock") {
        val m = new SerialVectorContract
        m.offer((1, 0))
        m.quiesce = true
        assert(!m.drained)
        m.accept() // already-offered command remains admissible under quiesce
        assert(!m.drained)
        m.complete((1, 0))
        assert(!m.drained)
        m.retire()
        assert(m.drained)
        intercept[IllegalArgumentException] { m.offer((2, 0)) }
    }

    test("precise trap retains its restart prefix and rejects scalar writeback") {
        val m = new SerialVectorContract
        m.offer((2, 1))
        m.accept()
        intercept[IllegalArgumentException] { m.complete((2, 1), exception = true, scalarWrite = true) }
        intercept[IllegalArgumentException] { m.complete((2, 1), vstart = 4) }
        m.complete((2, 1), exception = true, vstart = 4)
        assert(!m.drained)
        m.retire() // CPU accepts the trap and prefix state, not ordinary successful retirement
        assert(m.drained)
    }

}
