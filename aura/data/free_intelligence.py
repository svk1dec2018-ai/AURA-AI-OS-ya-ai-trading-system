from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import Enum
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IntelligenceKind(str, Enum):
    NEWS = "news"
    REGULATORY = "regulatory"
    CENTRAL_BANK = "central_bank"
    FILING = "filing"
    MACRO = "macro"


class ExternalIntelligenceEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    kind: IntelligenceKind
    title: str = Field(min_length=1)
    published_at: datetime
    observed_at: datetime
    url: str | None = None
    summary: str = ""
    symbols: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    sentiment: float | None = Field(default=None, ge=-1.0, le=1.0)
    trust_score: float = Field(default=0.7, ge=0.0, le=1.0)

    @field_validator("published_at", "observed_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("intelligence timestamps must be timezone-aware")
        return value.astimezone(UTC)


class MacroObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str = Field(min_length=1)
    series_id: str = Field(min_length=1)
    observation_date: str = Field(min_length=1)
    value: str = Field(min_length=1)
    realtime_start: str | None = None
    realtime_end: str | None = None
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("macro observed_at must be timezone-aware")
        return value.astimezone(UTC)


class IntelligenceSourceError(RuntimeError):
    pass


def _json_get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 15.0):
    request = Request(
        url,
        headers={"User-Agent": "AURA-AI-OS/0.1 intelligence", **(headers or {})},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise IntelligenceSourceError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise IntelligenceSourceError(f"network error: {exc.reason}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise IntelligenceSourceError("source returned invalid JSON") from exc


def _bytes_get(url: str, *, timeout: float = 15.0) -> bytes:
    request = Request(url, headers={"User-Agent": "AURA-AI-OS/0.1 intelligence"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise IntelligenceSourceError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise IntelligenceSourceError(f"network error: {exc.reason}") from exc


class RssIntelligenceSource:
    """Trusted RSS/Atom ingestion with point-in-time provenance."""

    def __init__(
        self,
        *,
        source: str,
        url: str,
        kind: IntelligenceKind,
        trust_score: float = 0.9,
    ) -> None:
        if not url.startswith("https://"):
            raise ValueError("RSS source must use HTTPS")
        if not 0 <= trust_score <= 1:
            raise ValueError("trust_score must be between 0 and 1")
        self.source = source
        self.url = url
        self.kind = kind
        self.trust_score = trust_score

    def fetch(self, *, observed_at: datetime | None = None) -> tuple[ExternalIntelligenceEvent, ...]:
        observed = observed_at or datetime.now(UTC)
        _require_aware(observed, "observed_at")
        try:
            root = ElementTree.fromstring(_bytes_get(self.url))
        except ElementTree.ParseError as exc:
            raise IntelligenceSourceError(f"invalid RSS XML from {self.source}") from exc
        events: list[ExternalIntelligenceEvent] = []
        entries = list(root.findall(".//item"))
        if not entries:
            entries = list(root.findall(".//{*}entry"))
        for entry in entries:
            title = _xml_text(entry, "title")
            if not title:
                continue
            link = _rss_link(entry)
            summary = _xml_text(entry, "description") or _xml_text(entry, "summary") or ""
            raw_date = (
                _xml_text(entry, "pubDate")
                or _xml_text(entry, "published")
                or _xml_text(entry, "updated")
            )
            published = _parse_feed_datetime(raw_date, fallback=observed)
            if published > observed:
                continue
            events.append(
                _event(
                    source=self.source,
                    kind=self.kind,
                    title=title,
                    published_at=published,
                    observed_at=observed,
                    url=link,
                    summary=summary,
                    trust_score=self.trust_score,
                )
            )
        return _dedupe_events(events)


DEFAULT_OFFICIAL_INDIA_RSS = (
    RssIntelligenceSource(
        source="RBI_PRESS_RELEASES",
        url="https://rbi.org.in/pressreleases_rss.xml",
        kind=IntelligenceKind.CENTRAL_BANK,
        trust_score=1.0,
    ),
    RssIntelligenceSource(
        source="RBI_NOTIFICATIONS",
        url="https://rbi.org.in/notifications_rss.xml",
        kind=IntelligenceKind.REGULATORY,
        trust_score=1.0,
    ),
    RssIntelligenceSource(
        source="SEBI_RSS",
        url="https://www.sebi.gov.in/sebirss.xml",
        kind=IntelligenceKind.REGULATORY,
        trust_score=1.0,
    ),
)


class GdeltDocClient:
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"

    def search(
        self,
        query: str,
        *,
        max_records: int = 50,
        observed_at: datetime | None = None,
    ) -> tuple[ExternalIntelligenceEvent, ...]:
        if not query.strip():
            raise ValueError("GDELT query cannot be empty")
        if not 1 <= max_records <= 250:
            raise ValueError("GDELT max_records must be between 1 and 250")
        observed = observed_at or datetime.now(UTC)
        params = urlencode(
            {
                "query": query,
                "mode": "artlist",
                "maxrecords": str(max_records),
                "format": "json",
                "sort": "datedesc",
            }
        )
        payload = _json_get(f"{self.endpoint}?{params}")
        articles = payload.get("articles", []) if isinstance(payload, dict) else []
        events: list[ExternalIntelligenceEvent] = []
        for article in articles:
            if not isinstance(article, dict):
                continue
            title = str(article.get("title") or "").strip()
            if not title:
                continue
            published = _parse_gdelt_datetime(article.get("seendate"), fallback=observed)
            if published > observed:
                continue
            topics = tuple(
                value
                for value in (
                    str(article.get("domain") or "").strip(),
                    str(article.get("sourcecountry") or "").strip(),
                )
                if value
            )
            events.append(
                _event(
                    source="GDELT_DOC_2",
                    kind=IntelligenceKind.NEWS,
                    title=title,
                    published_at=published,
                    observed_at=observed,
                    url=str(article.get("url") or "") or None,
                    topics=topics,
                    trust_score=0.65,
                )
            )
        return _dedupe_events(events)


class AlphaVantageNewsClient:
    endpoint = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = (api_key or os.environ.get("AURA_ALPHA_VANTAGE_API_KEY", "")).strip()
        if not self.api_key:
            raise RuntimeError("set AURA_ALPHA_VANTAGE_API_KEY")

    def search(
        self,
        *,
        tickers: Iterable[str] = (),
        topics: Iterable[str] = (),
        limit: int = 50,
        observed_at: datetime | None = None,
    ) -> tuple[ExternalIntelligenceEvent, ...]:
        observed = observed_at or datetime.now(UTC)
        ticker_values = tuple(sorted({item.strip().upper() for item in tickers if item.strip()}))
        topic_values = tuple(sorted({item.strip().lower() for item in topics if item.strip()}))
        params = {
            "function": "NEWS_SENTIMENT",
            "apikey": self.api_key,
            "limit": str(limit),
            "sort": "LATEST",
        }
        if ticker_values:
            params["tickers"] = ",".join(ticker_values)
        if topic_values:
            params["topics"] = ",".join(topic_values)
        payload = _json_get(f"{self.endpoint}?{urlencode(params)}")
        feed = payload.get("feed", []) if isinstance(payload, dict) else []
        events: list[ExternalIntelligenceEvent] = []
        for item in feed:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            published = _parse_alpha_time(item.get("time_published"), fallback=observed)
            if published > observed:
                continue
            sentiment = _bounded_sentiment(item.get("overall_sentiment_score"))
            tagged = tuple(
                sorted(
                    {
                        str(value.get("ticker") or "").strip().upper()
                        for value in item.get("ticker_sentiment", [])
                        if isinstance(value, dict) and value.get("ticker")
                    }
                )
            )
            events.append(
                _event(
                    source="ALPHA_VANTAGE_NEWS_SENTIMENT",
                    kind=IntelligenceKind.NEWS,
                    title=title,
                    published_at=published,
                    observed_at=observed,
                    url=str(item.get("url") or "") or None,
                    summary=str(item.get("summary") or ""),
                    symbols=tagged,
                    sentiment=sentiment,
                    trust_score=0.7,
                )
            )
        return _dedupe_events(events)


class FredClient:
    endpoint = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = (api_key or os.environ.get("AURA_FRED_API_KEY", "")).strip()
        if not self.api_key:
            raise RuntimeError("set AURA_FRED_API_KEY")

    def observations(
        self,
        series_id: str,
        *,
        realtime_start: str | None = None,
        realtime_end: str | None = None,
        limit: int = 100,
        observed_at: datetime | None = None,
    ) -> tuple[MacroObservation, ...]:
        observed = observed_at or datetime.now(UTC)
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": str(limit),
        }
        if realtime_start:
            params["realtime_start"] = realtime_start
        if realtime_end:
            params["realtime_end"] = realtime_end
        payload = _json_get(f"{self.endpoint}?{urlencode(params)}")
        values = payload.get("observations", []) if isinstance(payload, dict) else []
        return tuple(
            MacroObservation(
                source="FRED",
                series_id=series_id,
                observation_date=str(item.get("date") or ""),
                value=str(item.get("value") or ""),
                realtime_start=str(item.get("realtime_start") or "") or None,
                realtime_end=str(item.get("realtime_end") or "") or None,
                observed_at=observed,
            )
            for item in values
            if isinstance(item, dict) and item.get("date") and item.get("value") not in {None, ""}
        )


class SecEdgarClient:
    endpoint = "https://data.sec.gov/submissions"

    def __init__(self, user_agent: str | None = None) -> None:
        self.user_agent = (user_agent or os.environ.get("AURA_SEC_USER_AGENT", "")).strip()
        if not self.user_agent:
            raise RuntimeError("set AURA_SEC_USER_AGENT to a descriptive app/contact value")

    def recent_filings(
        self,
        cik: str,
        *,
        observed_at: datetime | None = None,
    ) -> tuple[ExternalIntelligenceEvent, ...]:
        observed = observed_at or datetime.now(UTC)
        normalized_cik = str(cik).strip().zfill(10)
        payload = _json_get(
            f"{self.endpoint}/CIK{normalized_cik}.json",
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
        )
        recent = payload.get("filings", {}).get("recent", {}) if isinstance(payload, dict) else {}
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        documents = recent.get("primaryDocument", [])
        company = str(payload.get("name") or f"CIK {normalized_cik}") if isinstance(payload, dict) else f"CIK {normalized_cik}"
        events: list[ExternalIntelligenceEvent] = []
        count = min(len(forms), len(dates), len(accessions), len(documents))
        for index in range(count):
            published = _date_only_utc(str(dates[index]))
            if published > observed:
                continue
            accession_compact = str(accessions[index]).replace("-", "")
            url = (
                "https://www.sec.gov/Archives/edgar/data/"
                f"{int(normalized_cik)}/{accession_compact}/{documents[index]}"
            )
            events.append(
                _event(
                    source="SEC_EDGAR",
                    kind=IntelligenceKind.FILING,
                    title=f"{company} filed {forms[index]}",
                    published_at=published,
                    observed_at=observed,
                    url=url,
                    topics=(str(forms[index]),),
                    trust_score=1.0,
                )
            )
        return _dedupe_events(events)


class FreeIntelligenceHub:
    """Failure-isolated free/official intelligence fan-in. It never creates orders."""

    def __init__(self, rss_sources: Iterable[RssIntelligenceSource] = DEFAULT_OFFICIAL_INDIA_RSS) -> None:
        self.rss_sources = tuple(rss_sources)

    async def official_india_events(self) -> tuple[ExternalIntelligenceEvent, ...]:
        observed = datetime.now(UTC)
        results = await asyncio.gather(
            *(asyncio.to_thread(source.fetch, observed_at=observed) for source in self.rss_sources),
            return_exceptions=True,
        )
        merged: list[ExternalIntelligenceEvent] = []
        for result in results:
            if isinstance(result, Exception):
                continue
            merged.extend(result)
        return _dedupe_events(merged)

    async def gdelt(self, query: str, *, max_records: int = 50) -> tuple[ExternalIntelligenceEvent, ...]:
        return await asyncio.to_thread(GdeltDocClient().search, query, max_records=max_records)


def _event(
    *,
    source: str,
    kind: IntelligenceKind,
    title: str,
    published_at: datetime,
    observed_at: datetime,
    url: str | None = None,
    summary: str = "",
    symbols: tuple[str, ...] = (),
    topics: tuple[str, ...] = (),
    sentiment: float | None = None,
    trust_score: float,
) -> ExternalIntelligenceEvent:
    canonical = "|".join((source, title.strip(), published_at.isoformat(), url or ""))
    event_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return ExternalIntelligenceEvent(
        event_id=event_id,
        source=source,
        kind=kind,
        title=title.strip(),
        published_at=published_at,
        observed_at=observed_at,
        url=url,
        summary=summary.strip(),
        symbols=symbols,
        topics=topics,
        sentiment=sentiment,
        trust_score=trust_score,
    )


def _dedupe_events(events: Iterable[ExternalIntelligenceEvent]) -> tuple[ExternalIntelligenceEvent, ...]:
    unique = {event.event_id: event for event in events}
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (item.published_at, item.source, item.event_id),
            reverse=True,
        )
    )


def _xml_text(entry, local_name: str) -> str:
    node = entry.find(local_name)
    if node is None:
        node = entry.find(f"{{*}}{local_name}")
    return (node.text or "").strip() if node is not None else ""


def _rss_link(entry) -> str | None:
    direct = _xml_text(entry, "link")
    if direct:
        return direct
    node = entry.find("{*}link")
    if node is not None:
        return str(node.attrib.get("href") or "") or None
    return None


def _parse_feed_datetime(value: str, *, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        return fallback


def _parse_gdelt_datetime(value, *, fallback: datetime) -> datetime:
    text = str(value or "").strip()
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    return fallback


def _parse_alpha_time(value, *, fallback: datetime) -> datetime:
    text = str(value or "").strip()
    for pattern in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    return fallback


def _date_only_utc(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        raise IntelligenceSourceError(f"invalid filing date: {value!r}") from exc


def _bounded_sentiment(value) -> float | None:
    if value in {None, ""}:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(-1.0, min(1.0, number))


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
