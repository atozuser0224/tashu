from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.auth_models import AuthPrincipal, AuthTokens, CreateUserRequest, UserResponse


class AuthError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class AuthConfig:
    access_ttl_seconds: int = 900
    refresh_ttl_seconds: int = 2_592_000

    @classmethod
    def from_env(cls) -> "AuthConfig":
        return cls(
            access_ttl_seconds=int(os.getenv("AUTH_ACCESS_TTL_SECONDS", "900")),
            refresh_ttl_seconds=int(
                os.getenv("AUTH_REFRESH_TTL_SECONDS", "2592000")
            ),
        )


class AuthStore:
    def __init__(self, database_path: str, config: AuthConfig | None = None) -> None:
        self.config = config or AuthConfig.from_env()
        if database_path != ":memory:":
            Path(database_path).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True
            )
        self._connection = sqlite3.connect(
            database_path, check_same_thread=False, timeout=30
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()
        self._initialize_schema()
        self._jwt_secret = self._load_secret()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _initialize_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS operation_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('admin', 'operator', 'driver')),
                    driver_id TEXT UNIQUE,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    token_jti TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    device_id TEXT,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_refresh_user
                    ON refresh_tokens(user_id, expires_at DESC);
                """
            )

    def _load_secret(self) -> bytes:
        configured = os.getenv("AUTH_JWT_SECRET")
        if configured:
            return configured.encode()
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT setting_value FROM operation_settings "
                "WHERE setting_key = 'auth_jwt_secret'"
            ).fetchone()
            if row:
                return row["setting_value"].encode()
            generated = secrets.token_urlsafe(64)
            self._connection.execute(
                "INSERT INTO operation_settings(setting_key, setting_value) VALUES (?, ?)",
                ("auth_jwt_secret", generated),
            )
            return generated.encode()

    def bootstrap_admin(
        self, username: str, password: str, display_name: str
    ) -> UserResponse:
        with self._lock, self._connection:
            count = self._connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if count:
                raise AuthError(409, "최초 관리자 등록은 사용자 DB가 비어 있을 때만 가능합니다.")
            return self._create_user_locked(
                CreateUserRequest(
                    username=username,
                    password=password,
                    display_name=display_name,
                    role="admin",
                )
            )

    def create_user(self, request: CreateUserRequest) -> UserResponse:
        with self._lock, self._connection:
            return self._create_user_locked(request)

    def _create_user_locked(self, request: CreateUserRequest) -> UserResponse:
        user_id = f"user-{uuid.uuid4().hex}"
        now = _utc_now()
        try:
            self._connection.execute(
                """
                INSERT INTO users (
                    user_id, username, password_hash, display_name, role,
                    driver_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    request.username.strip(),
                    _hash_password(request.password),
                    request.display_name.strip(),
                    request.role,
                    request.driver_id,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise AuthError(409, "이미 존재하는 사용자명 또는 기사 ID입니다.") from exc
        return self._user_from_row(self._user_row(user_id))

    def login(
        self, username: str, password: str, device_id: str | None = None
    ) -> AuthTokens:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
            ).fetchone()
            if row is None or not _verify_password(password, row["password_hash"]):
                raise AuthError(401, "사용자명 또는 비밀번호가 올바르지 않습니다.")
            if not row["is_active"]:
                raise AuthError(403, "비활성화된 계정입니다.")
            return self._issue_tokens_locked(row, device_id)

    def refresh(self, refresh_token: str) -> AuthTokens:
        with self._lock, self._connection:
            payload = self._decode_token(refresh_token, expected_type="refresh")
            token_row = self._connection.execute(
                "SELECT * FROM refresh_tokens WHERE token_jti = ?", (payload["jti"],)
            ).fetchone()
            if token_row is None or token_row["revoked_at"]:
                raise AuthError(401, "폐기되었거나 알 수 없는 Refresh Token입니다.")
            if datetime.fromisoformat(token_row["expires_at"]) <= datetime.now(
                timezone.utc
            ):
                raise AuthError(401, "Refresh Token이 만료되었습니다.")
            user = self._user_row(payload["sub"])
            if not user["is_active"]:
                raise AuthError(403, "비활성화된 계정입니다.")
            self._connection.execute(
                "UPDATE refresh_tokens SET revoked_at = ? WHERE token_jti = ?",
                (_utc_now(), payload["jti"]),
            )
            return self._issue_tokens_locked(user, token_row["device_id"])

    def logout(self, refresh_token: str) -> None:
        with self._lock, self._connection:
            payload = self._decode_token(refresh_token, expected_type="refresh")
            self._connection.execute(
                "UPDATE refresh_tokens SET revoked_at = ? WHERE token_jti = ?",
                (_utc_now(), payload["jti"]),
            )

    def authenticate(self, access_token: str) -> AuthPrincipal:
        payload = self._decode_token(access_token, expected_type="access")
        with self._lock:
            row = self._user_row(payload["sub"])
            if not row["is_active"]:
                raise AuthError(403, "비활성화된 계정입니다.")
            return AuthPrincipal(
                user_id=row["user_id"],
                username=row["username"],
                display_name=row["display_name"],
                role=row["role"],
                driver_id=row["driver_id"],
            )

    def _issue_tokens_locked(
        self, user: sqlite3.Row, device_id: str | None
    ) -> AuthTokens:
        now = datetime.now(timezone.utc)
        refresh_jti = uuid.uuid4().hex
        common = {
            "sub": user["user_id"],
            "role": user["role"],
            "driver_id": user["driver_id"],
            "iat": int(now.timestamp()),
        }
        access = self._encode_token(
            {
                **common,
                "type": "access",
                "jti": uuid.uuid4().hex,
                "exp": int((now + timedelta(seconds=self.config.access_ttl_seconds)).timestamp()),
            }
        )
        refresh_expires = now + timedelta(seconds=self.config.refresh_ttl_seconds)
        refresh = self._encode_token(
            {
                **common,
                "type": "refresh",
                "jti": refresh_jti,
                "exp": int(refresh_expires.timestamp()),
            }
        )
        self._connection.execute(
            """
            INSERT INTO refresh_tokens (
                token_jti, user_id, device_id, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                refresh_jti,
                user["user_id"],
                device_id,
                refresh_expires.isoformat(),
                now.isoformat(),
            ),
        )
        return AuthTokens(
            access_token=access,
            access_expires_in_seconds=self.config.access_ttl_seconds,
            refresh_token=refresh,
            refresh_expires_in_seconds=self.config.refresh_ttl_seconds,
            user=self._user_from_row(user),
        )

    def _encode_token(self, payload: dict) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        head = _b64(json.dumps(header, separators=(",", ":")).encode())
        body = _b64(json.dumps(payload, separators=(",", ":")).encode())
        signature = _b64(
            hmac.new(self._jwt_secret, f"{head}.{body}".encode(), hashlib.sha256).digest()
        )
        return f"{head}.{body}.{signature}"

    def _decode_token(self, token: str, expected_type: str) -> dict:
        try:
            head, body, signature = token.split(".")
            expected = hmac.new(
                self._jwt_secret, f"{head}.{body}".encode(), hashlib.sha256
            ).digest()
            if not hmac.compare_digest(_unb64(signature), expected):
                raise ValueError
            payload = json.loads(_unb64(body))
            if payload.get("type") != expected_type:
                raise ValueError
            if int(payload["exp"]) <= int(datetime.now(timezone.utc).timestamp()):
                raise AuthError(401, "인증 토큰이 만료되었습니다.")
            return payload
        except AuthError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AuthError(401, "유효하지 않은 인증 토큰입니다.") from exc

    def _user_row(self, user_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            raise AuthError(401, "사용자를 찾을 수 없습니다.")
        return row

    @staticmethod
    def _user_from_row(row: sqlite3.Row) -> UserResponse:
        return UserResponse(
            user_id=row["user_id"],
            username=row["username"],
            display_name=row["display_name"],
            role=row["role"],
            driver_id=row["driver_id"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
        )


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${_b64(salt)}${_b64(digest)}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt, expected = stored.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=_unb64(salt), n=2**14, r=8, p=1
        )
        return hmac.compare_digest(actual, _unb64(expected))
    except (TypeError, ValueError):
        return False


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
