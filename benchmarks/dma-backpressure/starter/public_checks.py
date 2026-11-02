"""Visible acceptance examples, with hand-calculated results (not a scoring metric)."""
import unittest
from dma_model import simulate


def case(depth=1):
    return {"config": {"queue_depth": depth, "bytes_per_cycle": 2, "setup_cycles": 1},
            "memory": [1, 2, 3, 4] + [0] * 8,
            "descriptors": [
                {"id": "a", "kind": "dma", "src": 0, "dst": 4, "nbytes": 4},
                {"id": "b", "kind": "dma", "src": 4, "dst": 8, "nbytes": 4},
                {"id": "c", "kind": "compute", "src": 0, "nbytes": 4, "cycles": 2}]}


class PublicExamples(unittest.TestCase):
    def test_depth_one_stalls_issue_until_dma_completion(self):
        result = simulate(case(1))
        self.assertEqual(result["events"], [
            {"id": "a", "admitted": 0, "start": 0, "end": 3},
            {"id": "b", "admitted": 3, "start": 3, "end": 6},
            {"id": "c", "admitted": 3, "start": 3, "end": 5}])
        self.assertEqual(result["total_cycles"], 6)

    def test_depth_two_allows_early_compute(self):
        result = simulate(case(2))
        self.assertEqual(result["events"], [
            {"id": "a", "admitted": 0, "start": 0, "end": 3},
            {"id": "b", "admitted": 0, "start": 3, "end": 6},
            {"id": "c", "admitted": 0, "start": 0, "end": 2}])
        self.assertEqual(result["memory"], [1, 2, 3, 4] * 3)
        self.assertEqual(result["checksums"], {"c": 10})

    def test_dependency_reads_completed_copy(self):
        data = case(2)
        data["descriptors"][2].update(src=8, depends=["b"])
        result = simulate(data)
        self.assertEqual(result["events"][2], {"id": "c", "admitted": 6, "start": 6, "end": 8})
        self.assertEqual(result["checksums"], {"c": 10})

    def test_invalid_queue(self):
        data = case(0)
        with self.assertRaises(ValueError):
            simulate(data)


if __name__ == "__main__":
    unittest.main()
