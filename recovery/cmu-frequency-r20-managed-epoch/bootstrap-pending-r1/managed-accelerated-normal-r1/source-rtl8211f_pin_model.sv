`timescale 1ns/1ps
// TEST ONLY. Clause22 pin responder for the managed MAC fixture, not a physical
// RTL8211F timing/electrical model, negotiation model, or clock-gating proof.
// Register policy/initial values match simulator/gsim/harness/
// rtl8211f_phy_manager.cpp; wire framing matches MdioClause22.scala and the
// independent pin oracle in fpga/zu15eg/native_phy_tx_init_tb.sv.
// clk must be the running MDIO controller clock, with >=2 clk edges per MDC
// half-cycle (the production engine's minimum). Response changes only after an
// observed falling MDC edge. No 300ns initializer-specific delay is assumed.
// inject_no_ack is rising-edge armed, consumed once on an addressed read. It
// releases TA/data (pull-up reads ffff), never shortcuts a controller response.
// BMSR deliberately returns latched-low on odd reads and live on even reads,
// exactly like the existing manager oracle. Link qualification/debounce belongs
// entirely to the real manager, not this model. Unspecified base regs read zero.
module rtl8211f_pin_model #(
    parameter [4:0] PHY_ADDRESS = 5'd1
)(
    input wire clk, reset,
    input wire mdc, mdio_out, mdio_oe,
    output reg mdio_in,
    input wire wire_link,
    input wire [1:0] wire_speed,
    input wire full_duplex, an_complete, remote_fault,
    input wire inject_no_ack,
    output reg in_transaction,
    output reg [15:0] page,
    output reg [31:0] transaction_count, read_count, write_count,
    output reg [31:0] status_count, bmsr_count, no_ack_count,
    output reg [4:0] last_phy, last_register,
    output reg last_write,
    output reg [15:0] last_data,
    output wire configuration_complete
);
    reg mdc_previous, inject_previous, no_ack_pending;
    reg [6:0] position;
    reg [13:0] header;
    wire [13:0] next_header = {header[12:0], mdio_out};
    reg frame_write, addressed, frame_no_ack;
    reg [4:0] frame_phy, frame_register;
    reg [15:0] read_data, write_data;
    reg [15:0] bmcr, advertisement, gig_advertisement, tx_delay, rx_delay;
    reg [15:0] mmd_control, mmd_address, eee;
    reg eee_written, bmcr_written;
    wire [15:0] next_write_data = {write_data[14:0], mdio_out};

    assign configuration_complete = page == 0 && tx_delay == 16'hf277 &&
        rx_delay == 16'h7898 && advertisement == 16'h0141 &&
        gig_advertisement == 16'h0600 && eee_written && eee == 0 &&
        bmcr_written && bmcr == 16'h1140;

    function automatic [15:0] read_register(input [4:0] number);
        begin
            read_register = 16'h0000;
            if (number == 31) read_register = page;
            else if (page == 0) begin
                case (number)
                    0: read_register = bmcr;
                    1: read_register = (an_complete ? 16'h0020 : 0) |
                        (remote_fault ? 16'h0010 : 0) |
                        ((bmsr_count[0] && wire_link) ? 16'h0004 : 0);
                    2: read_register = 16'h001c;
                    3: read_register = 16'hc916;
                    4: read_register = advertisement;
                    5: read_register = 16'h4141;
                    9: read_register = gig_advertisement;
                    10: read_register = 16'h7800;
                    // The established oracle leaves base13 unspecified/zero.
                    14: read_register = (mmd_control[4:0] == 7 && mmd_address == 60) ? eee : 0;
                    default: read_register = 0;
                endcase
            end else if (page == 16'h0d08 && number == 17) read_register = tx_delay;
            else if (page == 16'h0d08 && number == 21) read_register = rx_delay;
            else if (page == 16'h0a43 && number == 26)
                read_register = 16'h1000 | {10'b0, wire_speed, 4'b0} |
                    (full_duplex ? 16'h0008 : 0) | (wire_link ? 16'h0004 : 0);
            else $fatal(1, "PHY model unsupported vendor read page=%h reg=%0d", page, number);
        end
    endfunction

    task automatic write_register(input [4:0] number, input [15:0] value);
        begin
            if (number == 31) page <= value;
            else if (page == 0) begin
                case (number)
                    0: begin bmcr <= value & 16'hfdff; bmcr_written <= 1; end
                    4: advertisement <= value;
                    9: gig_advertisement <= value;
                    13: mmd_control <= value;
                    14: begin
                        if (mmd_control[15:14] == 0) mmd_address <= value;
                        else if (mmd_control[4:0] == 7 && mmd_address == 60) begin
                            eee <= value; eee_written <= 1;
                        end else $fatal(1, "PHY model unsupported MMD write");
                    end
                    default: $fatal(1, "PHY model unsupported base write reg=%0d", number);
                endcase
            end else if (page == 16'h0d08 && number == 17) tx_delay <= value;
            else if (page == 16'h0d08 && number == 21) rx_delay <= value;
            else $fatal(1, "PHY model unsupported vendor write page=%h reg=%0d", page, number);
        end
    endtask

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            mdc_previous <= 0; inject_previous <= 0; no_ack_pending <= 0;
            position <= 0; header <= 0; frame_write <= 0; addressed <= 0;
            frame_no_ack <= 0; frame_phy <= 0; frame_register <= 0;
            read_data <= 0; write_data <= 0; mdio_in <= 1;
            in_transaction <= 0; page <= 0;
            transaction_count <= 0; read_count <= 0; write_count <= 0;
            status_count <= 0; bmsr_count <= 0; no_ack_count <= 0;
            last_phy <= 0; last_register <= 0; last_write <= 0; last_data <= 0;
            bmcr <= 16'h1140; advertisement <= 16'h01e1;
            gig_advertisement <= 16'h0700; tx_delay <= 16'hf377;
            rx_delay <= 16'h7890; mmd_control <= 0; mmd_address <= 0;
            eee <= 0; eee_written <= 0; bmcr_written <= 0;
        end else begin
            mdc_previous <= mdc;
            inject_previous <= inject_no_ack;
            if (inject_no_ack && !inject_previous) no_ack_pending <= 1;
            if (mdc && !mdc_previous) begin
                in_transaction <= 1;
                if (position < 46 && mdio_oe !== 1'b1)
                    $fatal(1, "PHY model controller released preamble/header at bit %0d", position);
                if (position < 32 && mdio_out !== 1'b1)
                    $fatal(1, "PHY model requires full 32-one preamble");
                if (position >= 32 && position <= 45) header <= next_header;
                if (position == 45) begin
                    if (next_header[13:12] !== 2'b01 ||
                        (next_header[11:10] !== 2'b01 && next_header[11:10] !== 2'b10))
                        $fatal(1, "PHY model invalid Clause22 header %h", next_header);
                    frame_write <= next_header[11:10] == 2'b01;
                    frame_phy <= next_header[9:5]; frame_register <= next_header[4:0];
                    addressed <= next_header[9:5] == PHY_ADDRESS;
                    frame_no_ack <= no_ack_pending || (inject_no_ack && !inject_previous);
                    read_data <= 16'hffff; write_data <= 0;
                    if (next_header[9:5] == PHY_ADDRESS && next_header[11:10] == 2'b10) begin
                        read_data <= read_register(next_header[4:0]);
                        if (next_header[4:0] == 1 && page == 0) bmsr_count <= bmsr_count + 1;
                        if (next_header[4:0] == 26 && page == 16'h0a43) status_count <= status_count + 1;
                        if (no_ack_pending || (inject_no_ack && !inject_previous)) begin
                            no_ack_pending <= 0; no_ack_count <= no_ack_count + 1;
                        end
                    end
                end
                if (position >= 46) begin
                    if (mdio_oe !== frame_write)
                        $fatal(1, "PHY model turnaround/data ownership bit=%0d", position);
                    if (frame_write && position == 46 && mdio_out !== 1'b1)
                        $fatal(1, "PHY model write TA1");
                    if (frame_write && position == 47 && mdio_out !== 1'b0)
                        $fatal(1, "PHY model write TA0");
                    if (frame_write && position >= 48) write_data <= next_write_data;
                end
                if (position == 63) begin
                    position <= 64;
                    transaction_count <= transaction_count + 1;
                    last_phy <= frame_phy; last_register <= frame_register; last_write <= frame_write;
                    if (frame_write) begin
                        write_count <= write_count + 1; last_data <= next_write_data;
                        if (addressed) write_register(frame_register, next_write_data);
                    end else begin
                        read_count <= read_count + 1;
                        last_data <= (addressed && !frame_no_ack) ? read_data : 16'hffff;
                    end
                end else if (position < 63) position <= position + 1;
                else $fatal(1, "PHY model missing terminal falling edge");
            end
            if (!mdc && mdc_previous) begin
                mdio_in <= 1;
                if (position == 64) begin position <= 0; in_transaction <= 0; end
                else if (!frame_write && addressed && !frame_no_ack) begin
                    if (position == 47) mdio_in <= 0;
                    else if (position >= 48 && position <= 63) mdio_in <= read_data[63-position];
                end
            end
        end
    end
endmodule
