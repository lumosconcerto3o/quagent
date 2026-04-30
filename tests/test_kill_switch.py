"""
Tests for kill switch.
"""

import pytest
from app.kill_switch import KillSwitch


@pytest.fixture
def kill_switch():
    """Create a kill switch."""
    return KillSwitch()


def test_kill_switch_disabled_by_default(kill_switch):
    """Test that kill switch is disabled by default."""
    assert kill_switch.is_triggered() == False
    assert kill_switch.status.enabled == False


def test_trigger_kill_switch(kill_switch):
    """Test triggering the kill switch."""
    kill_switch.trigger("Test reason", "test_user")
    
    assert kill_switch.is_triggered() == True
    assert kill_switch.status.reason == "Test reason"
    assert kill_switch.status.triggered_by == "test_user"
    assert kill_switch.status.triggered_at is not None


def test_reset_kill_switch(kill_switch):
    """Test resetting the kill switch."""
    kill_switch.trigger("Test reason")
    assert kill_switch.is_triggered() == True
    
    kill_switch.reset("test_user")
    assert kill_switch.is_triggered() == False


def test_require_enabled(kill_switch):
    """Test require_enabled check."""
    # Should pass when not triggered
    assert kill_switch.require_enabled("test_operation") == True
    
    # Should fail when triggered
    kill_switch.trigger("System error")
    assert kill_switch.require_enabled("test_operation") == False


def test_get_status(kill_switch):
    """Test getting kill switch status."""
    status = kill_switch.get_status()
    assert status.enabled == False
    
    kill_switch.trigger("Test", "user1")
    status = kill_switch.get_status()
    assert status.enabled == True
    assert status.reason == "Test"
    assert status.triggered_by == "user1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
