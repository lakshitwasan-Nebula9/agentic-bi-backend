from pathlib import Path

import yaml

_PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> dict:
    """Load a prompt YAML by name (without .yaml extension)."""
    path = _PROMPTS_DIR / f"{name}.yaml"
    with path.open() as f:
        return yaml.safe_load(f)
