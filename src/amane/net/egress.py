"""出站 URL 策略: 协议白名单与内网地址判定.

协议是全局底线 (``WebClient`` 的每个请求都校验): curl 本身还支持 ``file`` / ``gopher`` 等协议,
而调用方的 URL 可能来自第三方数据. 地址判定按调用点开启 — 资源下载把第三方 URL 带进出站通道,
是否允许私网由调用方决定 (见 ``docs/dev/api.md``).
"""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
from urllib.parse import SplitResult, urlsplit

from .errors import EgressRejected, FailureKind, RequestError, RequestFailure

_ALLOWED_SCHEMES = frozenset({"http", "https"})

_DEFAULT_PORTS = {"http": 80, "https": 443}

_INTERNAL_NETWORKS = (
    ip_network("0.0.0.0/8"),
    ip_network("10.0.0.0/8"),
    ip_network("100.64.0.0/10"),
    ip_network("127.0.0.0/8"),
    ip_network("169.254.0.0/16"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("::/128"),
    ip_network("::1/128"),
    ip_network("64:ff9b:1::/48"),
    ip_network("fc00::/7"),
    ip_network("fe80::/10"),
    ip_network("fec0::/10"),
)
"""指向本机或内网的地址段. 只拒绝这些段, 其余地址放行, 不使用 is_global/is_private.
后两者会把 Teredo、基准测试段与文档段等判为非公网, 可能误拒 fake-IP DNS 或 DNS 封堵应答.
64:ff9b:1::/48 是本地 NAT64 前缀, 整段拒绝; well-known NAT64 的内嵌 IPv4 则单独拆出判断."""

_NAT64_PREFIX = ip_network("64:ff9b::/96")


def is_internal_address(address: str) -> bool:
    """地址是否指向本机或内网, 同时识别 IPv4-mapped IPv6 与 well-known NAT64."""
    ip = ip_address(address)
    if isinstance(ip, IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip in _NAT64_PREFIX:
            ip = IPv4Address(int(ip) & 0xFFFFFFFF)
    return any(ip in network for network in _INTERNAL_NETWORKS)


def is_public_address(address: str) -> bool:
    """兼容旧调用名; 当前策略含义是拒绝内网黑名单, 不是严格的 IANA global 分类."""
    return not is_internal_address(address)


def _rejected(url: str, message: str, *, detail: str = "URL 不受支持") -> EgressRejected:
    return EgressRejected(url, message, detail=detail)


def _unresolved(url: str, message: str) -> RequestError:
    """解析失败按网络故障处理: 它不是策略拒绝, 调用方不应据此判断地址不合规."""
    return RequestError(url, RequestFailure(kind=FailureKind.CURL, message=message))


def _split(url: str) -> SplitResult:
    try:
        return urlsplit(url)
    except ValueError as exc:
        raise _rejected(url, f"URL 无法解析: {exc}") from exc


def ensure_http_scheme(url: str) -> None:
    """出站 URL 只接受 http(s): 其余协议不进入 curl."""
    scheme = _split(url).scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise _rejected(url, f"拒绝的协议: {scheme or '(空)'}")


async def resolve_addresses(host: str, port: int) -> set[str]:
    """解析 host 的全部地址. 模块级函数便于测试替换, 策略对象自身不发起 I/O."""
    infos = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    return {str(info[4][0]) for info in infos}


def _looks_numeric(host: str) -> bool:
    """纯数值写法 (十进制 / 八进制 / 短写 / 十六进制)."""
    if host.lower().startswith("0x"):
        return True
    return bool(host) and all(ch.isdigit() or ch == "." for ch in host)


def _is_canonical_ip(host: str) -> bool:
    try:
        ip_address(host)
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class EgressPolicy:
    """出站目标判定: ``allow_private`` 决定是否接受非公网地址, ``max_redirects`` 是逐跳复查的跳数上限."""

    allow_private: bool = False
    max_redirects: int = 5

    async def ensure_allowed(self, url: str, *, allow_fake_ip: bool = True) -> set[str] | None:
        """校验 URL 并返回本次解析出的地址, 供直连请求 pin 到实际连接.

        ``allow_fake_ip`` 保留为调用兼容参数; fake-IP 与 DNS 封堵应答不指向内网, 不再因地址分类而拒绝.
        """
        del allow_fake_ip
        ensure_http_scheme(url)
        if self.allow_private:
            return None

        parsed = _split(url)
        host = parsed.hostname
        if not host:
            raise _rejected(url, "URL 缺少主机名")
        # curl 自己解析数值主机: 0177.0.0.1 是八进制、2130706433 是十进制, 与 getaddrinfo 的解释不同,
        # 只按解析结果判定会漏掉这些写法. 因此数值形态必须是规范写法.
        if _looks_numeric(host) and not _is_canonical_ip(host):
            raise _rejected(url, f"非规范的数值主机: {host}")
        try:
            port = parsed.port or _DEFAULT_PORTS[parsed.scheme.lower()]
        except ValueError as exc:
            raise _rejected(url, f"端口非法: {exc}") from exc

        try:
            addresses = await resolve_addresses(host, port)
        except (OSError, UnicodeError) as exc:
            raise _unresolved(url, f"主机解析失败: {exc}") from exc
        if not addresses:
            raise _unresolved(url, "主机解析无结果")

        # 任一地址落在私网就整体拒绝: 双栈主机可能同时给出公网与内网地址, 放行等于让 curl 自己选.
        for address in addresses:
            if is_internal_address(address):
                raise _rejected(url, f"地址指向内网: {address}", detail="不支持内网地址")
        return addresses
