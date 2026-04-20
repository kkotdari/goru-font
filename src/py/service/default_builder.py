#!/usr/bin/env python3
"""
Goru Font Builder — DefaultBuilder
Default implementation of Builder: FontForge script generation, parallel/sequential
execution, and post-processing.
"""

import sys
import copy
import queue
import shutil
import subprocess
import threading
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from multiprocessing import Manager, Queue
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from jinja2 import Template
from fontTools.ttLib import TTFont

# Ensure project root is in sys.path so multiprocessing workers can import src.*
# __file__ is src/py/service/default_builder.py → .parent×4 = goru-font/
_ROOT = Path(__file__).parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.py.service.builder import Builder
from src.py.utils.build_logger import BuildLogger


# ──────────────────────────── Helpers ────────────────────────────

def save_temp_files(tmpdir: Path, backups_dir: Path, logger: BuildLogger) -> Optional[Path]:
    """Copy temp build scripts to backups/ with timestamp (only if save_temp_files=true)."""
    try:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = backups_dir / f"scripts_{stamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        for item in tmpdir.iterdir():
            dest = backup_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
        logger.info(f"Temp scripts saved to: {backup_dir}")
        return backup_dir
    except Exception as e:
        logger.warning(f"Failed to save temp files: {e}")
        return None


def process_font_file(font_file: Path, logger: BuildLogger, half_width: int) -> bool:
    """Apply monospace metadata (post.isFixedPitch, OS/2 panose, xAvgCharWidth)."""
    try:
        if not font_file.exists():
            logger.warning(f"Font file not found: {font_file.name}")
            return False
        font = TTFont(font_file)
        if "post" in font and hasattr(font["post"], "isFixedPitch"):
            font["post"].isFixedPitch = 1
        if "OS/2" in font:
            os2 = font["OS/2"]
            if hasattr(os2, "panose"):
                os2.panose.bProportion = 9
            if hasattr(os2, "xAvgCharWidth"):
                os2.xAvgCharWidth = half_width
        font.save(font_file)
        return True
    except Exception as e:
        logger.error(f"Error applying metadata to {font_file.name}: {e}")
        return False


# ──────────────────────────── Script generation ────────────────────────────

def _sorted_languages(config: dict) -> List[Tuple[str, dict]]:
    """Return enabled languages sorted by their 'order' field."""
    languages = config.get("languages", {})
    result = []
    for lang_name, lang_cfg in languages.items():
        if isinstance(lang_cfg, dict):
            if lang_cfg.get("enabled", True):
                result.append((lang_name, lang_cfg))
        elif bool(lang_cfg):
            result.append((lang_name, {"enabled": True, "order": 99}))
    result.sort(key=lambda x: x[1].get("order", 99) if isinstance(x[1], dict) else 99)
    return result


_STYLE_KEYS  = ("regular", "bold", "italic", "bold_italic")
_STYLE_NAMES = ("Regular", "Bold", "Italic", "BoldItalic")


def generate_style_scripts(
    style: str,
    config: dict,
    fonts: dict,
    tmpdir: Path,
) -> Dict[str, Path]:
    """Render Jinja2 FontForge templates for one font style."""
    style_tmpdir = tmpdir / style
    style_tmpdir.mkdir(parents=True, exist_ok=True)

    runtime      = config["_runtime"]
    template_dir = Path(runtime["templates_dir"])
    output_dir   = Path(runtime["output_dir"]) / f"v{config['font']['version']}"
    output_dir.mkdir(parents=True, exist_ok=True)

    style_config = copy.deepcopy(config)
    style_config.setdefault("build", {})["styles"] = style

    sorted_langs = _sorted_languages(config)

    all_sfd_paths: Dict[str, List[str]] = {
        lang_name: [
            str(style_tmpdir / f"{lang_name}-{sn}.sfd").replace("\\", "/")
            for sn in _STYLE_NAMES
        ]
        for lang_name, _ in sorted_langs
    }

    base_vars = {
        "tmpdir":     str(style_tmpdir).replace("\\", "/"),
        "output_dir": str(output_dir).replace("\\", "/"),
        "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "logging":    config.get("logging", {}),
        **style_config,
    }

    scripts: Dict[str, Path] = {}

    for lang_name, lang_cfg in sorted_langs:
        template_file = lang_cfg.get("template") if isinstance(lang_cfg, dict) else None
        if not template_file:
            continue

        template_path = template_dir / template_file
        if not template_path.exists():
            continue

        input_files = [
            str(fonts.get(f"{lang_name}_{sk}", "")).replace("\\", "/")
            for sk in _STYLE_KEYS
        ]

        ref_sfds = [
            all_sfd_paths[ref_key]
            for ref_key in (lang_cfg.get("remove_overlaps_with", []) if isinstance(lang_cfg, dict) else [])
            if ref_key in all_sfd_paths
        ]

        lang_vars = {
            **base_vars,
            "lang":        lang_cfg,
            "lang_key":    lang_name,
            "input_files": input_files,
            "output_sfds": all_sfd_paths[lang_name],
            "ref_sfds":    ref_sfds,
        }

        with open(template_path, "r", encoding="utf-8") as f:
            template = Template(f.read())
        script_content = template.render(**lang_vars)
        script_path = style_tmpdir / f"{style}_{lang_name}.pe"
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_content)
        scripts[lang_name] = script_path

    merge_template = config.get("output", {}).get("merge_template", "final_merge.pe.j2")
    merge_path = template_dir / merge_template
    if merge_path.exists():
        sorted_langs_with_sfds = [
            {"key": lname, "cfg": lcfg, "sfd_paths": all_sfd_paths[lname]}
            for lname, lcfg in sorted_langs
        ]
        merge_vars = {**base_vars, "sorted_langs": sorted_langs_with_sfds}
        with open(merge_path, "r", encoding="utf-8") as f:
            template = Template(f.read())
        script_content = template.render(**merge_vars)
        script_path = style_tmpdir / f"{style}_merge.pe"
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_content)
        scripts["merge"] = script_path

    return scripts


# ──────────────────────────── FontForge execution ────────────────────────────

def run_fontforge_with_queue(
    script_path: Path,
    style: str,
    step_name: str,
    progress_queue: Optional[Queue] = None,
    log_queue: Optional[Queue] = None,
    timeout: int = 300,
    logger: Optional[BuildLogger] = None,
) -> Tuple[bool, str]:
    """Execute a FontForge script and route PROGRESS/PHASE/ERROR lines appropriately."""
    try:
        process = subprocess.Popen(
            ["fontforge", "-script", str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        full_log: List[str] = []
        current_phase = "Initializing"
        last_phase_displayed = None

        for line in iter(process.stdout.readline, ""):
            line = line.strip()
            if not line:
                continue
            full_log.append(line)

            is_progress = line.startswith("PROGRESS:")

            if log_queue and not is_progress:
                log_queue.put({"style": style, "step": step_name, "message": line})
            elif logger and not is_progress:
                logger.file_log(f"[{style}:{step_name}] {line}")

            if line.startswith("PHASE:"):
                current_phase = line.replace("PHASE:", "").strip()
                if logger and current_phase != last_phase_displayed:
                    logger.info(f"[{step_name}] {current_phase}")
                    last_phase_displayed = current_phase
                if progress_queue:
                    progress_queue.put({
                        "type": "phase", "style": style,
                        "step": step_name, "phase": current_phase,
                    })

            elif is_progress:
                try:
                    parts = line.split(":")
                    current = int(parts[2])
                    total   = int(parts[3])
                    if progress_queue:
                        progress_queue.put({
                            "type": "progress", "style": style, "step": step_name,
                            "current": current, "total": total, "phase": current_phase,
                        })
                    elif logger:
                        logger.progress_bar(current, total, prefix=current_phase,
                                            static_prefix=f"[{step_name}] ")
                        if current_phase != last_phase_displayed:
                            last_phase_displayed = current_phase
                except (ValueError, IndexError):
                    pass

            elif line.startswith(("STYLE_START:", "STYLE_END:", "GENERATED:")):
                if log_queue:
                    log_queue.put({"style": style, "step": step_name,
                                   "message": line, "important": True})
                elif logger:
                    logger.info(f"[{style}:{step_name}] {line}")

            elif line.startswith("ERROR:") or line.startswith("WARNING:"):
                is_err = line.startswith("ERROR:")
                if log_queue:
                    log_queue.put({"style": style, "step": step_name,
                                   "message": line, "error": is_err})
                elif logger:
                    if is_err and logger.progress_active:
                        logger.stop_progress()
                    if is_err:
                        logger.error(f"[{style}:{step_name}] {line}")
                    else:
                        logger.warning(f"[{style}:{step_name}] {line}")

        retcode = process.wait(timeout=timeout)
        if logger and logger.progress_active:
            logger.stop_progress()
        return retcode == 0, "\n".join(full_log)

    except subprocess.TimeoutExpired:
        process.kill()
        if logger and logger.progress_active:
            logger.stop_progress()
        return False, f"Timeout after {timeout}s"
    except Exception as e:
        if logger and getattr(logger, "progress_active", False):
            logger.stop_progress()
        return False, str(e)


# ──────────────────────────── Per-style processing ────────────────────────────

def process_single_style(
    style: str,
    config: dict,
    fonts: dict,
    tmpdir: Path,
    src_dir: Path,
    progress_queue: Optional[Queue] = None,
    log_queue: Optional[Queue] = None,
    logger: Optional[BuildLogger] = None,
) -> Tuple[str, bool, str]:
    """Generate scripts and run FontForge for one font style end-to-end."""
    root = str(src_dir.parent)
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        scripts = generate_style_scripts(style, config, fonts, tmpdir)

        sorted_langs = _sorted_languages(config)
        steps: List[Tuple[str, Path, int]] = []
        for lang_name, lang_cfg in sorted_langs:
            if lang_name in scripts:
                timeout = lang_cfg.get("timeout", 600) if isinstance(lang_cfg, dict) else 600
                steps.append((lang_name.capitalize(), scripts[lang_name], timeout))
        if "merge" in scripts:
            steps.append(("Merge", scripts["merge"], 600))

        for step_name, script_path, timeout in steps:
            if progress_queue:
                progress_queue.put({"type": "step_start", "style": style, "step": step_name})

            if log_queue:
                log_queue.put({"style": style, "step": step_name,
                               "message": f"=== Starting {step_name} ===", "important": True})

            success, log = run_fontforge_with_queue(
                script_path, style, step_name,
                progress_queue, log_queue, timeout, logger,
            )

            if not success:
                if progress_queue:
                    progress_queue.put({"type": "style_error", "style": style,
                                        "error": f"Step '{step_name}' failed"})
                if log_queue:
                    log_queue.put({"style": style, "step": step_name,
                                   "message": f"=== {step_name} Failed ===", "important": True})
                return style, False, f"Step '{step_name}' failed:\n{log}"

            if log_queue:
                log_queue.put({"style": style, "step": step_name,
                               "message": f"=== {step_name} Completed ===", "important": True})

        if progress_queue:
            progress_queue.put({"type": "style_complete", "style": style})
        elif logger:
            logger.success(f"Style {style} completed")

        return style, True, "Completed successfully"

    except Exception as e:
        if progress_queue:
            progress_queue.put({"type": "style_error", "style": style, "error": str(e)})
        return style, False, f"Unexpected error: {e}\n{traceback.format_exc()}"


# ──────────────────────────── Log queue processor ────────────────────────────

def _process_log_queue(log_queue: Queue, logger: BuildLogger,
                       stop_event: threading.Event) -> None:
    while not stop_event.is_set() or not log_queue.empty():
        try:
            msg     = log_queue.get(timeout=0.1)
            style   = msg.get("style", "unknown")
            step    = msg.get("step", "unknown")
            message = msg.get("message", "")
            is_err  = msg.get("error", False)
            is_key  = msg.get("important", False)

            if "PROGRESS:" in message:
                continue

            level = "ERROR" if is_err else ("INFO" if is_key else "DEBUG")
            logger.file_log(f"[{style}:{step}] {message}", level=level)
        except queue.Empty:
            continue
        except Exception as e:
            logger.file_log(f"[LOG_PROCESSOR] {e}", level="ERROR")


# ──────────────────────────── DefaultBuilder ────────────────────────────

class DefaultBuilder(Builder):
    """Runs FontForge processing, post-processing, and summary for one profile."""

    def run_build(self, args, config: dict, logger: BuildLogger, src_dir: Path,
                  temp_dir: Path, styles: list, fonts: dict) -> int:
        runtime     = config["_runtime"]
        save_temp   = config.get("output", {}).get("save_temp_files", False)
        workers     = getattr(args, "workers", 4)
        sequential  = getattr(args, "sequential", False)
        version_dir = Path(runtime["output_dir"]) / f"v{config['font']['version']}"
        backups_dir = Path(runtime["backups_dir"])

        overall_start = time.time()
        results: List[Tuple[str, bool, str]] = []

        logger.stage(1, 3, "FONTFORGE PROCESSING")

        try:
            if sequential or len(styles) == 1:
                for style in styles:
                    result = process_single_style(
                        style, config, fonts, temp_dir, src_dir,
                        progress_queue=None, log_queue=None, logger=logger,
                    )
                    results.append(result)
                    if not result[1]:
                        logger.error(f"{style} failed: {result[2][:200]}")
            else:
                manager = Manager()
                progress_queue = manager.Queue()
                log_queue      = manager.Queue()

                stop_log = threading.Event()
                log_thread = threading.Thread(
                    target=_process_log_queue,
                    args=(log_queue, logger, stop_log),
                    daemon=True,
                )
                log_thread.start()

                sorted_langs = _sorted_languages(config)
                lang_steps = [n.capitalize() for n, cfg in sorted_langs
                              if isinstance(cfg, dict) and cfg.get("enabled", True)]
                lang_steps.append("Merge")
                logger.start_parallel_progress(styles, progress_queue, lang_steps)

                with ProcessPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(
                            process_single_style,
                            style, config, fonts, temp_dir, src_dir,
                            progress_queue, log_queue,
                        ): style
                        for style in styles
                    }
                    for future in as_completed(futures):
                        style = futures[future]
                        try:
                            result = future.result()
                            results.append(result)
                        except Exception as e:
                            results.append((style, False, f"Worker crashed: {e}"))
                            progress_queue.put({"type": "style_error", "style": style,
                                                "error": "Worker crashed"})

                logger.stop_parallel_progress()
                stop_log.set()
                log_thread.join(timeout=2.0)

            if save_temp:
                save_temp_files(temp_dir, backups_dir, logger)

        except Exception as e:
            logger.error(f"Build stage failed: {e}")
            logger.debug(traceback.format_exc())
            return 1

        logger.stage(2, 3, "POST-PROCESSING")
        successful = [r for r in results if r[1]]

        if successful:
            family_short = config["font"]["family_short"]
            half_width   = config["width"]["half_width"]
            style_filename_map = {
                "regular":     "Regular",
                "bold":        "Bold",
                "italic":      "Italic",
                "bold_italic": "BoldItalic",
            }
            for style, _, __ in successful:
                fname = style_filename_map.get(style, style.capitalize())
                font_file = version_dir / f"{family_short}-{fname}.ttf"
                if font_file.exists():
                    if not process_font_file(font_file, logger, half_width):
                        logger.error(f"Metadata failed for {font_file.name}")
                else:
                    logger.warning(f"Output not found: {font_file.name}")

        logger.stage(3, 3, "SUMMARY")
        logger.summary_table(results, time.time() - overall_start)

        failed = [r for r in results if not r[1]]
        return 0 if not failed else 1
