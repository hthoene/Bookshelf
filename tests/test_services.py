import hashlib
from pathlib import Path

from bookshelf.services.hashing import filename_md5, partial_md5
from bookshelf.services.metadata import extract_metadata
from bookshelf.services.metadata.base import from_filename, html_to_text


def test_partial_md5_samples_koreader_offsets(tmp_path: Path) -> None:
    data = bytes(range(256)) * 20  # 5120 bytes
    path = tmp_path / "book.bin"
    path.write_bytes(data)
    # Offsets 0, 1024, 4096 are inside the file; 16384 is past the end.
    expected = hashlib.md5(data[0:1024] + data[1024:2048] + data[4096:5120]).hexdigest()
    assert partial_md5(path) == expected


def test_filename_md5_uses_basename() -> None:
    assert filename_md5("/mnt/onboard/Books/Emma.epub") == hashlib.md5(b"Emma.epub").hexdigest()


def test_from_filename() -> None:
    meta = from_filename("Jane Austen - Pride and Prejudice.epub")
    assert (meta.author, meta.title) == ("Jane Austen", "Pride and Prejudice")
    assert from_filename("some_book.pdf").title == "some book"


def test_html_to_text() -> None:
    assert html_to_text("<p>One &amp; two</p><p>Three<br>four</p>") == "One & two\n\nThree\n\nfour"


def test_broken_epub_falls_back_to_filename(tmp_path: Path) -> None:
    path = tmp_path / "broken.epub"
    path.write_bytes(b"definitely not a zip")
    meta = extract_metadata(path, "epub", "Ursula K. Le Guin - The Dispossessed.epub")
    assert meta.title == "The Dispossessed"
    assert meta.author == "Ursula K. Le Guin"
