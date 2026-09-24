"""``apollo doctor`` — preflight checks.

Each check has a documented fallback so a failure degrades gracefully rather than
blocking the whole system. The only *fatal* checks are the SQLite database and the
configured chat provider.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

import httpx

from apollo.config import Settings

TIMEOUT = httpx.Timeout(10.0)


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    fatal: bool = False
    fallback: str | None = None


def _check_database(settings: Settings) -> CheckResult:
    path = settings.db_file
    if not path.exists():
        return CheckResult(
            "database",
            ok=False,
            detail=f"{path} does not exist — run `apollo init-db`",
            fatal=True,
        )
    try:
        conn = sqlite3.connect(path)
        try:
            mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            conn.execute("PRAGMA busy_timeout=5000")
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()
    except sqlite3.Error as exc:  # pragma: no cover - io error path
        return CheckResult("database", ok=False, detail=str(exc), fatal=True)

    if "jobs" not in tables:
        return CheckResult(
            "database",
            ok=False,
            detail="connected but schema missing — run `apollo init-db`",
            fatal=True,
        )
    return CheckResult("database", ok=True, detail=f"{path} (journal_mode={mode})")


def _check_vault(settings: Settings) -> CheckResult:
    path = settings.vault_path
    if not path.exists():
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover
            return CheckResult("vault", ok=False, detail=str(exc), fatal=True)
    writable = path.is_dir()
    return CheckResult(
        "vault",
        ok=writable,
        detail=f"{path} ({'writable' if writable else 'not a directory'})",
        fatal=not writable,
    )


def _provider_headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _check_provider(settings: Settings, client: httpx.Client) -> CheckResult:
    base = settings.provider.base_url
    if not base:
        return CheckResult(
            "provider",
            ok=False,
            detail="APOLLO_PROVIDER__BASE_URL is unset",
            fatal=True,
        )
    url = base.rstrip("/") + "/models"
    try:
        resp = client.get(url, headers=_provider_headers(settings.provider.api_key))
    except httpx.HTTPError as exc:
        return CheckResult("provider", ok=False, detail=f"{url} unreachable: {exc}", fatal=True)
    if resp.status_code == 200:
        try:
            ids = [m.get("id") for m in resp.json().get("data", [])]
        except ValueError:
            ids = []
        return CheckResult("provider", ok=True, detail=f"{base} ({len(ids)} models listed)")
    if resp.status_code in (401, 403):
        return CheckResult("provider", ok=False, detail=f"auth rejected ({resp.status_code})", fatal=True)
    return CheckResult(
        "provider",
        ok=True,
        detail=f"{base} reachable; /models returned {resp.status_code} (chat may still work)",
    )


def _check_embeddings(settings: Settings, client: httpx.Client) -> CheckResult:
    base = settings.embeddings.base_url or settings.provider.base_url
    key = settings.embeddings.api_key or settings.provider.api_key
    if not base:
        return CheckResult(
            "embeddings",
            ok=False,
            detail="no provider configured",
            fallback=f"fallback={settings.embeddings.fallback}",
        )
    url = base.rstrip("/") + "/embeddings"
    model_id = settings.embedding_model_id()
    payload: dict[str, Any] = {"model": model_id, "input": ["ping"]}
    try:
        resp = client.post(url, headers=_provider_headers(key), json=payload)
    except httpx.HTTPError as exc:
        return CheckResult(
            "embeddings",
            ok=False,
            detail=f"{url} unreachable: {exc}",
            fallback=_embedding_fallback(settings),
        )
    if resp.status_code == 200:
        dims = None
        try:
            data = resp.json().get("data") or []
            if data:
                dims = len(data[0].get("embedding") or [])
        except ValueError:
            pass
        detail = f"{model_id} via {base}" + (f" ({dims} dims)" if dims else "")
        return CheckResult("embeddings", ok=True, detail=detail)
    return CheckResult(
        "embeddings",
        ok=False,
        detail=f"/embeddings returned {resp.status_code} for {model_id!r}",
        fallback=_embedding_fallback(settings),
    )


def _embedding_fallback(settings: Settings) -> str:
    if settings.embeddings.fallback == "provider":
        return "configure a second provider under [embeddings] or install `fastembed`"
    if settings.embeddings.fallback == "local":
        return (
            f"install the local-embeddings extra (fastembed, {settings.embeddings.local_model})"
        )
    return "embeddings disabled"


def _check_chroma(settings: Settings, client: httpx.Client) -> CheckResult:
    base = settings.memory.chroma_url.rstrip("/")
    if not settings.memory.enabled:
        return CheckResult("chroma", ok=True, detail="memory disabled")
    hosts = [base]
    # `chroma run` binds to localhost, which may resolve to IPv6 only.
    if "127.0.0.1" in base:
        hosts.append(base.replace("127.0.0.1", "localhost"))
    elif "localhost" in base:
        hosts.append(base.replace("localhost", "127.0.0.1"))
    for host in hosts:
        for suffix in ("/api/v2/heartbeat", "/api/v1/heartbeat", "/api/v2/version"):
            try:
                resp = client.get(host + suffix)
            except httpx.HTTPError:
                continue
            if resp.status_code == 200:
                return CheckResult("chroma", ok=True, detail=f"{host}{suffix} ok")
    return CheckResult(
        "chroma",
        ok=False,
        detail=f"{base} unreachable",
        fallback="start with `uv run chroma run --path ./data/chroma --port 8000` (or `scripts/run.sh start`)",
    )


def _check_telegram(settings: Settings, client: httpx.Client) -> CheckResult:
    token = settings.telegram.bot_token
    if not token:
        return CheckResult("telegram", ok=False, detail="APOLLO_TELEGRAM__BOT_TOKEN is unset")
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        resp = client.get(url)
    except httpx.HTTPError as exc:
        return CheckResult("telegram", ok=False, detail=f"unreachable: {exc}")
    if resp.status_code != 200:
        return CheckResult("telegram", ok=False, detail=f"getMe returned {resp.status_code}")
    me = resp.json().get("result", {})
    topics = me.get("has_topics_enabled")
    detail = f"@{me.get('username')} (id={me.get('id')})"
    ok = bool(topics) or not settings.telegram.topic_routing
    if topics is False and settings.telegram.topic_routing:
        detail += " — Topics in private chats DISABLED in BotFather"
        return CheckResult(
            "telegram",
            ok=False,
            detail=detail,
            fallback="BotFather → /mybots → Bot Settings → Topics in Private Chats → Enable",
        )
    detail += f"; topics={'on' if topics else 'off'}"
    return CheckResult("telegram", ok=ok, detail=detail)


def run_checks(settings: Settings) -> list[CheckResult]:
    results: list[CheckResult] = []
    results.append(_check_database(settings))
    results.append(_check_vault(settings))
    with httpx.Client(timeout=TIMEOUT) as client:
        results.append(_check_provider(settings, client))
        results.append(_check_embeddings(settings, client))
        results.append(_check_chroma(settings, client))
        results.append(_check_telegram(settings, client))
    return results


def all_ok(results: list[CheckResult]) -> bool:
    return all(r.ok for r in results if r.fatal)
