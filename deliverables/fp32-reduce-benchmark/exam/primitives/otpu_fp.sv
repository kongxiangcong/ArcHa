// Add-only excerpt; see NOTICE.md for provenance and modifications.
// openTPU fp32 arithmetic (docs/isa.md "Arithmetic").
// IEEE-754 binary32, round-to-nearest-even, flush-to-zero on inputs and outputs.
// Add-only excerpt of the original combinational arithmetic package.
package otpu_fp;

  typedef logic [31:0] f32_t;

  localparam f32_t F_ZERO  = 32'h0000_0000;
  localparam f32_t F_ONE   = 32'h3F80_0000;
  localparam f32_t F_TWO   = 32'h4000_0000;
  localparam f32_t F_HALF  = 32'h3F00_0000;
  localparam f32_t F_1P5   = 32'h3FC0_0000;
  localparam f32_t F_127   = 32'h42FE_0000;
  localparam f32_t F_M126  = 32'hC2FC_0000;   // -126.0
  localparam f32_t F_128   = 32'h4300_0000;   //  128.0
  localparam f32_t F_INF   = 32'h7F80_0000;
  localparam f32_t F_NINF  = 32'hFF80_0000;
  localparam f32_t F_M1    = 32'hBF80_0000;   // -1.0
  localparam f32_t F_NAN   = 32'h7FC0_0000;
  localparam f32_t F_INV127 = 32'h3C01_0204;  // f32(1/127)


  function automatic f32_t ftz(input f32_t a);
    return (a[30:23] == 8'd0) ? {a[31], 31'd0} : a;
  endfunction

  function automatic logic is_nan(input f32_t a);
    return (a[30:23] == 8'hFF) && (a[22:0] != 0);
  endfunction

  // Normalize while counting: the shift stages of the leading-zero search are the normalize
  // shifter (one mux chain, not an LZC plus a separate barrel shifter). m == 0 -> n = 31, y = 0.
  typedef struct packed {
    logic [4:0]  n;
    logic [27:0] y;       // m << n
  } norm28_t;

  function automatic norm28_t norm28(input logic [27:0] m);
    norm28_t r;
    r.y = m; r.n = '0;
    if (r.y[27:12] == 0) begin r.n[4] = 1'b1; r.y = r.y << 16; end
    if (r.y[27:20] == 0) begin r.n[3] = 1'b1; r.y = r.y << 8; end
    if (r.y[27:24] == 0) begin r.n[2] = 1'b1; r.y = r.y << 4; end
    if (r.y[27:26] == 0) begin r.n[1] = 1'b1; r.y = r.y << 2; end
    if (r.y[27] == 0)    begin r.n[0] = 1'b1; r.y = r.y << 1; end
    return r;
  endfunction

  // Align while collecting the sticky: each right-shift stage ORs the bits it drops.
  // Equals {x >> k, |x[k-1:0]} for k = 0..31 (x is 27 bits, so k >= 27 gives y = 0).
  typedef struct packed {
    logic        st;
    logic [26:0] y;
  } align27_t;

  function automatic align27_t align27(input logic [26:0] x, input logic [4:0] k);
    align27_t r;
    r.y = x; r.st = 1'b0;
    if (k[4]) begin r.st = r.st | (|r.y[15:0]); r.y = r.y >> 16; end
    if (k[3]) begin r.st = r.st | (|r.y[7:0]);  r.y = r.y >> 8;  end
    if (k[2]) begin r.st = r.st | (|r.y[3:0]);  r.y = r.y >> 4;  end
    if (k[1]) begin r.st = r.st | (|r.y[1:0]);  r.y = r.y >> 2;  end
    if (k[0]) begin r.st = r.st | r.y[0];       r.y = r.y >> 1;  end
    return r;
  endfunction

  typedef struct packed {
    logic        sp;
    logic [2:0]  sv;
    logic        sa;       // sign of the larger operand (the result sign unless it cancels)
    logic        sub;      // effective subtraction
    logic [7:0]  e;
    logic [7:0]  d;        // exponent difference (>= 0)
    logic [26:0] ma, mb;   // significands with 3 guard bits, mb not yet aligned
  } fadd_p1_t;

  typedef struct packed {
    logic        sp;
    logic [2:0]  sv;
    logic        sa;
    logic        sub;
    logic [7:0]  e;        // exponent of the larger operand (e <= 254 unless sp)
    logic [27:0] sum;
  } fadd_p2_t;

  typedef struct packed {
    logic               sp;
    logic [2:0]         sv;
    logic               s;
    logic signed [8:0]  e;    // e0 - 1, in [-31, 254] unless sp (s4 adds the 1 back)
    logic [26:0]        mn;   // normalized: mn[26] set, guard/round/sticky in [2:0]
  } fadd_nm_t;

  localparam logic [2:0] FADD_SV_NAN  = 3'b011;
  localparam logic [2:0] FADD_SV_ZERO = 3'b000;

  // Expand the 3-bit special value: NaN -> F_NAN, {s,2'b10} -> +-inf, 3'b000 -> F_ZERO.
  function automatic f32_t fadd_sv(input logic [2:0] sv);
    return {sv[2], {8{sv[1]}}, sv[0], 22'd0};
  endfunction

  function automatic fadd_p1_t fp_add_s1(input f32_t a_in, input f32_t b_in);
    fadd_p1_t r;
    f32_t a, b, t;
    a = ftz(a_in);
    b = ftz(b_in);
    // inf/NaN; the datapath fields below are don't-care when sp. A zero operand is not special:
    // its significand is 0 (hidden bit = exponent nonzero), and align/add/round return the other.
    r.sp = (a[30:23] == 8'hFF || b[30:23] == 8'hFF);
    if (is_nan(a) || is_nan(b)) r.sv = FADD_SV_NAN;
    else if (a[30:23] == 8'hFF && b[30:23] == 8'hFF && a[31] != b[31]) r.sv = FADD_SV_NAN;
    else r.sv = {(a[30:23] == 8'hFF) ? a[31] : b[31], 2'b10};
    if (b[30:0] > a[30:0]) begin
      t = a; a = b; b = t;
    end
    r.sa = a[31];
    r.sub = a[31] ^ b[31];
    r.e = a[30:23];
    r.d = a[30:23] - b[30:23];
    r.ma = {a[30:23] != 8'd0, a[22:0], 3'b000};
    r.mb = {b[30:23] != 8'd0, b[22:0], 3'b000};
    return r;
  endfunction

  function automatic fadd_p2_t fp_add_s2(input fadd_p1_t r);
    fadd_p2_t q;
    logic [26:0] mb;
    align27_t al;
    q.sp = r.sp; q.sv = r.sv; q.sa = r.sa; q.sub = r.sub;
    q.e = r.e;                               // the normalize's +1 is folded into s4
    // d = 0 shifts nothing (st = 0); d > 26 overrides, so the shifter only sees d[4:0].
    al = align27(r.mb, r.d[4:0]);
    mb = (r.d > 8'd26) ? 27'd1 : (al.y | {26'd0, al.st});
    q.sum = r.sub ? ({1'b0, r.ma} - {1'b0, mb}) : ({1'b0, r.ma} + {1'b0, mb});
    return q;
  endfunction

  // One normalize for add and sub over the 28-bit sum, counted and shifted together by norm28.
  // An add carry-out gives n = 0 (the sticky OR folds sum[1:0]); otherwise sum[26] is set, n = 1,
  // and y[0] is 0. A sub never carries out, so n = lzc27(sum[26:0]) + 1, which the
  // +1 folded into s4's constants absorbs. A zero add (0+0) leaves mn = 0 and e0 = 1 - 31 < 0:
  // s4 returns {sa, 0}, keeping the -0 of (-0)+(-0). A zero sub is the cancellation special;
  // norm28 moves any nonzero sum up to y[27] (16+8+4+2+1 >= 27), so !y[27] is sum == 0.
  function automatic fadd_nm_t fp_add_s3(input fadd_p2_t q);
    fadd_nm_t n;
    norm28_t nz;
    nz = norm28(q.sum);
    n.sp = q.sp;
    n.sv = q.sv;
    n.s = q.sa;
    if (q.sub && !nz.y[27] && !q.sp) begin
      n.sp = 1'b1;
      n.sv = FADD_SV_ZERO;
    end
    n.mn = {nz.y[27:2], nz.y[1] | nz.y[0]};
    n.e = 9'(q.e) - 9'(nz.n);                // e0 - 1
    return n;
  endfunction

  // x = n.e = e0 - 1: each test is the one on e0 (the exponent before rounding) with e0 = x + 1.
  function automatic f32_t fp_add_s4(input fadd_nm_t n);
    logic g, rs, c;
    logic signed [8:0] x;
    logic [23:0] mm;
    logic [24:0] mr;
    if (n.sp) return fadd_sv(n.sv);
    x = n.e;
    g  = n.mn[2];
    rs = n.mn[1] | n.mn[0];
    mm = n.mn[26:3];
    mr = {1'b0, mm} + ((g && (rs || mm[0])) ? 25'd1 : 25'd0);
    c = mr[24];   // as in fp_mul_s2: no post-round shift, flags off e0
    if (x >= 9'sd254 || (x == 9'sd253 && c)) return {n.s, 8'hFF, 23'd0};
    if (x < -9'sd1 || (x == -9'sd1 && !c)) return {n.s, 31'd0};
    return {n.s, 8'(x) + {6'd0, c, ~c}, mr[22:0]};   // 8'(e0) + 8'(c)
  endfunction

  function automatic f32_t fp_add(input f32_t a_in, input f32_t b_in);
    return fp_add_s4(fp_add_s3(fp_add_s2(fp_add_s1(a_in, b_in))));
  endfunction
endpackage
