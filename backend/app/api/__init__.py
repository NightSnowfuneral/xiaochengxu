"""HTTP 接口层。

路由只负责参数校验、调用 service、包装响应；不直接操作 ORM、Redis、
微信或云服务。请求级基础设施（数据库会话、Redis 客户端）统一由
`app.api.deps` 提供。
"""

__all__: list[str] = []
