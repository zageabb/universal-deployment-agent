"""Production health probes for the reviewed UDA topology.

No credentials are sent through the reverse proxy. Browser SSO acceptance
remains an independent operator gate. No service changes are performed.
"""
import base64
import http.client
import json
import ssl
import time
from urllib.parse import urlsplit

from deploy_agent import load_config


PORTS = {"home": 5048, "dashboard": 5030}
MAX_BODY = 65536


def request(scheme, host, port, path, headers=None, timeout=3):
    # Direct connections deliberately ignore environment proxy settings and
    # never follow redirects. HTTPS verifies hostname and certificate.
    if scheme == "https":
        conn = http.client.HTTPSConnection(host, port, timeout=timeout,
                                            context=ssl.create_default_context())
    elif scheme == "http" and host == "127.0.0.1":
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
    else:
        raise ValueError("Unsupported health endpoint")
    try:
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        return response.status, response.read(MAX_BODY + 1)
    finally:
        conn.close()


def healthy(result, version=None):
    status, body = result
    if status != 200 or len(body) > MAX_BODY:
        return False
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        return False
    return isinstance(value, dict) and value.get("ok") is True and (
        version is None or value.get("version") == version)


class Health:
    def __init__(self, config_path, *, expected_version=None, attempts=8,
                 delay=2, timeout=3, transport=request, sleep=time.sleep):
        if not 1 <= attempts <= 20 or not 0 <= delay <= 10 or not 0 < timeout <= 10:
            raise ValueError("Invalid bounded health policy")
        self.config_path = config_path
        self.version = expected_version
        self.attempts, self.delay, self.timeout = attempts, delay, timeout
        self.transport, self.sleep = transport, sleep

    def once(self, target):
        if target not in PORTS:
            raise ValueError("Unknown UDA health target")
        cfg = load_config(self.config_path)
        port = PORTS[target]
        def local(path, headers=None):
            return self.transport("http", "127.0.0.1", port, path,
                                  headers=headers, timeout=self.timeout)
        if not healthy(local("/health"), self.version if target == "dashboard" else None):
            return False
        if target == "dashboard":
            if local("/")[0] != 401:
                return False
            token = cfg.get("dashboard_token")
            if not isinstance(token, str) or not token:
                return False
            auth = base64.b64encode(("admin:" + token).encode()).decode("ascii")
            # Authenticated loopback HTML can exceed the health JSON bound;
            # status is checked, not the page content.
            return local("/", {"Authorization": "Basic " + auth})[0] == 200
        url = urlsplit(cfg["public_base_url"])
        if (url.scheme != "https" or not url.hostname or url.username is not None
                or url.password is not None or url.path not in ("", "/")
                or url.query or url.fragment or url.port not in (None, 443)):
            raise ValueError("Unexpected public HTTPS origin")
        return healthy(self.transport("https", url.hostname, 443, "/health",
                                      timeout=self.timeout))

    def __call__(self, target):
        if target not in PORTS:
            raise ValueError("Unknown UDA health target")
        for attempt in range(self.attempts):
            try:
                if self.once(target):
                    return True
            except (OSError, http.client.HTTPException):
                # Never expose request headers, token or response bodies.
                pass
            if attempt + 1 < self.attempts:
                self.sleep(self.delay)
        return False
