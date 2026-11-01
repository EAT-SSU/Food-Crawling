import pytest


@pytest.fixture(autouse=True)
def runtime_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GPT_API_KEY", "test-gpt-key")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/webhook")
    monkeypatch.setenv("API_BASE_URL", "https://api.example")
    monkeypatch.setenv("DEV_API_BASE_URL", "https://dev-api.example")
    monkeypatch.delenv("DORMITORY_RELAY_URL", raising=False)
    monkeypatch.delenv("DORMITORY_RELAY_TOKEN", raising=False)
