"""Safety checks must hold without a broker connection."""
import pytest

from guardrail_trader.broker import BrokerSafetyError, IBKRBroker, check_account, check_endpoint
from guardrail_trader.config import IBKRConfig


@pytest.mark.parametrize("port", [4001, 7496, 4003])
def test_paper_mode_refuses_live_ports(port):
    with pytest.raises(BrokerSafetyError):
        check_endpoint("paper", port)


@pytest.mark.parametrize("port", [4002, 7497, 4004])
def test_live_mode_refuses_paper_ports(port):
    with pytest.raises(BrokerSafetyError):
        check_endpoint("live", port)


def test_matching_ports_pass():
    check_endpoint("paper", 4002)
    check_endpoint("live", 4001)


def test_paper_mode_refuses_live_account():
    with pytest.raises(BrokerSafetyError):
        check_account("paper", "U1234567")


def test_live_mode_refuses_paper_account():
    with pytest.raises(BrokerSafetyError):
        check_account("live", "DU1234567")


def test_matching_accounts_pass():
    check_account("paper", "DU1234567")
    check_account("live", "U1234567")


def test_connect_refuses_live_port_before_any_network_call():
    cfg = IBKRConfig(mode="paper", host="127.0.0.1", port=4001, client_id=99, market_data_type=3)
    with pytest.raises(BrokerSafetyError):
        IBKRBroker(cfg).connect()


def test_readonly_broker_cannot_place_orders():
    cfg = IBKRConfig(mode="paper", host="127.0.0.1", port=4002, client_id=99, market_data_type=3)
    b = IBKRBroker(cfg, readonly=True)
    b.account_id = "DU1234567"
    with pytest.raises(BrokerSafetyError):
        b.place_order(contract=None, action="BUY", quantity=1, limit_price=1.0)


@pytest.mark.parametrize("action,qty,lmt", [("HOLD", 1, None), ("BUY", 0, None), ("BUY", -1, None), ("BUY", 1, -5.0)])
def test_invalid_orders_rejected(action, qty, lmt):
    cfg = IBKRConfig(mode="paper", host="127.0.0.1", port=4002, client_id=99, market_data_type=3)
    with pytest.raises(ValueError):
        IBKRBroker(cfg)._build_order(action, qty, lmt)


def test_context_manager_does_not_reconnect_when_already_connected(monkeypatch):
    """Regression: `with broker.connect():` opened a 2nd socket with the same clientId."""
    cfg = IBKRConfig(mode="paper", host="127.0.0.1", port=4002, client_id=99, market_data_type=3)
    b = IBKRBroker(cfg)
    monkeypatch.setattr(b.ib, "isConnected", lambda: True)
    monkeypatch.setattr(b.ib, "disconnect", lambda: None)
    monkeypatch.setattr(b, "connect", lambda: pytest.fail("connect() called twice"))
    with b as same:
        assert same is b
