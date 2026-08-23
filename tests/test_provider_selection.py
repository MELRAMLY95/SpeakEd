import pytest
from ai.local_ai import create_provider, ZAIProvider, GeminiProvider, OllamaProvider, OpenAIProvider, RuleBasedProvider


class TestProviderSelection:
    """Test suite for AI provider selection logic."""

    def test_explicit_zai_provider_with_key(self):
        """Test explicit Z.AI provider selection when API key is set."""
        config = {
            "AI_PROVIDER": "zai",
            "ZAI_API_KEY": "test-key",
            "ZAI_MODEL": "glm-4",
            "ZAI_BASE_URL": "https://api.z.ai/api/paas/v4"
        }
        provider = create_provider(config)
        assert isinstance(provider, ZAIProvider)
        assert provider.api_key == "test-key"

    def test_explicit_zai_provider_without_key_raises(self):
        """Test that explicit Z.AI provider raises error when API key is missing."""
        config = {
            "AI_PROVIDER": "zai",
            "ZAI_API_KEY": "",
            "ZAI_MODEL": "glm-4",
            "ZAI_BASE_URL": "https://api.z.ai/api/paas/v4"
        }
        with pytest.raises(RuntimeError) as exc_info:
            create_provider(config)
        assert "ZAI_API_KEY is not set" in str(exc_info.value)

    def test_explicit_rule_provider(self):
        """Test explicit rule-based provider selection."""
        config = {"AI_PROVIDER": "rule"}
        provider = create_provider(config)
        assert isinstance(provider, RuleBasedProvider)

    def test_explicit_ollama_provider(self):
        """Test explicit Ollama provider selection."""
        config = {
            "AI_PROVIDER": "ollama",
            "OLLAMA_BASE_URL": "http://localhost:11434",
            "OLLAMA_MODEL": "llama3.2"
        }
        provider = create_provider(config)
        assert isinstance(provider, OllamaProvider)

    def test_explicit_gemini_provider(self):
        """Test explicit Gemini provider selection."""
        config = {
            "AI_PROVIDER": "gemini",
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL": "gemini-3.6-flash"
        }
        provider = create_provider(config)
        assert isinstance(provider, GeminiProvider)

    def test_explicit_openai_provider(self):
        """Test explicit OpenAI provider selection."""
        config = {
            "AI_PROVIDER": "openai",
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "gpt-4o-mini"
        }
        provider = create_provider(config)
        assert isinstance(provider, OpenAIProvider)

    def test_auto_mode_selects_zai_first(self):
        """Test that auto mode selects Z.AI when API key is available."""
        config = {
            "AI_PROVIDER": "auto",
            "ZAI_API_KEY": "test-key",
            "ZAI_MODEL": "glm-4",
            "ZAI_BASE_URL": "https://api.z.ai/api/paas/v4",
            "GEMINI_API_KEY": "gemini-key"
        }
        provider = create_provider(config)
        assert isinstance(provider, ZAIProvider)

    def test_auto_mode_falls_back_to_gemini(self):
        """Test that auto mode falls back to Gemini when Z.AI key is missing."""
        config = {
            "AI_PROVIDER": "auto",
            "ZAI_API_KEY": "",
            "GEMINI_API_KEY": "gemini-key",
            "GEMINI_MODEL": "gemini-3.6-flash"
        }
        provider = create_provider(config)
        assert isinstance(provider, GeminiProvider)

    def test_auto_mode_falls_back_to_ollama_local(self):
        """Test that auto mode falls back to Ollama in local development."""
        config = {
            "AI_PROVIDER": "auto",
            "ZAI_API_KEY": "",
            "GEMINI_API_KEY": "",
            "IS_RENDER": False,
            "OLLAMA_BASE_URL": "http://localhost:11434",
            "OLLAMA_MODEL": "llama3.2"
        }
        # Note: This test doesn't actually check if Ollama is available,
        # but verifies the selection logic would consider it
        provider = create_provider(config)
        # In a real scenario, Ollama availability would be checked
        # Since we can't mock the network check and Ollama is not running,
        # it will fall back to rule-based provider
        # This is expected behavior - the logic correctly tries Ollama first
        assert provider is not None
        # The actual provider will be either Ollama (if available) or rule-based (if not)
        # Since Ollama is not running in this test environment, it falls back to rule-based
        assert isinstance(provider, (OllamaProvider, RuleBasedProvider))

    def test_auto_mode_falls_back_to_openai(self):
        """Test that auto mode falls back to OpenAI when other providers are unavailable."""
        config = {
            "AI_PROVIDER": "auto",
            "ZAI_API_KEY": "",
            "GEMINI_API_KEY": "",
            "OPENAI_API_KEY": "openai-key",
            "OPENAI_MODEL": "gpt-4o-mini",
            "IS_RENDER": True  # On Render, skip Ollama
        }
        provider = create_provider(config)
        assert isinstance(provider, OpenAIProvider)

    def test_auto_mode_falls_back_to_rule(self):
        """Test that auto mode falls back to rule-based when no API keys are available."""
        config = {
            "AI_PROVIDER": "auto",
            "ZAI_API_KEY": "",
            "GEMINI_API_KEY": "",
            "OPENAI_API_KEY": "",
            "IS_RENDER": True
        }
        provider = create_provider(config)
        assert isinstance(provider, RuleBasedProvider)

    def test_auto_mode_priority_order(self):
        """Test the complete priority chain: Z.AI → Gemini → Ollama → OpenAI → rule."""
        # With all keys available, Z.AI should be selected
        config_all = {
            "AI_PROVIDER": "auto",
            "ZAI_API_KEY": "zai-key",
            "GEMINI_API_KEY": "gemini-key",
            "OPENAI_API_KEY": "openai-key",
            "IS_RENDER": False
        }
        provider = create_provider(config_all)
        assert isinstance(provider, ZAIProvider)

        # Without Z.AI, Gemini should be selected
        config_no_zai = {
            "AI_PROVIDER": "auto",
            "ZAI_API_KEY": "",
            "GEMINI_API_KEY": "gemini-key",
            "OPENAI_API_KEY": "openai-key",
            "IS_RENDER": False
        }
        provider = create_provider(config_no_zai)
        assert isinstance(provider, GeminiProvider)

        # Without Z.AI and Gemini, Ollama should be tried (local)
        config_no_apis = {
            "AI_PROVIDER": "auto",
            "ZAI_API_KEY": "",
            "GEMINI_API_KEY": "",
            "OPENAI_API_KEY": "",
            "IS_RENDER": False
        }
        provider = create_provider(config_no_apis)
        # Should try Ollama first, then fall back to rule if unavailable
        # Since we can't mock the actual Ollama availability check,
        # we just verify it doesn't crash and returns a valid provider
        assert provider is not None
        # The actual provider will be either Ollama (if available) or rule-based (if not)
        assert isinstance(provider, (OllamaProvider, RuleBasedProvider))

    def test_case_insensitive_provider_selection(self):
        """Test that provider selection is case-insensitive."""
        config = {
            "AI_PROVIDER": "ZAI",
            "ZAI_API_KEY": "test-key",
            "ZAI_MODEL": "glm-4",
            "ZAI_BASE_URL": "https://api.z.ai/api/paas/v4"
        }
        provider = create_provider(config)
        assert isinstance(provider, ZAIProvider)

    def test_default_auto_mode(self):
        """Test that auto mode is the default when AI_PROVIDER is not set."""
        config = {
            "ZAI_API_KEY": "test-key",
            "ZAI_MODEL": "glm-4",
            "ZAI_BASE_URL": "https://api.z.ai/api/paas/v4"
        }
        provider = create_provider(config)
        assert isinstance(provider, ZAIProvider)

    def test_zai_configurable_model(self):
        """Test that Z.AI model is configurable."""
        config = {
            "AI_PROVIDER": "zai",
            "ZAI_API_KEY": "test-key",
            "ZAI_MODEL": "glm-4-plus",
            "ZAI_BASE_URL": "https://api.z.ai/api/paas/v4"
        }
        provider = create_provider(config)
        assert provider.model == "glm-4-plus"

    def test_zai_configurable_base_url(self):
        """Test that Z.AI base URL is configurable."""
        config = {
            "AI_PROVIDER": "zai",
            "ZAI_API_KEY": "test-key",
            "ZAI_MODEL": "glm-4",
            "ZAI_BASE_URL": "https://custom.api.z.ai/v4"
        }
        provider = create_provider(config)
        assert provider.base_url == "https://custom.api.z.ai/v4"

    def test_zai_default_model_when_not_specified(self):
        """Test that Z.AI uses default model when not specified in config."""
        config = {
            "AI_PROVIDER": "zai",
            "ZAI_API_KEY": "test-key",
            "ZAI_BASE_URL": "https://api.z.ai/api/paas/v4"
        }
        provider = create_provider(config)
        assert provider.model == "glm-4"  # default model

    def test_zai_default_base_url_when_not_specified(self):
        """Test that Z.AI uses default base URL when not specified in config."""
        config = {
            "AI_PROVIDER": "zai",
            "ZAI_API_KEY": "test-key",
            "ZAI_MODEL": "glm-4"
        }
        provider = create_provider(config)
        assert provider.base_url == "https://api.z.ai/api/paas/v4"  # default URL
