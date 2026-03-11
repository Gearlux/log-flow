import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple, cast

import yaml

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore


def get_xdg_config_dir() -> Path:
    """Get the XDG compliant configuration directory for LogFlow."""
    base = Path(os.getenv("XDG_CONFIG_HOME", "~/.config")).expanduser()
    return base / "logflow"


def load_config() -> Dict[str, Any]:
    """
    Load LogFlow configuration from standard locations.
    Priority: logflow.yaml -> logflow.yml -> pyproject.toml -> global config
    """

    def _yaml(p: Path) -> Dict[str, Any]:
        with open(p, "r") as f:
            return cast(Dict[str, Any], yaml.safe_load(f) or {})

    def _toml(p: Path) -> Dict[str, Any]:
        with open(p, "rb") as f:
            return cast(Dict[str, Any], tomllib.load(f).get("tool", {}).get("logflow", {}))

    candidates: List[Tuple[Path, Callable[[Path], Dict[str, Any]]]] = [
        (Path("logflow.yaml"), _yaml),
        (Path("logflow.yml"), _yaml),
        (Path("pyproject.toml"), _toml),
        (get_xdg_config_dir() / "config.yaml", _yaml),
    ]

    for path, loader in candidates:
        if path.exists():
            try:
                cfg = loader(path)
                if cfg:
                    return cfg
            except Exception:
                continue

    return {}
