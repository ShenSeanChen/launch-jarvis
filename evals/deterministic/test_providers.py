"""OFFLINE provider-table checks: every PROVIDERS entry must build the right
client, fill its default model ids, and be covered by the dashboard's pricing
and model-listing fallbacks. No network, no real keys (fakes via monkeypatch).

Born from a live regression hunt: adding a provider touches shared paths
(get_client, HAS_KEY, /api/models, PRICING), and nothing offline proved the
other five still worked. Now something does.
"""

from __future__ import annotations

import anthropic
import pytest

from waku.config import Settings
from waku.loop.models import PROVIDERS, OpenAICompatClient, get_client


@pytest.fixture(autouse=True)
def fake_keys(monkeypatch):
    for provider in PROVIDERS.values():
        monkeypatch.setenv(provider.key_env, "fake-key-for-tests")
    # a stray custom-endpoint override must not leak into these checks
    monkeypatch.delenv("WAKU_API_KEY", raising=False)
    monkeypatch.delenv("WAKU_BASE_URL", raising=False)


@pytest.mark.parametrize("name", list(PROVIDERS))
def test_get_client_builds_the_right_wire(name):
    provider = PROVIDERS[name]
    settings = Settings(provider=name, model="", small_model="", api_key="", base_url=None)
    client = get_client(settings)
    expected = anthropic.Anthropic if provider.kind == "anthropic" else OpenAICompatClient
    assert isinstance(client, expected)
    # defaults must be filled in so the loop never sends model=""
    assert settings.model == provider.model
    assert settings.small_model == provider.small_model


@pytest.mark.parametrize("name", list(PROVIDERS))
def test_missing_key_exits_with_the_key_name(name, monkeypatch):
    monkeypatch.delenv(PROVIDERS[name].key_env, raising=False)
    settings = Settings(provider=name, model="", small_model="", api_key="", base_url=None)
    with pytest.raises(SystemExit, match=PROVIDERS[name].key_env):
        get_client(settings)


def test_unknown_provider_names_the_choices():
    settings = Settings(provider="not-a-provider", model="", small_model="",
                        api_key="", base_url=None)
    with pytest.raises(SystemExit, match="openrouter"):
        get_client(settings)


@pytest.mark.parametrize("name", list(PROVIDERS))
def test_dashboard_pricing_covers_every_provider(name):
    from waku.ops.dashboard import PRICING

    assert name in PRICING


@pytest.mark.parametrize("name", [n for n, p in PROVIDERS.items()
                                  if p.kind == "anthropic" or not p.base_url])
def test_model_listing_falls_back_without_a_catalog(name, monkeypatch):
    """Providers with no listable catalog still give the picker their defaults
    (and never make a network call to get them)."""
    from waku.ops import dashboard

    monkeypatch.setenv("WAKU_PROVIDER", name)
    monkeypatch.delenv("WAKU_MODEL", raising=False)
    monkeypatch.delenv("WAKU_SMALL_MODEL", raising=False)
    result = dashboard.list_models()
    assert result["listed"] is False
    ids = [m["id"] for m in result["models"]]
    assert PROVIDERS[name].model in ids
