`timescale 1ns/1ps
// 200 MHz oscillator -> MIG UI250 -> CPU100 / AON-UART50 / MAC TX125 MHz.
// The physical oscillator is buffered only by MIG; AXI uses an asynchronous CDC IP.
module soc_top_gmac_ddr #(
    // Selected board baseline. Legacy PHY-added TX delay remains selectable.
    parameter FPGA_TX_CLOCK_SHIFT = 1,
    parameter TX_QUARTER_DDR = 1,
    // PHY-specific register programming belongs to firmware/Linux by default.
    // Optional autonomous bring-up helper is outside the generic Chisel MAC.
    parameter HARDWARE_PHY_INIT = 0
) (
    input wire clk_in1_p, clk_in1_n,
    input wire sys_rst_n, button_n, uart_rxd,
    output wire uart_txd, led,
    input wire eth_rxc, eth_rx_ctl,
    input wire [3:0] eth_rxd,
    output wire eth_txc, eth_tx_ctl,
    output wire [3:0] eth_txd,
    output wire eth_mdc, eth_reset_gate,
    inout wire eth_mdio,
    output wire [16:0] c0_ddr4_adr,
    output wire [1:0] c0_ddr4_ba,
    output wire [0:0] c0_ddr4_cke, c0_ddr4_cs_n, c0_ddr4_odt, c0_ddr4_bg,
    output wire c0_ddr4_reset_n, c0_ddr4_act_n,
    output wire [0:0] c0_ddr4_ck_t, c0_ddr4_ck_c,
    inout wire [3:0] c0_ddr4_dm_dbi_n,
    inout wire [31:0] c0_ddr4_dq,
    inout wire [3:0] c0_ddr4_dqs_t, c0_ddr4_dqs_c
);
    wire board_reset = ~sys_rst_n | ~button_n;
    wire ui_clk, ui_reset, calib_complete, clk_soc, clk_aon, clk_tx, clk_rx, clk_delay;
    wire cpu_locked, eth_locked, mmcm_locked, clk_tx_forward, clk_tx_pad, rx_clock_locked;
    assign mmcm_locked = cpu_locked & eth_locked;
    wire ui_reset_request = board_reset | ui_reset | ~calib_complete | ~mmcm_locked;
    (* ASYNC_REG = "TRUE" *) reg [2:0] ui_reset_pipe;
    always @(posedge ui_clk or posedge ui_reset_request)
        if (ui_reset_request) ui_reset_pipe <= 3'b111;
        else ui_reset_pipe <= {ui_reset_pipe[1:0], 1'b0};
    wire ui_aresetn = ~ui_reset_pipe[2];

    clk_wiz_ddr u_clk_wiz (
        .clk_in1(ui_clk), .clk_out1(clk_soc), .clk_out2(clk_aon), .clk_out3(),
        .reset(board_reset | ui_reset), .locked(cpu_locked)
    );
    generate if(FPGA_TX_CLOCK_SHIFT && TX_QUARTER_DDR) begin: centered_tx_clock
        // Common REF500 -> MAC125 and dedicated ODDR250 pad tree. Physical
        // TXC is generated in native_rgmii, not a separate forwarded tree.
        native_gmac_quarter_clock clock_dut(.ui_clock(ui_clk), .cold_reset(board_reset | ui_reset),
            .tx_source(clk_tx), .tx_forward_source(clk_tx_forward),
            .tx_pad_source(clk_tx_pad),
            .delay_source(clk_delay), .locked(eth_locked));
    end else if(FPGA_TX_CLOCK_SHIFT) begin: centered_tx_clock
        native_gmac_divided_clock clock_dut(.ui_clock(ui_clk), .cold_reset(board_reset | ui_reset),
            .tx_source(clk_tx), .tx_forward_source(clk_tx_forward), .tx_pad_source(clk_tx_pad),
            .delay_source(clk_delay), .locked(eth_locked));
    end else begin: legacy_tx_clock
        clk_wiz_eth u_eth_clk_wiz(.clk_in1(ui_clk), .clk_out1(clk_tx), .clk_out2(clk_delay),
            .reset(board_reset | ui_reset), .locked(eth_locked));
        assign clk_tx_forward=clk_tx;
        assign clk_tx_pad=clk_tx;
    end endgenerate
    (* ASYNC_REG="TRUE" *) reg [2:0] delay_reset_pipe;
    always @(posedge clk_delay or posedge reset_request)
        if (reset_request) delay_reset_pipe <= 3'b111;
        else delay_reset_pipe <= {delay_reset_pipe[1:0],1'b0};
    // At least 128ns of IDELAYCTRL reset AFTER stable REFCLK; synchronous release.
    reg [63:0] delay_reset_guard;
    always @(posedge clk_delay or posedge delay_reset_pipe[2])
        if (delay_reset_pipe[2]) delay_reset_guard <= {64{1'b1}};
        else delay_reset_guard <= {delay_reset_guard[62:0],1'b0};
    wire delay_reset = delay_reset_guard[63];
    wire delay_ready;
    // All board/UI/calibration/clock-unlock causes assert ui_reset_pipe
    // asynchronously. Its qualified output directly asserts CPU reset;
    // CPU release then waits three clk_soc edges without combinational CDC.
    wire reset_request = ~ui_aresetn;
    (* ASYNC_REG = "TRUE" *) reg [2:0] reset_pipe;
    always @(posedge clk_soc or posedge reset_request)
        if (reset_request) reset_pipe <= 3'b111;
        else reset_pipe <= {reset_pipe[1:0], 1'b0};
    wire soc_reset = reset_pipe[2];
    assign led = ~soc_reset;

    // Keep PHY and TX reset asserted until all replicated IDELAYCTRLs are
    // calibrated. Reassert on RDY loss; release is synchronized per domain.
    // Release PHY reset after 10ms on the un-gated AON clock. The carrier
    // NMOS inverts this signal: HIGH asserts PHYRSTB LOW, LOW releases it.
    wire phy_reset_request = board_reset | ui_reset | ~mmcm_locked | ~delay_ready;
    (* ASYNC_REG="TRUE" *) reg [2:0] phy_reset_pipe;
    always @(posedge clk_aon or posedge phy_reset_request)
        if (phy_reset_request) phy_reset_pipe <= 3'b111;
        else phy_reset_pipe <= {phy_reset_pipe[1:0],1'b0};
    reg [18:0] phy_reset_count;
    always @(posedge clk_aon or posedge phy_reset_pipe[2])
        if (phy_reset_pipe[2]) phy_reset_count <= 0;
        else if (phy_reset_count != 19'd500000) phy_reset_count <= phy_reset_count + 1'b1;
    assign eth_reset_gate = phy_reset_count != 19'd500000;
    wire rx_pad;
    IBUF rx_clock_pad (.I(eth_rxc), .O(rx_pad));
    generate if(FPGA_TX_CLOCK_SHIFT) begin: centered_rx_clock
        wire rx_source;
        native_gmac_rx_clock clock_dut(.pad_clock(rx_pad), .cold_reset(board_reset | ui_reset),
            .clock_source(rx_source), .locked(rx_clock_locked));
        BUFG rx_clock_buffer(.I(rx_source), .O(clk_rx));
    end else begin: legacy_rx_clock
        BUFG rx_clock_buffer(.I(rx_pad), .O(clk_rx));
        assign rx_clock_locked=1'b1;
    end endgenerate
    (* ASYNC_REG="TRUE" *) reg [2:0] rx_reset_pipe;
    wire rx_reset_request = soc_reset | ~delay_ready | ~rx_clock_locked;
    always @(posedge clk_rx or posedge rx_reset_request)
        if (rx_reset_request) rx_reset_pipe <= 3'b111;
        else rx_reset_pipe <= {rx_reset_pipe[1:0],1'b0};
    wire tx_reset_request = soc_reset | ~delay_ready;
    wire tx_reset_raw, tx_reset_forward, rx_allowed;
    wire mdio_pad, mdio_out, mdio_oe, mdio_cpu_input;
    wire software_mdc, software_mdio_out, software_mdio_oe;
    generate if(HARDWARE_PHY_INIT && FPGA_TX_CLOCK_SHIFT) begin: verified_phy
        native_phy_board_control control(.clock_aon(clk_aon), .clock_tx(clk_tx),
            .clock_forward(clk_tx_forward), .clock_rx(clk_rx),
            .cold_reset(soc_reset | eth_reset_gate), .tx_reset_request(tx_reset_request),
            .rx_reset(rx_reset_pipe[2]), .mdio_pad(mdio_pad),
            .software_mdc(software_mdc), .software_out(software_mdio_out), .software_oe(software_mdio_oe),
            .pad_mdc(eth_mdc), .pad_out(mdio_out), .pad_oe(mdio_oe), .cpu_mdio_input(mdio_cpu_input),
            .tx_reset_raw(tx_reset_raw), .tx_reset_forward(tx_reset_forward), .rx_allowed(rx_allowed));
    end else if(TX_QUARTER_DDR && FPGA_TX_CLOCK_SHIFT) begin: software_phy
        native_tx_word_reset_boundary tx_release(.clock_tx(clk_tx), .inhibit(tx_reset_request),
            .reset_raw(tx_reset_raw), .reset_forward(tx_reset_forward));
        assign rx_allowed=1'b1;
        assign eth_mdc=software_mdc;
        assign mdio_out=software_mdio_out;
        assign mdio_oe=software_mdio_oe;
        assign mdio_cpu_input=mdio_pad;
    end else begin: software_phy
        native_tx_reset_boundary tx_release(.clock_tx(clk_tx), .clock_forward(clk_tx_forward),
            .inhibit(tx_reset_request), .reset_raw(tx_reset_raw), .reset_forward(tx_reset_forward));
        // MAC control reset value disables TX/RX. Software configures/readbacks
        // PHY TXDLY=0, RXDLY=1 (rgmii-rxid) before enabling either direction.
        assign rx_allowed=1'b1;
        assign eth_mdc=software_mdc;
        assign mdio_out=software_mdio_out;
        assign mdio_oe=software_mdio_oe;
        assign mdio_cpu_input=mdio_pad;
    end endgenerate
    wire [7:0] gmii_tx_data, gmii_rx_data;
    wire gmii_tx_enable, gmii_tx_error, gmii_rx_valid, gmii_rx_error, gigabit_link;
    native_rgmii #(.FPGA_TX_CLOCK_SHIFT(FPGA_TX_CLOCK_SHIFT),
        .TX_QUARTER_DDR(TX_QUARTER_DDR && FPGA_TX_CLOCK_SHIFT),
        .ISOLATE_TX_PAD_CLOCK(FPGA_TX_CLOCK_SHIFT),
        .RX_DATA_DELAY_PS(FPGA_TX_CLOCK_SHIFT ? 0 : 1100)) u_rgmii (
        .delay_clock(clk_delay), .delay_reset(delay_reset), .delay_ready(delay_ready),
        .tx_clock(clk_tx), .tx_pad_clock(clk_tx_pad), .tx_forward_clock(clk_tx_forward), .tx_forward_reset(tx_reset_forward),
        .rx_clock(clk_rx), .tx_reset(tx_reset_raw), .rx_reset(rx_reset_pipe[2]),
        .gmii_tx_data(gmii_tx_data), .gmii_tx_enable(gmii_tx_enable), .gmii_tx_error(gmii_tx_error),
        .rgmii_rx_data(eth_rxd), .rgmii_rx_control(eth_rx_ctl),
        .rgmii_tx_data(eth_txd), .rgmii_tx_control(eth_tx_ctl), .rgmii_tx_clock(eth_txc),
        .gmii_rx_data(gmii_rx_data), .gmii_rx_valid(gmii_rx_valid), .gmii_rx_error(gmii_rx_error),
        .gigabit_link(gigabit_link));
    IOBUF mdio_pad_buffer (.IO(eth_mdio), .I(mdio_out), .T(~mdio_oe), .O(mdio_pad));
    // MDIO changes only at MDC edges, but the pad must still enter two FFs.
    // MDC period=400ns; PHY t6<=300ns plus 20ns synchronization fits the
    // next rising-edge sample. The first FF alone is the asynchronous boundary.
    (* ASYNC_REG="TRUE" *) reg mdio_meta, mdio_sync;
    always @(posedge clk_soc)
        if (soc_reset) begin mdio_meta <= 1'b1; mdio_sync <= 1'b1; end
        else begin mdio_meta <= mdio_cpu_input; mdio_sync <= mdio_meta; end
    wire [3:0] cpu_awid;
    wire [31:0] cpu_awaddr;
    wire [7:0] cpu_awlen;
    wire [2:0] cpu_awsize;
    wire [1:0] cpu_awburst;
    wire cpu_awlock;
    wire [3:0] cpu_awcache;
    wire [2:0] cpu_awprot;
    wire [3:0] cpu_awqos;
    wire cpu_awvalid;
    wire cpu_awready;
    wire [63:0] cpu_wdata;
    wire [7:0] cpu_wstrb;
    wire cpu_wlast;
    wire cpu_wvalid;
    wire cpu_wready;
    wire [3:0] cpu_bid;
    wire [1:0] cpu_bresp;
    wire cpu_bvalid;
    wire cpu_bready;
    wire [3:0] cpu_arid;
    wire [31:0] cpu_araddr;
    wire [7:0] cpu_arlen;
    wire [2:0] cpu_arsize;
    wire [1:0] cpu_arburst;
    wire cpu_arlock;
    wire [3:0] cpu_arcache;
    wire [2:0] cpu_arprot;
    wire [3:0] cpu_arqos;
    wire cpu_arvalid;
    wire cpu_arready;
    wire [3:0] cpu_rid;
    wire [63:0] cpu_rdata;
    wire [1:0] cpu_rresp;
    wire cpu_rlast;
    wire cpu_rvalid;
    wire cpu_rready;
    wire [3:0] mig_awid;
    wire [31:0] mig_awaddr;
    wire [7:0] mig_awlen;
    wire [2:0] mig_awsize;
    wire [1:0] mig_awburst;
    wire mig_awlock;
    wire [3:0] mig_awcache;
    wire [2:0] mig_awprot;
    wire [3:0] mig_awqos;
    wire mig_awvalid;
    wire mig_awready;
    wire [63:0] mig_wdata;
    wire [7:0] mig_wstrb;
    wire mig_wlast;
    wire mig_wvalid;
    wire mig_wready;
    wire [3:0] mig_bid;
    wire [1:0] mig_bresp;
    wire mig_bvalid;
    wire mig_bready;
    wire [3:0] mig_arid;
    wire [31:0] mig_araddr;
    wire [7:0] mig_arlen;
    wire [2:0] mig_arsize;
    wire [1:0] mig_arburst;
    wire mig_arlock;
    wire [3:0] mig_arcache;
    wire [2:0] mig_arprot;
    wire [3:0] mig_arqos;
    wire mig_arvalid;
    wire mig_arready;
    wire [3:0] mig_rid;
    wire [63:0] mig_rdata;
    wire [1:0] mig_rresp;
    wire mig_rlast;
    wire mig_rvalid;
    wire mig_rready;
    BoardSocTop u_soc (
        .clock(clk_soc), .reset(soc_reset), .io_ddrReady(~soc_reset),
        .io_peripheralClock(clk_aon), .io_alwaysOnClock(clk_aon),
        .io_nativeGmac_rawTxClock(clk_tx), .io_nativeGmac_rawRxClock(clk_rx),
        .io_nativeGmac_rxData(gmii_rx_data), .io_nativeGmac_rxValid(gmii_rx_valid & rx_allowed),
        .io_nativeGmac_rxError(gmii_rx_error & rx_allowed), .io_nativeGmac_linkUp(gigabit_link & rx_allowed),
        .io_nativeGmac_txData(gmii_tx_data), .io_nativeGmac_txEnable(gmii_tx_enable),
        .io_nativeGmac_txError(gmii_tx_error), .io_nativeGmac_mdc(software_mdc),
        .io_nativeGmac_mdioIn(mdio_sync), .io_nativeGmac_mdioOut(software_mdio_out), .io_nativeGmac_mdioOe(software_mdio_oe),
        .io_uartRx(uart_rxd), .io_uartTx(uart_txd),
        .io_ddrAxi_aw_bits_id(cpu_awid),
        .io_ddrAxi_aw_bits_addr(cpu_awaddr),
        .io_ddrAxi_aw_bits_len(cpu_awlen),
        .io_ddrAxi_aw_bits_size(cpu_awsize),
        .io_ddrAxi_aw_bits_burst(cpu_awburst),
        .io_ddrAxi_aw_bits_lock(cpu_awlock),
        .io_ddrAxi_aw_bits_cache(cpu_awcache),
        .io_ddrAxi_aw_bits_prot(cpu_awprot),
        .io_ddrAxi_aw_bits_qos(cpu_awqos),
        .io_ddrAxi_aw_valid(cpu_awvalid),
        .io_ddrAxi_aw_ready(cpu_awready),
        .io_ddrAxi_w_bits_data(cpu_wdata),
        .io_ddrAxi_w_bits_strb(cpu_wstrb),
        .io_ddrAxi_w_bits_last(cpu_wlast),
        .io_ddrAxi_w_valid(cpu_wvalid),
        .io_ddrAxi_w_ready(cpu_wready),
        .io_ddrAxi_b_bits_id(cpu_bid),
        .io_ddrAxi_b_bits_resp(cpu_bresp),
        .io_ddrAxi_b_valid(cpu_bvalid),
        .io_ddrAxi_b_ready(cpu_bready),
        .io_ddrAxi_ar_bits_id(cpu_arid),
        .io_ddrAxi_ar_bits_addr(cpu_araddr),
        .io_ddrAxi_ar_bits_len(cpu_arlen),
        .io_ddrAxi_ar_bits_size(cpu_arsize),
        .io_ddrAxi_ar_bits_burst(cpu_arburst),
        .io_ddrAxi_ar_bits_lock(cpu_arlock),
        .io_ddrAxi_ar_bits_cache(cpu_arcache),
        .io_ddrAxi_ar_bits_prot(cpu_arprot),
        .io_ddrAxi_ar_bits_qos(cpu_arqos),
        .io_ddrAxi_ar_valid(cpu_arvalid),
        .io_ddrAxi_ar_ready(cpu_arready),
        .io_ddrAxi_r_bits_id(cpu_rid),
        .io_ddrAxi_r_bits_data(cpu_rdata),
        .io_ddrAxi_r_bits_resp(cpu_rresp),
        .io_ddrAxi_r_bits_last(cpu_rlast),
        .io_ddrAxi_r_valid(cpu_rvalid),
        .io_ddrAxi_r_ready(cpu_rready)
    );
    axi_clock_converter_ddr u_axi_cdc (
        .s_axi_aclk(clk_soc), .s_axi_aresetn(~soc_reset),
        .m_axi_aclk(ui_clk), .m_axi_aresetn(ui_aresetn),
        .s_axi_awid(cpu_awid),
        .s_axi_awaddr(cpu_awaddr),
        .s_axi_awlen(cpu_awlen),
        .s_axi_awsize(cpu_awsize),
        .s_axi_awburst(cpu_awburst),
        .s_axi_awlock(cpu_awlock),
        .s_axi_awcache(cpu_awcache),
        .s_axi_awprot(cpu_awprot),
        .s_axi_awqos(cpu_awqos),
        .s_axi_awregion(4'b0000),
        .s_axi_awvalid(cpu_awvalid),
        .s_axi_awready(cpu_awready),
        .s_axi_wdata(cpu_wdata),
        .s_axi_wstrb(cpu_wstrb),
        .s_axi_wlast(cpu_wlast),
        .s_axi_wvalid(cpu_wvalid),
        .s_axi_wready(cpu_wready),
        .s_axi_bid(cpu_bid),
        .s_axi_bresp(cpu_bresp),
        .s_axi_bvalid(cpu_bvalid),
        .s_axi_bready(cpu_bready),
        .s_axi_arid(cpu_arid),
        .s_axi_araddr(cpu_araddr),
        .s_axi_arlen(cpu_arlen),
        .s_axi_arsize(cpu_arsize),
        .s_axi_arburst(cpu_arburst),
        .s_axi_arlock(cpu_arlock),
        .s_axi_arcache(cpu_arcache),
        .s_axi_arprot(cpu_arprot),
        .s_axi_arqos(cpu_arqos),
        .s_axi_arregion(4'b0000),
        .s_axi_arvalid(cpu_arvalid),
        .s_axi_arready(cpu_arready),
        .s_axi_rid(cpu_rid),
        .s_axi_rdata(cpu_rdata),
        .s_axi_rresp(cpu_rresp),
        .s_axi_rlast(cpu_rlast),
        .s_axi_rvalid(cpu_rvalid),
        .s_axi_rready(cpu_rready),
        .m_axi_awid(mig_awid),
        .m_axi_awaddr(mig_awaddr),
        .m_axi_awlen(mig_awlen),
        .m_axi_awsize(mig_awsize),
        .m_axi_awburst(mig_awburst),
        .m_axi_awlock(mig_awlock),
        .m_axi_awcache(mig_awcache),
        .m_axi_awprot(mig_awprot),
        .m_axi_awqos(mig_awqos),
        .m_axi_awvalid(mig_awvalid),
        .m_axi_awready(mig_awready),
        .m_axi_wdata(mig_wdata),
        .m_axi_wstrb(mig_wstrb),
        .m_axi_wlast(mig_wlast),
        .m_axi_wvalid(mig_wvalid),
        .m_axi_wready(mig_wready),
        .m_axi_bid(mig_bid),
        .m_axi_bresp(mig_bresp),
        .m_axi_bvalid(mig_bvalid),
        .m_axi_bready(mig_bready),
        .m_axi_arid(mig_arid),
        .m_axi_araddr(mig_araddr),
        .m_axi_arlen(mig_arlen),
        .m_axi_arsize(mig_arsize),
        .m_axi_arburst(mig_arburst),
        .m_axi_arlock(mig_arlock),
        .m_axi_arcache(mig_arcache),
        .m_axi_arprot(mig_arprot),
        .m_axi_arqos(mig_arqos),
        .m_axi_arvalid(mig_arvalid),
        .m_axi_arready(mig_arready),
        .m_axi_rid(mig_rid),
        .m_axi_rdata(mig_rdata),
        .m_axi_rresp(mig_rresp),
        .m_axi_rlast(mig_rlast),
        .m_axi_rvalid(mig_rvalid),
        .m_axi_rready(mig_rready)
    );
    ddr4_0 u_ddr (
        .sys_rst(board_reset), .c0_sys_clk_p(clk_in1_p), .c0_sys_clk_n(clk_in1_n),
        .c0_ddr4_ui_clk(ui_clk), .c0_ddr4_ui_clk_sync_rst(ui_reset),
        .c0_init_calib_complete(calib_complete), .c0_ddr4_aresetn(ui_aresetn),
        .c0_ddr4_adr(c0_ddr4_adr),
        .c0_ddr4_ba(c0_ddr4_ba),
        .c0_ddr4_cke(c0_ddr4_cke),
        .c0_ddr4_cs_n(c0_ddr4_cs_n),
        .c0_ddr4_odt(c0_ddr4_odt),
        .c0_ddr4_bg(c0_ddr4_bg),
        .c0_ddr4_reset_n(c0_ddr4_reset_n),
        .c0_ddr4_act_n(c0_ddr4_act_n),
        .c0_ddr4_ck_t(c0_ddr4_ck_t),
        .c0_ddr4_ck_c(c0_ddr4_ck_c),
        .c0_ddr4_dm_dbi_n(c0_ddr4_dm_dbi_n),
        .c0_ddr4_dq(c0_ddr4_dq),
        .c0_ddr4_dqs_t(c0_ddr4_dqs_t),
        .c0_ddr4_dqs_c(c0_ddr4_dqs_c),
        .c0_ddr4_s_axi_awid(mig_awid),
        .c0_ddr4_s_axi_awaddr(mig_awaddr[30:0]),
        .c0_ddr4_s_axi_awlen(mig_awlen),
        .c0_ddr4_s_axi_awsize(mig_awsize),
        .c0_ddr4_s_axi_awburst(mig_awburst),
        .c0_ddr4_s_axi_awlock(mig_awlock),
        .c0_ddr4_s_axi_awcache(mig_awcache),
        .c0_ddr4_s_axi_awprot(mig_awprot),
        .c0_ddr4_s_axi_awqos(mig_awqos),
        .c0_ddr4_s_axi_awvalid(mig_awvalid),
        .c0_ddr4_s_axi_awready(mig_awready),
        .c0_ddr4_s_axi_wdata(mig_wdata),
        .c0_ddr4_s_axi_wstrb(mig_wstrb),
        .c0_ddr4_s_axi_wlast(mig_wlast),
        .c0_ddr4_s_axi_wvalid(mig_wvalid),
        .c0_ddr4_s_axi_wready(mig_wready),
        .c0_ddr4_s_axi_bid(mig_bid),
        .c0_ddr4_s_axi_bresp(mig_bresp),
        .c0_ddr4_s_axi_bvalid(mig_bvalid),
        .c0_ddr4_s_axi_bready(mig_bready),
        .c0_ddr4_s_axi_arid(mig_arid),
        .c0_ddr4_s_axi_araddr(mig_araddr[30:0]),
        .c0_ddr4_s_axi_arlen(mig_arlen),
        .c0_ddr4_s_axi_arsize(mig_arsize),
        .c0_ddr4_s_axi_arburst(mig_arburst),
        .c0_ddr4_s_axi_arlock(mig_arlock),
        .c0_ddr4_s_axi_arcache(mig_arcache),
        .c0_ddr4_s_axi_arprot(mig_arprot),
        .c0_ddr4_s_axi_arqos(mig_arqos),
        .c0_ddr4_s_axi_arvalid(mig_arvalid),
        .c0_ddr4_s_axi_arready(mig_arready),
        .c0_ddr4_s_axi_rid(mig_rid),
        .c0_ddr4_s_axi_rdata(mig_rdata),
        .c0_ddr4_s_axi_rresp(mig_rresp),
        .c0_ddr4_s_axi_rlast(mig_rlast),
        .c0_ddr4_s_axi_rvalid(mig_rvalid),
        .c0_ddr4_s_axi_rready(mig_rready)
    );
endmodule
