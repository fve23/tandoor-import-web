"""One-time install hook run by Tandoor's ``plugin.py`` at container boot (when
``PLUGINS_BUILD=1``). Installs the optional ``curl_cffi`` dependency that the
strongest fetch tier (:func:`import_web.fetch._curl_cffi_get`) uses to get past
TLS-fingerprinting WAFs (e.g. Akamai on foodnetwork.com).

The import is attempted first so the hook is idempotent — a rebuild on an
already-provisioned container does nothing.
"""
import importlib
import subprocess
import sys


def main():
    for module, package in (('curl_cffi', 'curl_cffi>=0.7'), ('yt_dlp', 'yt-dlp')):
        try:
            importlib.import_module(module)
            continue
        except ImportError:
            pass
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
        except subprocess.CalledProcessError:
            pass  # optional dependency; the affected feature will raise a clear error at runtime


if __name__ == '__main__':
    main()
