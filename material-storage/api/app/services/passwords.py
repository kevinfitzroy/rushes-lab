"""本地账号密码 — hash / verify / 临时密码生成(#150 管理后台;P1 登录 #149 复用)。

约定:
- 算法 argon2id(标准 `$argon2id$v=19$...` 格式,任何 argon2 实现可互验);
  #149 登录验证直接用本模块 verify_password 即可
- 临时密码:管理员创建用户 / 重置密码时生成,只回显一次,不入 audit / log
"""
from __future__ import annotations

import secrets
import string

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# 去掉易混淆字符(0/O、1/l/I)与所有符号,便于线下口头传递
_TEMP_PW_ALPHABET = string.ascii_uppercase.replace("I", "").replace("O", "") \
    + string.ascii_lowercase.replace("l", "").replace("o", "") \
    + string.digits.replace("0", "").replace("1", "")


def hash_password(plain: str) -> str:
    """明文 → argon2id hash 字符串(password_hash 列)。"""
    return _hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    """登录校验;hash 非法 / 不匹配都返 False,不抛异常。"""
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, plain)
    except (VerifyMismatchError, VerificationError):
        return False
    except Exception:
        return False


def generate_temp_password(length: int = 12) -> str:
    """临时密码(首登强制改密用 #149;只回显给 admin 一次)。"""
    # secrets.choice 保证不可预测;固定 length 且去掉易混淆字符
    return "".join(secrets.choice(_TEMP_PW_ALPHABET) for _ in range(length))
