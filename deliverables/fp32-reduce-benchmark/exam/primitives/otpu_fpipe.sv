// Fixed arithmetic primitives; see NOTICE.md.
module otpu_delay #(parameter int W = 32, parameter int N = 1) (
  input  logic         clk,
  input  logic         en,
  input  logic [W-1:0] d,
  output logic [W-1:0] q
);
  // The last stage is a flip-flop, not part of a shift-register LUT: an SRL's clock-to-out is
  // ~1.5 ns, too slow in front of the multipliers and adders these lines feed.
  if (N == 0) begin : g_wire
    assign q = d;
  end else if (N == 1) begin : g_one
    (* shreg_extract = "no", keep *) logic [W-1:0] qr;
    always_ff @(posedge clk) if (en) qr <= d;
    assign q = qr;
  end else begin : g_regs
    logic [W-1:0] r [N - 1];
    (* shreg_extract = "no", keep *) logic [W-1:0] qr;
    always_ff @(posedge clk) if (en) begin
      r[0] <= d;
      for (int k = 1; k < N - 1; k++) r[k] <= r[k-1];
      qr <= r[N-2];
    end
    assign q = qr;
  end
endmodule

module otpu_fadd
  import otpu_fp::*;
#(parameter int LAT = 4) (
  input  logic  clk,
  input  logic  en,
  input  f32_t  a,
  input  f32_t  b,
  output f32_t  y
);
  fadd_p1_t s1;
  fadd_p2_t s2;
  fadd_nm_t s3;
  f32_t r;
  always_ff @(posedge clk) if (en) begin
    s1 <= fp_add_s1(a, b);
    s2 <= fp_add_s2(s1);
    s3 <= fp_add_s3(s2);
    r  <= fp_add_s4(s3);
  end
  otpu_delay #(.W(32), .N(LAT - 4)) u_pad (.clk, .en, .d(r), .q(y));
endmodule

module otpu_fadd2
  import otpu_fp::*;
(
  input  logic  clk,
  input  logic  en,
  input  f32_t  a,
  input  f32_t  b,
  output f32_t  y,
  output f32_t  yo
);
  fadd_p1_t s1;
  fadd_p2_t s2;
  fadd_nm_t s3;
  f32_t r;
  (* keep *) f32_t ro;
  always_ff @(posedge clk) if (en) begin
    s1 <= fp_add_s1(a, b);
    s2 <= fp_add_s2(s1);
    s3 <= fp_add_s3(s2);
    r  <= fp_add_s4(s3);
    ro <= fp_add_s4(s3);
  end
  assign y = r;
  assign yo = ro;
endmodule
