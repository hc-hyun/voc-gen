"""Extensible synthetic dataset generation package."""

from .core.profiles import DatasetProfile, load_dataset_profile
from .core.registry import get_adapter

__all__ = ["DatasetProfile", "get_adapter", "load_dataset_profile"]
