#!/usr/bin/env python3
"""프로필 proxy 계약과 기존 Docker/호스트 네트워크 충돌을 검사한다."""

import argparse
import ipaddress
import json
import shutil
import subprocess
import sys


PROFILES = {
    "prod": ("172.30.12.0/24", "172.30.12.10", "172.30.12.20"),
    "rehearsal": ("172.30.13.0/24", "172.30.13.10", "172.30.13.20"),
    "restore": ("172.30.14.0/24", "172.30.14.10", "172.30.14.20"),
}


def fail(message: str) -> None:
    print(f"[network-preflight] FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def run_json(command):
    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        return json.loads(result.stdout or "[]")
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        fail(f"검사 명령을 신뢰할 수 있게 실행하지 못했습니다: {command[0]}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--subnet", required=True)
    parser.add_argument("--caddy-ip", required=True)
    parser.add_argument("--backend-ip", required=True)
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    expected_subnet, expected_caddy, expected_backend = PROFILES[args.profile]
    try:
        target = ipaddress.ip_network(args.subnet, strict=True)
        caddy = ipaddress.ip_address(args.caddy_ip)
        backend = ipaddress.ip_address(args.backend_ip)
    except ValueError:
        fail("subnet/static IP 형식이 올바르지 않습니다")
    if (str(target), str(caddy), str(backend)) != (
        expected_subnet,
        expected_caddy,
        expected_backend,
    ):
        fail(f"{args.profile} 프로필의 승인된 subnet/static IP와 일치하지 않습니다")
    if caddy not in target or backend not in target or caddy == backend:
        fail("Caddy/backend IP는 서로 달라야 하며 proxy subnet 안에 있어야 합니다")
    if args.validate_only:
        return

    if shutil.which("docker") is None or shutil.which("ip") is None:
        fail("docker와 ip 명령이 모두 있어야 충돌을 fail-closed로 검사할 수 있습니다")

    network_ids = subprocess.run(
        ["docker", "network", "ls", "-q"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    ).stdout.split()
    networks = run_json(["docker", "network", "inspect", *network_ids]) if network_ids else []
    own_bridges: set[str] = set()
    for network in networks:
        labels = network.get("Labels") or {}
        own = (
            labels.get("com.docker.compose.project") == args.project
            and labels.get("com.docker.compose.network") == "proxy_internal"
        )
        for config in (network.get("IPAM") or {}).get("Config") or []:
            raw = config.get("Subnet")
            if not raw:
                continue
            try:
                existing = ipaddress.ip_network(raw, strict=False)
            except ValueError:
                fail("Docker network의 subnet 정보를 해석할 수 없습니다")
            if not target.overlaps(existing):
                continue
            if own and existing == target:
                network_id = network.get("Id")
                options = network.get("Options") or {}
                bridge = options.get("com.docker.network.bridge.name")
                if not bridge and network_id:
                    bridge = f"br-{network_id[:12]}"
                if not bridge:
                    fail("자기 Docker network의 bridge interface를 확인할 수 없습니다")
                own_bridges.add(bridge)
                continue
            fail(f"다른 Docker network와 proxy subnet이 겹칩니다: {existing}")

    routes = run_json(["ip", "-j", "-4", "route", "show"])
    for route in routes:
        raw = route.get("dst")
        if not raw or raw == "default":
            continue
        try:
            existing = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            fail("호스트 route 정보를 해석할 수 없습니다")
        own_bridge_route = existing == target and route.get("dev") in own_bridges
        if target.overlaps(existing) and not own_bridge_route:
            fail(f"호스트 route와 proxy subnet이 겹칩니다: {existing}")


if __name__ == "__main__":
    main()
