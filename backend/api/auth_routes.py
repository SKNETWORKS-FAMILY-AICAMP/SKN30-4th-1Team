import logging

import pymysql
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..db.mysql import get_connection
from ..rate_limit import RATE_LIMIT_LOGIN, RATE_LIMIT_SIGNUP, limiter
from .auth import (
    create_access_token,
    get_current_user_id,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: str
    password: str


def _normalize_email(email: str) -> str:
    email = email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="유효한 이메일 주소가 아닙니다.")
    return email


def _token_response(user_row: dict) -> dict:
    return {
        "access_token": create_access_token(user_row["id"]),
        "token_type": "bearer",
        "user": {
            "id": user_row["id"],
            "email": user_row["email"],
            "name": user_row["name"],
        },
    }


@router.post("/signup", status_code=201)
@limiter.limit(RATE_LIMIT_SIGNUP)
def signup(request: Request, body: SignupRequest):
    email = _normalize_email(body.email)
    password_hash = hash_password(body.password)

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            try:
                cursor.execute(
                    "INSERT INTO users (email, name, password_hash) VALUES (%s, %s, %s)",
                    (email, body.name.strip(), password_hash),
                )
            except pymysql.err.IntegrityError:
                raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다.")
            user_id = cursor.lastrowid
            cursor.execute("SELECT id, email, name FROM users WHERE id = %s", (user_id,))
            user_row = cursor.fetchone()
        # 토큰 생성(시크릿 검증 포함)을 commit 이전에 수행 — 시크릿 누락/약함으로 503이
        # 나더라도 계정이 남지 않도록 rollback 처리한다.
        response = _token_response(user_row)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return response


@router.post("/login")
@limiter.limit(RATE_LIMIT_LOGIN)
def login(request: Request, body: LoginRequest):
    email = _normalize_email(body.email)

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, email, name, password_hash FROM users WHERE email = %s",
                (email,),
            )
            user_row = cursor.fetchone()
    finally:
        conn.close()

    # 미가입/비밀번호 미설정(레거시 row)/불일치 모두 동일 메시지 — 계정 존재 여부 노출 방지
    if (
        not user_row
        or not user_row.get("password_hash")
        or not verify_password(body.password, user_row["password_hash"])
    ):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

    return _token_response(user_row)


@router.get("/me")
def me():
    user_id = get_current_user_id()
    if user_id is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, email, name, created_at FROM users WHERE id = %s", (user_id,))
            user_row = cursor.fetchone()
    finally:
        conn.close()

    if not user_row:
        raise HTTPException(status_code=401, detail="존재하지 않는 사용자입니다.")
    return user_row
