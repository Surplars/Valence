package soc.integration.spinor

import chisel3._
import vpu.Command

/** Native Spinor command payload for already decoded RV64 vector instructions.
  * Caller supplies architectural integer x0=0 and the full FPR value, including f0.
  * This is combinational formatting only: no admission, owner, CSR or retirement.
  * Spinor's registered offer captures the payload; all 80 token bits pass intact.
  */
object SpinorScalarOperands {
    def apply(instruction: UInt, integerLeft: UInt, integerRight: UInt, floatingLeft: UInt,
        token: UInt): Command = {
        require(instruction.getWidth == 32 && token.getWidth == 80)
        require(Seq(integerLeft, integerRight, floatingLeft).forall(_.getWidth == 64))
        val command = Wire(new Command)
        val floating = instruction(6, 0) === "h57".U && instruction(14, 12) === 5.U
        val immediateCsr = instruction(6, 0) === "h73".U && instruction(14)
        command.instruction := instruction
        command.scalar := Mux(floating, floatingLeft,
            Mux(immediateCsr, instruction(19, 15).pad(64), integerLeft))
        command.scalar2 := integerRight
        command.avl := integerLeft
        command.token := token
        command
    }
}
