import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from ai.local_ai import ZAIProvider
from ai.ai_provider import AIMessage


class TestZAIProvider:
    """Test suite for Z.AI provider implementation."""

    def test_provider_initialization(self):
        """Test that Z.AI provider initializes correctly with configuration."""
        provider = ZAIProvider(
            api_key="test-key",
            model="glm-4",
            base_url="https://api.z.ai/api/paas/v4"
        )
        assert provider.api_key == "test-key"
        assert provider.model == "glm-4"
        assert provider.base_url == "https://api.z.ai/api/paas/v4"
        assert provider.timeout == 30  # default timeout

    def test_is_available_with_key(self):
        """Test that provider is available when API key is set."""
        provider = ZAIProvider("test-key", "glm-4", "https://api.z.ai/api/paas/v4")
        assert provider.is_available() is True

    def test_is_available_without_key(self):
        """Test that provider is not available when API key is missing."""
        provider = ZAIProvider("", "glm-4", "https://api.z.ai/api/paas/v4")
        assert provider.is_available() is False

    def test_is_available_with_none_key(self):
        """Test that provider is not available when API key is None."""
        provider = ZAIProvider(None, "glm-4", "https://api.z.ai/api/paas/v4")
        assert provider.is_available() is False

    @patch('urllib.request.urlopen')
    def test_generate_text_response(self, mock_urlopen):
        """Test basic text generation without JSON mode."""
        # Mock the API response
        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "choices": [{
                "message": {
                    "content": "This is a test response."
                }
            }]
        }).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        provider = ZAIProvider("test-key", "glm-4", "https://api.z.ai/api/paas/v4")
        messages = [AIMessage(role="user", content="Test prompt")]
        
        result = provider.generate(messages, temperature=0.5, max_tokens=100)
        
        assert result == "This is a test response."
        mock_urlopen.assert_called_once()

    @patch('urllib.request.urlopen')
    def test_generate_json_response(self, mock_urlopen):
        """Test JSON mode generation."""
        # Mock the API response
        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "choices": [{
                "message": {
                    "content": '{"score": 5, "reason": "Good response"}'
                }
            }]
        }).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        provider = ZAIProvider("test-key", "glm-4", "https://api.z.ai/api/paas/v4")
        messages = [AIMessage(role="user", content="Test prompt")]
        
        result = provider.generate(messages, json_mode=True, temperature=0.2, max_tokens=200)
        
        assert result == '{"score": 5, "reason": "Good response"}'
        
        # Verify that the request included JSON mode
        call_args = mock_urlopen.call_args
        request_data = json.loads(call_args[0][0].data)
        assert request_data["response_format"] == {"type": "json_object"}

    @patch('urllib.request.urlopen')
    def test_generate_with_system_message(self, mock_urlopen):
        """Test that system messages are properly included in the request."""
        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "choices": [{
                "message": {
                    "content": "Response with system context"
                }
            }]
        }).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        provider = ZAIProvider("test-key", "glm-4", "https://api.z.ai/api/paas/v4")
        messages = [
            AIMessage(role="system", content="You are a helpful assistant"),
            AIMessage(role="user", content="Test prompt")
        ]
        
        result = provider.generate(messages)
        
        assert result == "Response with system context"
        
        # Verify both messages were sent
        call_args = mock_urlopen.call_args
        request_data = json.loads(call_args[0][0].data)
        assert len(request_data["messages"]) == 2
        assert request_data["messages"][0]["role"] == "system"
        assert request_data["messages"][1]["role"] == "user"

    @patch('urllib.request.urlopen')
    def test_generate_http_error(self, mock_urlopen):
        """Test handling of HTTP errors from the API."""
        from urllib.error import HTTPError
        
        # Mock an HTTP error
        mock_urlopen.side_effect = HTTPError(
            "https://api.z.ai/api/paas/v4/chat/completions",
            401,
            "Unauthorized",
            {},
            None
        )

        provider = ZAIProvider("test-key", "glm-4", "https://api.z.ai/api/paas/v4")
        messages = [AIMessage(role="user", content="Test prompt")]
        
        with pytest.raises(RuntimeError) as exc_info:
            provider.generate(messages)
        
        assert "Z.AI API error 401" in str(exc_info.value)

    @patch('urllib.request.urlopen')
    def test_generate_connection_error(self, mock_urlopen):
        """Test handling of connection errors."""
        from urllib.error import URLError
        
        # Mock a connection error
        mock_urlopen.side_effect = URLError("Connection refused")

        provider = ZAIProvider("test-key", "glm-4", "https://api.z.ai/api/paas/v4")
        messages = [AIMessage(role="user", content="Test prompt")]
        
        with pytest.raises(RuntimeError) as exc_info:
            provider.generate(messages)
        
        assert "Z.AI connection error" in str(exc_info.value)

    @patch('urllib.request.urlopen')
    def test_generate_invalid_json_response(self, mock_urlopen):
        """Test handling of invalid JSON in API response."""
        mock_response = Mock()
        mock_response.read.return_value = b"invalid json{{{"
        mock_urlopen.return_value.__enter__.return_value = mock_response

        provider = ZAIProvider("test-key", "glm-4", "https://api.z.ai/api/paas/v4")
        messages = [AIMessage(role="user", content="Test prompt")]
        
        with pytest.raises(RuntimeError) as exc_info:
            provider.generate(messages)
        
        assert "Z.AI returned invalid JSON" in str(exc_info.value)

    @patch('urllib.request.urlopen')
    def test_generate_unexpected_response_format(self, mock_urlopen):
        """Test handling of unexpected response format."""
        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "unexpected_field": "value"
        }).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        provider = ZAIProvider("test-key", "glm-4", "https://api.z.ai/api/paas/v4")
        messages = [AIMessage(role="user", content="Test prompt")]
        
        with pytest.raises(RuntimeError) as exc_info:
            provider.generate(messages)
        
        assert "Z.AI returned unexpected response format" in str(exc_info.value)

    @patch('urllib.request.urlopen')
    def test_generate_text_method(self, mock_urlopen):
        """Test the convenience generate_text method."""
        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "choices": [{
                "message": {
                    "content": "Generated text"
                }
            }]
        }).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        provider = ZAIProvider("test-key", "glm-4", "https://api.z.ai/api/paas/v4")
        
        result = provider.generate_text(
            "Test prompt",
            max_tokens=150,
            temperature=0.7,
            system="System instruction"
        )
        
        assert result == "Generated text"

    @patch('urllib.request.urlopen')
    def test_generate_text_method_json_mode(self, mock_urlopen):
        """Test generate_text method with JSON mode."""
        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "choices": [{
                "message": {
                    "content": '{"result": "success"}'
                }
            }]
        }).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        provider = ZAIProvider("test-key", "glm-4", "https://api.z.ai/api/paas/v4")
        
        result = provider.generate_text(
            "Test prompt",
            json_mode=True,
            temperature=0.2
        )
        
        assert result == '{"result": "success"}'

    @patch('urllib.request.urlopen')
    def test_generate_text_method_error_fallback(self, mock_urlopen):
        """Test that generate_text falls back gracefully on error in non-JSON mode."""
        mock_urlopen.side_effect = Exception("API error")

        provider = ZAIProvider("test-key", "glm-4", "https://api.z.ai/api/paas/v4")
        
        # Should return fallback text in non-JSON mode
        result = provider.generate_text("Test prompt", json_mode=False)
        
        assert "Good response. Keep practicing" in result

    @patch('urllib.request.urlopen')
    def test_generate_text_method_error_json_mode_raises(self, mock_urlopen):
        """Test that generate_text raises exception in JSON mode on error."""
        mock_urlopen.side_effect = Exception("API error")

        provider = ZAIProvider("test-key", "glm-4", "https://api.z.ai/api/paas/v4")
        
        # Should raise exception in JSON mode
        with pytest.raises(Exception):
            provider.generate_text("Test prompt", json_mode=True)

    @patch('urllib.request.urlopen')
    def test_temperature_and_max_tokens_passed(self, mock_urlopen):
        """Test that temperature and max_tokens are properly passed to API."""
        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "choices": [{
                "message": {
                    "content": "Response"
                }
            }]
        }).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        provider = ZAIProvider("test-key", "glm-4", "https://api.z.ai/api/paas/v4")
        messages = [AIMessage(role="user", content="Test")]
        
        provider.generate(messages, temperature=0.8, max_tokens=500)
        
        call_args = mock_urlopen.call_args
        request_data = json.loads(call_args[0][0].data)
        assert request_data["temperature"] == 0.8
        assert request_data["max_tokens"] == 500

    @patch('urllib.request.urlopen')
    def test_base_url_construction(self, mock_urlopen):
        """Test that base URL is properly constructed."""
        mock_response = Mock()
        mock_response.read.return_value = json.dumps({
            "choices": [{
                "message": {
                    "content": "Response"
                }
            }]
        }).encode('utf-8')
        mock_urlopen.return_value.__enter__.return_value = mock_response

        provider = ZAIProvider("test-key", "glm-4", "https://api.z.ai/api/paas/v4/")
        messages = [AIMessage(role="user", content="Test")]
        
        provider.generate(messages)
        
        # Verify the URL is constructed correctly (trailing slash should be removed)
        call_args = mock_urlopen.call_args
        assert call_args[0][0].full_url == "https://api.z.ai/api/paas/v4/chat/completions"

    def test_provider_name(self):
        """Test that provider name is set correctly."""
        provider = ZAIProvider("test-key", "glm-4", "https://api.z.ai/api/paas/v4")
        assert provider.name == "zai"
