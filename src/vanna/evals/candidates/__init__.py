"""Offline candidate factories for reproducible Vanna evaluation."""

from .sqlite_policy import CANDIDATE_NAME, build_variant

__all__ = ["CANDIDATE_NAME", "build_variant"]
