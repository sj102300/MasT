import os

# Local fake servers must not go through a corporate/agent proxy.
for _key in ("NO_PROXY", "no_proxy"):
    _cur = os.environ.get(_key, "")
    if "127.0.0.1" not in _cur:
        os.environ[_key] = ",".join(filter(None, [_cur, "127.0.0.1", "localhost"]))
