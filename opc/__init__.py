"""OPC: a domain-independent engine for automatic, budgeted, evidence-bound iteration.

The core knows editable paths, frozen evaluator files, ordered gates, a metrics
dictionary and a declarative acceptance rule. It does not know what an RTL file,
a compiler pass or a PIM bank is; a project supplies those through `.opc/`.
"""

__version__ = "0.3.0"

