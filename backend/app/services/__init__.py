"""业务服务层（Service）。

本包承载全部业务规则，路由层只负责参数校验、调用 service 与包装响应：

- 服务函数显式接收 `AsyncSession` / `redis.asyncio.Redis`，不自行创建连接，
  由依赖注入层统一管理生命周期；
- 写操作在 service 内显式 commit，读操作不改变事务状态；
- 支付回调、赠课等幂等逻辑全部下沉到本层，路由不得复制任何业务判断；
- 本文件不做任何 eager import，避免导入包时触发外部 SDK 初始化。
"""

__all__: list[str] = []
