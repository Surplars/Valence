package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._
import soc.platform.CommonA1RebuildProfile

/** Standalone boundary, not a reduced CPU configuration or a second FIFO implementation.
  * The host owns its accepted-descriptor ledger and checks every represented bit.
  * Capacity 8; non-flow latency 1; steady II 1; full pop does not lend enqueue credit.
  */
class M2TranslationBufferGsim extends Module {
    val p = CommonA1RebuildProfile.FullCandidate.config.coreParams
    require(p.renameWidth == 2 && p.completionWidth == 2 && p.commitWidth == 2 && p.fpEnabled && p.fpConfig.d,
        "M2 uses the unchanged complete two-issue FullCandidate parameters, including F/D")
    require(p.canonicalVirtualStoreOverlap && p.robBits == 4 && p.tagBits == 64 &&
        p.dataReturnHandleBits == 0 && p.postedProofConfig.isEmpty && !p.frozenStoreProofEnabled,
        "update the host's complete flat descriptor ABI if FullCandidate optional fields change")

    val io = IO(new Bundle {
        val inValid = Input(Bool())
        val inReady = Output(Bool())
        val outValid = Output(Bool())
        val outReady = Input(Bool())
        val count = Output(UInt(4.W))

        val inAtomic = Input(Bool())
        val inAtomicOp = Input(UInt(5.W))
        val inAddress = Input(UInt(64.W))
        val inWrite = Input(Bool())
        val inSize = Input(UInt(2.W))
        val inData = Input(UInt(64.W))
        val inMask = Input(UInt(8.W))
        val inVirtualized = Input(Bool())
        val inPrecheckedLoad = Input(Bool())
        val inTranslationEpoch = Input(UInt(32.W))
        val inPrefetchNextAllowed = Input(Bool())
        val inUncached = Input(Bool())
        val inCanonicalValid = Input(Bool())
        val inCanonicalIndex = Input(UInt(p.robBits.W))
        val inCanonicalTag = Input(UInt(p.tagBits.W))
        val inCanonicalEpoch = Input(UInt(32.W))
        val inOriginalVirtualAddress = Input(UInt(64.W))
        val inPrivilege = Input(UInt(2.W))
        val inCheckPhysical = Input(Bool())
        val inPageFault = Input(Bool())
        val inAccessFault = Input(Bool())

        val outAtomic = Output(Bool())
        val outAtomicOp = Output(UInt(5.W))
        val outAddress = Output(UInt(64.W))
        val outWrite = Output(Bool())
        val outSize = Output(UInt(2.W))
        val outData = Output(UInt(64.W))
        val outMask = Output(UInt(8.W))
        val outVirtualized = Output(Bool())
        val outPrecheckedLoad = Output(Bool())
        val outTranslationEpoch = Output(UInt(32.W))
        val outPrefetchNextAllowed = Output(Bool())
        val outUncached = Output(Bool())
        val outCanonicalValid = Output(Bool())
        val outCanonicalIndex = Output(UInt(p.robBits.W))
        val outCanonicalTag = Output(UInt(p.tagBits.W))
        val outCanonicalEpoch = Output(UInt(32.W))
        val outOriginalVirtualAddress = Output(UInt(64.W))
        val outPrivilege = Output(UInt(2.W))
        val outCheckPhysical = Output(Bool())
        val outPageFault = Output(Bool())
        val outAccessFault = Output(Bool())
    })

    val buffer = Module(new DataTranslationResultBuffer(p, entries = 8))
    require(buffer.io.enq.bits.getWidth == 351,
        "the 21-field host ABI must account for every FullCandidate descriptor bit")
    buffer.io.enq.valid := io.inValid
    io.inReady := buffer.io.enq.ready
    io.outValid := buffer.io.deq.valid
    buffer.io.deq.ready := io.outReady
    io.count := buffer.io.count

    val incoming = buffer.io.enq.bits
    incoming.request.atomic := io.inAtomic
    incoming.request.atomicOp := io.inAtomicOp
    incoming.request.address := io.inAddress
    incoming.request.write := io.inWrite
    incoming.request.size := io.inSize
    incoming.request.data := io.inData
    incoming.request.mask := io.inMask
    incoming.request.virtualized := io.inVirtualized
    incoming.request.precheckedLoad := io.inPrecheckedLoad
    incoming.request.translationEpoch := io.inTranslationEpoch
    incoming.request.prefetchNextAllowed := io.inPrefetchNextAllowed
    incoming.request.uncached := io.inUncached
    incoming.canonicalStoreOrigin.get.valid := io.inCanonicalValid
    incoming.canonicalStoreOrigin.get.bits.token.index := io.inCanonicalIndex
    incoming.canonicalStoreOrigin.get.bits.token.tag := io.inCanonicalTag
    incoming.canonicalStoreOrigin.get.bits.epoch := io.inCanonicalEpoch
    incoming.originalVirtualAddress.get := io.inOriginalVirtualAddress
    incoming.privilege := io.inPrivilege
    incoming.checkPhysical := io.inCheckPhysical
    incoming.pageFault := io.inPageFault
    incoming.accessFault := io.inAccessFault

    val outgoing = buffer.io.deq.bits
    io.outAtomic := outgoing.request.atomic
    io.outAtomicOp := outgoing.request.atomicOp
    io.outAddress := outgoing.request.address
    io.outWrite := outgoing.request.write
    io.outSize := outgoing.request.size
    io.outData := outgoing.request.data
    io.outMask := outgoing.request.mask
    io.outVirtualized := outgoing.request.virtualized
    io.outPrecheckedLoad := outgoing.request.precheckedLoad
    io.outTranslationEpoch := outgoing.request.translationEpoch
    io.outPrefetchNextAllowed := outgoing.request.prefetchNextAllowed
    io.outUncached := outgoing.request.uncached
    io.outCanonicalValid := outgoing.canonicalStoreOrigin.get.valid
    io.outCanonicalIndex := outgoing.canonicalStoreOrigin.get.bits.token.index
    io.outCanonicalTag := outgoing.canonicalStoreOrigin.get.bits.token.tag
    io.outCanonicalEpoch := outgoing.canonicalStoreOrigin.get.bits.epoch
    io.outOriginalVirtualAddress := outgoing.originalVirtualAddress.get
    io.outPrivilege := outgoing.privilege
    io.outCheckPhysical := outgoing.checkPhysical
    io.outPageFault := outgoing.pageFault
    io.outAccessFault := outgoing.accessFault
}

object M2TranslationBufferGsimMain extends App {
    require(args.length == 1, "usage: M2TranslationBufferGsimMain <target-dir>")
    ChiselStage.emitCHIRRTLFile(new M2TranslationBufferGsim, Array("--target-dir", args.head))
}
