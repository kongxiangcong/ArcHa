import unittest
from model import estimate


class PublicCases(unittest.TestCase):
    def test_ring_tie(self):
        t = [[0]*4 for _ in range(4)]
        t[0][2] = 20
        r = estimate(dict(topology='ring', nodes=4, bandwidth_bytes_s=10,
                          hop_latency_s=0.1), t)
        self.assertEqual(r['link_bytes'], [[0, 1, 20], [1, 2, 20]])
        self.assertAlmostEqual(r['total_time_s'], 2.2)

    def test_mesh_row_first_and_shared_link(self):
        t = [[0]*4 for _ in range(4)]
        t[0][3], t[2][3] = 10, 30
        r = estimate(dict(topology='mesh', rows=2, cols=2,
                          bandwidth_bytes_s=10, hop_latency_s=0.1), t)
        self.assertEqual(r['link_bytes'], [[0, 2, 10], [2, 3, 40]])
        self.assertAlmostEqual(r['total_time_s'], 4.2)

    def test_local(self):
        self.assertEqual(estimate(dict(topology='mesh', rows=1, cols=1,
            bandwidth_bytes_s=0, hop_latency_s=0), [[123]])['total_time_s'], 0)

    def test_blocked_used_link(self):
        with self.assertRaises(ValueError):
            estimate(dict(topology='ring', nodes=2, bandwidth_bytes_s=0,
                          hop_latency_s=0), [[0, 1], [0, 0]])


if __name__ == '__main__':
    unittest.main()
