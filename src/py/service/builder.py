#!/usr/bin/env python3
"""
Goru Font Builder — Builder interface
Defines the contract for font build execution (FontForge + post-processing).
"""

from abc import ABC, abstractmethod
from pathlib import Path


class Builder(ABC):
    """Contract for executing a single profile build: FontForge → post-process → summary."""

    @abstractmethod
    def run_build(self, args, config: dict, logger, src_dir: Path,
                  temp_dir: Path, styles: list, fonts: dict) -> int:
        """Run the full build pipeline for one profile. Returns exit code."""
        ...

    @classmethod
    def create(cls) -> "Builder":
        from src.py.service.default_builder import DefaultBuilder
        return DefaultBuilder()
