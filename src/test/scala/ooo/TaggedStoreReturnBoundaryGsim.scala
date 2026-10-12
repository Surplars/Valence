package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._
import soc.ip.bus.RegisterPort

/** Small real boundaries, independently driven by the host. No internal state is exposed or forced. */
class TaggedStoreReturnBoundaryGsim(tagged: Boolean = false) extends Module {
    private val p = TaggedStoreReturnBoundaryChecks.params(tagged)
    private val standard = CpuReturnConfig(4, 2, fpEnabled = true)
    private val largest = CpuReturnConfig(8, 8, fpEnabled = true)
    val io = IO(new Bundle {
        val store = Flipped(new DataPort(p.dataReturnHandleBits))
        val storeMemory = new DataPort(p.dataReturnHandleBits)
        val storeBusy = Output(Bool())
        val storeForwarded = Output(Bool())
        val route = Flipped(new DataPort(p.dataReturnHandleBits))
        val routeMemory = new DataPort(p.dataReturnHandleBits)
        val registers = new RegisterPort
        val taggedEnabled = Output(Bool())
        val namespaceHandle = Input(UInt(5.W))
        val namespaceSlot = Input(UInt(3.W))
        val standardInteger = Output(Bool())
        val standardStore = Output(Bool())
        val standardLegal = Output(Bool())
        val standardStoreHandle = Output(UInt(3.W))
        val largestInteger = Output(Bool())
        val largestStore = Output(Bool())
        val largestLegal = Output(Bool())
        val largestStoreHandle = Output(UInt(5.W))
    })
    val buffer = Module(new StoreBuffer(p))
    buffer.io.upstream <> io.store
    io.storeMemory <> buffer.io.memory
    buffer.io.fastStore.valid := false.B
    buffer.io.fastStore.bits := 0.U.asTypeOf(buffer.io.fastStore.bits)
    io.storeBusy := buffer.io.busy
    io.storeForwarded := buffer.io.forwarded

    val router = Module(new ParallelRegisterRouter(
        Seq((BigInt(8192), BigInt(16))), capacity = 4,
        bypassMemoryShift = true, returnConfig = p.cpuReturnConfig))
    router.io.upstream <> io.route
    io.routeMemory <> router.io.memory
    io.registers <> router.io.registers(0)

    io.taggedEnabled := tagged.B
    io.standardInteger := standard.integer(io.namespaceHandle)
    io.standardStore := standard.store(io.namespaceHandle)
    io.standardLegal := standard.legal(io.namespaceHandle)
    io.standardStoreHandle := standard.storeHandle(io.namespaceSlot(0, 0))
    io.largestInteger := largest.integer(io.namespaceHandle)
    io.largestStore := largest.store(io.namespaceHandle)
    io.largestLegal := largest.legal(io.namespaceHandle)
    io.largestStoreHandle := largest.storeHandle(io.namespaceSlot)
}

/** Exact namespace sizes and the public configuration contract, independent of generated RTL. */
object TaggedStoreReturnBoundaryChecks {
    def params(tagged: Boolean): OooParams = OooParams(
        memoryEntries = 2,
        storeBufferEntries = 1,
        bufferedRamStores = true,
        registeredLocalStoreResponses = true,
        registeredMemoryRequests = true,
        registeredStoreResponseOwners = true,
        taggedStoreReturns = tagged,
        machineSystem = true,
        floatingPoint = FloatingPointConfig.fullF,
        speculativeRamBase = 4096,
        speculativeRamBytes = 256
    )

    private def rejected(label: String)(construct: => Any): Unit = {
        val fails = try { construct; false } catch { case _: IllegalArgumentException => true }
        require(fails, s"configuration unexpectedly accepted: $label")
    }

    def verify(): Unit = {
        val small = params(tagged = true)
        val standard = CpuReturnConfig(4, 2, fpEnabled = true)
        val noFp = CpuReturnConfig(4, 2, fpEnabled = false)
        val larger = CpuReturnConfig(8, 4, fpEnabled = true)
        val largest = small.copy(memoryEntries = 8, storeBufferEntries = 8).cpuReturnConfig.get
        require(small.cpuReturnConfig.get == CpuReturnConfig(2, 1, fpEnabled = true))
        require(small.dataReturnHandleBits == 2 && small.cpuReturnConfig.get.tableEntries == 4)
        require(standard.handleCount == 7 && standard.handleBits == 3 &&
            standard.tableEntries == 8 && standard.fpHandle == 6)
        require(noFp.handleCount == 6 && noFp.handleBits == 3 && noFp.tableEntries == 8)
        require(larger.handleCount == 13 && larger.handleBits == 4 &&
            larger.tableEntries == 16 && larger.fpHandle == 12)
        require(largest.handleCount == 17 && largest.handleBits == 5 &&
            largest.tableEntries == 32 && largest.fpHandle == 16)
        require(!OooParams().taggedStoreReturns && OooParams().cpuReturnConfig.isEmpty)
        require(params(tagged = false).cpuReturnConfig.isEmpty && params(tagged = false).dataReturnHandleBits == 0)
        rejected("zero integer namespace") { CpuReturnConfig(0, 1, fpEnabled = false) }
        rejected("zero store namespace") { CpuReturnConfig(1, 0, fpEnabled = false) }
        rejected("unbuffered stores") { small.copy(bufferedRamStores = false) }
        rejected("unregistered requests") { small.copy(registeredMemoryRequests = false) }
        rejected("unregistered owners") { small.copy(registeredStoreResponseOwners = false) }
        rejected("fast store retirement") { small.copy(fastBufferedStoreRetire = true) }
        rejected("fast load retirement") { small.copy(fastHeadLoadRetire = true) }
        rejected("nine integer slots") { small.copy(memoryEntries = 9) }
        rejected("three store slots") { small.copy(storeBufferEntries = 3) }
    }
}

object TaggedStoreReturnNamespaceCheckMain extends App {
    TaggedStoreReturnBoundaryChecks.verify()
    println("TAGGED_RETURN_NAMESPACE_PASS small=4/2/4 standard=7/3/8 larger=13/4/16 largest=17/5/32")
}

object TaggedStoreReturnBoundaryGsimMain extends App {
    require(args.nonEmpty, "target directory required")
    TaggedStoreReturnBoundaryChecks.verify()
    ChiselStage.emitCHIRRTLFile(new TaggedStoreReturnBoundaryGsim(args.drop(1).contains("tagged")),
        Array("--target-dir", args.head))
}
