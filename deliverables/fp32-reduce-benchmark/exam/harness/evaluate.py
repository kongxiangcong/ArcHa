#!/usr/bin/env python3
"""Frozen FR64 evaluator. Runs only when explicitly invoked on Linux."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from vectors import generate

ROOT = Path(__file__).resolve().parents[1]

class InfraError(Exception): pass
class CandidateError(Exception): pass

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def run(argv, cwd, log, timeout=1800):
    try:
        with log.open('w', encoding='utf8') as f:
            p=subprocess.run(argv, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired) as exc:
        raise InfraError(str(exc)) from exc
    if p.returncode:
        raise CandidateError(f'command failed ({p.returncode}); see {log}')

def read_config():
    try:
        c=json.loads((ROOT/'toolchain.json').read_text())
        for k in ('liberty','yosys','verilator','openroad'):
            p=Path(c[k])
            if not p.is_absolute() or not p.is_file(): raise InfraError(f'missing absolute {k} path')
            if sha(p)!=c['sha256'][k]: raise InfraError(f'{k} changed since toolchain freeze')
        for rel, digest in json.loads((ROOT/'frozen.json').read_text()).items():
            if sha(ROOT/rel)!=digest: raise InfraError(f'frozen input changed: {rel}')
        return c
    except (OSError, KeyError, ValueError) as exc:
        raise InfraError('toolchain/frozen manifest missing or invalid: '+str(exc)) from exc

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    # Judge invokes this trusted evaluator with a hidden seed; participants use defaults.
    p.add_argument('--seed', type=int, default=20261025)
    p.add_argument('--rows', type=int, default=256)
    a=p.parse_args()
    out=a.out.resolve()
    if out.exists():
        print('Use a fresh --out directory',file=sys.stderr); return 75
    out.mkdir(parents=True)
    start=time.monotonic(); metrics={}; status='infra'; error=None
    try:
        c=read_config()
        if a.rows < 64: raise InfraError('at least 64 rows required')
        sources=sorted((ROOT/'rtl').glob('*.sv'))
        if not sources: raise CandidateError('no RTL submitted')
        for src in sources:
            if src.is_symlink(): raise CandidateError('symlink RTL')
            code=src.read_text()
            code=re.sub(r'/\*.*?\*/|//[^\n]*','',code,flags=re.S)
            if re.search(r'`include|\$(?:readmem\w*|fopen|fwrite|fdisplay|fscanf|system|finish)|\bDPI\b|\bbind\b',code):
                raise CandidateError('external IO, include, DPI or testbench access in submitted RTL')
        fixed=[ROOT/'primitives/otpu_fp.sv', ROOT/'primitives/otpu_fpipe.sv']
        sources=fixed+sources
        # Generated file paths contain no spaces after the trusted workspace staging below.
        stage=out/'src'; stage.mkdir()
        staged=[]
        for i, src in enumerate(sources):
            dst=stage/f's{i}.sv'; shutil.copyfile(src,dst); staged.append(dst)
        shutil.copyfile(ROOT/'harness/tb.sv',out/'tb.sv')
        stats=generate(out/'vectors.txt',a.seed,a.rows)
        run([c['verilator'],'--binary','--timing','--top-module','tb','-Wno-fatal',
             '--Mdir',str(out/'obj'),'-j',str(c['jobs']),*map(str,staged),str(out/'tb.sv')],
            out,out/'verilator.log')
        run([str(out/'obj/Vtb'),'+vectors='+str(out/'vectors.txt')],out,out/'simulation.log')
        if 'FR64_PASS' not in (out/'simulation.log').read_text(): raise CandidateError('no pass marker')
        metrics['correct']=1
        # Spaces in install/output paths are rejected rather than interpolated ambiguously.
        for s in [str(out),c['liberty']]:
            if not re.fullmatch(r'[A-Za-z0-9_/.:+-]+',s): raise InfraError('use simple Linux paths without spaces')
        ys='\n'.join([
            'read_slang --top reduce64 '+ ' '.join(map(str,staged)),
            'synth -top reduce64 -flatten -noabc',
            'dffunmap', 'dfflibmap -liberty '+c['liberty'],
            'abc -liberty '+c['liberty']+' -D 10000', 'clean', 'check -assert',
            'tee -o '+str(out/'stat.json')+' stat -json -liberty '+c['liberty'],
            'write_verilog -noattr -noexpr '+str(out/'mapped.v')])
        (out/'synth.ys').write_text(ys+'\n')
        run([c['yosys'],*c.get('yosys_args',[]),'-s',str(out/'synth.ys')],out,out/'yosys.log')
        try:
            data=json.loads((out/'stat.json').read_text())
            design=data.get('design') or data['modules']['\\reduce64']
            area=float(design['area'])
            if not math.isfinite(area) or area<=0: raise ValueError('nonpositive area')
            for module in data.get('modules',{}).values():
                if any(name.startswith('$') for name in module.get('num_cells_by_type',{})):
                    raise CandidateError('unmapped internal cells remain')
        except (OSError,KeyError,ValueError) as exc:
            raise InfraError('unrecognized area report: '+str(exc)) from exc
        tcl='\n'.join([
            'read_liberty {'+c['liberty']+'}', 'read_verilog {'+str(out/'mapped.v')+'}',
            'link_design reduce64', 'create_clock -name clk -period 10 [get_ports clk]',
            'set_clock_uncertainty 0.1 [get_clocks clk]',
            'set data_in [get_ports {rst en cap row_last sub* pacc*}]',
            'set_input_delay 1 -clock clk $data_in',
            'set_input_transition 0.1 $data_in',
            'set_output_delay 1 -clock clk [all_outputs]',
            'set_load 0.01 [all_outputs]',
            'check_setup -verbose', 'report_checks -path_delay max -group_count 5',
            'report_worst_slack -max', 'exit'])
        (out/'sta.tcl').write_text(tcl+'\n')
        run([c['openroad'],'-exit',str(out/'sta.tcl')],out,out/'sta.log')
        sta=(out/'sta.log').read_text()
        match=re.search(r'worst slack\s+([-+0-9.eE]+)',sta,re.I)
        if not match: raise InfraError('STA worst slack missing')
        slack=float(match.group(1))
        if not math.isfinite(slack): raise InfraError('nonfinite slack')
        metrics.update(area_um2=area,wns_ns=slack,latency_enabled_edges=28,initiation_interval=8)
        (out/'vectors_meta.json').write_text(json.dumps(stats,indent=2)+'\n')
        if slack<0: raise CandidateError('timing constraint violated')
        status='pass'
    except InfraError as exc: error=str(exc); status='infra'
    except CandidateError as exc: error=str(exc); status='fail'
    except (OSError,ValueError) as exc: error=str(exc); status='infra'
    result={'status':status,'metrics':metrics,'error':error,'elapsed_s':time.monotonic()-start,
            'metric_scope':'mapped cell area and post-synthesis zero-wire-parasitic STA; not physical PPA'}
    (out/'metrics.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
    return {'pass':0,'fail':1,'infra':75}[status]

if __name__=='__main__': sys.exit(main())
