"""FictionBook 2: title-info block and embedded base64 cover."""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from xml.etree import ElementTree as ET

from .base import BookMetadata, parse_float, register

NS = {"fb": "http://www.gribuser.ru/xml/fictionbook/2.0"}


@register("fb2")
def extract_fb2(path: Path) -> BookMetadata:
    root = ET.parse(path).getroot()
    info = root.find("fb:description/fb:title-info", NS)
    if info is None:
        return BookMetadata()

    authors = []
    for author in info.findall("fb:author", NS):
        parts = (_text(author, f"fb:{part}") for part in ("first-name", "middle-name", "last-name"))
        name = " ".join(p for p in parts if p) or _text(author, "fb:nickname")
        if name:
            authors.append(name)

    sequence = info.find("fb:sequence", NS)
    annotation = info.find("fb:annotation", NS)
    description = None
    if annotation is not None:
        paragraphs = (" ".join("".join(p.itertext()).split()) for p in annotation)
        description = "\n\n".join(p for p in paragraphs if p) or None

    return BookMetadata(
        title=_text(info, "fb:book-title"),
        author=" & ".join(authors) or None,
        series=sequence.get("name") if sequence is not None else None,
        series_index=parse_float(sequence.get("number")) if sequence is not None else None,
        description=description,
        language=_text(info, "fb:lang"),
        cover=_cover(root, info),
    )


def _text(parent: ET.Element, path: str) -> str | None:
    element = parent.find(path, NS)
    return element.text.strip() if element is not None and element.text else None


def _cover(root: ET.Element, info: ET.Element) -> bytes | None:
    image = info.find("fb:coverpage/fb:image", NS)
    if image is None:
        return None
    # The xlink prefix varies between files, so match any attribute named "href".
    reference = next((v for k, v in image.attrib.items() if k.endswith("href")), "").lstrip("#")
    for binary in root.findall("fb:binary", NS):
        if binary.get("id") == reference and binary.text:
            try:
                return base64.b64decode(binary.text)
            except (binascii.Error, ValueError):
                return None
    return None
