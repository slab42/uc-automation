#!/usr/bin/env python3

"""
Live connections for the web GUI's resource pages.

The resource pages talk to CUCM / CUC / Webex / CUBE from inside the FastAPI
process rather than by launching a script, so this module owns three things
the scripts get from setup/multi_object_loader.py in the terminal:

1. Targets. Which clusters, routers and Webex orgs exist, read from
   _DATA/clusters.csv, _DATA/routers.csv and the WEBEX: sections of
   .env/credentials.env.
2. Credentials. Read from .env/credentials.env with configparser directly,
   NOT through setup.env_loader.CredentialsLoader: its getters call
   getpass() when a password is blank, which would hang a web request
   forever. A blank password here is reported as "needs unlock" and the
   browser supplies it through POST /api/connections/{service}/{name}/unlock.
3. Clients. A cached ucmAPI.AXL / cucAPI.CUC / webexAPI.Webex per target,
   because building an AXL client parses a multi-megabyte WSDL and takes
   seconds.

Password handling matches the repo's hard rule: a secret supplied by the
browser is held in this process's memory only, is never written to disk,
never logged, and never appears in any API response. Every status dict
reports booleans (`has_password`, `unlocked`), never a value.
"""

from __future__ import annotations

import configparser
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "cucm", ROOT / "cuc", ROOT / "webex"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from setup.multi_object_loader import read_clusters_csv, read_routers_csv  # noqa: E402

CREDENTIALS_PATH = ROOT / ".env" / "credentials.env"
CLUSTERS_CSV = ROOT / "_DATA" / "clusters.csv"
ROUTERS_CSV = ROOT / "_DATA" / "routers.csv"
WSDL_DIR = ROOT / "cucm" / "schema"

SERVICES = ("CUCM", "CUC", "WEBEX", "CUBE")

#: Secret key name per service in credentials.env.
SECRET_KEY = {"CUCM": "password", "CUC": "password", "CUBE": "password",
              "WEBEX": "api_token"}


class NeedsCredentials(Exception):
    """Raised when a target has no usable secret in memory or on disk.

    The API turns this into 409 with the target name so the page can show
    its unlock form.
    """

    def __init__(self, service: str, name: str, username: str = "",
                 reason: str = "password required"):
        super().__init__(f"{service}:{name} {reason}")
        self.service = service
        self.name = name
        self.username = username
        self.reason = reason


class ConnectionError_(Exception):
    """A target is known but could not be reached or built."""


@dataclass
class Target:
    """One system a resource can be synced from."""

    service: str
    name: str
    server: str = ""
    version: str = ""
    extra: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"service": self.service, "name": self.name, "server": self.server,
                "version": self.version, **self.extra}


# -- credentials file -----------------------------------------------------

def _read_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if CREDENTIALS_PATH.exists():
        try:
            cfg.read(CREDENTIALS_PATH)
        except configparser.Error:
            pass
    return cfg


def _section_for(cfg: configparser.ConfigParser, service: str,
                 name: str) -> Tuple[Optional[str], Dict[str, str]]:
    """Return (section name, values) using the repo's object -> default order."""
    for candidate in (f"{service}:{name}", f"{service}:default"):
        if cfg.has_section(candidate):
            return candidate, {k.strip().lower(): (v or "").strip()
                               for k, v in cfg.items(candidate)}
    return None, {}


# -- in-memory secrets ----------------------------------------------------

_secrets: Dict[str, Tuple[str, str]] = {}   # "SERVICE:name" -> (username, secret)
_secrets_lock = threading.Lock()


def _key(service: str, name: str) -> str:
    return f"{service.upper()}:{name}"


def unlock(service: str, name: str, secret: str, username: str = "") -> None:
    """Hold a username/secret for this target for the life of the process."""
    service = service.upper()
    if not secret:
        raise ValueError("secret must not be empty")
    if not username:
        cfg = _read_config()
        _sec, values = _section_for(cfg, service, name)
        username = values.get("username", "")
    with _secrets_lock:
        _secrets[_key(service, name)] = (username, secret)
    _drop_client(service, name)


def forget(service: Optional[str] = None, name: Optional[str] = None) -> int:
    """Forget in-memory secrets (all of them when called with no arguments)."""
    with _secrets_lock:
        if service is None:
            n = len(_secrets)
            _secrets.clear()
        else:
            prefix = _key(service.upper(), name) if name else f"{service.upper()}:"
            doomed = [k for k in _secrets
                      if k == prefix or (name is None and k.startswith(prefix))]
            for k in doomed:
                _secrets.pop(k, None)
            n = len(doomed)
    _drop_client(service, name)
    return n


def resolve(service: str, name: str) -> Tuple[str, str]:
    """Return (username, secret) for a target or raise NeedsCredentials."""
    service = service.upper()
    with _secrets_lock:
        held = _secrets.get(_key(service, name))
    if held and held[1]:
        return held

    cfg = _read_config()
    section, values = _section_for(cfg, service, name)
    username = values.get("username", "")
    secret = values.get(SECRET_KEY.get(service, "password"), "")
    if not secret:
        raise NeedsCredentials(
            service, name, username,
            "no section in credentials.env" if section is None
            else "password is blank in credentials.env")
    return username, secret


def credential_status(service: str, name: str) -> dict:
    """What the page needs to decide between "Sync" and an unlock form."""
    service = service.upper()
    cfg = _read_config()
    section, values = _section_for(cfg, service, name)
    secret_key = SECRET_KEY.get(service, "password")
    with _secrets_lock:
        held = _secrets.get(_key(service, name))
    return {
        "service": service,
        "name": name,
        "section": section,
        "username": (held[0] if held and held[0] else values.get("username", "")),
        "secret_key": secret_key,
        "has_stored_secret": bool(values.get(secret_key)),
        "unlocked": bool(held and held[1]),
        "ready": bool((held and held[1]) or values.get(secret_key)),
    }


# -- targets --------------------------------------------------------------

def list_targets(service: str) -> List[Target]:
    """Targets for a service, in the order the CSV / credentials file lists them."""
    service = service.upper()
    if service in ("CUCM", "CUC"):
        wanted = service.lower()
        targets = []
        for row in read_clusters_csv(CLUSTERS_CSV):
            if row.get("cluster_type", "cucm") != wanted:
                continue
            if service == "CUCM" and row.get("server_type") not in ("publisher", "", None):
                continue
            targets.append(Target(service=service, name=row["name"], server=row["server"],
                                  version=row["version"],
                                  extra={"server_type": row.get("server_type", "")}))
        return targets
    if service == "CUBE":
        return [Target(service="CUBE", name=r["name"], server=r["ip"])
                for r in read_routers_csv(ROUTERS_CSV)]
    if service == "WEBEX":
        cfg = _read_config()
        names = [s.split(":", 1)[1] for s in cfg.sections() if s.startswith("WEBEX:")]
        ordered = [n for n in names if n != "default"] or names
        return [Target(service="WEBEX", name=n, server="webexapis.com") for n in ordered]
    return []


def find_target(service: str, name: str) -> Optional[Target]:
    for target in list_targets(service):
        if target.name == name:
            return target
    return None


def targets_view(service: str) -> List[dict]:
    """Targets plus their credential status, for the target picker."""
    return [{**t.to_dict(), **credential_status(service, t.name)}
            for t in list_targets(service)]


# -- clients --------------------------------------------------------------

_clients: Dict[str, object] = {}
_clients_lock = threading.Lock()


def _drop_client(service: Optional[str], name: Optional[str]) -> None:
    with _clients_lock:
        if service is None:
            _clients.clear()
            return
        prefix = _key(service.upper(), name) if name else f"{service.upper()}:"
        for k in [k for k in _clients if k == prefix or (name is None and k.startswith(prefix))]:
            _clients.pop(k, None)


def available_wsdl_versions() -> List[str]:
    if not WSDL_DIR.is_dir():
        return []
    return sorted(p.name for p in WSDL_DIR.iterdir()
                  if (p / "AXLAPI.wsdl").is_file())


def get_client(service: str, name: str):
    """A connected client for a target, built once and cached.

    Raises NeedsCredentials when no secret is available, or
    ConnectionError_ when the target or its WSDL is missing.
    """
    service = service.upper()
    target = find_target(service, name)
    if target is None:
        raise ConnectionError_(f"{service} target {name!r} is not defined")
    username, secret = resolve(service, name)

    cache_key = _key(service, name)
    with _clients_lock:
        client = _clients.get(cache_key)
    if client is not None:
        return client

    client = _build_client(target, username, secret)
    with _clients_lock:
        _clients[cache_key] = client
    return client


def _build_client(target: Target, username: str, secret: str):
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    if target.service == "CUCM":
        wsdl_path = WSDL_DIR / target.version / "AXLAPI.wsdl"
        if not wsdl_path.is_file():
            raise ConnectionError_(
                f"No AXL WSDL for CUCM version {target.version!r}. "
                f"Add cucm/schema/{target.version}/AXLAPI.wsdl "
                f"(have: {', '.join(available_wsdl_versions()) or 'none'})")
        from ucmAPI import AXL
        return AXL(username=username, password=secret,
                   wsdl=wsdl_path.absolute().as_uri(),
                   cucm=target.server, cucm_version=target.version)

    if target.service == "CUC":
        from cucAPI import CUC
        return CUC(username=username, password=secret,
                   server=target.server, version=target.version)

    if target.service == "WEBEX":
        from webexAPI import Webex
        return Webex(token=secret)

    if target.service == "CUBE":
        # netmiko sessions time out, so CUBE resources open their own
        # connection per sync via cube_session() instead of caching one.
        raise ConnectionError_("CUBE targets use cube_session(), not get_client()")

    raise ConnectionError_(f"Unknown service {target.service!r}")


def cube_session(name: str):
    """Open an SSH session to a router; caller closes it (context manager)."""
    target = find_target("CUBE", name)
    if target is None:
        raise ConnectionError_(f"CUBE target {name!r} is not in routers.csv")
    username, secret = resolve("CUBE", name)
    try:
        from netmiko import ConnectHandler
    except ImportError as exc:
        raise ConnectionError_(
            "netmiko is required for CUBE pages: pip install netmiko") from exc
    return ConnectHandler(device_type="cisco_ios", host=target.server,
                          username=username, password=secret, timeout=30,
                          fast_cli=False)
