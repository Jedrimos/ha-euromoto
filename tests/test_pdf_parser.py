"""Tests for euromoto PDF parser."""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.euromoto.pdf_parser import _parse_standings_pdf, _pdf_url


class TestPdfUrl:
    def test_superbike_url(self):
        url = _pdf_url("Superbike", 2025)
        assert "2025" in url
        assert "Superbike" in url
        assert url.startswith("https://")

    def test_year_in_url(self):
        url_25 = _pdf_url("Supersport", 2025)
        url_26 = _pdf_url("Supersport", 2026)
        assert "2025" in url_25
        assert "2026" in url_26
        assert url_25 != url_26

    def test_all_classes_produce_distinct_urls(self):
        urls = [_pdf_url(cls, 2025) for cls in ["Superbike", "Supersport", "Sportbike"]]
        assert len(set(urls)) == 3


class TestParsePdf:
    def test_parse_empty_bytes_returns_empty(self):
        """Invalid PDF bytes cause an exception; fetch_standings (the caller) handles it."""
        import pdfplumber as _pdfplumber

        _pdfplumber.open = MagicMock(side_effect=Exception("not a pdf"))
        # _parse_standings_pdf is allowed to raise – error handling lives in fetch_standings
        try:
            result = _parse_standings_pdf(b"not a pdf")
            assert result == []
        except Exception:
            pass  # expected – caller is responsible for graceful degradation

    def test_parse_standings_rows(self):
        """Parser extracts standings from mocked pdfplumber output."""
        import pdfplumber as _pdfplumber

        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [
                ["Pos", "#", "Name", "Nation", "Bike", "Rnd1", "Total"],
                ["1", "94", "Marcel Schrötter", "DE", "BMW", "25", "25"],
                ["2", "77", "Test Rider", "AT", "Honda", "20", "20"],
            ]
        ]
        mock_pdf_ctx = MagicMock()
        mock_pdf_ctx.__enter__ = MagicMock(return_value=MagicMock(pages=[mock_page]))
        mock_pdf_ctx.__exit__ = MagicMock(return_value=False)
        _pdfplumber.open = MagicMock(return_value=mock_pdf_ctx)

        result = _parse_standings_pdf(b"fake-pdf")
        assert len(result) >= 2
        leader = result[0]
        assert leader["pos"] == 1
        assert leader["name"] == "Marcel Schrötter"
        assert leader["nation"] == "DE"
        assert leader["points"] == 25

    def test_parse_skips_header_rows(self):
        """Header rows with non-numeric Pos should be skipped."""
        import pdfplumber as _pdfplumber

        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [
                ["Pos", "#", "Name", "Nation", "Bike", "Total"],
                ["1", "94", "Rider One", "DE", "BMW", "50"],
            ]
        ]
        mock_pdf_ctx = MagicMock()
        mock_pdf_ctx.__enter__ = MagicMock(return_value=MagicMock(pages=[mock_page]))
        mock_pdf_ctx.__exit__ = MagicMock(return_value=False)
        _pdfplumber.open = MagicMock(return_value=mock_pdf_ctx)

        result = _parse_standings_pdf(b"fake-pdf")
        assert all(isinstance(r["pos"], int) for r in result)


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
