package platform

import _root_.circt.stage.ChiselStage
import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import soc.platform._
import soc.ip.memory._

class NativeWireShapeFixture extends Module {
    val io = IO(new Bundle {
        val shared = Input(new NativeMemoryRequest)
        val i1 = Output(new soc.core.inorder.I1DataRequest)
        val a1 = Output(new soc.core.ooo.DataRequest)
        val sharedReply = Input(new NativeMemoryResponse)
        val i1Reply = Output(new soc.core.inorder.I1DataResponse)
        val a1Reply = Output(new soc.core.ooo.DataResponse)
    })
    require(io.shared.getWidth == 181 && io.sharedReply.getWidth == 66)
    require(io.i1.getWidth == io.shared.getWidth && io.a1.getWidth == io.shared.getWidth)
    require(io.i1Reply.getWidth == io.sharedReply.getWidth && io.a1Reply.getWidth == io.sharedReply.getWidth)
    io.i1 := io.shared.asTypeOf(io.i1)
    io.a1 := io.shared.asTypeOf(io.a1)
    io.i1Reply := io.sharedReply.asTypeOf(io.i1Reply)
    io.a1Reply := io.sharedReply.asTypeOf(io.a1Reply)
}
class CommonTilePortFixture(p: CommonCpuTilePortParams) extends RawModule {
    val cpu = IO(Flipped(new CommonCpuTilePort(p)))
    val fabric = IO(new CommonCpuTilePort(p))
    fabric <> cpu
}
class CommonPlatformBoundarySpec extends AnyFunSuite {
    test("I1 and A1 retain exactly the original native request and response widths") {
        val fir = ChiselStage.emitCHIRRTL(new NativeWireShapeFixture)
        assert(fir.contains("translationEpoch") && fir.contains("atomicOp"))
        assert(fir.contains("pageFault"))
    }
    test("the shared interrupt block contains exactly two APLICs and one MSI arbiter") {
        val fir = ChiselStage.emitCHIRRTL(new CommonInterruptFabric)
        assert(fir.linesIterator.count(_.contains(" of Aplic")) == 2)
        assert(fir.linesIterator.count(_.contains(" of TwoMasterRegisterArbiter")) == 1)
        assert(!fir.contains(" of Imsic"))
    }
    test("the CPU boundary retains both coherent clients and separate whole-line returns") {
        val fir = ChiselStage.emitCHIRRTL(new CommonTilePortFixture(CommonCpuTilePortParams()))
        assert(fir.contains("instructionFetch") && fir.contains("lineGrant") && fir.contains("UInt<512>"))
        assert(fir.contains("needsCoherenceLookup") && fir.contains("clearReservation"))
        assert(fir.contains("fabricDrainedEpoch") && fir.contains("privateOwnersDrained"))
        assert(fir.contains("msi") && fir.contains("timeSnapshot"))
        assert(CommonCpuTilePortParams().instruction.sourceBits == 4)
    }
    test("the contract rejects singleton owners and insufficient sink capacity") {
        intercept[IllegalArgumentException] { CommonCpuTilePortParams(homeAcquireEntries = 1) }
        intercept[IllegalArgumentException] { CommonCpuTilePortParams(homeWritebackEntries = 1) }
        intercept[IllegalArgumentException] { CommonCpuTilePortParams(homeAcquireEntries = 4) }
        intercept[IllegalArgumentException] { CommonCpuTilePortParams(scalarOwnerBits = 1) }
    }
}
