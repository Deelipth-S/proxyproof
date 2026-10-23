#!/usr/bin/env python3
"""ProxyProof local MVP server. Uses only the Python standard library."""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "proxyproof.sqlite3"
HOST = os.environ.get("PROXYPROOF_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
SESSION_SECRET = os.environ.get("PROXYPROOF_SECRET", "local-demo-secret-change-before-deploy").encode()
TOKEN_SECONDS = 5
RSSI_LIMIT = -75


def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def password_hash(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    salt = salt or secrets.token_bytes(16)
    return salt, hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)


def init_db():
    with connect() as db:
        db.executescript("""
          CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('organizer','student')),
            salt BLOB NOT NULL, password_hash BLOB NOT NULL,
            device_id TEXT UNIQUE, pending_device_id TEXT, created_at INTEGER NOT NULL
          );
          CREATE TABLE IF NOT EXISTS web_sessions (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL
          );
          CREATE TABLE IF NOT EXISTS attendance_sessions (
            id TEXT PRIMARY KEY, organizer_id TEXT NOT NULL REFERENCES users(id),
            class_name TEXT NOT NULL, started_at INTEGER NOT NULL, ends_at INTEGER NOT NULL,
            closed_at INTEGER, beacon_id TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES attendance_sessions(id) ON DELETE CASCADE,
            student_id TEXT NOT NULL REFERENCES users(id), marked_at INTEGER NOT NULL,
            method TEXT NOT NULL, rssi INTEGER, UNIQUE(session_id, student_id)
          );
        """)
        samples = [
            ("organizer-1", "organizer@proxyproof.app", "Olivia Chen", "organizer", "organizer123", None),
            ("student-maya", "maya@proxyproof.app", "Maya Patel", "student", "student123", "demo-maya-device"),
            ("student-arjun", "arjun@proxyproof.app", "Arjun Rao", "student", "student123", "demo-arjun-device"),
            ("student-leah", "leah@proxyproof.app", "Leah Kim", "student", "student123", "demo-leah-device"),
        ]
        for uid, email, name, role, pw, device in samples:
            if db.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
                continue
            salt, digest = password_hash(pw)
            db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?)",
                       (uid, email, name, role, salt, digest, device, None, int(time.time())))


def utc_stamp(seconds: int | None) -> str | None:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat() if seconds is not None else None


def current_token(session_id: str, beacon_id: str, at: int | None = None) -> str:
    bucket = int(at if at is not None else time.time()) // TOKEN_SECONDS
    message = f"{session_id}:{beacon_id}:{bucket}".encode()
    return hmac.new(SESSION_SECRET, message, hashlib.sha256).hexdigest()[:24]


class APIError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


class Handler(BaseHTTPRequestHandler):
    server_version = "ProxyProof/1.0"

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, payload, status=200, headers=None):
        raw = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def body(self):
        try:
            size = min(int(self.headers.get("Content-Length", "0")), 1_000_000)
            return json.loads(self.rfile.read(size) or b"{}")
        except (ValueError, json.JSONDecodeError):
            raise APIError(400, "Request body must be valid JSON.")

    def user(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("pp_session")
        if not morsel:
            return None
        with connect() as db:
            return db.execute("SELECT u.* FROM web_sessions s JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.expires_at>?",
                              (morsel.value, int(time.time()))).fetchone()

    def require_user(self, role=None):
        user = self.user()
        if not user:
            raise APIError(401, "Please sign in to continue.")
        if role and user["role"] != role:
            raise APIError(403, "This action is not available for your account.")
        return user

    def do_GET(self):
        try:
            path = urlparse(self.path).path
            if path == "/" or path.startswith("/static/"):
                return self.static(path)
            if path == "/api/me":
                user = self.user()
                return self.send_json({"user": self.public_user(user) if user else None})
            if path == "/api/dashboard":
                return self.send_json(self.dashboard(self.require_user()))
            if path == "/api/history":
                return self.send_json(self.history(self.require_user("student")))
            if path == "/api/devices":
                self.require_user("organizer")
                with connect() as db:
                    rows = db.execute("SELECT id,name,email,device_id,pending_device_id FROM users WHERE role='student' ORDER BY name").fetchall()
                return self.send_json({"devices": [dict(r) for r in rows]})
            if path == "/api/export.csv":
                return self.export_csv(self.require_user("organizer"))
            raise APIError(404, "That page or API route does not exist.")
        except APIError as e:
            self.send_json({"error": e.message}, e.status)
        except Exception as e:
            print("GET error:", repr(e))
            self.send_json({"error": "The server could not complete that request."}, 500)

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            data = self.body()
            if path == "/api/login":
                return self.login(data)
            if path == "/api/logout":
                cookie = SimpleCookie(self.headers.get("Cookie", ""))
                if cookie.get("pp_session"):
                    with connect() as db:
                        db.execute("DELETE FROM web_sessions WHERE id=?", (cookie["pp_session"].value,))
                return self.send_json({"ok": True}, headers={"Set-Cookie": "pp_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
            user = self.require_user()
            if path == "/api/sessions":
                self.require_user("organizer")
                return self.create_session(user, data)
            if path == "/api/proximity":
                self.require_user("student")
                return self.proximity(user, data)
            if path == "/api/device/request":
                self.require_user("student")
                return self.request_device(user, data)
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "sessions"] and parts[3] == "close":
                self.require_user("organizer")
                return self.close_session(user, parts[2])
            if len(parts) == 4 and parts[:2] == ["api", "sessions"] and parts[3] == "attendance":
                self.require_user("organizer")
                return self.manual_mark(user, parts[2], data)
            if len(parts) == 3 and parts[:2] == ["api", "devices"]:
                self.require_user("organizer")
                return self.review_device(parts[2], data)
            raise APIError(404, "That API route does not exist.")
        except APIError as e:
            self.send_json({"error": e.message}, e.status)
        except Exception as e:
            print("POST error:", repr(e))
            self.send_json({"error": "The server could not complete that request."}, 500)

    def login(self, data):
        email, password = str(data.get("email", "")).strip().lower(), str(data.get("password", ""))
        with connect() as db:
            row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if not row or not hmac.compare_digest(password_hash(password, row["salt"])[1], row["password_hash"]):
                raise APIError(401, "Email or password is incorrect.")
            sid, expires = secrets.token_urlsafe(32), int(time.time()) + 60 * 60 * 12
            db.execute("INSERT INTO web_sessions VALUES (?,?,?)", (sid, row["id"], expires))
        return self.send_json({"user": self.public_user(row)}, headers={"Set-Cookie": f"pp_session={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200"})

    def public_user(self, user):
        if not user:
            return None
        return {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"],
                "device_id": user["device_id"], "pending_device_id": user["pending_device_id"]}

    def dashboard(self, user):
        now = int(time.time())
        with connect() as db:
            db.execute("UPDATE attendance_sessions SET closed_at=ends_at WHERE closed_at IS NULL AND ends_at<=?", (now,))
            if user["role"] == "organizer":
                sessions = db.execute("SELECT s.*, COUNT(m.id) AS present FROM attendance_sessions s LEFT JOIN marks m ON m.session_id=s.id WHERE s.organizer_id=? GROUP BY s.id ORDER BY s.started_at DESC LIMIT 30", (user["id"],)).fetchall()
                active = next((r for r in sessions if r["closed_at"] is None and r["ends_at"] > now), None)
                marks = []
                if active:
                    marks = db.execute("SELECT u.id AS student_id,u.name,u.email,m.marked_at,m.method,m.rssi FROM users u LEFT JOIN marks m ON m.student_id=u.id AND m.session_id=? WHERE u.role='student' ORDER BY u.name", (active["id"],)).fetchall()
                students = db.execute("SELECT COUNT(*) AS n FROM users WHERE role='student'").fetchone()["n"]
                count = db.execute("SELECT COUNT(*) AS n FROM attendance_sessions WHERE organizer_id=?", (user["id"],)).fetchone()["n"]
                return {"user": self.public_user(user), "students": students, "session_count": count,
                        "active": self.session_json(active, marks) if active else None,
                        "recent": [self.session_json(r) for r in sessions]}
            history = self.history(user)
            active = db.execute("SELECT s.*,m.marked_at,m.method FROM attendance_sessions s LEFT JOIN marks m ON m.session_id=s.id AND m.student_id=? WHERE s.closed_at IS NULL AND s.ends_at>? ORDER BY s.started_at DESC LIMIT 1", (user["id"], now)).fetchone()
            return {"user": self.public_user(user), "history": history,
                    "active": self.session_json(active) if active else None}

    def session_json(self, row, marks=None):
        if not row:
            return None
        out = {"id": row["id"], "class_name": row["class_name"], "started_at": utc_stamp(row["started_at"]),
               "ends_at": utc_stamp(row["ends_at"]), "closed_at": utc_stamp(row["closed_at"]),
               "present": row["present"] if "present" in row.keys() else (1 if row["marked_at"] else 0),
               "duration": max(1, (row["ends_at"] - row["started_at"]) // 60)}
        if row["closed_at"] is None and row["ends_at"] > int(time.time()):
            out["beacon"] = {"id": row["beacon_id"], "token": current_token(row["id"], row["beacon_id"]), "rotates_in": TOKEN_SECONDS - int(time.time()) % TOKEN_SECONDS}
        if marks is not None:
            out["roster"] = [{"student_id": m["student_id"], "name": m["name"], "email": m["email"],
                              "marked_at": utc_stamp(m["marked_at"]), "method": m["method"], "rssi": m["rssi"]} for m in marks]
        return out

    def history(self, user):
        with connect() as db:
            sessions = db.execute("SELECT s.*,m.marked_at,m.method FROM attendance_sessions s LEFT JOIN marks m ON m.session_id=s.id AND m.student_id=? WHERE s.closed_at IS NOT NULL OR s.ends_at<=? ORDER BY s.started_at DESC", (user["id"], int(time.time()))).fetchall()
        attended = sum(1 for s in sessions if s["marked_at"] is not None)
        return {"sessions": [{"id": s["id"], "class_name": s["class_name"], "started_at": utc_stamp(s["started_at"]),
                               "present": s["marked_at"] is not None, "method": s["method"]} for s in sessions],
                "attended": attended, "total": len(sessions), "percentage": round(attended / len(sessions) * 100) if sessions else 0}

    def create_session(self, user, data):
        name = str(data.get("class_name", "")).strip()[:80]
        try:
            duration = int(data.get("duration", 5))
        except (ValueError, TypeError):
            duration = 0
        if not name:
            raise APIError(400, "Add a class or session name first.")
        if duration < 1 or duration > 120:
            raise APIError(400, "Session duration must be between 1 and 120 minutes.")
        now, sid, beacon_id = int(time.time()), secrets.token_urlsafe(12), secrets.token_hex(8)
        with connect() as db:
            running = db.execute("SELECT 1 FROM attendance_sessions WHERE organizer_id=? AND closed_at IS NULL AND ends_at>?", (user["id"], now)).fetchone()
            if running:
                raise APIError(409, "Close the current session before starting another.")
            db.execute("INSERT INTO attendance_sessions VALUES (?,?,?,?,?,?,?)", (sid, user["id"], name, now, now + duration * 60, None, beacon_id))
        return self.send_json({"ok": True, "session_id": sid}, 201)

    def close_session(self, user, sid):
        with connect() as db:
            cur = db.execute("UPDATE attendance_sessions SET closed_at=? WHERE id=? AND organizer_id=? AND closed_at IS NULL", (int(time.time()), sid, user["id"]))
            if not cur.rowcount:
                raise APIError(404, "The active session could not be found.")
        return self.send_json({"ok": True})

    def manual_mark(self, user, sid, data):
        student_id = str(data.get("student_id", ""))
        present = bool(data.get("present"))
        with connect() as db:
            session = db.execute("SELECT * FROM attendance_sessions WHERE id=? AND organizer_id=?", (sid, user["id"])).fetchone()
            student = db.execute("SELECT id FROM users WHERE id=? AND role='student'", (student_id,)).fetchone()
            if not session or session["closed_at"] is not None or session["ends_at"] <= int(time.time()):
                raise APIError(409, "This session is no longer open for edits.")
            if not student:
                raise APIError(404, "Student not found.")
            if present:
                db.execute("INSERT INTO marks(session_id,student_id,marked_at,method,rssi) VALUES(?,?,?,?,NULL) ON CONFLICT(session_id,student_id) DO UPDATE SET marked_at=excluded.marked_at,method='manual',rssi=NULL", (sid, student_id, int(time.time()), "manual"))
            else:
                db.execute("DELETE FROM marks WHERE session_id=? AND student_id=?", (sid, student_id))
        return self.send_json({"ok": True})

    def proximity(self, user, data):
        sid, token = str(data.get("session_id", "")), str(data.get("token", ""))
        device, student_id = str(data.get("device_id", "")), user["id"]
        try:
            rssi = int(data.get("rssi"))
        except (ValueError, TypeError):
            raise APIError(400, "A valid signal strength is required.")
        now = int(time.time())
        with connect() as db:
            session = db.execute("SELECT * FROM attendance_sessions WHERE id=?", (sid,)).fetchone()
            if not session or session["closed_at"] is not None or session["ends_at"] <= now:
                raise APIError(409, "The attendance window is closed.")
            if not hmac.compare_digest(token, current_token(sid, session["beacon_id"], now)):
                raise APIError(401, "That beacon token has expired. Scan the current signal again.")
            if not user["device_id"] or user["device_id"] != device:
                raise APIError(403, "This device is not approved for your account.")
            if rssi < RSSI_LIMIT:
                raise APIError(422, "The signal is too weak to confirm that you are in the room.")
            existing = db.execute("SELECT student_id FROM marks WHERE session_id=? AND student_id=?", (sid, student_id)).fetchone()
            if existing:
                return self.send_json({"ok": True, "already_marked": True})
            db.execute("INSERT INTO marks(session_id,student_id,marked_at,method,rssi) VALUES(?,?,?,?,?)", (sid, student_id, now, "ble", rssi))
        return self.send_json({"ok": True, "marked_at": utc_stamp(now)}, 201)

    def request_device(self, user, data):
        device = str(data.get("device_id", "")).strip()[:120]
        if not device:
            raise APIError(400, "A device identifier is required.")
        with connect() as db:
            taken = db.execute("SELECT id FROM users WHERE device_id=? AND id<>?", (device, user["id"])).fetchone()
            if taken:
                raise APIError(409, "That device is already registered to another student.")
            db.execute("UPDATE users SET pending_device_id=? WHERE id=?", (device, user["id"]))
        return self.send_json({"ok": True})

    def review_device(self, student_id, data):
        approve = bool(data.get("approve"))
        with connect() as db:
            row = db.execute("SELECT pending_device_id FROM users WHERE id=? AND role='student'", (student_id,)).fetchone()
            if not row or not row["pending_device_id"]:
                raise APIError(404, "No pending device request was found.")
            if approve:
                used = db.execute("SELECT id FROM users WHERE device_id=? AND id<>?", (row["pending_device_id"], student_id)).fetchone()
                if used:
                    raise APIError(409, "That device is already registered to another student.")
                db.execute("UPDATE users SET device_id=pending_device_id,pending_device_id=NULL WHERE id=?", (student_id,))
            else:
                db.execute("UPDATE users SET pending_device_id=NULL WHERE id=?", (student_id,))
        return self.send_json({"ok": True})

    def export_csv(self, user):
        with connect() as db:
            rows = db.execute("SELECT s.class_name,s.started_at,u.name,u.email,CASE WHEN m.id IS NULL THEN 'Absent' ELSE 'Present' END AS status,m.marked_at,m.method,m.rssi FROM attendance_sessions s CROSS JOIN users u LEFT JOIN marks m ON m.session_id=s.id AND m.student_id=u.id WHERE s.organizer_id=? AND u.role='student' ORDER BY s.started_at DESC,u.name", (user["id"],)).fetchall()
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["Session", "Session started (UTC)", "Student", "Email", "Status", "Marked at (UTC)", "Method", "RSSI"])
        for row in rows:
            writer.writerow([row["class_name"], utc_stamp(row["started_at"]), row["name"], row["email"], row["status"], utc_stamp(row["marked_at"]), row["method"] or "", row["rssi"] if row["rssi"] is not None else ""])
        raw = out.getvalue().encode("utf-8-sig")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", "attachment; filename=proxyproof-attendance.csv")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def static(self, path):
        rel = "index.html" if path == "/" else path.removeprefix("/static/")
        target = (ROOT / "static" / rel).resolve()
        if not target.is_relative_to(ROOT / "static") or not target.is_file():
            self.send_error(404)
            return
        mime = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}.get(target.suffix, "application/octet-stream")
        raw = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)


if __name__ == "__main__":
    init_db()
    print(f"ProxyProof is running at http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
