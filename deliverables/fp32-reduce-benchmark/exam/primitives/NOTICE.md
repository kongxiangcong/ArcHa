# Fixed arithmetic IP

Source: FeSens/openTPU, commit `7e42a626f714edd07867702c38c954082d51f587`, Apache-2.0 (LICENSE).
Original files: rtl/vpu/otpu_fp.sv and rtl/vpu/otpu_fpipe.sv.
Only add types/functions and delay/fadd/fadd2 modules are retained; module/function
names and logic preserved. Other arithmetic and all reduction implementations are excluded.
This primitive source is permitted shared infrastructure, not a reduction solution.
Do not retrieve upstream reduction code or optimization history during the experiment.
