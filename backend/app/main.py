"""FastAPI application: routes for auth, diary entries, transcription, photos."""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import images
from .auth import (
    COOKIE_NAME,
    MAX_AGE_SECONDS,
    check_password,
    issue_cookie_value,
    require_auth,
)
from . import db as db_module
from .cleanup import get_cleaner
from .db import get_conn, init_db
from .storage import get_storage
from .transcription import get_transcriber

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="audio_diary", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Dependencies & schemas
# --------------------------------------------------------------------------- #
def db_dep():
    with get_conn() as conn:
        yield conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class LoginReq(BaseModel):
    password: str


class EntryUpdate(BaseModel):
    entry_date: str | None = None
    raw_text: str | None = None
    clean_text: str | None = None


def _photos_for(conn: sqlite3.Connection, entry_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id FROM photos WHERE entry_id = ? ORDER BY id", (entry_id,)
    ).fetchall()
    return [
        {"id": r["id"], "url": f"/api/photos/{r['id']}", "thumb_url": f"/api/photos/{r['id']}/thumb"}
        for r in rows
    ]


def _entry_out(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "entry_date": row["entry_date"],
        "raw_text": row["raw_text"],
        "clean_text": row["clean_text"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "photos": _photos_for(conn, row["id"]),
    }


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@app.post("/api/login")
def login(body: LoginReq) -> Response:
    if not check_password(body.password):
        raise HTTPException(status_code=401, detail="パスワードが違います")
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        COOKIE_NAME,
        issue_cookie_value(),
        max_age=MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,  # set True when served over HTTPS
    )
    return resp


@app.post("/api/logout")
def logout() -> Response:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME)
    return resp


@app.get("/api/me")
def me(_: None = Depends(require_auth)) -> dict:
    return {"authed": True}


# --------------------------------------------------------------------------- #
# Entries
# --------------------------------------------------------------------------- #
@app.post("/api/entries/transcribe")
async def transcribe_entry(
    audio: UploadFile,
    entry_date: str | None = Form(default=None),
    _: None = Depends(require_auth),
    conn: sqlite3.Connection = Depends(db_dep),
) -> dict:
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="音声データが空です")

    # Transcription and cleanup make blocking network calls; run them off the
    # event loop so the server stays responsive.
    mime = audio.content_type or "audio/webm"
    raw = await run_in_threadpool(get_transcriber().transcribe, data, mime)
    clean = await run_in_threadpool(get_cleaner().clean, raw)

    the_date = entry_date or date.today().isoformat()
    now = _now()
    cur = conn.execute(
        "INSERT INTO entries (entry_date, raw_text, clean_text, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (the_date, raw, clean, now, now),
    )
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _entry_out(conn, row)


@app.get("/api/entries")
def list_entries(
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    _: None = Depends(require_auth),
    conn: sqlite3.Connection = Depends(db_dep),
) -> dict:
    limit = max(1, min(limit, 200))
    query = (q or "").strip()

    if not query:
        rows = conn.execute(
            "SELECT * FROM entries ORDER BY entry_date DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    elif db_module.FTS_ENABLED and len(query) >= 3:
        # FTS5 trigram: wrap as a quoted string for substring matching.
        escaped = query.replace('"', '""')
        rows = conn.execute(
            "SELECT e.* FROM entries e JOIN entries_fts f ON e.id = f.rowid "
            "WHERE entries_fts MATCH ? ORDER BY rank LIMIT ? OFFSET ?",
            (f'"{escaped}"', limit, offset),
        ).fetchall()
    else:
        like = f"%{query}%"
        rows = conn.execute(
            "SELECT * FROM entries WHERE raw_text LIKE ? OR clean_text LIKE ? "
            "ORDER BY entry_date DESC, id DESC LIMIT ? OFFSET ?",
            (like, like, limit, offset),
        ).fetchall()

    return {"entries": [_entry_out(conn, r) for r in rows]}


@app.get("/api/entries/{entry_id}")
def get_entry(
    entry_id: int,
    _: None = Depends(require_auth),
    conn: sqlite3.Connection = Depends(db_dep),
) -> dict:
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="日記が見つかりません")
    return _entry_out(conn, row)


@app.put("/api/entries/{entry_id}")
def update_entry(
    entry_id: int,
    body: EntryUpdate,
    _: None = Depends(require_auth),
    conn: sqlite3.Connection = Depends(db_dep),
) -> dict:
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="日記が見つかりません")

    fields = {
        "entry_date": body.entry_date if body.entry_date is not None else row["entry_date"],
        "raw_text": body.raw_text if body.raw_text is not None else row["raw_text"],
        "clean_text": body.clean_text if body.clean_text is not None else row["clean_text"],
    }
    conn.execute(
        "UPDATE entries SET entry_date = ?, raw_text = ?, clean_text = ?, updated_at = ? "
        "WHERE id = ?",
        (fields["entry_date"], fields["raw_text"], fields["clean_text"], _now(), entry_id),
    )
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    return _entry_out(conn, row)


@app.delete("/api/entries/{entry_id}")
def delete_entry(
    entry_id: int,
    _: None = Depends(require_auth),
    conn: sqlite3.Connection = Depends(db_dep),
) -> dict:
    storage = get_storage()
    photos = conn.execute(
        "SELECT storage_key, thumb_key FROM photos WHERE entry_id = ?", (entry_id,)
    ).fetchall()
    for p in photos:
        storage.delete(p["storage_key"])
        if p["thumb_key"]:
            storage.delete(p["thumb_key"])
    cur = conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="日記が見つかりません")
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Photos
# --------------------------------------------------------------------------- #
@app.post("/api/entries/{entry_id}/photos")
async def add_photo(
    entry_id: int,
    photo: UploadFile,
    _: None = Depends(require_auth),
    conn: sqlite3.Connection = Depends(db_dep),
) -> dict:
    row = conn.execute("SELECT id FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="日記が見つかりません")

    data = await photo.read()
    if not data:
        raise HTTPException(status_code=400, detail="画像が空です")
    try:
        full, thumb = await run_in_threadpool(images.process, data)
    except Exception:
        raise HTTPException(status_code=400, detail="画像の処理に失敗しました")

    now = _now()
    cur = conn.execute(
        "INSERT INTO photos (entry_id, storage_key, thumb_key, created_at) "
        "VALUES (?, '', '', ?)",
        (entry_id, now),
    )
    photo_id = cur.lastrowid
    storage_key = f"{entry_id}/{photo_id}.jpg"
    thumb_key = f"{entry_id}/{photo_id}_thumb.jpg"

    storage = get_storage()
    storage.save(storage_key, full)
    storage.save(thumb_key, thumb)
    conn.execute(
        "UPDATE photos SET storage_key = ?, thumb_key = ? WHERE id = ?",
        (storage_key, thumb_key, photo_id),
    )
    return {
        "id": photo_id,
        "url": f"/api/photos/{photo_id}",
        "thumb_url": f"/api/photos/{photo_id}/thumb",
    }


def _serve_photo(conn: sqlite3.Connection, photo_id: int, thumb: bool) -> Response:
    row = conn.execute(
        "SELECT storage_key, thumb_key FROM photos WHERE id = ?", (photo_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="写真が見つかりません")
    key = row["thumb_key"] if thumb and row["thumb_key"] else row["storage_key"]
    storage = get_storage()
    if not storage.exists(key):
        raise HTTPException(status_code=404, detail="写真ファイルがありません")
    return Response(
        content=storage.load(key),
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.get("/api/photos/{photo_id}")
def get_photo(
    photo_id: int,
    _: None = Depends(require_auth),
    conn: sqlite3.Connection = Depends(db_dep),
) -> Response:
    return _serve_photo(conn, photo_id, thumb=False)


@app.get("/api/photos/{photo_id}/thumb")
def get_photo_thumb(
    photo_id: int,
    _: None = Depends(require_auth),
    conn: sqlite3.Connection = Depends(db_dep),
) -> Response:
    return _serve_photo(conn, photo_id, thumb=True)


@app.delete("/api/photos/{photo_id}")
def delete_photo(
    photo_id: int,
    _: None = Depends(require_auth),
    conn: sqlite3.Connection = Depends(db_dep),
) -> dict:
    row = conn.execute(
        "SELECT storage_key, thumb_key FROM photos WHERE id = ?", (photo_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="写真が見つかりません")
    storage = get_storage()
    storage.delete(row["storage_key"])
    if row["thumb_key"]:
        storage.delete(row["thumb_key"])
    conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Frontend (PWA) — mounted last so /api/* routes take precedence.
# --------------------------------------------------------------------------- #
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
