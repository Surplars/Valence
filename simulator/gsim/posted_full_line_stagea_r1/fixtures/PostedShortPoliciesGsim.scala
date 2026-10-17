package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._

/** Focused timeout boundary test. Environmental identity is explicit; no cache/TL. */
class PostedShortPoliciesGsim extends Module {
    val c = PostedStoreMergeConfig(enabled = true, generationBits = 8, epochBits = 8,
        cacheSets = 8, guaranteedBase = 4096, guaranteedBytes = 4096)
    val io = IO(new Bundle {
        val allocate = Input(Bool())
        val allocateSealed = Input(Bool())
        val generation = Input(UInt(8.W))
        val full = Input(Bool())
        val seal = Input(Bool())
        val release = Input(Bool())
        val ready = Input(Bool())
        val valid3 = Output(Bool())
        val valid4 = Output(Bool())
        val kind3 = Output(Bool())
        val kind4 = Output(Bool())
        val age3 = Output(UInt(2.W))
        val age4 = Output(UInt(2.W))
        val open3 = Output(Bool())
        val open4 = Output(Bool())
        val accepted3 = Output(Bool())
        val accepted4 = Output(Bool())
        val generation3 = Output(UInt(8.W))
        val generation4 = Output(UInt(8.W))
    })
    val policies = Seq(3, 4).map(n => Module(new PostedFullLinePolicy(c, n)))
    for (p <- policies) {
        p.io.allocate.valid := io.allocate
        p.io.allocate.bits := 0.U.asTypeOf(p.io.allocate.bits)
        p.io.allocate.bits.context.owner.generation := io.generation
        p.io.allocate.bits.context.cohortRoot.generation := io.generation
        p.io.allocate.bits.context.lineAddress := 4096.U
        p.io.allocateSealed := io.allocateSealed
        p.io.full := io.full
        p.io.seal := io.seal
        p.io.release := io.release
        p.io.decision.ready := io.ready
    }
    Seq(io.valid3, io.valid4).zip(policies).foreach { case (o, p) => o := p.io.decision.valid }
    Seq(io.kind3, io.kind4).zip(policies).foreach { case (o, p) => o := p.io.decision.bits.permissionOnly }
    Seq(io.age3, io.age4).zip(policies).foreach { case (o, p) => o := p.io.age }
    Seq(io.open3, io.open4).zip(policies).foreach { case (o, p) => o := p.io.joinOpen }
    Seq(io.accepted3, io.accepted4).zip(policies).foreach { case (o, p) => o := p.io.accepted }
    Seq(io.generation3, io.generation4).zip(policies).foreach {
        case (o, p) => o := p.io.decision.bits.context.owner.generation
    }
}
object PostedShortPoliciesGsimMain extends App {
    require(args.length == 1)
    ChiselStage.emitCHIRRTLFile(new PostedShortPoliciesGsim, Array("--target-dir", args(0)))
}
