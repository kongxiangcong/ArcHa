"""Keep benchmark material checks in the normal framework regression entry point."""
import importlib.util
from pathlib import Path

PATH = (Path(__file__).resolve().parents[2] / "benchmarks" /
        "dma-backpressure" / "examiner" / "test_materials.py")
spec = importlib.util.spec_from_file_location("dma_material_tests", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
MaterialTests = module.MaterialTests
