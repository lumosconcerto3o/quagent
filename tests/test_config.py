"""
Tests for configuration management.
"""

import pytest
import os
import tempfile
import yaml
from pathlib import Path

from app.config import (
    load_config,
    get_config,
    reset_config_cache,
    QuAgentConfig,
    IBKRConfig,
)


def test_load_paper_config(tmp_path):
    """Test loading paper config."""
    config_content = {
        'trading_mode': 'paper',
        'allow_live': False,
        'ibkr': {
            'host': '127.0.0.1',
            'port': 7497,
        },
    }
    
    config_file = tmp_path / "paper.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(config_content, f)
    
    # Mock the get_relative_path to return our temp file
    import app.config
    original_get_relative_path = app.config.get_relative_path
    
    def mock_get_relative_path(path):
        if "paper.yaml" in path:
            return config_file
        return original_get_relative_path(path)
    
    app.config.get_relative_path = mock_get_relative_path
    
    try:
        config = load_config("paper.yaml")
        assert config.trading_mode == 'paper'
        assert config.allow_live == False
        assert config.ibkr.port == 7497
    finally:
        app.config.get_relative_path = original_get_relative_path


def test_config_validation():
    """Test config validation."""
    # Valid config should work
    config = QuAgentConfig(
        trading_mode='paper',
        allow_live=False,
    )
    assert config.trading_mode == 'paper'
    
    # Invalid trading mode should fail
    with pytest.raises(ValueError):
        QuAgentConfig(trading_mode='invalid')
    
    # Live mode without allow_live should fail
    with pytest.raises(ValueError):
        load_config("configs/live.yaml")  # Will fail if allow_live is false


def test_ibkr_config_validation():
    """Test IBKR config validation."""
    config = IBKRConfig(host="127.0.0.1", port=7497)
    assert config.port == 7497
    
    # Invalid port should fail
    with pytest.raises(ValueError):
        IBKRConfig(port=99999)


def test_config_cache():
    """Test config caching."""
    reset_config_cache()
    
    # First call loads config
    config1 = get_config("configs/paper.yaml")
    
    # Second call should return same instance from cache
    config2 = get_config("configs/paper.yaml")
    
    assert config1 is config2  # Same object


def test_allowed_asset_classes_config():
    """allowed_asset_classes must be configurable and default to STK only."""
    config = QuAgentConfig(
        trading_mode='paper',
        account={'allowed_asset_classes': ['STK']},
    )
    assert config.account.allowed_asset_classes == ['STK']

    # Default (no account section overrides) must also be STK-only
    default_config = QuAgentConfig(trading_mode='paper')
    assert default_config.account.allowed_asset_classes == ['STK']


def test_require_stop_loss_config():
    """require_stop_loss must be configurable; default is False."""
    default_config = QuAgentConfig(trading_mode='paper')
    assert default_config.account.require_stop_loss is False

    strict_config = QuAgentConfig(
        trading_mode='paper',
        account={'require_stop_loss': True},
    )
    assert strict_config.account.require_stop_loss is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
