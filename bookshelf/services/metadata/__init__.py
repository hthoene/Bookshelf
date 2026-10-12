"""Metadata extraction. Each format module registers an extractor via ``@register``.

To support a new format, add a module here with a function decorated by
``@register("<ext>")`` that returns a ``BookMetadata``, and import it below.
"""

from . import comic, epub, fb2, pdf  # noqa: F401  (registers extractors)
from .base import BookMetadata, extract_metadata, register

__all__ = ["BookMetadata", "extract_metadata", "register"]
