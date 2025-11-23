from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.llm.client import (
    chat_completion,
    clear_client_cache,
    create_llm_client,
    get_llm_client,
)
from app.agents.llm.settings import LLMSettings

# Mark all tests in this module as asynchronous
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def clear_cache_after_test():
    """Fixture to automatically clear client cache after each test."""
    yield
    clear_client_cache()


@pytest.fixture
def mock_settings():
    """Provides mock LLMSettings, bypassing environment loading."""
    settings = LLMSettings(
        DEEPSEEK_BASE_URL="https://api.deepseek.com",
        DEEPSEEK_API_KEY="test_key_that_is_long_enough",
        DEEPSEEK_MODEL="test_model",
        DEEPSEEK_TEMPERATURE=0.5,
        DEEPSEEK_MAX_TOKENS=1024,
        DEEPSEEK_TIMEOUT=120,
        AGENT_MAX_RETRIES=2,
    )
    with patch("app.agents.llm.client.get_llm_settings", return_value=settings):
        yield settings


def test_create_llm_client_success(mock_settings):
    """Test successful creation of the LLM client."""
    with patch("app.agents.llm.client.ChatOpenAI") as mock_chat_openai:
        client = create_llm_client(settings=mock_settings)
        mock_chat_openai.assert_called_once_with(
            model=mock_settings.deepseek_model,
            base_url=mock_settings.deepseek_base_url,
            api_key=mock_settings.deepseek_api_key,
            temperature=mock_settings.deepseek_temperature,
            max_tokens=mock_settings.deepseek_max_tokens,
            timeout=mock_settings.deepseek_timeout,
            max_retries=mock_settings.agent_max_retries,
            streaming=False,
        )
        assert client is not None


def test_create_llm_client_no_api_key(mock_settings):
    """Test ValueError when API key is missing."""
    mock_settings.deepseek_api_key = ""  # Invalid key
    with pytest.raises(ValueError, match="Invalid or missing DEEPSEEK_API_KEY"):
        create_llm_client(settings=mock_settings)


def test_create_llm_client_creation_fails(mock_settings):
    """Test that exceptions during client creation are propagated."""
    with patch(
        "app.agents.llm.client.ChatOpenAI", side_effect=Exception("Creation Failed")
    ):
        with pytest.raises(Exception, match="Creation Failed"):
            create_llm_client(settings=mock_settings)


def test_get_llm_client_is_cached(mock_settings):
    """Test that get_llm_client caches the client instance."""
    with patch("app.agents.llm.client.ChatOpenAI") as mock_chat_openai:
        client1 = get_llm_client()
        client2 = get_llm_client()
        mock_chat_openai.assert_called_once()
        assert client1 is client2


def test_clear_client_cache(mock_settings):
    """Test that the client cache can be cleared."""
    with patch("app.agents.llm.client.ChatOpenAI") as mock_chat_openai:
        get_llm_client()
        get_llm_client()
        mock_chat_openai.assert_called_once()

        clear_client_cache()

        get_llm_client()
        assert mock_chat_openai.call_count == 2


async def test_chat_completion_success():
    """Test a successful chat completion call."""
    mock_client = MagicMock()
    mock_client.ainvoke = AsyncMock(return_value=AIMessage(content="4"))

    with patch("app.agents.llm.client.get_llm_client", return_value=mock_client):
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "Let me think..."},
        ]
        response = await chat_completion(messages)

        assert response == "4"
        mock_client.ainvoke.assert_awaited_once()

        called_messages = mock_client.ainvoke.call_args[0][0]
        assert isinstance(called_messages[0], SystemMessage)
        assert called_messages[0].content == "You are a helpful assistant."
        assert isinstance(called_messages[1], HumanMessage)
        assert called_messages[1].content == "What is 2+2?"
        assert isinstance(called_messages[2], AIMessage)
        assert called_messages[2].content == "Let me think..."


async def test_chat_completion_with_overrides():
    """Test chat completion with temperature and max_tokens overrides."""
    mock_client = MagicMock()
    # Let bind() return the mock client itself to allow chaining.
    mock_client.bind.return_value = mock_client
    # The client needs an awaitable ainvoke method.
    mock_client.ainvoke = AsyncMock(return_value=AIMessage(content="overridden"))

    with patch("app.agents.llm.client.get_llm_client", return_value=mock_client):
        response = await chat_completion(
            messages=[{"role": "user", "content": "test"}],
            temperature=0.9,
            max_tokens=500,
        )

        assert response == "overridden"
        assert mock_client.bind.call_count == 2
        mock_client.bind.assert_any_call(temperature=0.9)
        mock_client.bind.assert_any_call(max_tokens=500)
        mock_client.ainvoke.assert_awaited_once()


async def test_chat_completion_failure():
    """Test that exceptions during chat completion are propagated."""
    mock_client = MagicMock()
    mock_client.ainvoke = AsyncMock(side_effect=Exception("LLM call failed"))

    with patch("app.agents.llm.client.get_llm_client", return_value=mock_client):
        with pytest.raises(Exception, match="LLM call failed"):
            await chat_completion([{"role": "user", "content": "test"}])
