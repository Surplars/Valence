package soc.core.ooo

import chisel3._
import chisel3.util._

class RobToken(p: OooParams) extends Bundle {
    val index = UInt(p.robBits.W)
    val tag   = UInt(p.tagBits.W)
}

/** Architectural register identities, without values or old pipeline control. */
class RenameRequest extends Bundle {
    val pc          = UInt(64.W)
    val instruction = UInt(32.W)
    val rs1         = UInt(5.W)
    val rs2         = UInt(5.W)
    val rd          = UInt(5.W)
    val writesRd    = Bool()
}

class RenamedInstruction(p: OooParams) extends Bundle {
    val token          = new RobToken(p)
    val source1        = UInt(p.physBits.W)
    val source2        = UInt(p.physBits.W)
    val destination    = UInt(p.physBits.W)
    val oldDestination = UInt(p.physBits.W)
    val writesRd       = Bool()
    val moveAlias      = Bool()
}

class BackendCompletion(p: OooParams) extends Bundle {
    val token     = new RobToken(p)
    val data      = UInt(64.W)
    val nextPc    = UInt(64.W)
    val exception = Bool()
    val cause     = UInt(64.W)
    val tval      = UInt(64.W)
}

class CommitRecord(p: OooParams) extends Bundle {
    val token       = new RobToken(p)
    val pc          = UInt(64.W)
    val instruction = UInt(32.W)
    val rd          = UInt(5.W)
    val destination = UInt(p.physBits.W)
    val writesRd    = Bool()
    val data        = UInt(64.W)
    val nextPc      = UInt(64.W)
}

class FrontendRedirect(p: OooParams) extends Bundle {
    val token  = new RobToken(p)
    val pc     = UInt(64.W)
    val target = UInt(64.W)
}

class RecoveryRequest(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    // Branch recovery preserves its boundary; exception recovery also removes it.
    val inclusive = Bool()
}

class HeadException(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val pc    = UInt(64.W)
    val cause = UInt(64.W)
    val tval  = UInt(64.W)
}

private[ooo] class RobEntry(p: OooParams) extends Bundle {
    val tag            = UInt(p.tagBits.W)
    val pc             = if (!p.bankedRobPayload) Some(UInt(64.W)) else None
    val instruction    = if (!p.bankedRobPayload) Some(UInt(32.W)) else None
    val rd             = UInt(5.W)
    val destination    = UInt(p.physBits.W)
    val oldDestination = UInt(p.physBits.W)
    val writesRd       = Bool()
    val done           = Bool()
    val data           = UInt(64.W)
    val nextPc         = UInt(64.W)
    val exception      = Bool()
    val cause          = UInt(64.W)
    val tval           = UInt(64.W)
}
