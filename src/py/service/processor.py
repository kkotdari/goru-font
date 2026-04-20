#!/usr/bin/env python3
"""
Goru Font Builder — Processor interface
Defines the contract for build orchestration.
"""

from abc import ABC, abstractmethod


class Processor(ABC):
    """Contract for the top-level build orchestration (profile loading → build loop)."""

    @abstractmethod
    def init(self, args) -> int:
        """Entry point: accept CLI args, build all requested profiles, return exit code."""
        ...

    @classmethod
    def create(cls) -> "Processor":
        from src.py.service.default_processor import DefaultProcessor
        return DefaultProcessor()
