"""示例项目：模拟一个简单的用户 API 模块。"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(slots=True)
class User:
    id: str
    name: str
    email: str


users: dict[str, User] = {}


def get_user(user_id: str) -> User | None:
    # TODO: 加上数据库查询，目前只用了内存 dict
    return users.get(user_id)


def create_user(name: str, email: str) -> User:
    # FIXME: ID 生成方式应该换成 UUID，时间戳容易冲突
    user_id = f"user-{int(time.time() * 1000)}"
    user = User(user_id, name, email)
    users[user_id] = user
    return user


def delete_user(user_id: str) -> bool:
    # TODO: 软删除而不是物理删除
    return users.pop(user_id, None) is not None
