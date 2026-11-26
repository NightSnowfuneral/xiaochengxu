"""小程序虚拟支付（道具直购）下单签名服务。

流程：

1. 按 product_id 找到商品映射与课程，确定购买环境（env）；
2. 复用 v3 的购买资格校验（课程上架、未重复购买）；
3. 用前端最新 `wx.login` code 调 code2session 取 session_key（可选，
   缺失时只生成 paySig）；
4. 创建 `source=wx_vpay` 的 pending 订单，OutTradeNo 即 order_no；
5. 生成 signData 字符串，计算 paySig（AppKey）与 signature（session_key）。

安全约束：

- AppKey / session_key 绝不返回前端、不写日志、不落库；
- 金额只取 `vpay_products.price`，且必须等于课程展示价；
- 客户端传入的 product_id 只作为课程提示，最终商品/价格/env 由服务端
  按课程与购买环境重新解析；
- 发货只信 xpay 推送，客户端支付成功回调不发放任何权限。
"""

from __future__ import annotations

import json
import logging

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.exception import (
    BusinessException,
    InternalServerError,
    NotFoundError,
)
from ..core.xpay_crypto import (
    XPAY_ENV_PROD,
    XPAY_ENV_SANDBOX,
    XpayCryptoError,
    hmac_sha256_hex,
    load_xpay_profiles,
)
from ..models import Order, OrderSource, OrderStatus, VpayProduct
from ..schemas import VirtualPayCreateResponse
from . import order_service, user_service, wechat_service

logger = logging.getLogger(__name__)

VIRTUAL_PAY_MODE = "short_series_goods"
_PAY_SIG_URI = "requestVirtualPayment"
_CREATE_LOCK_TTL_SECONDS = 5
_CREATE_LOCK_PREFIX = "lock:vpay:create"
_ORDER_NO_MAX_ATTEMPTS = 3


def resolve_purchase_env(platform: str) -> int:
    """购买环境：iOS 无沙箱恒为现网；安卓仅非生产后端允许沙箱。"""

    if platform == "ios":
        return XPAY_ENV_PROD
    if settings.app_env == "production":
        return XPAY_ENV_PROD
    return XPAY_ENV_SANDBOX


def _purchase_credentials(env: int) -> tuple[str, str]:
    """返回 (offerId, AppKey)；缺失或配置不完整时统一 503。"""

    offer_id = (settings.wechat_xpay_offer_id or "").strip()
    if not offer_id:
        logger.error("虚拟支付下单失败：WECHAT_XPAY_OFFER_ID 未配置")
        raise BusinessException(
            "虚拟支付暂不可用，请稍后重试",
            code="PAYMENT_UNAVAILABLE",
            status_code=503,
        )

    try:
        profiles = load_xpay_profiles(settings)
    except XpayCryptoError:
        logger.exception("虚拟支付下单失败：配置不完整")
        raise BusinessException(
            "虚拟支付暂不可用，请稍后重试",
            code="PAYMENT_UNAVAILABLE",
            status_code=503,
        ) from None

    profile = next((item for item in profiles if item.env == env), None)
    if profile is None:
        logger.error("虚拟支付下单失败：env=%s 未配置 AppKey", env)
        raise BusinessException(
            "虚拟支付暂不可用，请稍后重试",
            code="PAYMENT_UNAVAILABLE",
            status_code=503,
        )
    return offer_id, profile.app_key


async def _resolve_mapping(
    session: AsyncSession,
    *,
    product_id: str,
    env: int,
) -> VpayProduct:
    """解析权威商品映射。

    先用前端传入的 product_id 找课程；再按 (课程, 当前环境) 重新取
    权威商品与价格，避免跨环境使用错误的商品或价格。
    """

    rows = (
        await session.scalars(
            select(VpayProduct)
            .where(VpayProduct.product_id == product_id)
            .order_by(VpayProduct.id.asc())
        )
    ).all()
    if not rows:
        raise NotFoundError(
            "商品不存在或已下架",
            code="VPAY_PRODUCT_NOT_FOUND",
        )

    enabled_rows = [row for row in rows if row.enabled]
    if not enabled_rows:
        raise BusinessException(
            "该商品暂不可购买",
            code="VPAY_PRODUCT_DISABLED",
            status_code=409,
        )

    course_id = enabled_rows[0].course_id
    candidates = (
        await session.scalars(
            select(VpayProduct)
            .where(
                VpayProduct.course_id == course_id,
                VpayProduct.env == env,
                VpayProduct.enabled.is_(True),
            )
            .order_by(VpayProduct.id.asc())
        )
    ).all()
    if not candidates:
        raise BusinessException(
            "该课程未配置当前购买环境，请稍后重试",
            code="VPAY_PRODUCT_ENV_MISMATCH",
            status_code=409,
        )

    mapping = next(
        (row for row in candidates if row.product_id == product_id),
        candidates[0],
    )
    if mapping.price <= 0:
        raise BusinessException(
            "商品价格配置有误，暂不可购买",
            code="VPAY_PRICE_MISMATCH",
            status_code=409,
        )
    return mapping


def build_sign_data(
    *,
    offer_id: str,
    env: int,
    product_id: str,
    goods_price: int,
    out_trade_no: str,
    attach: str,
) -> str:
    """生成 signData 字符串。

    只序列化一次：签名与下发给前端必须是同一个字符串，键顺序与
    分隔符不能变化。`goodsPrice` 单位固定为分。
    """

    return json.dumps(
        {
            "offerId": offer_id,
            "buyQuantity": 1,
            "env": env,
            "currencyType": "CNY",
            "productId": product_id,
            "goodsPrice": goods_price,
            "outTradeNo": out_trade_no,
            "attach": attach,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def sign_virtual_payment(
    sign_data: str,
    *,
    app_key: str,
    session_key: str | None,
) -> tuple[str, str | None]:
    """返回 (paySig, signature)。

    paySig 证明商品与价格由服务端授权；signature 把订单绑定到当前
    微信登录会话。未提供 session_key（仅 product_id + openid 的接入）
    时无法生成用户态签名，signature 为 None。
    """

    pay_sig = hmac_sha256_hex(
        app_key,
        f"{_PAY_SIG_URI}&{sign_data}",
    )
    signature = (
        hmac_sha256_hex(session_key, sign_data)
        if session_key is not None
        else None
    )
    return pay_sig, signature


async def _acquire_create_lock(
    redis: Redis,
    *,
    user_id: int,
    course_id: int,
) -> str:
    key = f"{_CREATE_LOCK_PREFIX}:{user_id}:{course_id}"
    acquired = await redis.set(
        key,
        "1",
        nx=True,
        ex=_CREATE_LOCK_TTL_SECONDS,
    )
    if not acquired:
        raise BusinessException(
            "下单请求过于频繁，请稍后重试",
            code="ORDER_CREATE_TOO_FREQUENT",
            status_code=409,
        )
    return key


async def _release_create_lock(redis: Redis, key: str) -> None:
    try:
        await redis.delete(key)
    except Exception:  # noqa: BLE001 - 防连点锁为 best-effort
        logger.warning("释放虚拟支付下单锁失败")


async def create_virtual_order(
    session: AsyncSession,
    *,
    user_id: int,
    product_id: str,
    platform: str,
    login_code: str | None,
    redis: Redis,
    expected_openid: str | None = None,
) -> VirtualPayCreateResponse:
    """创建 pending 虚拟支付订单并返回签名参数。

    - `login_code`：下单当下的 `wx.login` code，用于取 session_key 并
      生成用户态 signature；为空时只生成 paySig，signature 为 None。
    - `expected_openid`：客户端显式声明的 openid（兼容
      `/api/wx/xpay/create_order` 接入），必须与 JWT 用户绑定的微信
      openid 一致，服务端不会信任该值本身。
    """

    env = resolve_purchase_env(platform)
    offer_id, app_key = _purchase_credentials(env)

    user = await user_service.get_user_model(session, user_id)

    if expected_openid is not None and expected_openid != user.openid:
        logger.warning("虚拟支付付款人与登录用户不一致: user_id=%s", user_id)
        raise BusinessException(
            "付款人身份与登录用户不一致",
            code="PAYMENT_OPENID_MISMATCH",
            status_code=403,
        )

    mapping = await _resolve_mapping(
        session,
        product_id=product_id,
        env=env,
    )
    course = await order_service.ensure_course_purchasable(
        session,
        user_id=user_id,
        course_id=mapping.course_id,
    )

    if mapping.price != course.price:
        logger.error(
            "虚拟支付商品价格与课程价格不一致: course_id=%s product_id=%s "
            "mapping_price=%s course_price=%s env=%s",
            course.id,
            mapping.product_id,
            mapping.price,
            course.price,
            env,
        )
        raise BusinessException(
            "商品价格配置有误，暂不可购买",
            code="VPAY_PRICE_MISMATCH",
            status_code=409,
        )

    lock_key = await _acquire_create_lock(
        redis,
        user_id=user_id,
        course_id=course.id,
    )

    try:
        # 每次下单使用新的 wx.login code：code 一次性、session_key 用完即弃，
        # 不落库也不刷新，避免 session_key 过期带来的支付失败。
        payment_openid = user.openid
        session_key: str | None = None
        if login_code is not None:
            wx_session = await wechat_service.code_to_session(login_code)
            if not user.openid or wx_session.openid != user.openid:
                logger.warning(
                    "虚拟支付付款人与登录用户不一致: user_id=%s", user_id
                )
                raise BusinessException(
                    "付款人身份与登录用户不一致",
                    code="PAYMENT_OPENID_MISMATCH",
                    status_code=403,
                )
            payment_openid = wx_session.openid
            session_key = wx_session.session_key

        if not payment_openid:
            # 没有 login_code 时必须能从账号绑定中确认付款人，否则订单
            # 无法归属到任何微信身份。
            raise BusinessException(
                "账号未绑定微信，请重新登录后重试",
                code="PAYMENT_OPENID_MISMATCH",
                status_code=403,
            )

        order_no = ""
        for attempt in range(_ORDER_NO_MAX_ATTEMPTS):
            candidate = order_service.generate_order_no()
            session.add(
                Order(
                    order_no=candidate,
                    user_id=user_id,
                    course_id=course.id,
                    amount=mapping.price,
                    status=OrderStatus.PENDING,
                    source=OrderSource.WX_VPAY,
                    openid=payment_openid,
                    product_id=mapping.product_id,
                    pay_env=env,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                if attempt + 1 >= _ORDER_NO_MAX_ATTEMPTS:
                    logger.error("虚拟支付下单失败：订单号连续冲突")
                    raise InternalServerError(
                        "订单创建失败，请稍后重试"
                    ) from None
                continue
            order_no = candidate
            break

        if not order_no:
            raise InternalServerError("订单创建失败，请稍后重试")

        sign_data = build_sign_data(
            offer_id=offer_id,
            env=env,
            product_id=mapping.product_id,
            goods_price=mapping.price,
            out_trade_no=order_no,
            attach=str(course.id),
        )
        pay_sig, signature = sign_virtual_payment(
            sign_data,
            app_key=app_key,
            session_key=session_key,
        )

        logger.info(
            "虚拟支付订单创建成功: order_no=%s user_id=%s course_id=%s "
            "product_id=%s env=%s amount=%s",
            order_no,
            user_id,
            course.id,
            mapping.product_id,
            env,
            mapping.price,
        )

        return VirtualPayCreateResponse(
            order_no=order_no,
            out_trade_no=order_no,
            course_id=course.id,
            amount=mapping.price,
            status=OrderStatus.PENDING,
            sign_data=sign_data,
            pay_sig=pay_sig,
            signature=signature,
            mode=VIRTUAL_PAY_MODE,
            env=env,
        )
    finally:
        # 连点锁只覆盖单次下单处理窗口；用户取消后应能立即重新发起，
        # 因此无论成功失败都在请求结束时释放。
        await _release_create_lock(redis, lock_key)


__all__ = [
    "VIRTUAL_PAY_MODE",
    "build_sign_data",
    "create_virtual_order",
    "resolve_purchase_env",
    "sign_virtual_payment",
]
