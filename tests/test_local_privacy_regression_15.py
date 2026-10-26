import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from founder_signal.config import Config
from founder_signal.extraction import extract
from founder_signal.ledger import Source


def test_config_cloud_fallback_defaults_and_env():
    cfg_default = Config()
    assert cfg_default.allow_cloud_fallback is False

    with patch.dict(os.environ, {"FOUNDER_SIGNAL_ALLOW_CLOUD_FALLBACK": "true"}):
        cfg_true = Config.from_env()
        assert cfg_true.allow_cloud_fallback is True

    with patch.dict(os.environ, {"FOUNDER_SIGNAL_ALLOW_CLOUD_FALLBACK": "1"}):
        cfg_one = Config.from_env()
        assert cfg_one.allow_cloud_fallback is True

    with patch.dict(os.environ, {"FOUNDER_SIGNAL_ALLOW_CLOUD_FALLBACK": "false"}):
        cfg_false = Config.from_env()
        assert cfg_false.allow_cloud_fallback is False


def test_local_privacy_refuses_openai_fallback_by_default():
    """Verify that even when OPENAI_API_KEY is present in the environment,
    extract() never reaches out to OpenAI unless allow_cloud_fallback is explicitly True.
    """
    source = Source(
        id="test:privacy:1",
        kind="email",
        title="Investor Update",
        body="I will send the finalized pitch deck by Friday afternoon.",
    )

    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fake-key-for-test"}):
        # Default config: allow_cloud_fallback is False
        config = Config(
            use_llm=True,
            ollama_host="http://127.0.0.1:9999",  # unreachable Ollama to force fallback
            allow_cloud_fallback=False,
        )

        # Mock OpenAI module if imported
        with patch("founder_signal.extraction.OpenAI", create=True) as mock_openai:
            result = extract(source, use_llm=True, config=config)

            # Never called OpenAI
            mock_openai.assert_not_called()
            # Extractor fell back cleanly to offline rules
            assert result.extractor == "rules"
            assert len(result.commitments) >= 1
            assert "pitch deck" in result.commitments[0].description.lower()


def test_cloud_fallback_allowed_when_explicitly_opted_in():
    """Verify that when allow_cloud_fallback=True and OPENAI_API_KEY is set,
    cloud LLM fallback is permitted when Ollama is unavailable.
    """
    source = Source(
        id="test:privacy:2",
        kind="email",
        title="Investor Update",
        body="I will send the finalized pitch deck by Friday afternoon.",
    )

    fake_openai_client = MagicMock()
    mock_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = (
        '{"commitments": [{"description": "Send pitch deck", "due_date": "2026-10-30", '
        '"owner": "Founder", "evidence": "I will send the finalized pitch deck", "priority": "high"}], '
        '"decisions": [], "follow_ups": []}'
    )
    mock_completion.choices = [mock_choice]
    fake_openai_client.chat.completions.create.return_value = mock_completion

    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI.return_value = fake_openai_client

    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fake-key-for-test", "FOUNDER_SIGNAL_MODEL": "gpt-4o-mini"}):
        config = Config(
            use_llm=True,
            ollama_host="http://127.0.0.1:9999",  # unreachable Ollama
            allow_cloud_fallback=True,
        )

        with patch.dict("sys.modules", {"openai": mock_openai_module}):
            result = extract(source, use_llm=True, config=config)

            fake_openai_client.chat.completions.create.assert_called_once()
            assert result.extractor == "openai/gpt-4o-mini"
            assert len(result.commitments) == 1
            assert result.commitments[0].description == "Send pitch deck"
