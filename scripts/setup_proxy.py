#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parse optional NODE_LINK (VLESS URL) and generate sing-box / xray configuration.
Supports tcp, ws, grpc, http (h2), httpupgrade, and tls / reality / none.
Listens on local SOCKS5 proxy: socks5://127.0.0.1:1080
"""

import json
import os
import subprocess
import sys
import time
import urllib.parse
import socket


def set_github_env(key: str, value: str):
    env_file = os.environ.get("GITHUB_ENV")
    if env_file:
        with open(env_file, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")
    print(f"[ENV] {key}={value}")


def parse_vless_link(link: str) -> dict:
    link = link.strip()
    if not link.startswith("vless://"):
        raise ValueError("NODE_LINK must start with vless://")

    parsed = urllib.parse.urlsplit(link)
    uuid = urllib.parse.unquote(parsed.username or "")
    server = parsed.hostname or ""
    port = parsed.port or 443

    if not uuid or not server:
        raise ValueError("Invalid VLESS link: missing uuid or server hostname")

    params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))

    net_type = params.get("type", "tcp").lower()
    security = params.get("security", "none").lower()
    sni = params.get("sni", "") or params.get("peer", "") or server
    host = params.get("host", "") or sni
    path = urllib.parse.unquote(params.get("path", "/"))
    service_name = urllib.parse.unquote(params.get("serviceName", ""))
    flow = params.get("flow", "")
    fp = params.get("fp", "chrome") or "chrome"
    pbk = params.get("pbk", "")
    sid = params.get("sid", "")
    alpn_str = urllib.parse.unquote(params.get("alpn", ""))
    alpn = [x.strip() for x in alpn_str.split(",") if x.strip()] if alpn_str else []
    allow_insecure = params.get("allowInsecure", "0") in ("1", "true", "True")

    # Build streamSettings representation (wsSettings / tcpSettings / grpcSettings / httpSettings)
    # and convert to sing-box outbound structure
    stream_info = {"network": net_type}
    transport = None

    if net_type == "ws":
        ws_settings = {
            "path": path if path else "/",
            "headers": {"Host": host} if host else {},
        }
        stream_info["wsSettings"] = ws_settings
        transport = {
            "type": "ws",
            "path": ws_settings["path"],
        }
        if host:
            transport["headers"] = {"Host": host}
        # Handle early data query in path like ?ed=2048
        if "?ed=" in ws_settings["path"]:
            base_path, ed_part = ws_settings["path"].split("?ed=", 1)
            try:
                max_ed = int(ed_part.split("&")[0])
                transport["path"] = base_path or "/"
                transport["max_early_data"] = max_ed
                transport["early_data_header_name"] = "Sec-WebSocket-Protocol"
            except ValueError:
                pass

    elif net_type == "grpc":
        grpc_settings = {
            "serviceName": service_name,
            "multiMode": params.get("mode", "gun") == "multi",
        }
        stream_info["grpcSettings"] = grpc_settings
        transport = {
            "type": "grpc",
            "service_name": service_name,
        }

    elif net_type in ("http", "h2"):
        http_settings = {
            "host": [h.strip() for h in host.split(",") if h.strip()] if host else [server],
            "path": path if path else "/",
        }
        stream_info["httpSettings"] = http_settings
        transport = {
            "type": "http",
            "host": http_settings["host"],
            "path": http_settings["path"],
        }

    elif net_type == "httpupgrade":
        httpupgrade_settings = {
            "path": path if path else "/",
            "host": host,
        }
        stream_info["httpupgradeSettings"] = httpupgrade_settings
        transport = {
            "type": "httpupgrade",
            "path": httpupgrade_settings["path"],
        }
        if host:
            transport["host"] = host

    else:
        # tcpSettings
        header_type = params.get("headerType", "none")
        tcp_settings = {"header": {"type": header_type}}
        stream_info["tcpSettings"] = tcp_settings
        if header_type == "http":
            transport = {
                "type": "http",
                "path": path if path else "/",
            }
            if host:
                transport["host"] = [host]

    print(f"[Proxy] Parsed VLESS server={server}:{port}, network={net_type}, security={security}")
    print(f"[Proxy] Generated streamSettings: {json.dumps(stream_info, ensure_ascii=False)}")

    outbound = {
        "type": "vless",
        "tag": "vless-out",
        "server": server,
        "server_port": port,
        "uuid": uuid,
    }

    if flow:
        outbound["flow"] = flow

    if security in ("tls", "reality"):
        tls_cfg = {
            "enabled": True,
            "server_name": sni,
            "insecure": allow_insecure,
            "utls": {
                "enabled": True,
                "fingerprint": fp,
            },
        }
        if alpn:
            tls_cfg["alpn"] = alpn
        if security == "reality":
            tls_cfg["reality"] = {
                "enabled": True,
                "public_key": pbk,
                "short_id": sid,
            }
        outbound["tls"] = tls_cfg

    if transport:
        outbound["transport"] = transport

    singbox_config = {
        "log": {
            "level": "info",
            "timestamp": True,
        },
        "inbounds": [
            {
                "type": "socks",
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "listen_port": 1080,
            },
            {
                "type": "http",
                "tag": "http-in",
                "listen": "127.0.0.1",
                "listen_port": 1081,
            },
        ],
        "outbounds": [
            outbound,
            {
                "type": "direct",
                "tag": "direct",
            },
        ],
    }

    return singbox_config


def wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main():
    node_link = os.environ.get("NODE_LINK", "").strip()
    if not node_link:
        print("[Proxy] NODE_LINK is empty. Using direct connection (IS_PROXY=false).")
        set_github_env("IS_PROXY", "false")
        set_github_env("PROXY_URL", "")
        return

    try:
        config = parse_vless_link(node_link)
    except Exception as e:
        print(f"[Proxy] Failed to parse NODE_LINK: {e}. Falling back to direct connection.")
        set_github_env("IS_PROXY", "false")
        set_github_env("PROXY_URL", "")
        return

    config_path = "/tmp/singbox_config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"[Proxy] Wrote sing-box config to {config_path}")

    # Start sing-box in background
    log_file = open("/tmp/singbox.log", "w", encoding="utf-8")
    proc = subprocess.Popen(
        ["sing-box", "run", "-c", config_path],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"[Proxy] Started sing-box with PID {proc.pid}")

    if not wait_for_port("127.0.0.1", 1080, timeout=12.0):
        print("[Proxy] sing-box failed to listen on 127.0.0.1:1080. Log output:")
        try:
            with open("/tmp/singbox.log", "r", encoding="utf-8") as lf:
                print(lf.read())
        except Exception:
            pass
        set_github_env("IS_PROXY", "false")
        set_github_env("PROXY_URL", "")
        return

    print("[Proxy] Local SOCKS5 proxy is listening on socks5://127.0.0.1:1080")
    set_github_env("IS_PROXY", "true")
    set_github_env("PROXY_URL", "socks5://127.0.0.1:1080")
    set_github_env("HTTP_PROXY_URL", "http://127.0.0.1:1081")


if __name__ == "__main__":
    main()
