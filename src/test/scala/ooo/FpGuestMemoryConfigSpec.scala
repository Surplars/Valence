package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._

/** Structural preparation checks only; response/context ownership is checked in GSIM. */
private class FpGuestMemoryTransportConfig(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val memoryCompletion = Input(new BackendCompletion(p))
        val fpResult = Input(new FloatingPointResult(p))
        val nextPc = Input(UInt(64.W))
        val memoryResult = Output(new FloatingPointResult(p))
        val completion = Output(new BackendCompletion(p))
        val effectivePrivilege = Input(UInt(2.W))
        val hostSatp = Input(UInt(64.W))
        val guestAddress = Input(Bool())
        val translated = Output(Bool())
    })
    io.memoryResult := FloatingPointResultTransport.fromMemory(p, io.memoryCompletion)
    io.completion := FloatingPointResultTransport.toBackend(p, io.fpResult, io.nextPc)
    io.translated := FloatingPointMemoryContext.translated(p.virtualMemoryLevels,
        io.effectivePrivilege, io.hostSatp, io.guestAddress)
}

class FpGuestMemoryConfigSpec extends AnyFunSuite {
    private val host = OooParams(machineSystem = true, virtualMemoryLevels = 3, pmpEntries = 16,
        floatingPoint = FloatingPointConfig.fullFD)
    private val guest = host.copy(hypervisorExperiment = true)
    private val nativeFields = Set("data", "error", "pageFault")
    private val resultFields = Set("token", "value", "flags", "exception", "cause", "tval")
    private val memoryPorts = Set("execute", "pc", "trap", "complete", "memory", "busy", "pmpState",
        "dataPrivilege", "virtualized")
    private val modes = Seq((false, false, false), (true, false, false),
        (true, true, false), (true, true, true))

    test("memory transport preparation changes no default profile or ISA advertisement") {
        for (p <- Seq(OooParams(), BoardSocConfig.timingParams(BoardSocConfig.timingProfile),
            BoardSocConfig.boardParams(BoardSocConfig.timingProfile))) {
            assert(!p.hypervisorExperiment && !p.fpEnabled && !p.basicCounters)
            assert(!p.misaValue.testBit(7) && !p.misaValue.testBit(5) && !p.misaValue.testBit(3))
            assert(p.issueWidth == 2)
        }
        assert(guest.fpConfig == FloatingPointConfig.fullFD && guest.fpConfig.complete)
        assert(guest.fpConfig.resources == FloatingPointResourceConfig.baseline)
        assert(!guest.advertiseFloatingPoint && !guest.misaValue.testBit(7))
        assert(guest.misaValue == host.misaValue && guest.advertisedIsa == host.advertisedIsa)
    }

    test("all four buffer modes use one native-shaped response envelope with optional provenance and handles") {
        for ((payload, head, flow) <- modes; metadata <- Seq(false, true); tagged <- Seq(false, true)) {
            val config = if (tagged) Some(CpuReturnConfig(32, 31, fpEnabled = true)) else None
            val responseFields = nativeFields ++ (if (tagged) Set("returnHandle") else Set.empty[String])
            val extraPorts = if (metadata) Set("downstreamGuestFault", "upstreamGuestFault") else Set.empty[String]
            val fir = ChiselStage.emitCHIRRTL {
                val buffer = new DataResponseBuffer(registerPayload = payload, registerHead = head,
                    emptyFlow = flow, returnConfig = config, guestFaultMetadata = metadata)
                assert(buffer.io.elements.keySet == Set("upstream", "downstream", "idle") ++ extraPorts)
                assert(buffer.io.upstream.response.bits.elements.keySet == responseFields)
                assert(buffer.io.downstream.response.bits.elements.keySet == responseFields)
                assert(buffer.responses.enq.bits.elements.keySet == responseFields ++
                    (if (metadata) Set("guestFault") else Set.empty[String]))
                assert(buffer.responses.enq.bits.guestFault.isDefined == metadata)
                assert(buffer.io.downstreamGuestFault.isDefined == metadata)
                assert(buffer.io.upstreamGuestFault.isDefined == metadata)
                buffer.responses.enq.bits.returnHandle.foreach(handle => assert(handle.getWidth == 6))
                buffer
            }
            // Generated instance names are not a contract. Require exactly one
            // child instance, of the selected two-entry queue type.
            val instanceTypes = "(?m)^\\s*inst \\S+ of (\\S+)".r.findAllMatchIn(fir).map(_.group(1)).toSeq
            val queueType = if (head) "TwoEntryRegisterQueue" else "Queue2_OwnedDataResponse"
            assert(instanceTypes.size == 1 && instanceTypes.head.matches(s"${queueType}(?:_[0-9]+)?"))
            assert(fir.contains("guestFault") == metadata)
        }
    }

    test("result helpers preserve optional envelope shape without storage") {
        for (p <- Seq(host, guest)) {
            val fir = ChiselStage.emitCHIRRTL {
                val transport = new FpGuestMemoryTransportConfig(p)
                assert(transport.io.fpResult.elements.keySet == resultFields ++
                    (if (p.hypervisorExperiment) Set("guestFault") else Set.empty[String]))
                assert(transport.io.memoryResult.guestFault.isDefined == p.hypervisorExperiment)
                assert(transport.io.completion.guestFault.isDefined == p.hypervisorExperiment)
                transport
            }
            assert(!fir.linesIterator.exists(line => line.trim.startsWith("reg ") ||
                line.trim.startsWith("regreset ") || line.trim.startsWith("inst ")))
        }
    }

    test("memory accepts optional guest context and queues its complete response metadata") {
        for (p <- Seq(host, guest)) {
            ChiselStage.emitCHIRRTL {
                val memory = new FloatingPointMemoryPipeline(p)
                assert(memory.io.elements.keySet == memoryPorts ++
                    (if (p.hypervisorExperiment) Set("guestAddress", "guestFault") else Set.empty[String]))
                assert(memory.io.guestAddress.isDefined == p.hypervisorExperiment)
                assert(memory.lsu.io.guestFault.isDefined == p.hypervisorExperiment)
                assert(memory.responses.responses.enq.bits.guestFault.isDefined == p.hypervisorExperiment)
                memory
            }
        }
    }

    test("standalone add producer initializes the optional result envelope") {
        for (p <- Seq(host, guest)) {
            ChiselStage.emitCHIRRTL {
                val add = new FloatingPointAdd(p)
                assert(add.io.result.bits.guestFault.isDefined == p.hypervisorExperiment)
                assert(add.result.guestFault.isDefined == p.hypervisorExperiment)
                add
            }
        }
    }

    test("both actual H plus FP integration guards remain enforced") {
        for (p <- Seq(guest, guest.copy(floatingPoint = FloatingPointConfig.fullF),
            guest.copy(floatingPoint = FloatingPointConfig.disabled, experimentalFloatingPoint = true))) {
            val systemError = intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new MachineSystemUnit(p, experimentalHypervisor = true))
            }
            assert(systemError.getMessage.contains("guest FP state is not yet integrated"))
            val backendError = intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new IntegerBackend(p, experimentalHypervisor = true))
            }
            assert(backendError.getMessage.contains(
                "experimental H uses owner-carried translated memory without host-only proofs"))
        }
    }
}
