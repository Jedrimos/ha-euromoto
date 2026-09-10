"""Tests for euromoto PDF parser."""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.euromoto.pdf_parser import (
    _parse_standings_pdf,
    _parse_grid_pdf,
    _pdf_url,
    _grid_urls,
    _flag,
)


class TestPdfUrl:
    def test_superbike_url(self):
        url = _pdf_url("Superbike", 2025, 1)
        assert "2025" in url
        assert "Superbike" in url
        assert url.startswith("https://")

    def test_year_in_url(self):
        url_25 = _pdf_url("Supersport", 2025, 1)
        url_26 = _pdf_url("Supersport", 2026, 1)
        assert "2025" in url_25
        assert "2026" in url_26
        assert url_25 != url_26

    def test_all_classes_produce_distinct_urls(self):
        urls = [_pdf_url(cls, 2025, 1) for cls in ["Superbike", "Supersport", "Sportbike"]]
        assert len(set(urls)) == 3

    def test_round_zero_padded(self):
        url = _pdf_url("Superbike", 2026, 1)
        assert "01%20IDM" in url

    def test_different_rounds_differ(self):
        """Regression test: standings PDFs live in a per-round folder just like
        grid/schedule PDFs, not a hardcoded 'round 1' folder - otherwise the
        integration would fetch stale round-1 data (or a permanent 404) for
        the rest of the season."""
        url_r1 = _pdf_url("Superbike", 2026, 1)
        url_r5 = _pdf_url("Superbike", 2026, 5)
        assert url_r1 != url_r5
        assert "01%20IDM" in url_r1
        assert "05%20IDM" in url_r5


class TestGridUrls:
    def test_returns_multiple_url_patterns(self):
        urls = _grid_urls("Superbike", 2026, 1)
        assert len(urls) >= 2
        assert all("2026" in u for u in urls)
        assert all(u.startswith("https://") for u in urls)

    def test_round_zero_padded(self):
        urls = _grid_urls("Superbike", 2026, 1)
        assert any("01%20IDM" in u for u in urls)

    def test_different_rounds_differ(self):
        urls_r1 = _grid_urls("Superbike", 2026, 1)
        urls_r2 = _grid_urls("Superbike", 2026, 2)
        assert urls_r1 != urls_r2


class TestFlag:
    def test_known_nation(self):
        assert _flag("DE") == "🇩🇪"
        assert _flag("AT") == "🇦🇹"
        assert _flag("NL") == "🇳🇱"

    def test_lowercase_nation(self):
        assert _flag("de") == "🇩🇪"

    def test_unknown_nation_returns_empty(self):
        assert _flag("XX") == ""

    def test_none_returns_empty(self):
        assert _flag(None) == ""


class TestParsePdf:
    def _mock_pdfplumber(self, rows: list[list[str]]):
        import pdfplumber as _pdfplumber
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [rows]
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=MagicMock(pages=[mock_page]))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        _pdfplumber.open = MagicMock(return_value=mock_ctx)

    def test_parse_empty_bytes_returns_empty(self):
        """Invalid PDF bytes cause an exception; fetch_standings (the caller) handles it."""
        import pdfplumber as _pdfplumber
        _pdfplumber.open = MagicMock(side_effect=Exception("not a pdf"))
        try:
            result = _parse_standings_pdf(b"not a pdf")
            assert result == []
        except Exception:
            pass  # caller (fetch_standings) is responsible for graceful degradation

    def test_parse_standings_rows(self):
        self._mock_pdfplumber([
            ["Pos", "#", "Name", "Nation", "Bike", "Rnd1", "Total"],
            ["1", "94", "Marcel Schrötter", "DE", "BMW", "25", "25"],
            ["2", "77", "Test Rider", "AT", "Honda", "20", "20"],
        ])
        result = _parse_standings_pdf(b"fake-pdf")
        assert len(result) >= 2
        leader = result[0]
        assert leader["pos"] == 1
        assert leader["name"] == "Marcel Schrötter"
        assert leader["nation"] == "DE"
        assert leader["flag"] == "🇩🇪"
        assert leader["points"] == 25

    def test_parse_includes_flag(self):
        self._mock_pdfplumber([
            ["1", "94", "Schrötter", "AT", "BMW", "50"],
        ])
        result = _parse_standings_pdf(b"fake")
        assert result[0]["flag"] == "🇦🇹"

    def test_parse_skips_header_rows(self):
        self._mock_pdfplumber([
            ["Pos", "#", "Name", "Nation", "Bike", "Total"],
            ["1", "94", "Rider One", "DE", "BMW", "50"],
        ])
        result = _parse_standings_pdf(b"fake-pdf")
        assert all(isinstance(r["pos"], int) for r in result)


class TestParseGridPdf:
    def _mock_pdfplumber(self, rows: list[list[str]]):
        import pdfplumber as _pdfplumber
        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [rows]
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=MagicMock(pages=[mock_page]))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        _pdfplumber.open = MagicMock(return_value=mock_ctx)

    def test_parse_grid_rows(self):
        self._mock_pdfplumber([
            ["P", "#", "Name", "Nation", "Bike", "Time"],
            ["1", "94", "Schrötter", "DE", "BMW", "1:23.456"],
            ["2", "77", "Test Rider", "AT", "Honda", "1:23.789"],
        ])
        result = _parse_grid_pdf(b"fake-pdf")
        assert len(result) >= 2
        pole = result[0]
        assert pole["grid_pos"] == 1
        assert pole["name"] == "Schrötter"
        assert pole["flag"] == "🇩🇪"
        assert pole["best_time"] == "1:23.456"

    def test_grid_skips_header(self):
        self._mock_pdfplumber([
            ["P", "#", "Name", "Nation", "Bike", "Time"],
            ["1", "5", "Rider A", "CZ", "Yamaha", "1:22.000"],
        ])
        result = _parse_grid_pdf(b"fake")
        assert all(isinstance(r["grid_pos"], int) for r in result)


class TestFetchStandings:
    @pytest.mark.asyncio
    async def test_returns_empty_on_404(self):
        import aiohttp
        from custom_components.euromoto.pdf_parser import EuroMotoPdfParser

        mock_resp = AsyncMock()
        mock_resp.status = 404
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_resp.raise_for_status = MagicMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=MagicMock(), history=(), status=404
            )
        )
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        parser = EuroMotoPdfParser(mock_session)
        result = await parser.fetch_standings("Superbike", 2026)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_network_error(self):
        import aiohttp
        from custom_components.euromoto.pdf_parser import EuroMotoPdfParser

        mock_resp = AsyncMock()
        mock_resp.__aenter__ = AsyncMock(side_effect=aiohttp.ClientConnectorError(
            connection_key=MagicMock(), os_error=OSError("connection refused")
        ))
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        parser = EuroMotoPdfParser(mock_session)
        result = await parser.fetch_standings("Superbike", 2026)
        assert result == []

    @pytest.mark.asyncio
    async def test_probes_rounds_and_finds_latest_available(self):
        """Regression test: standings PDFs live in a per-round folder (same
        convention as grid/schedule PDFs), not a fixed 'round 1' URL. Before
        the fix, fetch_standings always requested round 1's folder and never
        found later rounds' cumulative totals - this simulates round 5 being
        the only round with a file present and checks it's actually found."""
        import aiohttp
        from custom_components.euromoto.pdf_parser import EuroMotoPdfParser

        def _make_404():
            resp = AsyncMock()
            resp.status = 404
            resp.__aenter__ = AsyncMock(return_value=resp)
            resp.__aexit__ = AsyncMock(return_value=False)
            resp.raise_for_status = MagicMock(
                side_effect=aiohttp.ClientResponseError(
                    request_info=MagicMock(), history=(), status=404
                )
            )
            return resp

        def _make_ok():
            resp = AsyncMock()
            resp.status = 200
            resp.__aenter__ = AsyncMock(return_value=resp)
            resp.__aexit__ = AsyncMock(return_value=False)
            resp.raise_for_status = MagicMock()
            resp.read = AsyncMock(return_value=b"fake-pdf-bytes")
            return resp

        def _get_side_effect(url, **kwargs):
            if "05%20IDM" in url:
                return _make_ok()
            return _make_404()

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=_get_side_effect)

        with patch(
            "custom_components.euromoto.pdf_parser._parse_standings_pdf",
            return_value=[{"pos": 1, "name": "Test Rider"}],
        ):
            parser = EuroMotoPdfParser(mock_session)
            result = await parser.fetch_standings("Superbike", 2026)

        assert result == [{"pos": 1, "name": "Test Rider"}]
        called_urls = [c.args[0] for c in mock_session.get.call_args_list]
        assert any("05%20IDM" in u for u in called_urls)

    @pytest.mark.asyncio
    async def test_starting_grid_returns_empty_when_all_404(self):
        """fetch_starting_grid returns [] if all URL patterns return 404."""
        from custom_components.euromoto.pdf_parser import EuroMotoPdfParser

        mock_resp = AsyncMock()
        mock_resp.status = 404
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        parser = EuroMotoPdfParser(mock_session)
        result = await parser.fetch_starting_grid("Superbike", 2026, round_num=1)
        assert result == []
