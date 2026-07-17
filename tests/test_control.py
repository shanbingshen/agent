import pytest
from arthra.config import Settings
from arthra.control import ControlPolicy


@pytest.fixture
def policy():
    return ControlPolicy(Settings(control_max_power_limit_kw=500))


def test_control_allowlist(policy):
    policy.validate("ems", "setPowerLimit", {"value": 300})
    with pytest.raises(ValueError, match="白名单"):
        policy.validate("ems", "shell", {})


def test_control_limits(policy):
    with pytest.raises(ValueError, match="0 到 500"):
        policy.validate("ems", "setPowerLimit", {"value": 999})
    with pytest.raises(ValueError, match="模式"):
        policy.validate("compressor", "setMode", {"mode": "unsafe"})

