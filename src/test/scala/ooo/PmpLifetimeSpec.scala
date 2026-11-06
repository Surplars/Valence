package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.core.ooo._
import soc.platform.{CommonA1RebuildProfile, CommonCpuProfile}

/** Pure elaboration contracts. No hardware simulator and no claim about active X behavior.
  * Compare expanded expression graphs, not generated temporary names or assertion token counts.
  * The expected predicates below are independent, explicit contracts, not another DUT emission.
  */
class PmpLifetimeSpec extends AnyFunSuite {
    private def compact(s: String): String = s.replaceAll("\\s+", "")
    private def u(n: Int, width: Int = 0): String =
        s"UInt<${if (width == 0) math.max(1, BigInt(n).bitLength) else width}>(0h${n.toHexString})"
    private val zero = u(0)
    private def call(op: String, args: String*): String = s"$op(${args.mkString(",")})"
    private def not(s: String): String = call("eq", s, zero)
    private case class Check(predicate: String, enable: String, clock: String, guards: Seq[String])

    // Deliberately restricted to emitted CHIRRTL nodes and unconditional connections.
    // Unsupported conditional resets/connections fail rather than being flattened optimistically.
    private class Body(val text: String) {
        private val lines = text.replaceAll(" @\\[[^\\n]*?\\]", "").linesIterator.toVector
        private val node = "\\s*node (\\w+) = (.+)".r
        private val nodes = lines.collect { case node(name, expression) => name -> compact(expression) }.toMap
        private val token = "[A-Za-z_][A-Za-z_0-9]*(?:\\.[A-Za-z_][A-Za-z_0-9]*|\\[[0-9]+\\])*".r
        def expand(expression: String, seen: Set[String] = Set.empty): String =
            token.replaceAllIn(compact(expression), m => nodes.get(m.matched) match {
                case Some(value) =>
                    require(!seen(m.matched), s"cyclic node ${m.matched}")
                    java.util.regex.Matcher.quoteReplacement(expand(value, seen + m.matched))
                case None => java.util.regex.Matcher.quoteReplacement(m.matched)
            })
        def connection(port: String): String = {
            val prefix = s"    connect $port, "
            val matches = lines.filter(_.trim.startsWith(s"connect $port, "))
            require(matches.size == 1 && matches.head.startsWith(prefix), s"not one unconditional connection: $port")
            expand(matches.head.stripPrefix(prefix))
        }
        def checks: Seq[Check] = {
            var guards = Vector.empty[(Int, String)]
            val assertion = "intrinsic\\(circt_chisel_ifelsefatal<.*>, ([^,]+), ([^,]+), ([^)]+)\\)".r
            lines.flatMap { line =>
                val indent = line.takeWhile(_ == ' ').length
                guards = guards.takeWhile(_._1 < indent)
                val trimmed = line.trim
                if (trimmed.startsWith("when ")) guards :+= indent -> trimmed.stripPrefix("when ").stripSuffix(" :")
                trimmed match {
                    case assertion(clock, predicate, enable) =>
                        Some(Check(expand(predicate), expand(enable), expand(clock), guards.map(g => expand(g._2))))
                    case _ => None
                }
            }
        }
    }
    private def body(fir: String, name: String): Body = {
        val header = ("(?m)^  (?:public )?module " + name + " :[^\\n]*\\n").r
        val start = header.findFirstMatchIn(fir).getOrElse(fail(s"missing module $name")).end
        val tail = fir.substring(start)
        new Body(tail.take("(?m)^  (?:public )?(?:ext)?module ".r.findFirstMatchIn(tail).map(_.start).getOrElse(tail.length)))
    }
    private def normalizedReset(expression: String): String = expression.replace("asUInt(reset)", "reset")
    private def checkOwner(owner: Body, expected: String): Unit = {
        assert(normalizedReset(owner.connection("pmpDenied_pmp.reset")) == expected)
        assert(owner.connection("pmpDenied_pmp.clock") == "clock")
    }

    // Natural access means size <= 3 and low address bits aligned to 1 << size.
    private val mask = (0 until 3).foldLeft(u(7, 3)) { (otherwise, size) =>
        call("mux", call("eq", u(size), "io.size"), u((1 << size) - 1), otherwise)
    }
    private val aligned = call("and", call("leq", "io.size", u(3)),
        call("eq", call("and", call("bits", "io.address", "2", "0"), mask), zero))
    // With shared bounds the access cannot change the original address's 8-byte beat.
    private val offset = (1 until 8).foldLeft(u(0, 7)) { (otherwise, size) =>
        call("mux", call("eq", u(size), "io.size"), u((1 << size) - 1, 7), otherwise)
    }
    private val start = call("cat", zero, "io.address")
    private val sameBeat = call("eq", call("bits", start, "64", "3"),
        call("bits", call("or", start, offset), "64", "3"))
    private def checkPredicates(checker: Body, decoded: Boolean): Unit = {
        val checks = checker.checks
        assert(checks.map(_.predicate) == (if (decoded) Seq(aligned) else Seq(aligned, sameBeat)))
        checks.foreach { c =>
            assert(c.clock == "clock" && c.guards.isEmpty)
            assert(normalizedReset(c.enable) == not("reset"))
        }
    }
    private def checkBridge(owner: Body, state: String, copies: Int): Unit = {
        val checks = owner.checks.filter(_.predicate.contains(s"$state.region"))
        val expected = for (_ <- 0 until copies; i <- 0 until 16) yield {
            val low = s"$state.regionLow[$i]"
            val end = s"$state.regionEnd[$i]"
            val predicates = Seq(
                call("and", not(call("orr", call("bits", low, "64", "56"))),
                    not(call("orr", call("bits", end, "64", "56")))),
                call("and", call("eq", call("bits", low, "1", "0"), zero),
                    call("eq", call("bits", end, "1", "0"), u(3))),
                call("leq", low, end))
            predicates.map(p => Check(p, not("reset"), "clock", Seq(s"$state.regionActive[$i]")))
        }
        assert(checks.map(c => c.copy(enable = normalizedReset(c.enable))) == expected.flatten)
    }

    for (decoded <- Seq(false, true)) {
        test(s"actual FP prepared owner and walker issue owners retain exact PMP predicates (decoded=$decoded)") {
            val params = if (decoded) CommonA1RebuildProfile.FullR1M3EfficiencyRefactor2.config.coreParams
                else CommonCpuProfile.A1.fpga.coreParams
            val fp = ChiselStage.emitCHIRRTL(new FloatingPointMemoryPipeline(params))
            val fpBody = body(fp, "FloatingPointMemoryPipeline")
            checkOwner(fpBody, call("or", "reset", not("preparedValid")))
            assert(fpBody.connection("pmpDenied_pmp.io.size") == "prepared.size")
            assert(fpBody.connection("pmpDenied_pmp.io.privilege") == "io.dataPrivilege")
            checkPredicates(body(fp, if (decoded) "DecodedNaturalPmpChecker" else "PmpChecker"), decoded)
            if (decoded) checkBridge(fpBody, "io.pmpState", 1)
            // I/D production instances differ by maximum page-table depth. Cover all supported depths.
            for (levels <- Seq(3, 4, 5)) {
                val fir = ChiselStage.emitCHIRRTL(new SvPageTableWalker(levels, 16, decoded))
                val walker = body(fir, "SvPageTableWalker")
                checkOwner(walker, call("or", "reset", call("neq", "state", u(1, 2))))
                assert(walker.connection("pmpDenied_pmp.io.address") == walker.expand("pteAddress"))
                assert(walker.connection("pmpDenied_pmp.io.size") == u(3))
                assert(walker.connection("pmpDenied_pmp.io.privilege") == u(1))
                assert(walker.connection("pmpDenied_pmp.io.access") == u(0, 2))
                checkPredicates(body(fir, if (decoded) "DecodedNaturalPmpChecker" else "PmpChecker"), decoded)
                if (decoded) checkBridge(walker, "io.pmpState", 1)
            }
        }
        test(s"raw fixture retains unsanitized payload and original decoded-state reset (decoded=$decoded)") {
            val fir = ChiselStage.emitCHIRRTL(new PmpLifetimeContract(decoded))
            val fixture = body(fir, "PmpLifetimeContract")
            for (i <- 0 until 3) {
                val instance = s"io_denied_${i}_pmp"
                for (port <- Seq("address", "size", "privilege", "access"))
                    assert(fixture.connection(s"$instance.io.$port") == s"io.$port")
                val owner = if (i == 0) "io.preparedValid" else call("eq", s"io.walker${i - 1}State", u(1))
                assert(normalizedReset(fixture.connection(s"$instance.reset")) == call("or", "reset", not(owner)))
                assert(fixture.connection(s"io.denied[$i]") == s"$instance.io.denied")
                checkPredicates(body(fir, (if (decoded) "DecodedNaturalPmpChecker" else "PmpChecker") +
                    (if (i == 0) "" else s"_$i")), decoded)
            }
            if (decoded) checkBridge(fixture, "io.state", 3)
        }
    }

    test("owner graph check rejects reset-only, permission/ready gating, and conditional reset mutations") {
        val fir = ChiselStage.emitCHIRRTL(new SvPageTableWalker())
        val original = body(fir, "SvPageTableWalker").text
        val expected = call("or", "reset", call("neq", "state", u(1, 2)))
        for (replacement <- Seq("reset", "UInt<1>(0h1)", "io.memory.request.ready", "pmpDenied_pmp.io.denied")) {
            val mutated = original.replaceAll("(?m)^    connect pmpDenied_pmp.reset, .+$",
                s"    connect pmpDenied_pmp.reset, $replacement")
            intercept[org.scalatest.exceptions.TestFailedException] { checkOwner(new Body(mutated), expected) }
        }
        intercept[IllegalArgumentException] {
            checkOwner(new Body(original.replace("    connect pmpDenied_pmp.reset,", "      connect pmpDenied_pmp.reset,")), expected)
        }
    }
}
