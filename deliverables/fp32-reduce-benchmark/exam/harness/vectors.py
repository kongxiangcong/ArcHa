"""Stimulus and independent cycle scoreboard; public algorithm, private final seed."""
import random
from golden import reduce64

CORNERS = [0, 0x80000000, 1, 0x80000001, 0x7fffff, 0x807fffff,
           0x800000, 0x80800000, 0x3f800000, 0xbf800000, 0x33800000,
           0x3f800001, 0x7f7fffff, 0xff7fffff, 0x7f800000, 0xff800000,
           0x7fc00000, 0x7f800001, 0xffc12345]

def generate(path, seed, rows):
    rng = random.Random(seed)
    stimuli = []
    def beat(rst=0, en=1, cap=0, sub=0, words=None):
        packed = sum(w << (32*k) for k, w in enumerate(words or [rng.getrandbits(32) for _ in range(8)]))
        stimuli.append((rst, en, cap, int(cap and sub == 7), sub, packed))
    beat(rst=1, en=0)
    # Continuous rows, gaps, pauses, reset with an in-flight partial row.
    for r in range(rows):
        if r % 37 == 36:
            for s in range(3): beat(cap=1, sub=s)
            beat(rst=1, en=rng.randrange(2))
        if r < len(CORNERS):
            w = [CORNERS[r]] * 64
        elif r % 4 == 0:
            w = [rng.choice(CORNERS) for _ in range(64)]
        elif r % 4 == 1:
            w = [rng.getrandbits(32) for _ in range(32)]
            w += [x ^ 0x80000000 for x in w]
        elif r % 4 == 2:
            w = [(rng.randrange(2)<<31) | (rng.randrange(120,136)<<23) | rng.getrandbits(23) for _ in range(64)]
        else:
            w = [rng.getrandbits(32) for _ in range(64)]
        for s in range(8):
            if r >= 32:
                for _ in range(rng.choice([0,0,0,1,3])): beat(en=0)
            beat(cap=1, sub=s, words=w[s*8:s*8+8])
        if r >= 32:
            for _ in range(8*rng.choice([0,0,1,2])): beat()
    for _ in range(40): beat()
    tick = -1
    due = {}
    partial = []
    valid, value = 0, 0
    checked = 0
    with path.open('w', encoding='ascii') as f:
        for rst, en, cap, last, sub, packed in stimuli:
            if rst:
                tick=-1; due={}; partial=[]; valid=0
            elif en:
                tick += 1
                if cap:
                    if sub == 0: partial=[]
                    partial += [(packed >> (32*k)) & 0xffffffff for k in range(8)]
                    if last: due[tick+27]=reduce64(partial)
                valid=int(tick in due)
                if valid: value=due.pop(tick); checked+=1
            f.write(f'{rst} {en} {cap} {last} {sub} {packed:064x} {valid} {value:08x}\n')
    assert checked > 0
    return {'cycles':len(stimuli), 'outputs':checked, 'seed':seed, 'rows':rows}
