import com.xilinx.rapidwright.util.FileTools;
import com.xilinx.rapidwright.device.*;
import com.xilinx.rapidwright.design.*;
import com.xilinx.rapidwright.timing.*;
import java.nio.file.*;
import java.io.*;
import java.util.*;

/** Local, in-memory analysis only. Never routes or writes a checkpoint. */
public final class TimingReference {
    static void row(PrintWriter writer, Object... fields) {
        for (int i = 0; i < fields.length; i++) {
            if (i > 0) writer.print('\t');
            writer.print(String.valueOf(fields[i]).replace("\t", " ").replace("\n", " ").replace("\r", " "));
        }
        writer.println();
        writer.flush();
    }
    static Cell cell(Design design, String name) {
        Cell cell = design.getCell(name);
        if (cell == null || cell.getBEL() == null) throw new IllegalArgumentException("Missing placed cell: " + name);
        return cell;
    }
    static String physical(Cell cell, String logical) {
        String pin = cell.getPhysicalPinMapping(logical);
        if (pin == null) throw new IllegalArgumentException("Missing physical pin: " + cell.getName() + "/" + logical);
        return pin;
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 5) throw new IllegalArgumentException("DCP EDIF logic-input net-input check-input required");
        FileTools.setOverrideDataFileDownload(true);
        Design.setAutoGenerateReadableEdif(false);
        if (!Design.getPartNameFromDCP(args[0]).equals("xczu15eg-ffvb1156-2-i"))
            throw new IllegalArgumentException("Only the validated xczu15eg-ffvb1156-2-i part is supported");
        Design design = Design.readCheckpoint(args[0], args[1]);
        System.out.println("Read " + design.getPartName() + " cells=" + design.getCells().size());
        TimingModel timing = new TimingModel(design.getDevice());
        timing.build();
        DelayModel model = timing.getDelayModel();
        try (PrintWriter writer = new PrintWriter("logic-results.tsv")) {
            row(writer, "path", "cell", "input", "output", "site", "bel", "physical_input", "physical_output", "rw_ps", "vivado_ps", "difference_ps", "status");
            for (String line : Files.readAllLines(Path.of(args[2]))) {
                String[] f = line.split("\t");
                Cell c = cell(design, f[1]);
                String input = physical(c, f[2]), output = physical(c, f[3]);
                short delay = model.getLogicDelay(model.getBELIndex(c.getBELName()), input, output);
                row(writer, f[0], f[1], f[2], f[3], c.getSiteName(), c.getBELName(), input, output, delay, f[4], delay - Integer.parseInt(f[4]), delay >= 0 ? "SUPPORTED" : "UNSUPPORTED");
            }
        }
        try (PrintWriter writer = new PrintWriter("check-arcs.tsv")) {
            row(writer, "path", "cell", "bel", "clock_pin", "endpoint_pin", "raw_model_ps", "status");
            for (String line : Files.readAllLines(Path.of(args[4]))) {
                String[] f = line.split("\t");
                Cell c = cell(design, f[1]);
                String clock = physical(c, "C"), endpoint = physical(c, f[2]);
                short delay = model.getLogicDelay(model.getBELIndex(c.getBELName()), clock, endpoint);
                // Even CLK->D is a model table entry, not a validated setup constraint.
                row(writer, f[0], f[1], c.getBELName(), clock, endpoint, delay, "NOT_VALIDATED_AS_TIMING_CHECK");
            }
        }
        try (PrintWriter writer = new PrintWriter("net-results.tsv");
             PrintWriter additions = new PrintWriter("in-memory-pin-additions.tsv");
             PrintWriter intra = new PrintWriter("intrasite-results.tsv")) {
            row(writer, "path", "net", "source_cell", "source_pin", "vivado_ps", "sink_cell", "sink_pin", "stored_pips", "pins_before", "pins_after", "source_sitepin", "sink_sitepin", "raw_rw_ps", "valid_net_estimate", "status");
            row(additions, "net", "site", "site_pin", "is_output");
            row(intra, "path", "net", "site", "source_bel_pin", "sink_bel_pin", "raw_rw_ps", "vivado_ps", "valid_direct_lookup", "observed_difference_ps");
            for (String line : Files.readAllLines(Path.of(args[3]))) {
                String[] f = line.split("\t");
                Net net = design.getNet(f[1]);
                Cell source = cell(design, f[2]), sink = cell(design, f[5]);
                BELPin sourcePin = source.getBEL().getPin(physical(source, f[3]));
                BELPin sinkPin = sink.getBEL().getPin(physical(sink, f[6]));
                if (source.getSite().equals(sink.getSite())) {
                    String from = source.getBELName() + "/" + sourcePin.getName();
                    String to = sink.getBELName() + "/" + sinkPin.getName();
                    Short delay = model.getIntraSiteDelay(source.getSite().getSiteTypeEnum(), from, to);
                    boolean valid = delay != null && delay >= 0;
                    row(intra, f[0], f[1], source.getSiteName(), from, to, delay, f[4], valid, valid ? delay - Integer.parseInt(f[4]) : "");
                }
                if (net == null) {
                    row(writer, f[0], f[1], f[2], f[3], f[4], f[5], f[6], "", "", "", "", "", "", false, "NO_EXACT_PHYSICAL_NET_NAME");
                    continue;
                }
                int before = net.getPins().size(), pipCount = net.getPIPs().size();
                try {
                    for (SitePinInst pin : DesignTools.createMissingSitePinInsts(design, net))
                        row(additions, net.getName(), pin.getSite().getName(), pin.getName(), pin.isOutPin());
                    SitePinInst from = source.getSitePinFromLogicalPin(f[3], null);
                    SitePinInst to = sink.getSitePinFromLogicalPin(f[6], null);
                    float raw = timing.calcDelay(from, to, sourcePin, sinkPin, net);
                    row(writer, f[0], f[1], f[2], f[3], f[4], f[5], f[6], pipCount, before, net.getPins().size(), from, to, raw, false,
                        pipCount == 0 ? "REJECT_NO_ROUTED_PIPS" : "REJECT_ROUTING_NOT_VALIDATED");
                } catch (Exception exception) {
                    row(writer, f[0], f[1], f[2], f[3], f[4], f[5], f[6], pipCount, before, net.getPins().size(), "", "", "", false, "ERROR: " + exception);
                }
                if (net.getPIPs().size() != pipCount) throw new IllegalStateException("PIPs changed");
            }
        }
    }
}
