"""Load MM/MD addresses and credentials from a local YAML file."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class MmEntry(BaseModel):
    ip: str
    username: str
    password: str


class MdEntry(BaseModel):
    ip: str
    username: str | None = None
    password: str | None = None


class DevicesConfig(BaseModel):
    """与 aos8.devices.example.yaml 结构一致。"""

    verify_ssl: bool = False
    mm: MmEntry
    md: list[MdEntry] = Field(default_factory=list)


def default_devices_config_path() -> Path:
    raw = os.environ.get("AOS8_DEVICES_CONFIG", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd() / "aos8.devices.yaml"


def load_devices_config(path: Path | None = None) -> DevicesConfig:
    p = path or default_devices_config_path()
    p = p.expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(
            f"Device config file not found: {p}. Copy aos8.devices.example.yaml to aos8.devices.yaml and fill in the credentials, "
            f"or specify the path through the environment variable AOS8_DEVICES_CONFIG."
        )
    text = p.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid config file format (should be a YAML mapping): {p}")
    return DevicesConfig.model_validate(data)


def resolve_md_logins(cfg: DevicesConfig) -> tuple[list[str], dict[str, tuple[str, str]]]:
    """Return (ordered list of MD IPs, per-IP (username, password) overrides)."""
    order: list[str] = []
    logins: dict[str, tuple[str, str]] = {}
    for m in cfg.md:
        host = m.ip.strip()
        if not host:
            continue
        order.append(host)
        u = m.username if m.username is not None else cfg.mm.username
        p = m.password if m.password is not None else cfg.mm.password
        logins[host] = (u, p)
    return order, logins
