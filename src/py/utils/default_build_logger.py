#!/usr/bin/env python3
"""
Goru Font Builder — DefaultBuildLogger
Concrete implementation of IBuildLogger.
"""

import sys
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.py.utils.build_logger import BuildLogger, LogLevel

_R       = "\033[0m"
_B       = "\033[1m"
_I       = "\033[3m"
_DIM     = "\033[2m"
_INV     = "\033[7m"
_NI      = "\033[27m"
_CYAN    = "\033[38;5;116m"
_MAGENTA = "\033[38;5;219m"
_YELLOW  = "\033[38;5;229m"
_GREEN   = "\033[38;5;114m"
_RED     = "\033[38;5;210m"

_RS_GREEN = "color(114)"
_RS_RED   = "color(210)"
_RS_CYAN  = "color(116)"

try:
    from rich.console import Console
    from rich.live import Live
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class DefaultBuildLogger(BuildLogger):
    """Terminal + file logger with hierarchical indentation and optional Rich parallel progress."""

    def __init__(self,
                 console_level: str = "INFO",
                 file_level: str = "DEBUG",
                 log_to_file: bool = True,
                 log_dir=None,
                 use_colors: bool = True,
                 use_rich: bool = False,
                 colors_256=None,
                 font_version: str = None,
                 **kwargs):
        self.console_level   = getattr(LogLevel, console_level.upper(), LogLevel.INFO)
        self.file_level      = getattr(LogLevel, file_level.upper(), LogLevel.DEBUG)
        self.log_to_file     = log_to_file
        self.tty             = sys.stdout.isatty()
        self.use_colors      = use_colors and self.tty
        self.use_rich        = use_rich and RICH_AVAILABLE
        self.progress_active = False
        self._stage_start: Optional[datetime] = None

        self.log_file    = None
        self.file_lock   = threading.Lock()
        self.log_buffer: List[str] = []
        self.buffer_lock = threading.Lock()

        self._par: Dict[str, dict] = {}
        self._prog_thread: Optional[threading.Thread] = None
        self._stop_prog   = threading.Event()
        self._live        = None

        self.console = None
        if self.use_rich:
            self.console = Console(no_color=not self.use_colors, force_terminal=True,
                                   highlight=False, soft_wrap=True)

        if self.log_to_file:
            log_dir = Path(log_dir) if log_dir else Path.cwd() / "logs"
            log_dir.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self.log_file = open(log_dir / f"build_{stamp}.log", "w", encoding="utf-8")
            self._fwrite(f"Log started at {stamp}")
            self._fwrite("-" * 70)

    # ── Top-level display ─────────────────────────────────────────────────

    def print_banner(self, title: str, art_lines: List[str], subtitle: str) -> None:
        print()
        g = f"{_GREEN}{_B}" if self.use_colors else ""
        r = _R if self.use_colors else ""
        print(f"{g}{title}{r}")
        print()
        for line in art_lines:
            print(f"{g}{line}{r}" if self.use_colors else line)
        print()
        print(f"{g}{subtitle}{r}")
        print()

    def print_profile(self, label: str, idx: int, total: int,
                      profiles: List[str] = None) -> None:
        print()
        if profiles:
            parts = []
            for i, p in enumerate(profiles):
                if i < idx - 1:
                    parts.append(f"{_GREEN}{_I}{p}{_R}" if self.use_colors else f"{p}")
                elif i == idx - 1:
                    parts.append(f"{_MAGENTA}{_B}{_I}{p}{_R}" if self.use_colors else f"{p}")
                else:
                    parts.append(f"{_DIM}{p}{_R}" if self.use_colors else p)
            inner = " · ".join(parts)
            hdr = f"{_MAGENTA}{_B}PROFILE {idx}/{total}:{_R}" if self.use_colors else f"PROFILE {idx}/{total}:"
            print(f"{hdr} [ {inner} ]")
        else:
            text = f"PROFILE {idx}/{total} — {label.upper()}"
            print(f"{_MAGENTA}{_B}{text}{_R}" if self.use_colors else text)

    def update_profile_elapsed(self, elapsed: float) -> None:
        dim = _DIM if self.use_colors else ""
        rst = _R   if self.use_colors else ""
        print(f"  {dim}── {elapsed:.1f}s{rst}")

    def print_build_summary(self, results: List[Tuple[str, int]]) -> None:
        bar = "━" * 54
        print()
        print("BUILD SUMMARY")
        print(bar)
        for label, code in results:
            mark   = "✓" if code == 0 else "✗"
            status = "OK" if code == 0 else "FAILED"
            if self.use_colors:
                col = _GREEN if code == 0 else _RED
                print(f"  {col}{mark}{_R}  {label:<24}  {status}")
            else:
                print(f"  {mark}  {label:<24}  {status}")
        print(bar)

    # ── Structural headers ─────────────────────────────────────────────────

    def config_file(self, config_type: str, filename: str) -> None:
        if self.use_colors:
            print(f"  Loading [{config_type}]: {_CYAN}{filename}{_R}")
        else:
            print(f"  Loading [{config_type}]: {filename}")

    def _print_stage_elapsed(self) -> None:
        if self._stage_start is None:
            return
        elapsed = (datetime.now() - self._stage_start).total_seconds()
        dim = _DIM if self.use_colors else ""
        rst = _R   if self.use_colors else ""
        print(f"    {dim}── {elapsed:.1f}s{rst}")

    def stage(self, n: int, total: int, name: str) -> None:
        self._print_stage_elapsed()
        text = f"STAGE {n}/{total}: {name}"
        self._fwrite(f"\n[STAGE] {text}")
        print()
        print(f"  {_CYAN}{_B}{text}{_R}" if self.use_colors else f"  {text}")
        self._stage_start = datetime.now()

    # ── Core log methods ───────────────────────────────────────────────────

    def _out(self, line: str, level: LogLevel = LogLevel.INFO) -> None:
        if self.log_to_file and level <= self.file_level:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            self._fwrite(f"[{stamp}] {line.lstrip()}")
        if level > self.console_level:
            return
        if self.progress_active:
            with self.buffer_lock:
                self.log_buffer.append(line)
        else:
            print(line)

    def info(self, msg: str) -> None:
        self._out(f"    {msg}")

    def success(self, msg: str) -> None:
        mark = f"{_GREEN}✓{_R}" if self.use_colors else "✓"
        self._out(f"    {mark} {msg}", LogLevel.SUCCESS)

    def warning(self, msg: str) -> None:
        mark = f"{_YELLOW}⚠{_R}" if self.use_colors else "⚠"
        self._out(f"    {mark} {msg}", LogLevel.WARNING)

    def error(self, msg: str) -> None:
        mark = f"{_RED}✗{_R}" if self.use_colors else "✗"
        self._out(f"    {mark} {msg}", LogLevel.ERROR)

    def debug(self, msg: str) -> None:
        line = (f"    {_DIM}[debug] {msg}{_R}" if self.use_colors
                else f"    [debug] {msg}")
        self._out(line, LogLevel.DEBUG)

    def file_log(self, msg: str, level: str = "DEBUG") -> None:
        log_level = getattr(LogLevel, level.upper(), LogLevel.DEBUG)
        if not self.log_to_file or log_level > self.file_level:
            return
        if "PROGRESS:" in msg.upper():
            return
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self._fwrite(f"[{stamp}] [{level}] {msg}")

    # ── Sequential progress bar ────────────────────────────────────────────

    def progress_bar(self, current: int, total: int, prefix: str = "",
                     static_prefix: str = "") -> None:
        if not self.progress_active:
            self.progress_active = True
        prefix  = prefix or "Processing"
        percent = int(current / total * 100) if total > 0 else 0
        filled  = int(len(prefix) * percent / 100)
        if self.tty and filled > 0:
            bar = f"{_INV}{prefix[:filled]}{_NI}{prefix[filled:]}"
        else:
            bar = prefix
        sys.stdout.write(f"\r    {static_prefix}{bar} · {percent}% ({current}/{total})")
        sys.stdout.flush()
        if current >= total:
            print()
            self._flush_buffer()
            self.progress_active = False

    def stop_progress(self) -> None:
        if self.progress_active:
            print()
            self._flush_buffer()
            self.progress_active = False

    # ── Parallel progress display (Rich) ──────────────────────────────────

    def start_parallel_progress(self, styles: List[str], progress_queue,
                                languages: List[str] = None) -> None:
        if not self.use_rich:
            return
        self._par = {
            s: {"step": "", "phase": "Initializing", "current": 0,
                "total": 0, "complete": False, "error": False,
                "done_steps": [], "all_steps": list(languages or [])}
            for s in styles
        }
        self._par_start = datetime.now()
        self._stop_prog.clear()
        self._prog_thread = threading.Thread(
            target=self._drain_queue, args=(progress_queue,), daemon=True)
        self._prog_thread.start()
        self._live = Live(self._render(), console=self.console,
                          refresh_per_second=20, transient=False)
        self._live.start()

    def _render(self) -> "Text":
        t   = Text()
        sep = " · "
        c   = _RS_CYAN  if self.use_colors else ""
        ok  = _RS_GREEN if self.use_colors else "bold"
        err = _RS_RED   if self.use_colors else "reverse"

        for style, s in self._par.items():
            t.append("    ")
            t.append(f"{style:<15}", style=c)
            t.append(sep)

            all_steps  = s["all_steps"]
            done_steps = s["done_steps"]
            curr_step  = s["step"]

            if all_steps:
                t.append("[ ")
                for i, lang in enumerate(all_steps):
                    if i > 0:
                        t.append(sep)
                    if lang in done_steps:
                        t.append(lang, style=f"italic {ok}" if self.use_colors else "italic")
                    elif lang == curr_step and not s["complete"] and not s["error"]:
                        t.append(lang, style=f"bold italic {c}" if self.use_colors else "bold italic")
                    else:
                        t.append(lang, style="dim")
                t.append(" ]")
                t.append(sep)

            if s["complete"]:
                t.append("✓\n", style=ok)
            elif s["error"]:
                t.append("✗ " + s["phase"].replace("Error: ", "") + "\n", style=err)
            else:
                phase = s["phase"]
                cur   = s["current"]
                tot   = s["total"]
                if tot > 0 and "processing" in phase.lower():
                    pct    = int(cur / tot * 100)
                    filled = int(len(phase) * pct / 100)
                    if filled > 0:
                        t.append(phase[:filled], style="reverse")
                    if filled < len(phase):
                        t.append(phase[filled:])
                    t.append(f"{sep}{pct}%\n", style="dim")
                else:
                    t.append(phase + "\n")

        return t

    def _drain_queue(self, q) -> None:
        while not self._stop_prog.is_set():
            try:
                msg  = q.get(timeout=0.1)
                styl = msg.get("style")
                if styl not in self._par:
                    continue
                s  = self._par[styl]
                mt = msg.get("type")
                if mt == "step_start":
                    prev = s["step"]
                    if prev and prev not in s["done_steps"]:
                        s["done_steps"].append(prev)
                    s["step"]  = msg.get("step", "")
                    s["phase"] = f"{s['step']}..."
                elif mt == "progress":
                    s["current"] = msg.get("current", 0)
                    s["total"]   = msg.get("total", 0)
                    if "phase" in msg:
                        s["phase"] = msg["phase"]
                elif mt == "phase":
                    if msg.get("phase"):
                        s["phase"] = msg["phase"]
                elif mt == "style_complete":
                    if s["step"] and s["step"] not in s["done_steps"]:
                        s["done_steps"].append(s["step"])
                    s["complete"] = True
                    s["phase"]    = "Complete"
                elif mt == "style_error":
                    s["error"] = True
                    s["phase"] = f"Error: {msg.get('error', 'Unknown')}"
                if self._live:
                    self._live.update(self._render())
            except queue.Empty:
                continue
            except Exception:
                pass

    def stop_parallel_progress(self) -> None:
        if self._prog_thread:
            self._stop_prog.set()
            self._prog_thread.join(timeout=1.0)
        if self._live:
            self._live.stop()
            self._live = None

    # ── Per-style summary table ────────────────────────────────────────────

    def summary_table(self, results: List[Tuple[str, bool, str]], elapsed: float = 0) -> None:  # noqa: ARG002
        if not results:
            return
        self._print_stage_elapsed()
        self._stage_start = None
        self._fwrite("\n[SUMMARY]")
        if self.use_rich and self.console:
            from rich.table import Table
            from rich.box import SIMPLE
            t = Table(show_header=False, box=SIMPLE, show_edge=False, padding=(0, 2))
            t.add_column(width=15)
            t.add_column(width=3, justify="center")
            t.add_column(width=40)
            for style, ok, msg in results:
                mark   = "✓" if ok else "✗"
                mstyle = (_RS_GREEN if ok else _RS_RED) if self.use_colors else (
                         "bold" if ok else "reverse")
                detail = "OK" if ok else (msg or "failed").split("\n")[0][:40]
                t.add_row(f"  {style}", f"[{mstyle}]{mark}[/{mstyle}]", detail)
            self.console.print(t)
        else:
            for style, ok, msg in results:
                mark   = "✓" if ok else "✗"
                detail = "OK" if ok else (msg or "failed").split("\n")[0][:40]
                if self.use_colors:
                    col = _GREEN if ok else _RED
                    print(f"    {col}{mark}{_R}  {_CYAN}{style:<15}{_R}  {detail}")
                else:
                    print(f"    {mark}  {style:<15}  {detail}")

    # ── Internal helpers ───────────────────────────────────────────────────

    def _fwrite(self, msg: str) -> None:
        if self.log_file and not self.log_file.closed:
            with self.file_lock:
                self.log_file.write(msg + "\n")
                self.log_file.flush()

    def _flush_buffer(self) -> None:
        with self.buffer_lock:
            for line in self.log_buffer:
                print(line)
            self.log_buffer.clear()

    def close(self) -> None:
        self.stop_parallel_progress()
        if self.log_file and not self.log_file.closed:
            self._fwrite("-" * 70)
            self._fwrite(f"Log ended at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            self.log_file.close()
            self.log_file = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
