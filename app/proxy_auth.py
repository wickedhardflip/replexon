"""Optional single sign-on behind a reverse proxy (for example Caddy forward_auth).

Trusts the Remote-User header only with both locks: the connection comes from a trusted network
(default: Docker, 172.16.0.0/12) AND carries the shared X-Homelab-Proxy secret. Off by default."""
import hmac
from ipaddress import ip_address, ip_network

from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.models.user import User


def _peer_trusted(host: str) -> bool:
    try:
        addr = ip_address(host)
    except ValueError:
        return False
    return any(addr in ip_network(n.strip()) for n in settings.trusted_proxy_networks.split(",") if n.strip())


def proxy_user(request, db: DBSession) -> User | None:
    if not settings.trust_proxy_auth or not settings.proxy_auth_secret:
        return None
    if not request.client or not _peer_trusted(request.client.host):
        return None
    if not hmac.compare_digest(request.headers.get("x-homelab-proxy", "").encode(), settings.proxy_auth_secret.encode()):
        return None
    name = request.headers.get("remote-user", "").strip().lower()
    if not name:
        return None
    mapping = dict(p.split("=", 1) for p in settings.proxy_auth_user_map.split(",") if "=" in p)
    return db.query(User).filter(User.username == mapping.get(name, name)).first()
