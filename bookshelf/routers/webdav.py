"""Minimal WebDAV server (class 1 subset) for KOReader's cloud storage and sync.

Each user gets one flat folder at ``/webdav/``, authenticated with HTTP Basic. KOReader uses it
to sync ``statistics.sqlite3``: GET (with ETag), merge on the device, PUT with ``If-Match``.
Supported methods: OPTIONS, PROPFIND, GET, HEAD, PUT, DELETE. Sub-folders are not supported.
"""

from __future__ import annotations

from datetime import datetime
from email.utils import format_datetime
from urllib.parse import quote
from xml.sax.saxutils import escape

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response

from ..deps import AppSettings, AppStorage, BasicAuthUser
from ..models import User
from ..services.files import FileStore, PreconditionFailed, StoredFile, is_valid_name
from ..storage import Storage

router = APIRouter(prefix="/webdav", tags=["webdav"])

PREFIX = "/webdav/"
ALLOWED_METHODS = "OPTIONS, PROPFIND, GET, HEAD, PUT, DELETE"


def _store(storage: Storage, user: User) -> FileStore:
    return FileStore(storage.user_files_dir(user.id))


def _file_name(name: str) -> str:
    """Validate the path below /webdav/; only plain file names are allowed."""
    name = name.strip("/")
    if "/" in name:
        raise HTTPException(status_code=409, detail="Folders are not supported.")
    if not is_valid_name(name):
        raise HTTPException(status_code=400, detail="Invalid file name.")
    return name


# --- PROPFIND ---------------------------------------------------------------------------------


def _http_date(value: datetime) -> str:
    return format_datetime(value, usegmt=True)


def _response_xml(href: str, props: str) -> str:
    return (
        f"<D:response><D:href>{escape(href)}</D:href><D:propstat><D:prop>{props}</D:prop>"
        "<D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"
    )


def _collection_xml(files: list[StoredFile]) -> str:
    modified = max((f.modified for f in files), default=None)
    props = (
        "<D:displayname>Bookshelf</D:displayname><D:resourcetype><D:collection/></D:resourcetype>"
    )
    if modified:
        props += f"<D:getlastmodified>{_http_date(modified)}</D:getlastmodified>"
    return _response_xml(PREFIX, props)


def _file_xml(file: StoredFile) -> str:
    props = (
        f"<D:displayname>{escape(file.name)}</D:displayname><D:resourcetype/>"
        f"<D:getcontentlength>{file.size}</D:getcontentlength>"
        "<D:getcontenttype>application/octet-stream</D:getcontenttype>"
        f"<D:getlastmodified>{_http_date(file.modified)}</D:getlastmodified>"
        f"<D:getetag>{escape(file.etag)}</D:getetag>"
    )
    return _response_xml(PREFIX + quote(file.name), props)


def _multistatus(responses: list[str]) -> Response:
    body = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<D:multistatus xmlns:D="DAV:">{"".join(responses)}</D:multistatus>'
    )
    return Response(body, status_code=207, media_type='application/xml; charset="utf-8"')


# --- Endpoints --------------------------------------------------------------------------------


@router.options("/{name:path}")
def options(name: str) -> Response:
    return Response(headers={"DAV": "1", "Allow": ALLOWED_METHODS, "MS-Author-Via": "DAV"})


@router.api_route("/{name:path}", methods=["PROPFIND"])
def propfind(request: Request, name: str, user: BasicAuthUser, storage: AppStorage) -> Response:
    store = _store(storage, user)
    if not name.strip("/"):
        files = store.list()
        responses = [_collection_xml(files)]
        if request.headers.get("depth", "1") != "0":
            responses += [_file_xml(file) for file in files]
        return _multistatus(responses)
    file = store.get(_file_name(name))
    if file is None:
        raise HTTPException(status_code=404, detail="Not found.")
    return _multistatus([_file_xml(file)])


@router.api_route("/{name:path}", methods=["GET", "HEAD"])
def download(name: str, user: BasicAuthUser, storage: AppStorage) -> Response:
    store = _store(storage, user)
    if not name.strip("/"):
        return PlainTextResponse("\n".join(file.name for file in store.list()))
    file = store.get(_file_name(name))
    if file is None:
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(
        file.path,
        media_type="application/octet-stream",
        headers={"ETag": file.etag, "Cache-Control": "no-cache"},
    )


@router.put("/{name:path}")
async def upload(
    request: Request,
    name: str,
    user: BasicAuthUser,
    storage: AppStorage,
    settings: AppSettings,
) -> Response:
    name = _file_name(name)
    store = _store(storage, user)
    temp_path = store.new_temp_path()
    try:
        size = 0
        with temp_path.open("wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="File too large.")
                out.write(chunk)
        # No awaits from here on: check-and-replace is atomic within the event loop.
        created = store.commit(
            temp_path,
            name,
            if_match=request.headers.get("if-match"),
            if_none_match=request.headers.get("if-none-match"),
        )
    except PreconditionFailed:
        return Response(status_code=412)
    finally:
        temp_path.unlink(missing_ok=True)
    stored = store.get(name)
    headers = {"ETag": stored.etag} if stored else {}
    return Response(status_code=201 if created else 204, headers=headers)


@router.delete("/{name:path}")
def delete(name: str, user: BasicAuthUser, storage: AppStorage) -> Response:
    if not _store(storage, user).delete(_file_name(name)):
        raise HTTPException(status_code=404, detail="Not found.")
    return Response(status_code=204)


@router.api_route("/{name:path}", methods=["MKCOL", "MOVE", "COPY", "LOCK", "PROPPATCH"])
def unsupported(name: str, user: BasicAuthUser) -> Response:
    return Response(status_code=405, headers={"Allow": ALLOWED_METHODS})
