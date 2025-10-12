from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"


MYSELF_QUERY = "query MyselfBalance { myself { clientBalance currentSpendPerHr } }"


@dataclass(frozen=True)
class BalanceInfo:
    client_balance: float
    current_spend_per_hr: float


class RunpodClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "RunpodClient":
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=httpx.Timeout(15.0, connect=10.0),
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=httpx.Timeout(15.0, connect=10.0),
            )
        return self._client

    async def fetch_balance(self) -> BalanceInfo:
        client = await self._ensure_client()
        for attempt in range(3):
            try:
                response = await client.post(
                    url=RUNPOD_GRAPHQL_URL,
                    json={"query": MYSELF_QUERY},
                )
                response.raise_for_status()
                payload = response.json()
                if "errors" in payload:
                    raise RuntimeError(str(payload["errors"]))
                data = payload.get("data", {})
                myself = data.get("myself", {})
                balance = float(myself.get("clientBalance") or 0.0)
                spend = float(myself.get("currentSpendPerHr") or 0.0)
                return BalanceInfo(client_balance=balance, current_spend_per_hr=spend)
            except Exception as e:  # noqa: BLE001
                wait = 2**attempt
                logger.warning("RunPod fetch attempt %s failed: %s", attempt + 1, e)
                if attempt == 2:
                    raise
                await asyncio.sleep(wait)

        # Unreachable due to raise above
        return BalanceInfo(client_balance=0.0, current_spend_per_hr=0.0)
