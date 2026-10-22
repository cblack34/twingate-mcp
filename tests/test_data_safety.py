import inspect
import json
import re
from pathlib import Path
from typing import Any

from polyfactory.factories.pydantic_factory import ModelFactory

from tests import factories

ROOT = Path(__file__).parent.parent
SAFE_DOMAINS = ("example.com", "example.org", "example.net")
EMAIL_KEYS = {"email", "user_email", "userEmail"}
HOST_KEYS = {"address"}
NETWORK_KEYS = {"network", "remote_network", "remoteNetwork"}


def domain_ok(domain: str) -> bool:
    return any(domain == d or domain.endswith(f".{d}") for d in SAFE_DOMAINS)


def violations(value: Any, key: str = "") -> list[str]:
    if isinstance(value, dict):
        if key in HOST_KEYS and "value" in value:
            value = value | {"address": value["value"]}
        if key in NETWORK_KEYS and "name" in value:
            value = value | {"network": value["name"]}
        return [v for k, item in value.items() for v in violations(item, k)]  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list):
        return [v for item in value for v in violations(item, key)]  # pyright: ignore[reportUnknownVariableType]
    if not isinstance(value, str):
        return []
    if (key in EMAIL_KEYS or "@" in value) and not domain_ok(value.rpartition("@")[2]):
        return [f"{key}={value}"]
    if key in HOST_KEYS and not domain_ok(value):
        return [f"{key}={value}"]
    if key in NETWORK_KEYS and value not in factories.FAKE_NETWORKS:
        return [f"{key}={value}"]
    return []


def test_queries_are_read_only() -> None:
    files = list((ROOT / "queries").glob("*.graphql"))
    assert files
    for path in files:
        assert not re.search(r"\bmutation\b", path.read_text(), re.IGNORECASE), path


def test_generated_client_has_no_mutations() -> None:
    files = list((ROOT / "src/twingate_mcp/_generated").rglob("*.py"))
    assert files
    for path in files:
        assert not re.search(r"mutation", path.read_text(), re.IGNORECASE), path


def test_fixtures_are_synthetic() -> None:
    files = list((ROOT / "tests/fixtures").glob("*.json"))
    assert files
    for path in files:
        assert violations(json.loads(path.read_text())) == [], path


def test_factories_are_synthetic() -> None:
    found = [
        f
        for _, f in inspect.getmembers(factories, inspect.isclass)
        if issubclass(f, ModelFactory) and not f.__dict__.get("__is_base_factory__")
    ]
    assert len(found) == 16
    for factory in found:
        for instance in factory.batch(200):
            data = instance.model_dump(by_alias=True)
            if factory in (factories.RemoteNetworkFactory, factories.ListRemoteNetworksNodeFactory):
                data["network"] = data.pop("name")
            assert violations(data) == [], factory.__name__


def test_guard_catches_real_looking_data() -> None:
    assert violations({"email": "ceo@realcorp.io"})
    assert violations({"address": "db.internal.realcorp.io"})
    assert violations({"remoteNetwork": {"name": "prod-us-east"}})
    assert violations({"address": {"value": "db.realcorp.io"}})
    assert not violations({"email": "a@sub.example.net"})
