# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
"""Support code of the end-to-end suites (no tests in here).

Layout, one concern per module (fixtures built on them live in ``tests/e2e/conftest.py``):

* ``server``    - ``LiveServer``, ``ServerOptions``, ``running_server``: the real app in a thread.
* ``unavailable`` - the ASGI wrapper behind the ``export_unavailable`` server option.
* ``clients``   - httpx clients (same-origin, hostile origin, no origin) and multipart helpers.
* ``builders``  - CSV / graph payload builders and the sample data of E2E.md.
* ``waits``     - ``wait_until`` (bounded polling for non-browser conditions).
* ``uiwait``    - Playwright waits on the DOM signals of docs/ui/testing.md
                  (``data-ready``, ``data-loading``).
* ``browser``   - Chrome launch and browser-context creation.
* ``watch``     - ``PageWatch`` / ``WatchedPage``: console, page error, CSP and network collectors.
* ``session``   - ``PageFactory``: pages per test, failure artefacts, the clean-at-teardown check.
* ``pages``     - ``AppPage``: the base of the suites' page objects.
"""
