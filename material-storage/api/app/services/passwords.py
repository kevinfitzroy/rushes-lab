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
_TEMP_PW_UPPER = string.ascii_uppercase.replace("I", "").replace("O", "")
_TEMP_PW_LOWER = string.ascii_lowercase.replace("l", "").replace("o", "")
_TEMP_PW_DIGITS = string.digits.replace("0", "").replace("1", "")
_TEMP_PW_ALPHABET = _TEMP_PW_UPPER + _TEMP_PW_LOWER + _TEMP_PW_DIGITS


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
    """临时密码(首登强制改密用 #149;只回显给 admin 一次)。

    保证同时含大写 / 小写 / 数字:既满足 validate_password_policy(字母 + 数字),
    也避免"管理员发的临时密码自己不合规"这种尴尬。
    原实现是纯随机采样,12 位缺数字的概率约 (48/56)^12 ≈ 16% ——
    tests/test_passwords.py::test_temp_password_has_both_cases_and_digits
    长期 flaky(handoff 记为"基线 flaky")的根因就是这个,属于生成器该修而非测试该松。
    """
    if length < 3:
        raise ValueError("临时密码至少 3 位(大写 / 小写 / 数字各一)")
    # 三类各取一个保底,其余随机;再整体洗牌让位置也不可预测(secrets.choice 保证熵)
    chars = [
        secrets.choice(_TEMP_PW_UPPER),
        secrets.choice(_TEMP_PW_LOWER),
        secrets.choice(_TEMP_PW_DIGITS),
    ]
    chars += [secrets.choice(_TEMP_PW_ALPHABET) for _ in range(length - 3)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
