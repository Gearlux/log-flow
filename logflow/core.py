import os
import re
import shutil
import sys
import time
from datetime import datetime
from multiprocessing import current_process
from pathlib import Path
from typing import Any, Optional, TypedDict, Union

from loguru import logger

from logflow import discovery
from logflow.config import load_config
from logflow.intercept import setup_interception


class State(TypedDict):
    configured: bool
    log_file: Optional[Path]


_STATE: State = {
    "configured": False,
    "log_file": None,
}


def _reset_state() -> None:
    _STATE["configured"] = False
    _STATE["log_file"] = None
    logger.remove()


def _rotate(path: Path, retention: int = 5) -> None:
    """Manual rotation of an existing log file (Main process only)."""
    if not path.exists() or path.stat().st_size == 0 or discovery.get_rank() not in (None, 0):
        return

    timestamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d_%H-%M-%S")
    rotated_path = path.parent / f"{path.stem}.{timestamp}{path.suffix}"

    try:
        path.rename(rotated_path)
        pattern = re.escape(path.stem) + r"\.\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}" + re.escape(path.suffix)
        candidates = sorted(
            [p for p in path.parent.iterdir() if p.is_file() and re.fullmatch(pattern, p.name)],
            key=lambda p: (p.stat().st_mtime, p.name),
            reverse=True,
        )
        for old in candidates[retention:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception:
        pass


def _perform_pivot(current_log: Path, new_log: Path, do_rotation: bool, retention: int) -> None:
    """Transition from an interim log file to a final target file."""
    logger.remove()
    try:
        logger.complete()
    except Exception:
        pass

    if do_rotation:
        _rotate(new_log, retention)

    if current_log.exists():
        try:
            shutil.copy2(current_log, new_log)
            time.sleep(0.05)
            current_log.unlink()
        except Exception:
            pass
    _STATE["configured"] = False


def configure_logging(
    log_dir: Optional[Union[str, Path]] = None,
    script_name: Optional[str] = None,
    file_level: Optional[str] = None,
    console_level: Optional[str] = None,
    rotation_on_startup: Optional[bool] = None,
    retention: Optional[int] = None,
    enqueue: Optional[bool] = None,
    force: bool = False,
) -> None:
    """
    Configure the global LogFlow system with Atomic Pivot support.
    """
    is_main_proc = current_process().name == "MainProcess" and discovery.get_rank() in (None, 0)

    if _STATE["configured"] and not force:
        return

    # 1. Resolve Parameters
    cfg = load_config()
    log_dir_path = Path(log_dir or os.getenv("LOGFLOW_DIR") or cfg.get("log_dir") or "./logs").expanduser().resolve()
    log_dir_path.mkdir(parents=True, exist_ok=True)

    def resolve(val: Any, env: str, key: str, default: Any) -> Any:
        return val if val is not None else (os.getenv(env) or cfg.get(key) or default)

    f_level = str(resolve(file_level, "LOGFLOW_FILE_LEVEL", "file_level", "DEBUG")).upper()
    c_level = str(resolve(console_level, "LOGFLOW_CONSOLE_LEVEL", "console_level", "INFO")).upper()
    retention_val = int(resolve(retention, "LOGFLOW_RETENTION", "retention", 5))
    do_rotation = bool(resolve(rotation_on_startup, "LOGFLOW_ROTATION_ON_STARTUP", "rotation_on_startup", True))

    target_name = discovery.determine_script_name(resolve(script_name, "LOGFLOW_SCRIPT_NAME", "script_name", None))
    new_log_file = log_dir_path / f"{target_name}.log"

    # 2. PIVOT & ROTATION
    if is_main_proc:
        curr = _STATE["log_file"]
        if curr and new_log_file.resolve() != curr.resolve():
            _perform_pivot(curr, new_log_file, do_rotation, retention_val)
        elif do_rotation and not _STATE["configured"] and new_log_file.exists():
            _rotate(new_log_file, retention_val)

    # 3. Setup Sinks
    def rank_filter(record: Any) -> bool:
        r = discovery.get_rank()
        record["extra"]["rank_tag"] = f"[rank {r}] | " if r and r > 0 else ""
        return True

    if not _STATE["configured"]:
        logger.remove()
        fmt = (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "{extra[rank_tag]}<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        )
        logger.add(sys.stderr, level=c_level, format=fmt, filter=rank_filter, colorize=True)

    file_fmt = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {extra[rank_tag]}{name}:{function}:{line} | {message}"
    logger.add(
        str(new_log_file),
        level=f_level,
        format=file_fmt,
        filter=rank_filter,
        enqueue=bool(enqueue),
        mode="a",
    )

    was_cfg = _STATE["configured"]
    _STATE.update({"log_file": new_log_file, "configured": True})
    setup_interception()

    if is_main_proc:
        os.environ.update({"_LOGFLOW_CONFIGURED": "1", "LOGFLOW_SCRIPT_NAME": target_name})
        time.sleep(0.05)
        # Global retention cleanup
        lfs = sorted(
            [f for f in log_dir_path.glob("*.log") if f.is_file() and f.resolve() != new_log_file.resolve()],
            key=os.path.getmtime,
            reverse=True,
        )
        for f in lfs[retention_val - 1 :]:
            try:
                f.unlink()
            except Exception:
                pass
        logger.info(f"LogFlow {'Re-' if was_cfg else ''}initialized: {new_log_file.name}")


def shutdown_logging() -> None:
    try:
        logger.complete()
    except Exception:
        pass


def get_logger(name: Optional[str] = None) -> Any:
    if not _STATE["configured"]:
        configure_logging()
    return logger.bind(name=name) if name else logger
