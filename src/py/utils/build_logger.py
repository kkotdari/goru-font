#!/usr/bin/env python3
"""
Goru Font Builder — BuildLogger interface
Defines the contract for all build pipeline display and file logging.
"""

from abc import ABC, abstractmethod
from enum import IntEnum
from typing import List, Tuple


class LogLevel(IntEnum):
    ERROR   = 10
    WARNING = 20
    INFO    = 30
    SUCCESS = 35
    DEBUG   = 40


class BuildLogger(ABC):
    """Contract for all build pipeline display and logging."""

    progress_active: bool  # must be maintained by implementations

    @classmethod
    def create(cls, **kwargs) -> "BuildLogger":
        from src.py.utils.default_build_logger import DefaultBuildLogger
        return DefaultBuildLogger(**kwargs)

    @abstractmethod
    def print_banner(self, title: str, art_lines: List[str], subtitle: str) -> None: ...

    @abstractmethod
    def print_profile(self, label: str, idx: int, total: int,
                      profiles: List[str] = None) -> None: ...

    @abstractmethod
    def update_profile_elapsed(self, elapsed: float) -> None: ...

    @abstractmethod
    def print_build_summary(self, results: List[Tuple[str, int]]) -> None: ...

    @abstractmethod
    def stage(self, n: int, total: int, name: str) -> None: ...

    @abstractmethod
    def config_file(self, config_type: str, filename: str) -> None: ...

    @abstractmethod
    def info(self, msg: str) -> None: ...

    @abstractmethod
    def success(self, msg: str) -> None: ...

    @abstractmethod
    def warning(self, msg: str) -> None: ...

    @abstractmethod
    def error(self, msg: str) -> None: ...

    @abstractmethod
    def debug(self, msg: str) -> None: ...

    @abstractmethod
    def file_log(self, msg: str, level: str = "DEBUG") -> None: ...

    @abstractmethod
    def progress_bar(self, current: int, total: int, prefix: str = "",
                     static_prefix: str = "") -> None: ...

    @abstractmethod
    def stop_progress(self) -> None: ...

    @abstractmethod
    def start_parallel_progress(self, styles: List[str], progress_queue,
                                languages: List[str] = None) -> None: ...

    @abstractmethod
    def stop_parallel_progress(self) -> None: ...

    @abstractmethod
    def summary_table(self, results: List[Tuple[str, bool, str]],
                      elapsed: float) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
