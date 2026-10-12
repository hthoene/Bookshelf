"""Document identifiers compatible with KOReader's progress sync plugin."""

from __future__ import annotations

import hashlib
from pathlib import Path

_SAMPLE_SIZE = 1024


def partial_md5(path: Path) -> str:
    """KOReader's default "binary" document hash (``util.partialMD5``).

    Hashes 1 KiB samples at offsets 0, 1 KiB, 4 KiB, 16 KiB, … (1024 << 2*i for i = 0..10),
    stopping at the first offset beyond the end of the file.
    """
    digest = hashlib.md5()
    with path.open("rb") as file:
        for i in range(-1, 11):
            file.seek(0 if i < 0 else _SAMPLE_SIZE << (2 * i))
            sample = file.read(_SAMPLE_SIZE)
            if not sample:
                break
            digest.update(sample)
    return digest.hexdigest()


def filename_md5(filename: str) -> str:
    """KOReader's alternative "filename" document hash: MD5 of the file's base name."""
    return hashlib.md5(Path(filename).name.encode()).hexdigest()
