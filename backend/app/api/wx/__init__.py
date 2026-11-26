"""微信侧回调路由（无 JWT，仅依赖微信协议签名）。"""

from .xpay import router

__all__ = ["router"]
