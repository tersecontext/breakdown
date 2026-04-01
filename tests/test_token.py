import pytest
import jwt as pyjwt
import uuid

from app.token import create_access_token, decode_access_token, generate_refresh_token, hash_refresh_token


def test_create_and_decode_roundtrip():
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    token = create_access_token(user_id, session_id, "admin")
    payload = decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["jti"] == str(session_id)
    assert payload["role"] == "admin"


def test_expired_token_raises(monkeypatch):
    import app.token as token_module
    monkeypatch.setattr(token_module.settings, "access_token_ttl", -1)
    token = create_access_token(uuid.uuid4(), uuid.uuid4(), "member")
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_access_token(token)


def test_tampered_token_raises():
    token = create_access_token(uuid.uuid4(), uuid.uuid4(), "member")
    tampered = token[:-4] + "xxxx"
    with pytest.raises(pyjwt.PyJWTError):
        decode_access_token(tampered)


def test_generate_refresh_token_returns_pair():
    raw, hashed = generate_refresh_token()
    assert len(raw) == 64  # hex(32 bytes)
    assert hashed == hash_refresh_token(raw)


def test_different_raw_tokens_produce_different_hashes():
    raw1, h1 = generate_refresh_token()
    raw2, h2 = generate_refresh_token()
    assert h1 != h2
    assert len(h1) == 64  # SHA-256 hex digest is 64 chars
