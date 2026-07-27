import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


_PATH = Path(__file__).resolve().parents[1] / "deploy" / "check-proxy-network.py"
_SPEC = importlib.util.spec_from_file_location("proxy_preflight", _PATH)
proxy_preflight = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(proxy_preflight)


def _argv(monkeypatch, *extra):
    monkeypatch.setattr(
        "sys.argv",
        [
            str(_PATH),
            "--profile",
            "rehearsal",
            "--project",
            "paim-rehearsal",
            "--subnet",
            "172.30.13.0/24",
            "--caddy-ip",
            "172.30.13.10",
            "--backend-ip",
            "172.30.13.20",
            *extra,
        ],
    )


def test_profile_contract_validation_does_not_need_docker(monkeypatch):
    _argv(monkeypatch, "--validate-only")
    proxy_preflight.main()


def test_profile_contract_rejects_unapproved_subnet(monkeypatch):
    _argv(monkeypatch, "--validate-only")
    monkeypatch.setattr("sys.argv", [arg.replace("172.30.13.0/24", "172.31.0.0/24") for arg in __import__("sys").argv])
    with pytest.raises(SystemExit):
        proxy_preflight.main()


def test_foreign_overlapping_docker_network_is_rejected(monkeypatch):
    _argv(monkeypatch)
    monkeypatch.setattr(proxy_preflight.shutil, "which", lambda _: "/bin/tool")
    foreign = [{
        "Labels": {"com.docker.compose.project": "other"},
        "IPAM": {"Config": [{"Subnet": "172.30.13.0/24"}]},
    }]
    responses = iter([
        SimpleNamespace(stdout="network-id\n"),
        SimpleNamespace(stdout=json.dumps(foreign)),
    ])
    monkeypatch.setattr(proxy_preflight.subprocess, "run", lambda *a, **k: next(responses))
    with pytest.raises(SystemExit):
        proxy_preflight.main()


def test_self_owned_exact_network_and_route_are_allowed(monkeypatch):
    _argv(monkeypatch)
    monkeypatch.setattr(proxy_preflight.shutil, "which", lambda _: "/bin/tool")
    own = [{
        "Id": "1234567890abcdef",
        "Labels": {
            "com.docker.compose.project": "paim-rehearsal",
            "com.docker.compose.network": "proxy_internal",
        },
        "IPAM": {"Config": [{"Subnet": "172.30.13.0/24"}]},
    }]
    responses = iter([
        SimpleNamespace(stdout="network-id\n"),
        SimpleNamespace(stdout=json.dumps(own)),
        SimpleNamespace(stdout=json.dumps([{
            "dst": "172.30.13.0/24", "dev": "br-1234567890ab"
        }]))
    ])
    monkeypatch.setattr(proxy_preflight.subprocess, "run", lambda *a, **k: next(responses))
    proxy_preflight.main()


def test_same_cidr_on_foreign_interface_is_rejected(monkeypatch):
    _argv(monkeypatch)
    monkeypatch.setattr(proxy_preflight.shutil, "which", lambda _: "/bin/tool")
    own = [{
        "Id": "1234567890abcdef",
        "Labels": {
            "com.docker.compose.project": "paim-rehearsal",
            "com.docker.compose.network": "proxy_internal",
        },
        "IPAM": {"Config": [{"Subnet": "172.30.13.0/24"}]},
    }]
    responses = iter([
        SimpleNamespace(stdout="network-id\n"),
        SimpleNamespace(stdout=json.dumps(own)),
        SimpleNamespace(stdout=json.dumps([
            {"dst": "172.30.13.0/24", "dev": "br-1234567890ab"},
            {"dst": "172.30.13.0/24", "dev": "eth0", "metric": 10},
        ])),
    ])
    monkeypatch.setattr(proxy_preflight.subprocess, "run", lambda *a, **k: next(responses))
    with pytest.raises(SystemExit):
        proxy_preflight.main()
