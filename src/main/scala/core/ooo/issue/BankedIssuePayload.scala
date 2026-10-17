package soc.core.ooo

import chisel3._
import chisel3.util._

/** Allocation-only context; scheduler classes, ready state and full owners stay in registers. */
class ImmutableIssuePayload extends Bundle {
    val pc = UInt(64.W)
    val instruction = UInt(32.W)
    val expandedInstruction = UInt(32.W)
    val predictedNextPc = UInt(64.W)
    val immediate = UInt(64.W)
    val fetchTval = UInt(64.W)
}

object ImmutableIssuePayload {
    val fields: Seq[(String, Int)] = Seq("pc" -> 64, "instruction" -> 32, "expandedInstruction" -> 32,
        "predictedNextPc" -> 64, "immediate" -> 64, "fetchTval" -> 64)
    val all: Set[String] = fields.map(_._1).toSet
    val execution: Set[String] = all - "expandedInstruction"
    val head: Set[String] = Set("pc", "instruction", "expandedInstruction")

    def fromRequest(request: IntegerRequest): ImmutableIssuePayload = {
        val result = Wire(new ImmutableIssuePayload)
        result.pc := request.rename.pc
        result.instruction := request.rename.instruction
        result.expandedInstruction := request.expandedInstruction
        result.predictedNextPc := request.predictedNextPc.bits
        result.immediate := request.immediate
        result.fetchTval := request.fetchTval
        result
    }

    def insert(request: IntegerRequest, payload: ImmutableIssuePayload): Unit = {
        request.rename.pc := payload.pc
        request.rename.instruction := payload.instruction
        request.expandedInstruction := payload.expandedInstruction
        request.predictedNextPc.bits := payload.predictedNextPc
        request.immediate := payload.immediate
        request.fetchTval := payload.fetchTval
    }
}

/** Per-field, two-parity-bank issue context RAM with explicit asynchronous read ports.
  *
  * Two accepted contiguous allocation lanes have opposite parity, including ROB
  * wrap. Each field/bank therefore has exactly one physical write port. Fields
  * have only the reader ports requested at elaboration; no scheduler-wide array
  * view or all-field read is exposed. Reads add no cycle and have no write-through
  * bypass. RAM is not reset: the caller's full-owner/live metadata remains the
  * authorization, and disabled reads return zero without inspecting stale data.
  */
class BankedIssuePayload(entries: Int, readFields: Seq[Set[String]]) extends Module {
    require(entries >= 4 && isPow2(entries))
    require(readFields.nonEmpty && readFields.forall(fs => fs.nonEmpty && fs.subsetOf(ImmutableIssuePayload.all)))
    private val indexBits = log2Ceil(entries)
    val io = IO(new Bundle {
        val write = Input(Vec(2, Valid(new Bundle {
            val index = UInt(indexBits.W)
            val data = new ImmutableIssuePayload
        })))
        val address = Input(Vec(readFields.size, UInt(indexBits.W)))
        val enable = Input(Vec(readFields.size, Bool()))
        val data = Output(Vec(readFields.size, new ImmutableIssuePayload))
    })
    val writes = (0 until 2).map { bank =>
        val select = io.write.map(w => w.valid && w.bits.index(0) === bank.U)
        assert(PopCount(select) <= 1.U, "issue allocation writes must occupy distinct parity banks")
        val index = Mux(select(0), io.write(0).bits.index, io.write(1).bits.index)
        (select.reduce(_ || _), select(0), index(indexBits - 1, 1))
    }
    io.data.foreach(_ := 0.U.asTypeOf(new ImmutableIssuePayload))
    for ((field, bits) <- ImmutableIssuePayload.fields) {
        val readers = readFields.indices.filter(readFields(_).contains(field))
        if (readers.nonEmpty) {
            val banks = (0 until 2).map { bank =>
                val memory = Mem(entries / 2, UInt(bits.W)).suggestName(s"${field}Bank$bank")
                val (enable, first, index) = writes(bank)
                when(enable) {
                    memory.write(index, Mux(first,
                        io.write(0).bits.data.elements(field).asUInt,
                        io.write(1).bits.data.elements(field).asUInt))
                }
                memory
            }
            for (port <- readers) {
                val index = io.address(port)
                val data0 = banks(0).read(index(indexBits - 1, 1))
                val data1 = banks(1).read(index(indexBits - 1, 1))
                io.data(port).elements(field) := Mux(io.enable(port), Mux(index(0), data1, data0), 0.U)
            }
        }
    }
}
