package platform

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.platform.{CommonCpuClockBoundary, CommonCpuTilePortParams}

/** Evaluate the actual elaborated Bool next-state cone, without a second RTL
  * implementation or a simulator/backend substitution. This verifies the source
  * announcement equation, not metastability, physical timing, or owner drain.
  */
class TransportEmptyAnnouncementSpec extends AnyFunSuite {
    private val p = CommonCpuTilePortParams()
    private lazy val fir = ChiselStage.emitCHIRRTL(new CommonCpuClockBoundary(p))
    private lazy val body = {
        val header = "(?m)^  (?:public )?module CommonCpuClockBoundary\\b".r.findFirstMatchIn(fir).get
        val tail = fir.substring(header.end)
        "(?m)^  (?:public )?(?:module|extmodule) ".r.findFirstMatchIn(tail)
            .map(m => tail.substring(0, m.start)).getOrElse(tail)
    }
    private lazy val nodes = "(?m)^\\s*node ([\\w$]+) = (.+)$".r.findAllMatchIn(body)
        .map(m => m.group(1) -> m.group(2).takeWhile(_ != '@').trim).toMap

    private def args(s: String): Seq[String] = {
        var depth = 0
        var start = 0
        val parts = scala.collection.mutable.ArrayBuffer.empty[String]
        s.indices.foreach { i =>
            s(i) match {
                case '(' => depth += 1
                case ')' => depth -= 1
                case ',' if depth == 0 => parts += s.substring(start, i).trim; start = i + 1
                case _ =>
            }
        }
        parts += s.substring(start).trim
        parts.toSeq
    }
    private def eval(expr: String, inputs: Map[String, Boolean], seen: Set[String] = Set.empty): Boolean = {
        if (inputs.contains(expr)) inputs(expr)
        else if (nodes.contains(expr)) {
            require(!seen(expr), s"cycle in announcement cone: $expr")
            eval(nodes(expr), inputs, seen + expr)
        } else if (expr == "UInt<1>(0h0)" || expr == "UInt<1>(0)") false
        else if (expr == "UInt<1>(0h1)" || expr == "UInt<1>(1)") true
        else {
            val call = "^(and|or|not|eq)\\((.*)\\)$".r
            expr match {
                case call(op, arguments) =>
                    val values = args(arguments).map(eval(_, inputs, seen))
                    op match {
                        case "and" => require(values.size == 2); values.head && values(1)
                        case "or" => require(values.size == 2); values.head || values(1)
                        case "not" => require(values.size == 1); !values.head
                        case "eq" => require(values.size == 2); values.head == values(1)
                    }
                case _ => fail(s"Unreviewed announcement dependency or operator: $expr")
            }
        }
    }
    private def coherent(prefix: String, lanes: Seq[String]): Seq[String] =
        (Seq("instructionFetch") ++ (0 until p.coherentClients).map(i => s"coherent[$i]")).flatMap {
            port => lanes.map(lane => s"$prefix.$port.$lane.valid")
        }
    private val cpuOffers = coherent("cpu", Seq("a", "c", "e")) ++
        (0 until p.scalarPorts).map(i => s"cpu.scalar[$i].request.valid") ++
        Seq("cpu.msi.response.valid", "cpu.maintenanceStatus.valid")
    private val fabricOffers = coherent("fabric", Seq("b", "d")) ++
        (0 until p.coherentClients).map(i => s"fabric.lineGrant[$i].valid") ++
        (0 until p.scalarPorts).map(i => s"fabric.scalar[$i].response.valid") ++
        Seq("fabric.msi.request.valid", "fabric.maintenance.valid", "fabric.fabricDrainedEpoch.valid")

    for ((direction, clock, offers) <- Seq(
        ("cpu", "cpuClock", cpuOffers), ("fabric", "fabricClock", fabricOffers))) {
        test(s"$direction announcement is a reset-low source FF directly feeding the existing synchronizer") {
            val destination = if (direction == "cpu") "cpuEmptyInFabric" else "fabricEmptyInCpu"
            val connection = ("(?m)^\\s*connect \\S*" + destination +
                "\\S*\\.levelIn, ([\\w$]+)(?:\\s|$)").r.findFirstMatchIn(body).get
            val reg = connection.group(1)
            assert(("(?m)^\\s*regreset " + java.util.regex.Pattern.quote(reg) +
                " : UInt<1>, " + clock + ", \\S+, UInt<1>\\((?:0h0|0)\\)").r.findFirstIn(body).nonEmpty)
            assert(!nodes.contains(reg), "synchronizer input must be a register, not a combinational alias")
        }
        test(s"$direction actual emitted next state cancels idle for every raw offer including a stalled first beat") {
            val destination = if (direction == "cpu") "cpuEmptyInFabric" else "fabricEmptyInCpu"
            val reg = ("(?m)^\\s*connect \\S*" + destination +
                "\\S*\\.levelIn, ([\\w$]+)(?:\\s|$)").r.findFirstMatchIn(body).get.group(1)
            val next = ("(?m)^\\s*connect " + java.util.regex.Pattern.quote(reg) +
                ", (.+)$").r.findFirstMatchIn(body).get.group(1).takeWhile(_ != '@').trim
            assert(offers.distinct.size == offers.size && offers.size < 20)
            for (empty <- Seq(false, true); mask <- 0 until (1 << offers.size)) {
                val inputs = offers.zipWithIndex.map { case (name, bit) =>
                    name -> ((mask & (1 << bit)) != 0)
                }.toMap + (s"${direction}TransportEmpty" -> empty)
                assert(eval(next, inputs) == (empty && mask == 0),
                    s"$direction empty=$empty offers=0x${mask.toHexString}")
            }
            // Negative control: plain RegNext(localEmpty) lies on a first offer.
            val firstOffer = offers.map(_ -> false).toMap + (offers.head -> true) +
                (s"${direction}TransportEmpty" -> true)
            assert(eval(s"${direction}TransportEmpty", firstOffer))
            assert(!eval(next, firstOffer))
        }
    }
}
