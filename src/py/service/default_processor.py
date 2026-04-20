#!/usr/bin/env python3
"""
Goru Font Builder — DefaultProcessor
Default implementation of Processor: config loading, validation, and build orchestration.
"""

import os
import sys
import signal
import atexit
import shutil
import yaml
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional

from src.py.service.processor import Processor

# ── Bootstrap ─────────────────────────────────────────────────────────────────
# Walk up from __file__ to find the 'src/' directory — robust to file moves.
# "configs/paths.yaml" relative to src/ is the one unavoidable string constant.

def _find_src_dir() -> Path:
    p = Path(__file__).resolve().parent
    while p.name != "src":
        if p == p.parent:
            raise RuntimeError(f"Cannot locate 'src/' directory from {__file__}")
        p = p.parent
    return p

_SRC_DIR  = _find_src_dir()
_BASE_DIR = _SRC_DIR.parent

# GORU_PATHS_FILE env var overrides the paths file location for alternate deployments.
_PATHS_FILE = (
    Path(os.environ["GORU_PATHS_FILE"]).resolve()
    if "GORU_PATHS_FILE" in os.environ
    else _SRC_DIR / "configs" / "paths.yaml"
)

_REQUIRED_PATH_KEYS   = ["source_fonts", "templates", "output", "logs", "temp", "backups", "profile_registry"]
_REQUIRED_CONFIG_DIRS = ["font", "build", "logging"]


def _load_yaml_raw(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_paths() -> dict:
    if not _PATHS_FILE.exists():
        print(f"ERROR: paths.yaml not found at {_PATHS_FILE}")
        sys.exit(1)
    data = _load_yaml_raw(_PATHS_FILE)
    errors = []
    for k in _REQUIRED_PATH_KEYS:
        if k not in data:
            errors.append(f"  missing key: '{k}'")
    for k in _REQUIRED_CONFIG_DIRS:
        if k not in data.get("config_dirs", {}):
            errors.append(f"  missing config_dirs.{k}")
    if errors:
        print(f"ERROR: paths.yaml is incomplete ({_PATHS_FILE}):")
        for e in errors:
            print(e)
        sys.exit(1)
    return data


_PATHS = _load_paths()

SOURCE_DIR    = _BASE_DIR / _PATHS["source_fonts"]
TEMPLATES_DIR = _BASE_DIR / _PATHS["templates"]
OUTPUT_DIR    = _BASE_DIR / _PATHS["output"]
LOGS_DIR      = _BASE_DIR / _PATHS["logs"]
TEMP_DIR      = _BASE_DIR / _PATHS["temp"]
BACKUPS_DIR   = _BASE_DIR / _PATHS["backups"]

_CONFIG_TYPE_DIRS: dict = {k: _BASE_DIR / v for k, v in _PATHS["config_dirs"].items()}
_PROFILE_REGISTRY: Path = _BASE_DIR / _PATHS["profile_registry"]


# ──────────────────────────── Config loading ────────────────────────────

def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_with_extends(directory: Path, filename: str, _seen: set = None) -> dict:
    """Load a YAML file and recursively merge any 'extends' base file."""
    if _seen is None:
        _seen = set()
    if filename in _seen:
        print(f"WARNING: circular extends detected for {filename}")
        return {}
    _seen.add(filename)

    path = directory / filename
    if not path.exists():
        return {}

    data = _load_yaml(path)
    if "extends" in data:
        base_file = data.pop("extends")
        base_data = _load_with_extends(directory, base_file, _seen)
        data = _deep_merge(base_data, data)
    return data


def load_config(profile: Optional[str] = None, logger=None) -> dict:
    """
    Load merged configuration from the profile registry and optional profile override.

    Config lookup order:
      1. profile_registry defines default filenames per config type
      2. If --profile is given, its per-type overrides replace the defaults
      3. Each file is loaded with 'extends' inheritance support
    """
    if not _PROFILE_REGISTRY.exists():
        print(f"ERROR: profile registry not found at {_PROFILE_REGISTRY}")
        sys.exit(1)

    registry = _load_yaml(_PROFILE_REGISTRY)
    config_files = dict(registry.get("configs", {}))

    if profile:
        profiles = registry.get("profiles", {})
        if profile in profiles:
            config_files.update(profiles[profile])
        else:
            available = ", ".join(profiles.keys())
            if logger:
                logger.warning(f"profile '{profile}' not found. Available: {available}")
            else:
                print(f"    ⚠ profile '{profile}' not found. Available: {available}")

    merged: dict = {}
    for config_type, directory in _CONFIG_TYPE_DIRS.items():
        filename = config_files.get(config_type)
        if not filename:
            if logger:
                logger.warning(f"no {config_type} config specified")
            else:
                print(f"    ⚠ no {config_type} config specified")
            continue
        path = directory / filename
        if not path.exists():
            if logger:
                logger.warning(f"{config_type} config not found: {path}")
            else:
                print(f"    ⚠ {config_type} config not found: {path}")
            continue
        if logger:
            logger.config_file(config_type, filename)
        else:
            print(f"    Loading [{config_type}]: {filename}")
        data = _load_with_extends(directory, filename)
        merged = _deep_merge(merged, data)

    return merged


# ──────────────────────────── Config validation ────────────────────────────

_REQUIRED_CONFIG = [
    ("font",    "family"),
    ("font",    "family_short"),
    ("font",    "version"),
    ("font",    "copyright"),
    ("metrics", "em_ascent"),
    ("metrics", "em_descent"),
    ("metrics", "win_ascent"),
    ("metrics", "win_descent"),
    ("width",   "half_width"),
    ("width",   "full_width"),
    ("width",   "threshold"),
]

_REQUIRED_LANG_SCALE = ("half_width_x", "half_width_y", "full_width_x", "full_width_y")


def _validate_config(config: dict) -> list:
    """Return a list of error strings describing missing required fields. Empty = OK."""
    errors = []

    for *parents, key in _REQUIRED_CONFIG:
        node = config
        path = ".".join(parents + [key])
        ok = True
        for p in parents:
            if not isinstance(node, dict) or p not in node:
                ok = False
                break
            node = node[p]
        if not ok or not isinstance(node, dict) or key not in node:
            errors.append(f"  missing required field: {path}")

    languages = config.get("languages")
    if not isinstance(languages, dict) or not languages:
        errors.append("  missing required section: languages")
        return errors

    enabled = [
        (name, cfg) for name, cfg in languages.items()
        if isinstance(cfg, dict) and cfg.get("enabled", True)
    ]
    if not enabled:
        errors.append("  no languages are enabled")
        return errors

    for lang_name, lang_cfg in enabled:
        for field in ("template", "dir"):
            if not lang_cfg.get(field):
                errors.append(f"  languages.{lang_name}.{field}: required")
        src = lang_cfg.get("source_files") or {}
        if not src:
            errors.append(f"  languages.{lang_name}.source_files: required")
        else:
            for sk in ("regular", "bold", "italic", "bold_italic"):
                if sk not in src:
                    errors.append(f"  languages.{lang_name}.source_files.{sk}: required")
        scale = lang_cfg.get("scale") or {}
        for k in _REQUIRED_LANG_SCALE:
            if k not in scale:
                errors.append(f"  languages.{lang_name}.scale.{k}: required")

    return errors


# ──────────────────────────── Logger setup ────────────────────────────

def _setup_logger(config: dict):
    from src.py.utils.build_logger import BuildLogger

    log_cfg = config.get("logging", {})
    log_cfg["font_version"] = config["font"]["version"]

    raw_dir = log_cfg.get("log_dir")
    log_cfg["log_dir"] = str(_BASE_DIR / raw_dir) if raw_dir else str(LOGS_DIR)

    return BuildLogger.create(**log_cfg)


# ──────────────────────────── Font validation ────────────────────────────

def _validate_fonts(config: dict, styles: list) -> list:
    """Return list of missing-font error strings (empty = all OK)."""
    errors = []
    for lang, lang_cfg in config["languages"].items():
        if not (isinstance(lang_cfg, dict) and lang_cfg.get("enabled", True)):
            continue
        lang_sources = lang_cfg["source_files"]
        lang_dir = SOURCE_DIR / lang_cfg["dir"]
        for style in styles:
            fname = lang_sources.get(style)
            if not fname:
                errors.append(f"  [{lang}] {style}: not specified in source_files")
            elif not (lang_dir / fname).exists():
                errors.append(f"  [{lang}] {style}: file not found ({lang_dir / fname})")
    return errors


def _build_fonts_dict(config: dict) -> dict:
    """Build the {lang_style: Path} mapping passed to build functions."""
    fonts: dict = {}
    for lang, lang_cfg in config["languages"].items():
        if not (isinstance(lang_cfg, dict) and lang_cfg.get("enabled", True)):
            continue
        lang_dir = SOURCE_DIR / lang_cfg["dir"]
        lang_sources = lang_cfg["source_files"]
        for style_key in ("regular", "bold", "italic", "bold_italic"):
            fname = lang_sources.get(style_key)
            if fname:
                fonts[f"{lang}_{style_key}"] = lang_dir / fname
    return fonts


# ──────────────────────────── Temp directory ────────────────────────────

def _make_temp_dir() -> Path:
    """Create a timestamped subdirectory in temp/ for this build run."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    build_temp = TEMP_DIR / f"build_{stamp}"
    build_temp.mkdir(parents=True, exist_ok=True)
    return build_temp


def _cleanup_temp(build_temp: Path) -> None:
    """Remove build temp dir and the parent temp/ dir if it becomes empty."""
    try:
        if build_temp.exists():
            shutil.rmtree(build_temp, ignore_errors=True)
        if TEMP_DIR.exists() and not any(TEMP_DIR.iterdir()):
            TEMP_DIR.rmdir()
    except Exception:
        pass


def _register_cleanup(build_temp: Path, logger) -> None:
    """Register temp cleanup for both normal exit and signals."""
    def _on_exit():
        _cleanup_temp(build_temp)

    def _on_signal(sig, frame):
        if logger:
            try:
                logger.warning("Interrupted — cleaning up temp files...")
            except Exception:
                pass
        _cleanup_temp(build_temp)
        sys.exit(0)

    atexit.register(_on_exit)
    signal.signal(signal.SIGINT, _on_signal)
    try:
        signal.signal(signal.SIGTERM, _on_signal)
    except (OSError, ValueError):
        pass  # SIGTERM not always available on Windows


# ──────────────────────────── Single-profile build ────────────────────────────

def _build_one_profile(args, profile: Optional[str]) -> int:
    """Load, validate, and run the full build for a single profile."""
    from src.py.utils.build_logger import BuildLogger
    _disp = BuildLogger.create(log_to_file=False)
    try:
        config = load_config(profile, logger=_disp)
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: failed to load configuration: {e}")
        traceback.print_exc()
        return 1

    config_errors = _validate_config(config)
    if config_errors:
        print("ERROR: configuration is incomplete — cannot start build:")
        for e in config_errors:
            print(e)
        return 1

    logger = _setup_logger(config)
    _profile_start = datetime.now()

    try:
        from src.py.service.builder import Builder as IBuilder

        raw_styles = getattr(args, "styles", None) or config.get("build", {}).get("styles", "all")
        if isinstance(raw_styles, str):
            styles = ["regular", "bold", "italic", "bold_italic"] if raw_styles == "all" else [raw_styles]
        elif isinstance(raw_styles, list):
            styles = ["regular", "bold", "italic", "bold_italic"] if "all" in raw_styles else list(raw_styles)
        else:
            styles = ["regular", "bold", "italic", "bold_italic"]

        font_errors = _validate_fonts(config, styles)
        if font_errors:
            logger.error("Font file validation failed — missing files:")
            for e in font_errors:
                logger.error(e)
            return 1
        logger.success("Font validation passed")

        fonts = _build_fonts_dict(config)
        config["build"]["styles"] = styles

        config["_runtime"] = {
            "templates_dir": str(TEMPLATES_DIR).replace("\\", "/"),
            "output_dir":    str(OUTPUT_DIR).replace("\\", "/"),
            "backups_dir":   str(BACKUPS_DIR).replace("\\", "/"),
        }

        build_temp = _make_temp_dir()
        _register_cleanup(build_temp, logger)

        return IBuilder.create().run_build(
            args=args,
            config=config,
            logger=logger,
            src_dir=_SRC_DIR,
            temp_dir=build_temp,
            styles=styles,
            fonts=fonts,
        )

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.debug(traceback.format_exc())
        return 1
    finally:
        elapsed = (datetime.now() - _profile_start).total_seconds()
        logger.update_profile_elapsed(elapsed)
        logger.close()


# ──────────────────────────── DefaultProcessor ────────────────────────────

class DefaultProcessor(Processor):
    """Runs one or more profiles sequentially, printing profile headers and a final summary."""

    def init(self, args) -> int:
        import copy
        from src.py.utils.build_logger import BuildLogger

        _disp = BuildLogger.create(log_to_file=False)

        raw = getattr(args, "profile", None)
        profile_list: list = raw if isinstance(raw, list) else ([raw] if raw else [None])
        total = len(profile_list)

        all_labels = [p or "default" for p in profile_list]
        results: list[tuple[str, int]] = []

        for idx, profile in enumerate(profile_list, 1):
            label = profile or "default"
            _disp.print_profile(label, idx, total, all_labels)
            args_copy = copy.copy(args)
            args_copy.profile = profile
            code = _build_one_profile(args_copy, profile)
            results.append((label, code))

        if total > 1:
            _disp.print_build_summary(results)

        return 0 if all(c == 0 for _, c in results) else 1
