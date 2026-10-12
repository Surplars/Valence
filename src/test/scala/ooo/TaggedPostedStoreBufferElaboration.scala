package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths, StandardOpenOption}
import soc.core.ooo._

/** Elaborate the real optional posted StoreBuffer branches with and without tags.
  * This is a type/connection regression check, not a behavioral or authority proof.
  */
object TaggedPostedStoreBufferElaborationMain extends App {
    require(args.length == 1, "fresh output directory required")
    val directory = Paths.get(args.head)
    Files.createDirectories(directory)
    for (tagged <- Seq(false, true)) {
        val p = OooParams(memoryEntries = 4, storeBufferEntries = 2,
            bufferedRamStores = true, registeredMemoryRequests = true,
            registeredStoreResponseOwners = true, registeredLocalStoreResponses = true,
            taggedStoreReturns = tagged, postedStoreMerge = true,
            machineSystem = true, floatingPoint = FloatingPointConfig.fullF,
            pmpEntries = 16, virtualMemoryLevels = 3,
            speculativeRamBase = 4096, speculativeRamBytes = 4096)
        require(p.postedProofConfig.nonEmpty)
        require(p.cpuReturnConfig == (if (tagged) Some(CpuReturnConfig(4, 2, fpEnabled = true)) else None))
        // Direct elaboration executes the optional memoryProof/fastStore payload
        // mux construction, including the formerly mismatched tagged operand.
        val fir = ChiselStage.emitCHIRRTL(new StoreBuffer(p))
        val io = fir.linesIterator.dropWhile(line => !line.startsWith("  module StoreBuffer :") &&
            !line.startsWith("  public module StoreBuffer :")).find(_.startsWith("    output io :")).getOrElse(
            throw new IllegalStateException("missing actual StoreBuffer IO"))
        Seq("upstreamProof :", "fastProof :", "memoryProof :", "postedCompleted :", "externalPostedBusy :")
            .foreach(field => require(io.contains(field), s"posted branch absent: $field"))
        require(io.contains("returnHandle : UInt<3>") == tagged, "wrong actual tagged 4/2/FP port shape")
        require(fir.contains("legacyPostedAccepted") && fir.contains("finalChecked"), "posted proof payload absent")
        Files.writeString(directory.resolve(s"StoreBuffer-posted-tagged${if (tagged) 1 else 0}.fir"), fir,
            StandardOpenOption.CREATE_NEW)
    }
    println("TAGGED_POSTED_STORE_BUFFER_ELABORATION_PASS models=2 namespace=4/2/FP")
}
