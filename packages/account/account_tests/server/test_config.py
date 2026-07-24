"""Config loading tests: keeps sample_configs/account.yml.sample in sync with AppConfig."""

from pathlib import Path

from memmachine_account.server.config import load_config

SAMPLE_CONFIG_PATH = Path(__file__).parents[4] / "sample_configs" / "account.yml.sample"


def test_sample_config_parses_against_current_schema():
    assert SAMPLE_CONFIG_PATH.is_file(), f"expected sample config at {SAMPLE_CONFIG_PATH}"
    config = load_config(str(SAMPLE_CONFIG_PATH))

    assert config.server.port == 8090
    assert config.memmachine_upstream.base_url == "http://memmachine:8080"
    assert config.storage.sqlite_path == "/data/memmachine-account.db"
    assert config.auth.failed_login_lockout_threshold == 5
    assert config.smtp.encryption == "starttls"
