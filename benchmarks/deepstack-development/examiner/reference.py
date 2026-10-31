"""Operator-only scalar oracle for the published restricted topology contract."""
import math


def estimate(config, traffic):
    def integer(x, minimum=0):
        if isinstance(x, bool) or not isinstance(x, int) or x < minimum:
            raise ValueError('integer')
        return x
    def real(x):
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0:
            raise ValueError('finite nonnegative number')
        return x
    topo = config['topology']
    if topo == 'ring':
        rows, cols = 1, integer(config['nodes'], 2)
        edges = {(s, (s+d) % cols) for s in range(cols) for d in (-1, 1)}
    elif topo == 'mesh':
        rows, cols = integer(config['rows'], 1), integer(config['cols'], 1)
        edges = set()
        for s in range(rows*cols):
            r, c = divmod(s, cols)
            for dr, dc in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                if 0 <= r+dr < rows and 0 <= c+dc < cols:
                    edges.add((s, (r+dr)*cols+c+dc))
    else:
        raise ValueError('topology')
    n = rows * cols
    bw, latency = real(config['bandwidth_bytes_s']), real(config['hop_latency_s'])
    props = {edge: (bw, latency) for edge in edges}
    seen = set()
    for link in config.get('links', []):
        edge = integer(link['src']), integer(link['dst'])
        if edge not in edges or edge in seen:
            raise ValueError('edge')
        seen.add(edge)
        props[edge] = real(link['bandwidth_bytes_s']), real(link['hop_latency_s'])
    if len(traffic) != n or any(len(row) != n for row in traffic):
        raise ValueError('shape')
    used, longest = {}, 0
    for s in range(n):
        for d in range(n):
            amount = integer(traffic[s][d])
            if not amount or s == d:
                continue
            current, delay = s, 0
            while current != d:
                if topo == 'ring':
                    delta = 1 if (d-current) % n <= (current-d) % n else -1
                    nxt = (current+delta) % n
                else:
                    r, c = divmod(current, cols)
                    rd, cd = divmod(d, cols)
                    nxt = current + ((cols if rd > r else -cols) if r != rd else (1 if cd > c else -1))
                edge = current, nxt
                used[edge] = used.get(edge, 0) + amount
                delay += props[edge][1]
                current = nxt
            longest = max(longest, delay)
    if any(props[e][0] == 0 for e in used):
        raise ValueError('used zero-bandwidth edge')
    transmission = max((v/props[e][0] for e, v in used.items()), default=0)
    return dict(link_bytes=[[s, d, used[s, d]] for s, d in sorted(used)],
                hop_time_s=longest, link_time_s=transmission, total_time_s=longest+transmission)
