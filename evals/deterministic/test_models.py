from types import SimpleNamespace

from waku.config import Settings
from waku.loop import models


def test_xai_grok_provider_uses_expected_key_endpoint_and_models(monkeypatch, tmp_path):
    captured = {}

    class StubOpenAICompatClient:
        def __init__(self, *, api_key, base_url, timeout):
            captured.update(api_key=api_key, base_url=base_url, timeout=timeout)

    monkeypatch.setenv("XAI_API_KEY", "test-xai-key")
    monkeypatch.setattr(models, "OpenAICompatClient", StubOpenAICompatClient)
    settings = Settings(provider="xai", api_key="", base_url=None, model="",
                        small_model="", home=tmp_path)

    client = models.get_client(settings)

    assert isinstance(client, StubOpenAICompatClient)
    assert captured["api_key"] == "test-xai-key"
    assert captured["base_url"] == "https://api.x.ai/v1"
    assert settings.model == "grok-4"


def test_openai_default_is_a_real_catalog_id(tmp_path):
    """Regression: the default was bare 'gpt-5.6', which isn't a callable id
    (the catalog ships gpt-5.6-luna/-sol/-terra). Flagship is the -sol variant."""
    from waku.loop.models import PROVIDERS
    assert PROVIDERS["openai"].model == "gpt-5.6-sol"
    assert PROVIDERS["openai"].default_pair() == ["gpt-5.6-sol", "gpt-5.6-luna"]


def test_deepseek_provider_uses_expected_key_endpoint_and_models(monkeypatch, tmp_path):
    captured = {}

    class StubOpenAICompatClient:
        def __init__(self, *, api_key, base_url, timeout):
            captured.update(api_key=api_key, base_url=base_url, timeout=timeout)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setattr(models, "OpenAICompatClient", StubOpenAICompatClient)
    settings = Settings(
        provider="deepseek",
        api_key="",
        base_url=None,
        model="",
        small_model="",
        home=tmp_path,
    )

    client = models.get_client(settings)

    assert isinstance(client, StubOpenAICompatClient)
    assert captured["api_key"] == "test-deepseek-key"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert settings.model == "deepseek-v4-pro"
    assert settings.small_model == "deepseek-v4-pro"


def test_minimax_provider_uses_expected_key_endpoint_and_models(monkeypatch, tmp_path):
    captured = {}

    class StubAnthropicClient:
        def __init__(self, *, api_key, base_url, timeout):
            captured.update(api_key=api_key, base_url=base_url, timeout=timeout)
            self.messages = None

    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")
    monkeypatch.setitem(
        __import__("sys").modules,
        "anthropic",
        SimpleNamespace(Anthropic=StubAnthropicClient),
    )
    settings = Settings(
        provider="minimax",
        api_key="",
        base_url=None,
        model="",
        small_model="",
        home=tmp_path,
    )

    client = models.get_client(settings)

    assert isinstance(client, StubAnthropicClient)
    assert captured["api_key"] == "test-minimax-key"
    assert captured["base_url"] == "https://api.minimaxi.com/anthropic"
    assert captured["timeout"] == 120.0
    assert settings.model == "MiniMax-M3"
    assert settings.small_model == "MiniMax-M2"
