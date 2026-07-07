"""
Explain Engine — traceable score attribution for the FenJue scoring system.

Each scored dimension is broken down into:
    - raw score (0-10)
    - weight in the composite formula
    - weighted contribution (= raw × weight)
    - source describing how the score was derived

This makes every score auditable and explainable to humans.
"""
from explain.engine import ExplainEngine

__all__ = ["ExplainEngine"]
