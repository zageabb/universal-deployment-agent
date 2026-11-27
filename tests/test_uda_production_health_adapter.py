import base64
import pytest
from tools import uda_production_health_adapter as h


@pytest.fixture
def lab(tmp_path, monkeypatch):
    cfg = {"dashboard_token": "fixture-secret", "public_base_url": "https://example.test"}
    monkeypatch.setattr(h, "load_config", lambda _: cfg)
    calls = []
    def transport(scheme, host, port, path, headers=None, timeout=3):
        calls.append((scheme, host, port, path, headers))
        if path == "/health":
            return 200, b'{"ok":true,"version":"fixture"}'
        return (200 if headers else 401), b"html"
    probe = h.Health(tmp_path / "config.json", expected_version="fixture",
                     transport=transport, attempts=2, sleep=lambda _: None)
    return probe, cfg, calls


def test_home_direct_and_proxy(lab):
    probe, _, calls = lab
    assert probe("home")
    assert calls == [("http", "127.0.0.1", 5048, "/health", None),
                     ("https", "example.test", 443, "/health", None)]


def test_dashboard_authenticated_loopback(lab):
    probe, _, calls = lab
    assert probe("dashboard")
    assert calls[-1] == ("http", "127.0.0.1", 5030, "/",
                         {"Authorization": "Basic " + base64.b64encode(b"admin:fixture-secret").decode()})
    assert len(calls) == 3


@pytest.mark.parametrize("result", [(302, b'{"ok":true}'), (200, b'{"ok":1}'),
                                    (200, b"html"), (200, b"x" * 65537),
                                    (200, b'{"ok":true,"version":"wrong"}')])
def test_bad_health_refused(lab, result):
    probe, _, _ = lab
    calls = []
    def transport(*args, **kwargs):
        calls.append(args)
        return result
    probe.transport = transport
    assert not probe("dashboard")
    assert len(calls) == 2


def test_network_failure_bounded(lab):
    probe, _, _ = lab
    calls = []
    def transport(*args, **kwargs):
        calls.append(args)
        raise OSError("fixture")
    probe.transport = transport
    assert not probe("home")
    assert len(calls) == 2


def test_unexpected_origin_refused(lab):
    probe, cfg, calls = lab
    cfg["public_base_url"] = "http://example.test"
    with pytest.raises(ValueError, match="HTTPS origin"):
        probe("home")
    assert len(calls) == 1


def test_unknown_target_refused(lab):
    probe, _, calls = lab
    with pytest.raises(ValueError, match="Unknown"):
        probe("unrelated")
    assert not calls


def test_dashboard_requires_authentication(lab):
    probe, _, _ = lab
    probe.transport = lambda *a, **k: (200, b'{"ok":true,"version":"fixture"}')
    assert not probe("dashboard")
