import json
import subprocess
from pathlib import Path

import pytest

from election_map_slovakia import pages


class FakeWrangler:
    """Wrangler logged in to *accounts*, or not logged in (None)."""

    def __init__(self, accounts: list[dict] | None):
        self.accounts = accounts
        self.calls: list[tuple[list[str], dict | None]] = []

    def __call__(self, command, *, env=None, capture_output=False, **_):
        args = command[3:]
        self.calls.append((args, env))
        if not capture_output:
            return subprocess.CompletedProcess(command, 0)
        if self.accounts is None:
            out, code = '{"loggedIn": false}', 1
        elif args[:2] == ["auth", "token"]:
            # The banner some versions print before the JSON.
            out, code = '⛅️ wrangler\n{"type": "oauth", "token": "oauth-token"}', 0
        else:
            out, code = json.dumps({"loggedIn": True, "accounts": self.accounts}), 0
        return subprocess.CompletedProcess(command, code, out, "")


@pytest.fixture
def wrangler(monkeypatch: pytest.MonkeyPatch):
    def install(accounts: list[dict] | None) -> FakeWrangler:
        fake = FakeWrangler(accounts)
        monkeypatch.setattr(subprocess, "run", fake)
        return fake

    monkeypatch.delenv(pages.TOKEN_ENV, raising=False)
    monkeypatch.delenv(pages.ACCOUNT_ENV, raising=False)
    pages.credentials.cache_clear()
    yield install
    pages.credentials.cache_clear()


def test_the_environment_comes_first(wrangler, monkeypatch: pytest.MonkeyPatch):
    fake = wrangler([{"name": "a", "id": "1"}])
    monkeypatch.setenv(pages.TOKEN_ENV, "env-token")
    monkeypatch.setenv(pages.ACCOUNT_ENV, "env-account")
    assert pages.credentials() == ("env-token", "env-account")
    assert fake.calls == []


def test_the_login_of_wrangler(wrangler, tmp_path: Path):
    fake = wrangler([{"name": "Site", "id": "abc"}])
    assert pages.credentials() == ("oauth-token", "abc")
    # Wrangler deploys to that account, without asking which.
    assert pages.deploy(tmp_path, "ems-results", "key live") == 0
    args, env = fake.calls[-1]
    assert args[:2] == ["pages", "deploy"]
    assert env is not None and env[pages.ACCOUNT_ENV] == "abc"


def test_several_accounts_need_the_one_named(wrangler, monkeypatch: pytest.MonkeyPatch):
    wrangler([{"name": "Site", "id": "abc"}, {"name": "Other", "id": "def"}])
    with pytest.raises(pages.PagesError, match=r"2 accounts: Site \(abc\)"):
        pages.credentials()
    monkeypatch.setenv(pages.ACCOUNT_ENV, "def")
    pages.credentials.cache_clear()
    assert pages.credentials() == ("oauth-token", "def")


def test_no_credentials(wrangler):
    wrangler(None)
    with pytest.raises(pages.PagesError, match="npx wrangler login"):
        pages.credentials()
