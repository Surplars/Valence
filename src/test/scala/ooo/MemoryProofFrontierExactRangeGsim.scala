package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

class MemoryProofFrontierExactRangeGsim extends Module {
    val p = MemoryProofFrontierExactFixture.profile(true).coreParams
    MemoryProofFrontierExactFixture.validate(p)
    val io = IO(new Bundle {
        val allocate = Input(Valid(new MemoryProofQuery(p)))
        val head = Input(UInt(p.robBits.W))
        val pending = Input(UInt(64.W))
        val memoryLive = Input(UInt(64.W))
        val ordinary = Input(UInt(64.W))
        val stores = Input(UInt(64.W))
        val systems = Input(UInt(64.W))
        val canonicalLoads = Input(UInt(64.W))
        val canonicalStores = Input(UInt(64.W))
        val checkedStore = Input(Valid(new CanonicalStoreCertificate(p)))
        val clearOwners = Input(UInt(64.W))
        val pause = Input(Bool())
        val cancelQueries = Input(Bool())
        val queryEligible = Input(UInt(64.W))
        val selected = Input(Valid(new RobToken(p)))
        val consume = Input(Valid(new RobToken(p)))
        val frontierAccepted = Input(Bool())
        val oldLine = Input(Valid(new MemoryProofLine(p)))
        val warm = Flipped(new DataPort)
        val physical = new DataPort
        val pte = new SvPteReadPort
        val context = Input(new VmCsrState)
        val pmpCfg = Input(UInt(8.W))
        val pmpAddress = Input(UInt(54.W))
        val flush = Input(Bool())
        val queryOwner = Output(Valid(UInt(p.robBits.W)))
        val query = Output(Valid(new VirtualLoadPrecheckRequest))
        val queryHit = Output(Valid(new VirtualLoadPrecheckResponse))
        val selectedProof = Output(Valid(new MemoryAddressProof(p)))
        val selectedBound = Output(Bool())
        val frontier = Output(Valid(new MemoryAddressProof(p)))
        val pendingProof = Output(UInt(64.W))
        val reservedCount = Output(UInt(5.W))
        val allowedCount = Output(UInt(5.W))
        val boundCount = Output(UInt(5.W))
        val epoch = Output(UInt(32.W))
        val stable = Output(Bool())
        val translationWalk = Output(Bool())
        val idle = Output(Bool())
    })
    val owners = Reg(Vec(64, new MemoryProofQuery(p)))
    when(io.allocate.valid) { owners(io.allocate.bits.token.index) := io.allocate.bits }
    val bank = Module(new MemoryProofFrontier(p))
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true))
    val translation = Module(new SvTranslationService(3, 16, 16, loadPeek = true))
    val pmp = MemoryProofFrontierFixture.pmp(io.pmpCfg, io.pmpAddress)
    bank.io.head := io.head
    bank.io.pending := io.pending
    bank.io.memoryLive := io.memoryLive
    bank.io.ordinary := io.ordinary
    bank.io.stores := io.stores
    bank.io.systems := io.systems
    bank.io.canonicalLoads := io.canonicalLoads
    bank.io.canonicalStores := io.canonicalStores
    bank.io.checkedStore := io.checkedStore
    bank.io.clearOwners := io.clearOwners
    bank.io.pause := io.pause
    bank.io.flushQueries := io.cancelQueries || io.flush
    bank.io.queryEligible := io.queryEligible
    bank.io.query := owners(bank.io.queryOwner.bits)
    bank.io.resultToken := owners(bank.io.resultIndex).token
    bank.io.pmpState := pmp
    bank.io.privilege := io.context.dataPrivilege
    bank.io.selected := io.selected
    bank.io.consume := io.consume
    bank.io.frontierAccepted := io.frontierAccepted
    bank.io.liveLines := 0.U.asTypeOf(bank.io.liveLines)
    bank.io.liveLines(0) := io.oldLine
    bank.io.precheck <> adapter.io.loadPrecheck.get
    adapter.io.virtual <> io.warm
    adapter.io.canonicalStoreOrigin.get := 0.U.asTypeOf(adapter.io.canonicalStoreOrigin.get)
    adapter.io.frozenStoreProof.get := 0.U.asTypeOf(adapter.io.frozenStoreProof.get)
    // This bank/permission boundary sends only ordinary virtual warm requests.
    // It has no CPU posted owner; full posted/cache composition is tested separately.
    adapter.io.posted.get.upstreamProof := 0.U.asTypeOf(adapter.io.posted.get.upstreamProof)
    adapter.io.posted.get.externalBusy := false.B
    adapter.io.posted.get.aggregateDrained := adapter.io.idle
    adapter.io.vmState := io.context
    adapter.io.pmpState := pmp
    adapter.io.precheckFlush.get := io.flush
    translation.io.client <> adapter.io.translation
    translation.io.loadPeek.get <> adapter.io.translationPeek.get
    translation.io.pmpState := pmp
    translation.io.flush := io.flush
    io.physical <> adapter.io.physical
    io.pte <> translation.io.memory
    io.queryOwner := bank.io.queryOwner
    io.query := bank.io.precheck.request
    io.queryHit := bank.io.precheck.response
    io.selectedProof := bank.io.selectedProof
    io.selectedBound := bank.io.selectedBound
    io.frontier := bank.io.frontier
    io.pendingProof := bank.io.pendingProof
    io.reservedCount := bank.io.reservedCount
    io.allowedCount := bank.io.allowedCount
    io.boundCount := bank.io.boundCount
    io.epoch := adapter.io.loadPrecheck.get.epoch
    io.stable := adapter.io.loadPrecheck.get.stable
    io.translationWalk := translation.io.walkStart
    io.idle := adapter.io.idle && translation.io.idle
}

object MemoryProofFrontierExactRangeGsimMain extends App {
    require(args.length == 1)
    ChiselStage.emitCHIRRTLFile(new MemoryProofFrontierExactRangeGsim, Array("--target-dir", args.head))
    val profile = MemoryProofFrontierExactFixture.profile(true)
    def quote(text: String): String = "\"" + text.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
    def json(value: Any): String = value match {
        case text: String => quote(text)
        case value: Boolean => value.toString
        case value: Int => value.toString
        case value: Long => value.toString
        case value: BigInt => value.toString
        case value: Option[_] => value.map(json).getOrElse("null")
        case fields: collection.Map[_, _] => fields.toSeq.sortBy(_._1.toString)
            .map { case (key, value) => quote(key.toString) + ":" + json(value) }.mkString("{", ",", "}")
        case values: Seq[_] => values.map(json).mkString("[", ",", "]")
        case product: Product => json(product.productElementNames.zip(product.productIterator).toMap)
        case other => throw new IllegalArgumentException("unhandled range parameter " + other)
    }
    val report = Map[String, Any]("actualBankParameters" -> profile.coreParams,
        "canonicalOptions" -> MemoryProofFrontierExactFixture.canonicalOptions.toSeq.sorted,
        "scope" -> "bank/service/PMP only; no backend, response buffer or cache instantiated",
        "postedScope" -> "no posted owner; ordinary virtual warm requests only",
        "translationEntries" -> 16, "pmpEntries" -> 16)
    java.nio.file.Files.writeString(java.nio.file.Paths.get(args.head, "exact-parameters.json"), json(report) + "\n")
}
