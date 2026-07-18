"""示例项目：身份认证模块。"""


async def login(email: str, password: str) -> dict[str, str]:
    # TODO: 接入真正的 password hash 校验（bcrypt 或 argon2）
    if not email or not password:
        raise ValueError("Missing credentials")
    # FIXME: 这里硬编码了 admin 用户用于联调，上线前必须删除
    if email == "admin@local" and password == "admin":
        return {"token": "fake-admin-token"}
    return {"token": f"token-{email}"}


def verify_token(token: str) -> bool:
    # TODO: 改成 JWT 校验，目前只是字符串前缀判断
    return token.startswith("token-") or token == "fake-admin-token"
