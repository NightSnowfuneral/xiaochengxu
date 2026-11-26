"""应用配置。

通过 pydantic-settings 读取项目根目录 `.env` 与环境变量。容器部署时由
Compose 注入环境变量，不依赖镜像内存在 `.env` 文件。

约束：
- 本地开发与生产的差异全部通过环境变量表达；
- C 端用户 JWT 与 Admin JWT 使用两套独立密钥，并在加载配置时强制校验不同；
- 敏感值使用 SecretStr，避免被日志或异常信息意外打印。
"""

from __future__ import annotations

import base64
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """全局配置。所有字段与根目录 `.env.example` 一一对应。"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_ignore_empty=True,
        frozen=True,
    )

    # ------------------------------------------------------------------
    # 基础
    # ------------------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = Field(default="huahuo-spark", min_length=1)
    api_prefix: str = "/api/v1"
    # 应用日志级别；生产默认 INFO，输出业务启动、进度落库与异常日志。
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    cors_allow_origins: str = (
        "http://127.0.0.1:5173,http://localhost:5173"
    )

    # ------------------------------------------------------------------
    # MySQL
    # ------------------------------------------------------------------
    mysql_host: str = "127.0.0.1"
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_database: str = "huahuo_spark"
    mysql_user: str = "spark"
    mysql_password: SecretStr = SecretStr("")
    mysql_root_password: SecretStr | None = None
    database_url: SecretStr

    # ------------------------------------------------------------------
    # Redis 与学习进度缓冲
    # ------------------------------------------------------------------
    redis_url: SecretStr
    redis_port: int = Field(default=6379, ge=1, le=65535)
    study_progress_ttl_seconds: int = Field(default=604800, ge=60)
    study_progress_flush_interval_seconds: int = Field(default=60, ge=1)

    # ------------------------------------------------------------------
    # C 端用户 JWT（与 Admin JWT 完全隔离）
    # ------------------------------------------------------------------
    user_jwt_secret: SecretStr
    user_jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    user_jwt_expire_minutes: int = Field(default=10080, ge=1)

    # ------------------------------------------------------------------
    # B 端管理员 JWT（与 C 端 JWT 完全隔离）
    # ------------------------------------------------------------------
    admin_jwt_secret: SecretStr
    admin_jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    admin_jwt_expire_minutes: int = Field(default=480, ge=1)

    # ------------------------------------------------------------------
    # 初始管理员
    # ------------------------------------------------------------------
    admin_initial_username: str = Field(default="admin", min_length=1)
    admin_initial_password: SecretStr | None = None

    # ------------------------------------------------------------------
    # 微信小程序
    # ------------------------------------------------------------------
    wechat_app_id: str | None = None
    wechat_app_secret: SecretStr | None = None

    # ------------------------------------------------------------------
    # 微信支付 v3
    # ------------------------------------------------------------------
    wechat_pay_mch_id: str | None = None
    wechat_pay_cert_serial_no: str | None = None
    wechat_pay_private_key_path: str = Field(
        default="/run/secrets/wechatpay_apiclient_key.pem",
        min_length=1,
    )
    wechat_pay_api_v3_key: SecretStr | None = None
    # 新版商户使用「微信支付公钥」替代平台证书；公钥内容与公钥 ID 必须
    # 同时配置。公钥既可写入文件（*_PATH），也可直接放在环境变量里。
    wechat_pay_public_key_path: str | None = None
    wechat_pay_public_key: SecretStr | None = None
    wechat_pay_public_key_id: str | None = None
    wechat_pay_notify_url: str | None = None
    # 支付成功后课程授权的有效天数；续期与首次购买均使用该值。
    course_valid_day: int = Field(default=365, ge=1, le=36500)
    # 待支付订单超时自动关闭：分钟数与扫描周期。
    order_close_timeout_minutes: int = Field(default=30, ge=1)
    order_close_scan_interval_seconds: int = Field(default=300, ge=10)
    # 每日对账：周期与回溯天数；只检查近期订单，避免全表扫描。
    order_reconcile_interval_seconds: int = Field(default=86400, ge=600)
    order_reconcile_lookback_days: int = Field(default=7, ge=1, le=90)

    # ------------------------------------------------------------------
    # 微信小程序虚拟支付（xpay）消息推送
    # ------------------------------------------------------------------
    # 每个环境三项必须同时配置；Token 与 EncodingAESKey 用于验签 / AES
    # 解密，AppKey 用于服务端下单签名（paySig），不参与回调验签。
    wechat_xpay_prod_app_key: SecretStr | None = None
    wechat_xpay_prod_msg_token: SecretStr | None = None
    wechat_xpay_prod_encoding_aes_key: SecretStr | None = None
    wechat_xpay_sandbox_app_key: SecretStr | None = None
    wechat_xpay_sandbox_msg_token: SecretStr | None = None
    wechat_xpay_sandbox_encoding_aes_key: SecretStr | None = None
    # 小程序虚拟支付后台「支付基础配置」中的 offerId；现网与沙箱共用。
    wechat_xpay_offer_id: str | None = None
    # 已处理 xpay 订单的 Redis 幂等键 TTL（秒，默认 30 天）。
    wechat_xpay_idempotency_ttl_seconds: int = Field(
        default=2592000,
        ge=60,
    )
    # 回调报文硬上限；必须小于 MySQL TEXT 的 64 KiB 上限。
    wechat_xpay_max_body_bytes: int = Field(
        default=49152,
        ge=1024,
        le=65536,
    )

    # ------------------------------------------------------------------
    # 腾讯云 COS
    # ------------------------------------------------------------------
    tencentcloud_secret_id: str | None = None
    tencentcloud_secret_key: SecretStr | None = None
    cos_bucket: str | None = None
    cos_region: str = "ap-guangzhou"
    cos_public_base_url: str | None = None

    # ------------------------------------------------------------------
    # 腾讯云 VOD
    # ------------------------------------------------------------------
    vod_app_id: int | None = Field(default=None, ge=1)
    vod_play_key: SecretStr | None = None
    vod_play_key_expire_seconds: int = Field(default=7200, ge=60)
    vod_upload_procedure: str = Field(
        default="SimpleAesEncryptPreset",
        min_length=1,
        max_length=100,
        description="上传后自动执行的加密转码任务流模板名",
    )
    vod_upload_max_size_mb: int = Field(
        default=2048,
        ge=1,
        le=10240,
        description="单个视频上传大小上限（MB）",
    )

    # ------------------------------------------------------------------
    # 前端构建变量（非敏感）
    # ------------------------------------------------------------------
    taro_app_api_base_url: str = "http://127.0.0.1:8000/api/v1"
    # 后台管理构建变量：本地开发为绝对地址，生产为与 /admin/ 同源的相对路径 /api/v1
    vite_api_base_url: str = "http://127.0.0.1:8000/api/v1"

    @field_validator(
        "mysql_root_password",
        "admin_initial_password",
        "wechat_app_secret",
        "wechat_pay_api_v3_key",
        "wechat_pay_public_key",
        "wechat_xpay_prod_app_key",
        "wechat_xpay_prod_msg_token",
        "wechat_xpay_prod_encoding_aes_key",
        "wechat_xpay_sandbox_app_key",
        "wechat_xpay_sandbox_msg_token",
        "wechat_xpay_sandbox_encoding_aes_key",
        "tencentcloud_secret_key",
        "vod_play_key",
        mode="before",
    )
    @classmethod
    def empty_optional_secret_to_none(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            return None if not value.get_secret_value() else value
        if isinstance(value, str) and not value:
            return None
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("API_PREFIX 必须以 / 开头且不能以 / 结尾")
        return value

    @field_validator("cors_allow_origins")
    @classmethod
    def validate_cors_allow_origins(cls, value: str) -> str:
        """只接受逗号分隔的 HTTP(S) 源，避免误配通配符或带路径地址。"""

        origins: list[str] = []
        for raw in value.split(","):
            origin = raw.strip().rstrip("/")
            if not origin:
                continue
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "CORS_ALLOW_ORIGINS 必须为逗号分隔的 HTTP(S) 源，"
                    "不能包含路径、查询参数或通配符"
                )
            if origin not in origins:
                origins.append(origin)
        return ",".join(origins)

    @field_validator("database_url", "redis_url")
    @classmethod
    def validate_required_url_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("数据库与 Redis 连接串不能为空")
        return value

    @field_validator("user_jwt_secret", "admin_jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT 密钥长度不得少于 32 个字符")
        return value

    @field_validator("admin_initial_password")
    @classmethod
    def validate_admin_initial_password(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return value
        raw = value.get_secret_value()
        if not raw:
            return None
        if len(raw) < 12:
            raise ValueError("初始管理员密码长度不得少于 12 个字符")
        if len(raw.encode("utf-8")) > 72:
            raise ValueError("初始管理员密码不得超过 bcrypt 的 72 字节上限")
        return value

    @field_validator("wechat_pay_api_v3_key")
    @classmethod
    def validate_wechat_pay_api_v3_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return value
        raw = value.get_secret_value()
        if raw and len(raw.encode("utf-8")) != 32:
            raise ValueError("WECHAT_PAY_API_V3_KEY 必须为 32 字节")
        return value

    @field_validator(
        "wechat_xpay_prod_app_key",
        "wechat_xpay_sandbox_app_key",
    )
    @classmethod
    def validate_xpay_app_key(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value().strip()
        if not raw:
            return None
        if len(raw) < 8 or len(raw) > 128:
            raise ValueError("虚拟支付 AppKey 长度必须在 8–128 个字符之间")
        return SecretStr(raw)

    @field_validator(
        "wechat_xpay_prod_msg_token",
        "wechat_xpay_sandbox_msg_token",
    )
    @classmethod
    def validate_xpay_msg_token(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value().strip()
        if not raw:
            return None
        if re.fullmatch(r"[A-Za-z0-9_]{3,32}", raw) is None:
            raise ValueError(
                "虚拟支付消息 Token 只能包含字母、数字、下划线，长度 3–32"
            )
        return SecretStr(raw)

    @field_validator(
        "wechat_xpay_prod_encoding_aes_key",
        "wechat_xpay_sandbox_encoding_aes_key",
    )
    @classmethod
    def validate_xpay_encoding_aes_key(
        cls,
        value: SecretStr | None,
    ) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value().strip()
        if not raw:
            return None
        if len(raw) != 43:
            raise ValueError("虚拟支付 EncodingAESKey 必须为 43 个字符")
        try:
            decoded = base64.b64decode(raw + "=", validate=True)
        except Exception as exc:
            raise ValueError("虚拟支付 EncodingAESKey 不是合法 Base64") from exc
        if len(decoded) != 32:
            raise ValueError("虚拟支付 EncodingAESKey 解码后必须为 32 字节")
        return SecretStr(raw)

    @field_validator("vod_app_id", mode="before")
    @classmethod
    def empty_vod_app_id_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator(
        "wechat_pay_notify_url",
        "cos_public_base_url",
        "taro_app_api_base_url",
        "vite_api_base_url",
    )
    @classmethod
    def validate_http_url(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            if info.field_name in {"wechat_pay_notify_url", "cos_public_base_url"}:
                return None
            raise ValueError(f"{info.field_name.upper()} 不能为空")
        # 后台构建允许相对路径（生产 /api/v1，与 /admin/ 同源），但不能是协议相对地址
        if (
            info.field_name == "vite_api_base_url"
            and value.startswith("/")
            and not value.startswith("//")
        ):
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{info.field_name.upper()} 必须是合法的 HTTP(S) 地址")
        if info.field_name == "wechat_pay_notify_url" and parsed.scheme != "https":
            raise ValueError("WECHAT_PAY_NOTIFY_URL 必须是 HTTPS 地址")
        return value

    @model_validator(mode="after")
    def validate_isolation_and_intervals(self) -> Settings:
        if (
            self.user_jwt_secret.get_secret_value()
            == self.admin_jwt_secret.get_secret_value()
        ):
            raise ValueError("USER_JWT_SECRET 与 ADMIN_JWT_SECRET 必须使用不同密钥")
        if (
            self.study_progress_flush_interval_seconds
            >= self.study_progress_ttl_seconds
        ):
            raise ValueError("学习进度落库周期必须小于 Redis 缓冲 TTL")
        return self

    @model_validator(mode="after")
    def validate_xpay_profiles(self) -> Settings:
        groups = (
            (
                "WECHAT_XPAY_PROD",
                (
                    self.wechat_xpay_prod_app_key,
                    self.wechat_xpay_prod_msg_token,
                    self.wechat_xpay_prod_encoding_aes_key,
                ),
            ),
            (
                "WECHAT_XPAY_SANDBOX",
                (
                    self.wechat_xpay_sandbox_app_key,
                    self.wechat_xpay_sandbox_msg_token,
                    self.wechat_xpay_sandbox_encoding_aes_key,
                ),
            ),
        )
        configured = False
        for label, values in groups:
            present = [value for value in values if value is not None]
            if present and len(present) != len(values):
                raise ValueError(
                    f"{label}_APP_KEY / {label}_MSG_TOKEN / "
                    f"{label}_ENCODING_AES_KEY 必须同时配置"
                )
            configured = configured or bool(present)

        if configured and not self.wechat_app_id:
            raise ValueError("配置微信虚拟支付时 WECHAT_APP_ID 不能为空")

        prod_token = self.wechat_xpay_prod_msg_token
        sandbox_token = self.wechat_xpay_sandbox_msg_token
        prod_aes = self.wechat_xpay_prod_encoding_aes_key
        sandbox_aes = self.wechat_xpay_sandbox_encoding_aes_key
        if (
            prod_token is not None
            and sandbox_token is not None
            and prod_token.get_secret_value()
            == sandbox_token.get_secret_value()
        ):
            raise ValueError(
                "正式与沙箱虚拟支付的 MSG_TOKEN 必须不同，否则无法区分环境"
            )
        if (
            prod_aes is not None
            and sandbox_aes is not None
            and prod_aes.get_secret_value()
            == sandbox_aes.get_secret_value()
        ):
            raise ValueError(
                "正式与沙箱虚拟支付的 ENCODING_AES_KEY 必须不同，否则无法区分环境"
            )
        return self

    @property
    def xpay_configured(self) -> bool:
        return any(
            value is not None
            for value in (
                self.wechat_xpay_prod_app_key,
                self.wechat_xpay_prod_msg_token,
                self.wechat_xpay_prod_encoding_aes_key,
                self.wechat_xpay_sandbox_app_key,
                self.wechat_xpay_sandbox_msg_token,
                self.wechat_xpay_sandbox_encoding_aes_key,
            )
        )

    @property
    def cors_origins(self) -> list[str]:
        """返回规范化后的 CORS 允许源列表。"""

        if not self.cors_allow_origins:
            return []
        return self.cors_allow_origins.split(",")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回进程内唯一配置实例，便于测试时调用 cache_clear()。"""

    return Settings()


settings = get_settings()

__all__ = ["ENV_FILE", "PROJECT_ROOT", "Settings", "get_settings", "settings"]
