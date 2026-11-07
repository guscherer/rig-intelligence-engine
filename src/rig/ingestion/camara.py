"""Cliente HTTP assincrono para a API de Dados Abertos da Camara.

Interface publica: ``CamaraClient`` e ``Proposition``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field


class Proposition(BaseModel):
    """Proposicao retornada por ``GET /proposicoes/{id}``."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: int
    sigla_tipo: str | None = Field(default=None, alias="siglaTipo")
    numero: int | None = None
    ano: int | None = None
    ementa: str | None = None
    keywords: str | None = None
    url_inteiro_teor: str | None = Field(default=None, alias="urlInteiroTeor")
    status_proposicao: Any | None = Field(default=None, alias="statusProposicao")
    data_apresentacao: str | None = Field(default=None, alias="dataApresentacao")

    # Acesso por alias camelCase, usado por consumidores que preferem o contrato da API.
    @property
    def siglaTipo(self) -> str | None:  # noqa: N802 - alias intencional do contrato externo
        return self.sigla_tipo

    @property
    def urlInteiroTeor(self) -> str | None:  # noqa: N802 - alias intencional do contrato externo
        return self.url_inteiro_teor

    @property
    def statusProposicao(self) -> Any | None:  # noqa: N802 - alias intencional do contrato externo
        return self.status_proposicao

    @property
    def dataApresentacao(self) -> str | None:  # noqa: N802 - alias intencional do contrato externo
        return self.data_apresentacao

    def __getitem__(self, key: str) -> Any:
        data = self.model_dump(by_alias=True)
        if key in data:
            return data[key]
        return getattr(self, key)


class CamaraClient:
    """Cliente HTTP assincrono para dadosabertos.camara.leg.br."""

    def __init__(
        self,
        *args: Any,
        base_url: str | None = None,
        user_agent: str | None = None,
        rps: float | None = None,
        cache_dir: str | Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> None:
        if args:
            first = args[0]
            if isinstance(first, httpx.AsyncClient):
                client = client if client is not None else first
            elif isinstance(first, str):
                base_url = base_url if base_url is not None else first
            else:
                transport = transport if transport is not None else first
        if "http_client" in kwargs:
            client = kwargs.pop("http_client")

        self.base_url = (
            base_url
            or os.environ.get("CAMARA_API_BASE", "https://dadosabertos.camara.leg.br/api/v2")
        ).rstrip("/")
        self.user_agent = user_agent or os.environ.get(
            "CAMARA_USER_AGENT", "rig-intelligence-engine/0.1"
        )
        if rps is None:
            try:
                rps = float(os.environ.get("CAMARA_RPS", "1"))
            except ValueError:
                rps = 1.0
        self.rps = max(float(rps), 0.01)
        self.max_retries = max(0, int(max_retries))

        if cache_dir is None:
            data_dir = os.environ.get("DATA_DIR", "./data")
            cache_dir = Path(data_dir) / "cache" / "camara"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._owns_client = client is None
        self._transport = transport
        self._client: httpx.AsyncClient | None = client
        if self._owns_client:
            self._client = httpx.AsyncClient(
                transport=transport,
                headers={"User-Agent": self.user_agent},
                timeout=30.0,
            )

        self._semaphore = asyncio.Semaphore(1)
        self._throttle_lock = asyncio.Lock()
        self._last_request = 0.0

    async def __aenter__(self) -> CamaraClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def listar_proposicoes(
        self, sigla_tipo: str, ano: int, desde_id: int | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        pagina = 1
        while True:
            params = {
                "siglaTipo": sigla_tipo,
                "ano": ano,
                "itens": 100,
                "pagina": pagina,
                "ordem": "DESC",
                "ordenarPor": "id",
            }
            response = await self._request("GET", f"{self.base_url}/proposicoes", params=params)
            payload = response.json()
            items = payload.get("dados", []) if isinstance(payload, dict) else []
            if not items:
                break

            parar = False
            for item in items:
                item_id = item.get("id") if isinstance(item, dict) else None
                if desde_id is not None and isinstance(item_id, int) and item_id <= desde_id:
                    parar = True
                    break
                yield item

            if parar:
                break
            pagina += 1

    async def detalhar(self, proposicao_id: int) -> Proposition:
        response = await self._request("GET", f"{self.base_url}/proposicoes/{proposicao_id}")
        payload = response.json()
        dados = payload.get("dados", payload) if isinstance(payload, dict) else payload
        return Proposition.model_validate(dados)

    async def inteiro_teor(self, url: str) -> bytes:
        response = await self._request("GET", url)
        return response.content

    # ------------------------------------------------------------------ #
    # Internos
    # ------------------------------------------------------------------ #

    def _cache_key(self, method: str, url: str, params: Any) -> str:
        normalized = json.dumps(
            {"m": method.upper(), "u": url, "p": params or {}},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _cache_paths(self, key: str) -> tuple[Path, Path]:
        return self.cache_dir / f"{key}.body", self.cache_dir / f"{key}.meta.json"

    def _read_cache(self, key: str) -> tuple[dict[str, Any], bytes] | None:
        body_path, meta_path = self._cache_paths(key)
        if not (body_path.exists() and meta_path.exists()):
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            body = body_path.read_bytes()
        except (OSError, ValueError):
            return None
        headers = dict(meta.get("headers", {}))
        headers.pop("content-encoding", None)
        headers.pop("content-length", None)
        meta["headers"] = headers
        return meta, body

    def _write_cache(self, key: str, response: httpx.Response) -> None:
        body_path, meta_path = self._cache_paths(key)
        try:
            body_path.write_bytes(response.content)
            meta = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
            }
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
        except OSError:
            pass

    async def _throttle(self) -> None:
        async with self._throttle_lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            min_interval = 1.0 / self.rps
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
            self._last_request = time.monotonic()

    async def _sleep_backoff(self, attempt: int, retry_after: str | None) -> None:
        if retry_after is not None:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = 0.0
        else:
            delay = 0.1 * (2**attempt)
        jitter = random.SystemRandom().uniform(0.0, delay if delay > 0 else 0.1)
        await asyncio.sleep(delay + jitter)

    async def _request(
        self, method: str, url: str, *, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        key = self._cache_key(method, url, params)
        cached = self._read_cache(key)
        if cached is not None:
            meta, body = cached
            request = httpx.Request(method, url, params=params)
            return httpx.Response(
                status_code=int(meta.get("status_code", 200)),
                content=body,
                headers=meta.get("headers", {}),
                request=request,
            )

        client = self._client
        if client is None:
            raise RuntimeError("CamaraClient esta fechado")

        last_exc: Exception | None = None
        async with self._semaphore:
            await self._throttle()
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.request(
                        method,
                        url,
                        params=params,
                        headers={"User-Agent": self.user_agent},
                    )
                except httpx.HTTPError as exc:
                    last_exc = exc
                    if attempt >= self.max_retries:
                        raise
                    await self._sleep_backoff(attempt, None)
                    continue

                if response.status_code == 404:
                    response.raise_for_status()

                if response.status_code == 429 or response.status_code >= 500:
                    if attempt >= self.max_retries:
                        response.raise_for_status()
                    await self._sleep_backoff(attempt, response.headers.get("Retry-After"))
                    continue

                response.raise_for_status()
                self._write_cache(key, response)
                return response

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("falha inesperada na requisicao")
