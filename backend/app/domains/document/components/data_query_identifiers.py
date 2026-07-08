"""DATA_QUERY 动态表标识符规则。

该模块集中管理逻辑表名、物理表名和动态 SQL identifier 的安全边界。
调用方只允许把这里校验或生成过的 identifier 拼进 DDL/DML，业务数据值仍必须
通过 SQLAlchemy 参数绑定传入，避免把用户输入直接插入 SQL 字符串。
"""

from __future__ import annotations

import hashlib
import re


POSTGRES_IDENTIFIER_MAX_LENGTH = 63
DATA_QUERY_PHYSICAL_TABLE_PREFIX = "dq"
DATA_QUERY_NAMESPACE_TOKEN_LENGTH = 12
SAFE_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9_]+$")

# PostgreSQL 普通 identifier 最多 63 字节。物理表名格式固定为：
#   dq_{12位namespace_hash}_{tableName}
# 因此逻辑表名长度必须预留前缀、分隔符和 namespace token 的空间。
MAX_DATA_QUERY_TABLE_NAME_LENGTH = (
    POSTGRES_IDENTIFIER_MAX_LENGTH
    - len(DATA_QUERY_PHYSICAL_TABLE_PREFIX)
    - 1
    - DATA_QUERY_NAMESPACE_TOKEN_LENGTH
    - 1
)


def is_valid_data_query_table_name(table_name: str) -> bool:
    """判断用户传入的 DATA_QUERY 逻辑表名是否能生成安全物理表名。

    这里同时校验字符集和长度。字符集保证后续不需要复杂 quoting 也不会产生
    SQL 注入面；长度校验保证生成后的物理表名不会被 PostgreSQL 静默截断。
    """

    return (
        bool(SAFE_IDENTIFIER_PATTERN.fullmatch(table_name))
        and len(table_name) <= MAX_DATA_QUERY_TABLE_NAME_LENGTH
    )


def build_data_query_physical_table_name(*, namespace: str, table_name: str) -> str:
    """根据 namespace 和逻辑表名生成 PostgreSQL 安全的物理表名。

    namespace 可能来自用户或租户标识，不能原样进入表名，因此先取稳定 hash token。
    tableName 已被人为约束为小写英文、数字和下划线，可作为物理表名后缀保留可读性。
    """

    if not is_valid_data_query_table_name(table_name):
        raise ValueError("invalid table name")
    # 使用 hash token 隔离不同上传者，避免原始 namespace 过长或包含不可用字符。
    namespace_token = hashlib.sha256(namespace.encode("utf-8")).hexdigest()[
        :DATA_QUERY_NAMESPACE_TOKEN_LENGTH
    ]
    physical_table_name = f"{DATA_QUERY_PHYSICAL_TABLE_PREFIX}_{namespace_token}_{table_name}"
    if len(physical_table_name) > POSTGRES_IDENTIFIER_MAX_LENGTH:
        raise ValueError("invalid table name")
    return physical_table_name


def quote_generated_identifier(identifier: str) -> str:
    """校验并 quote 后端生成的 PostgreSQL identifier。

    本函数只服务于表名、列名这类 identifier，不处理行数据。行数据必须走 bind
    params；如果未来新增 identifier 来源，也应先复用这里的校验再拼 SQL。
    """

    if (
        not SAFE_IDENTIFIER_PATTERN.fullmatch(identifier)
        or len(identifier) > POSTGRES_IDENTIFIER_MAX_LENGTH
    ):
        raise ValueError("invalid generated identifier")
    return f'"{identifier}"'
