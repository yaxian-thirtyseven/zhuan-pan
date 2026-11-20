import hashlib
import logging
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from .extract import MAX_UPLOAD, extract_items
from .ocr import OCRUnavailable

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.environ.get("WHEEL_DB", str(ROOT / "data" / "wheel.sqlite3")))
ADMIN = "hello_world"
SESSION_TTL = 7 * 24 * 60 * 60
MAX_ITEMS = 500
logger = logging.getLogger(__name__)


@contextmanager
def database():
    connection = sqlite3.connect(DB, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)


@asynccontextmanager
async def lifespan(_app):
    DB.parent.mkdir(parents=True, exist_ok=True)
    generated_password = None
    with database() as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY, salt BLOB NOT NULL, password BLOB NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                admin INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, username TEXT NOT NULL REFERENCES users(username),
                expires INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL REFERENCES users(username),
                text TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS items_by_user ON items(username, id);
            CREATE TABLE IF NOT EXISTS draws (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL REFERENCES users(username),
                text TEXT NOT NULL, drawn_at INTEGER NOT NULL, batch_id INTEGER
            );
            CREATE INDEX IF NOT EXISTS draws_by_user ON draws(username, id);
        """)
        db.execute("BEGIN IMMEDIATE")
        user_columns = {column["name"] for column in db.execute("PRAGMA table_info(users)")}
        if "admin" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN admin INTEGER NOT NULL DEFAULT 0")
        draw_columns = {column["name"] for column in db.execute("PRAGMA table_info(draws)")}
        if "batch_id" not in draw_columns:
            db.execute("ALTER TABLE draws ADD COLUMN batch_id INTEGER")
        db.execute("CREATE INDEX IF NOT EXISTS draws_by_batch ON draws(username, batch_id)")
        if db.execute("PRAGMA user_version").fetchone()[0] < 1:
            # The old schema stored pending and disabled accounts with the same flag.
            db.execute("UPDATE users SET enabled = 1 WHERE enabled = 0")
            db.execute("PRAGMA user_version = 1")
        if not db.execute("SELECT 1 FROM users WHERE username = ?", (ADMIN,)).fetchone():
            initial_password = os.environ.get("WHEEL_ADMIN_PASSWORD")
            if not initial_password:
                initial_password = generated_password = secrets.token_urlsafe(24)
            salt = secrets.token_bytes(16)
            db.execute("INSERT INTO users(username, salt, password, enabled) VALUES (?, ?, ?, 1)",
                       (ADMIN, salt, password_hash(initial_password, salt)))
    if generated_password:
        print(f"管理员 {ADMIN} 的初始密码为 {generated_password}，请保存。", flush=True)
    yield


app = FastAPI(title="转盘工坊", lifespan=lifespan)


class Credentials(BaseModel):
    username: str = Field(max_length=32)
    password: str = Field(max_length=128)


class ItemsInput(BaseModel):
    items: list[str] = Field(max_length=MAX_ITEMS)


class PermissionInput(BaseModel):
    enabled: bool


class AdminRoleInput(BaseModel):
    admin: bool = Field(strict=True)


class DrawInput(BaseModel):
    count: int = Field(default=1, strict=True, ge=1, le=MAX_ITEMS)
    allow_repeats: bool = False


def identity(user):
    owner = user["username"] == ADMIN
    return {"username": user["username"], "enabled": bool(user["enabled"]),
            "admin": owner or bool(user["admin"]), "owner": owner}


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(wheel_session: str | None = Cookie(default=None)):
    if wheel_session:
        with database() as db:
            user = db.execute("""
                SELECT u.* FROM users u JOIN sessions s USING(username)
                WHERE s.token = ? AND s.expires > ?
            """, (token_digest(wheel_session), int(time.time()))).fetchone()
        if user:
            return identity(user)
    raise HTTPException(401, "请先登录")


def permitted(user: dict = Depends(current_user)):
    if not user["enabled"]:
        raise HTTPException(403, "账号已停用")
    return user["username"]


def administrator(user: dict = Depends(current_user)):
    if not user["enabled"]:
        raise HTTPException(403, "账号已停用")
    if not user["admin"]:
        raise HTTPException(403, "此操作需要管理员权限")
    return user


def site_owner(user: dict = Depends(administrator)):
    if not user["owner"]:
        raise HTTPException(403, "仅内置管理员可修改管理员身份")
    return user


@app.get("/api/health")
def health():
    return {"ok": True}


def create_session(db, username):
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db.execute("DELETE FROM sessions WHERE expires <= ?", (now,))
    db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token_digest(token), username, now + SESSION_TTL))
    return token


def set_session_cookie(response: Response, token: str):
    response.set_cookie("wheel_session", token, max_age=SESSION_TTL, httponly=True, samesite="strict")


@app.post("/api/register", status_code=201)
def register(data: Credentials, response: Response):
    username = data.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{3,32}", username):
        raise HTTPException(400, "账号需为 3–32 位英文字母、数字或下划线")
    if (len(data.password) < 6 or not re.search(r"[A-Za-z]", data.password)
            or not re.search(r"[0-9]", data.password)):
        raise HTTPException(400, "密码至少 6 位，且包含英文字母和数字")
    salt = secrets.token_bytes(16)
    try:
        with database() as db:
            db.execute("INSERT INTO users(username, salt, password, enabled) VALUES (?, ?, ?, 1)",
                       (username, salt, password_hash(data.password, salt)))
            token = create_session(db, username)
    except sqlite3.IntegrityError as error:
        raise HTTPException(409, "该账号已存在") from error
    set_session_cookie(response, token)
    return identity({"username": username, "enabled": True, "admin": False})


@app.post("/api/login")
def login(data: Credentials, response: Response):
    username = data.username.strip().lower()
    with database() as db:
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        digest = password_hash(data.password, user["salt"] if user else bytes(16))
        if not user or not secrets.compare_digest(digest, user["password"]):
            raise HTTPException(401, "账号或密码错误")
        token = create_session(db, username)
    set_session_cookie(response, token)
    return identity(user)


@app.post("/api/logout")
def logout(response: Response, wheel_session: str | None = Cookie(default=None)):
    if wheel_session:
        with database() as db:
            db.execute("DELETE FROM sessions WHERE token = ?", (token_digest(wheel_session),))
    response.delete_cookie("wheel_session")
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return user


@app.get("/api/admin/users")
def users(_admin: dict = Depends(administrator)):
    with database() as db:
        return [identity(row) for row in db.execute("SELECT * FROM users ORDER BY username")]


@app.patch("/api/admin/users/{username}")
def permission(username: str, data: PermissionInput, admin: dict = Depends(administrator)):
    if username == ADMIN:
        raise HTTPException(400, "内置管理员权限不可修改")
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        account = db.execute("SELECT admin FROM users WHERE username = ?", (username,)).fetchone()
        if account is None:
            raise HTTPException(404, "账号不存在")
        if account["admin"] and not admin["owner"]:
            raise HTTPException(403, "仅内置管理员可停用或恢复管理员账号")
        db.execute("UPDATE users SET enabled = ? WHERE username = ?", (data.enabled, username))
    return {"enabled": data.enabled}


@app.patch("/api/admin/users/{username}/role")
def admin_role(username: str, data: AdminRoleInput, _owner: dict = Depends(site_owner)):
    if username == ADMIN:
        raise HTTPException(400, "内置管理员身份不可修改")
    with database() as db:
        changed = db.execute("UPDATE users SET admin = ? WHERE username = ?", (data.admin, username))
        if not changed.rowcount:
            raise HTTPException(404, "账号不存在")
    return {"admin": data.admin}


def clear_wheel_data(username: str | None):
    with database() as db:
        if username is None:
            db.execute("DELETE FROM draws")
            db.execute("DELETE FROM items")
        else:
            if not db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise HTTPException(404, "账号不存在")
            db.execute("DELETE FROM draws WHERE username = ?", (username,))
            db.execute("DELETE FROM items WHERE username = ?", (username,))


@app.delete("/api/admin/wheel", status_code=204)
def clear_all_wheels(_admin: dict = Depends(administrator)):
    clear_wheel_data(None)


@app.delete("/api/admin/users/{username}/wheel", status_code=204)
def clear_account_wheel(username: str, _admin: dict = Depends(administrator)):
    clear_wheel_data(username)


@app.delete("/api/wheel", status_code=204)
def clear_own_wheel(user: dict = Depends(current_user)):
    clear_wheel_data(user["username"])


@app.get("/api/wheel")
def wheel(username: str = Depends(permitted)):
    with database() as db:
        db.execute("BEGIN")
        items = db.execute("SELECT id, text FROM items WHERE username = ? ORDER BY id", (username,))
        recent = db.execute("""
            SELECT id, text, drawn_at, batch_id FROM draws WHERE username = ? ORDER BY id DESC LIMIT 30
        """, (username,)).fetchall()
        last_results = []
        if recent:
            batch_id = recent[0]["batch_id"] or recent[0]["id"]
            last_results = db.execute("""
                SELECT id, text, drawn_at FROM draws
                WHERE username = ? AND (id = ? OR batch_id = ?) ORDER BY id
            """, (username, batch_id, batch_id)).fetchall()
        return {
            "items": [dict(row) for row in items],
            "history": [{key: row[key] for key in ("id", "text", "drawn_at")} for row in recent],
            "last_results": [dict(row) for row in last_results],
        }


@app.post("/api/items", status_code=201)
def add_items(data: ItemsInput, username: str = Depends(permitted)):
    items = [value.strip() for value in data.items if value.strip()]
    if not items or any(len(value) > 250 for value in items):
        raise HTTPException(400, "请填写选项，每条最多 250 字")
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        count = db.execute("SELECT count(*) FROM items WHERE username = ?", (username,)).fetchone()[0]
        if count + len(items) > MAX_ITEMS:
            raise HTTPException(400, f"转盘最多可保存 {MAX_ITEMS} 条选项")
        added = []
        for value in items:
            row = db.execute("INSERT INTO items(username, text) VALUES (?, ?)", (username, value))
            added.append({"id": row.lastrowid, "text": value})
    return added


@app.delete("/api/items/{item_id}", status_code=204)
def remove_item(item_id: int, username: str = Depends(permitted)):
    with database() as db:
        db.execute("DELETE FROM items WHERE id = ? AND username = ?", (item_id, username))


@app.post("/api/extract")
def extract(file: UploadFile, _username: str = Depends(permitted)):
    raw = file.file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "单个文件最大为 20 MB")
    try:
        options = extract_items(file.filename or "", raw)
    except OCRUnavailable as error:
        logger.exception("OCR engine failed")
        raise HTTPException(503, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if not options:
        raise HTTPException(422, "没有识别到可导入的文字。请确认文件包含清晰文字后重试")
    if len(options) > MAX_ITEMS:
        raise HTTPException(422, f"文件包含超过 {MAX_ITEMS} 条内容，请拆分后导入")
    return {"items": options}


@app.post("/api/draw")
def draw(data: DrawInput | None = None, username: str = Depends(permitted)):
    # A request without a body keeps the original single-draw behavior.
    settings = data or DrawInput(allow_repeats=True)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        items = db.execute("SELECT id, text FROM items WHERE username = ? ORDER BY id", (username,)).fetchall()
        if not items:
            raise HTTPException(400, "请先添加转盘选项")
        if settings.allow_repeats:
            indices = [secrets.randbelow(len(items)) for _ in range(settings.count)]
        else:
            distinct = {}
            for index, item in enumerate(items):
                distinct.setdefault(item["text"], index)
            if settings.count > len(distinct):
                raise HTTPException(400, f"不允许重复时最多可抽取 {len(distinct)} 人")
            indices = secrets.SystemRandom().sample(list(distinct.values()), settings.count)
        now = int(time.time())
        results = []
        batch_id = None
        for index in indices:
            item = items[index]
            row = db.execute("INSERT INTO draws(username, text, drawn_at, batch_id) VALUES (?, ?, ?, ?)",
                             (username, item["text"], now, batch_id))
            if batch_id is None:
                batch_id = row.lastrowid
            results.append({"id": row.lastrowid, "item_id": item["id"], "text": item["text"],
                            "drawn_at": now, "index": index})
        return {**results[0], "results": results, "items": [dict(option) for option in items]}
