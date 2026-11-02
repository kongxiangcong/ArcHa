"""Public deterministic DDR4 inputs. Addresses in bytes; time comes from simulator."""
import json
from pathlib import Path
import random


def generate(out, pattern='random', count=10000, seed=421, write_every=5):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    trace = out / 'input.trace'
    rng = random.Random(seed)
    with trace.open('w') as f:
        for i in range(count):
            if pattern == 'stream':
                address = (i * 64) % (1 << 30)
            elif pattern == 'samebank':
                address = (i % 4096) * 262144
            elif pattern == 'local':
                address = rng.randrange(16) * 64
            elif pattern == 'random':
                address = rng.randrange((1 << 30) // 64) * 64
            else:
                raise ValueError(pattern)
            op = 'ST' if write_every and i % write_every == write_every-1 else 'LD'
            f.write(f'{op} {address}\n')
    cfg = {'Frontend': {'impl': 'LoadStoreTrace', 'clock_ratio': 1, 'path': str(trace.resolve())},
           'MemorySystem': {'impl': 'GenericDRAM', 'clock_ratio': 1,
               'DRAM': {'impl': 'DDR4', 'org': {'preset': 'DDR4_8Gb_x8', 'channel': 1, 'rank': 2},
                        'timing': {'preset': 'DDR4_2400R'}},
               'Controller': {'impl': 'Generic', 'Scheduler': {'impl': 'FRFCFS'},
                   'RefreshManager': {'impl': 'AllBank'}, 'RowPolicy': {'impl': 'ClosedRowPolicy', 'cap': 4}},
               'AddrMapper': {'impl': 'RoBaRaCoCh'}}}
    config = out / 'config.json'
    config.write_text(json.dumps(cfg, indent=2)+'\n')
    return config


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--output', default='results/public-input')
    p.add_argument('--pattern', choices=['stream', 'random', 'samebank', 'local'], default='random')
    p.add_argument('--count', type=int, default=10000)
    p.add_argument('--seed', type=int, default=421)
    args = p.parse_args()
    print(generate(args.output, args.pattern, args.count, args.seed))
