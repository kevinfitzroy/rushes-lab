"""本地密码工具单测(#150)— 不依赖 DB / 容器,`uv run pytest` 可跑。"""
from __future__ import annotations

from app.services.passwords import generate_temp_password, hash_password, verify_password


def test_hash_verify_roundtrip() -> None:
    h = hash_password("s3cret-pw!")
    assert h.startswith("$argon2id$v=19$")
    assert verify_password("s3cret-pw!", h)
    assert not verify_password("wrong", h)


def test_verify_invalid_hash_returns_false() -> None:
    assert not verify_password("x", "")
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("x", "$argon2id$v=19$broken")


def test_temp_password_shape() -> None:
    for _ in range(20):
        pw = generate_temp_password()
        assert len(pw) == 12
        # 不含易混淆字符(0/O/1/l/I),便于口头/书面传递
        for ch in pw:
            assert ch not in "0O1lI"


def test_temp_password_has_both_cases_and_digits() -> None:
    pw = generate_temp_password()
    assert any(c.isupper() for c in pw)
    assert any(c.islower() for c in pw)
    assert any(c.isdigit() for c in pw)
