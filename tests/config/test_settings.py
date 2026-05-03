from backend.config.settings import Settings


class TestClaudeCliSettings:
    """Test Claude CLI configuration settings."""

    def test_default_claude_config_dir(self):
        s = Settings(_env_file=None)
        assert s.claude_config_dir == "/root/.claude"

    def test_default_claude_cli_path(self):
        s = Settings(_env_file=None)
        assert s.claude_cli_path == "claude"

    def test_claude_config_dir_from_env(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/custom/.claude")
        s = Settings(_env_file=None)
        assert s.claude_config_dir == "/custom/.claude"

    def test_claude_cli_path_from_env(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CLI_PATH", "/usr/local/bin/claude")
        s = Settings(_env_file=None)
        assert s.claude_cli_path == "/usr/local/bin/claude"

    # NOTE: claude_stream_timeout was removed from Settings — it now
    # lives in system_settings (key ``claude_stream_timeout_seconds``)
    # so operators can change it without a redeploy. The DB-backed
    # equivalent is covered by tests/test_system_settings_service.py.
