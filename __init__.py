"""FenJue Engine V1 — 认知差驱动的产业投资研究中台"""

__version__ = "1.0.0"

from pathlib import Path

ROOT = Path(__file__).parent
CONFIG = ROOT / "config" / "fenjue.yaml"
PROMPTS = ROOT / "prompts" / "templates.yaml"
