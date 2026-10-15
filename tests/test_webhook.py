from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from app import bot


@pytest.mark.asyncio
async def test_webhook_rejects_forged_updates(monkeypatch):
    process=AsyncMock()
    monkeypatch.setattr(bot,'ptb_app',SimpleNamespace(process_update=process,bot=None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bot.fastapi_app),base_url='http://test') as client:
        response=await client.post('/webhook',json={'update_id':1})
    assert response.status_code==403
    process.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_accepts_telegram_secret(monkeypatch):
    process=AsyncMock()
    monkeypatch.setattr(bot,'ptb_app',SimpleNamespace(process_update=process,bot=None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bot.fastapi_app),base_url='http://test') as client:
        response=await client.post('/webhook',json={'update_id':1},headers={'X-Telegram-Bot-Api-Secret-Token':bot.WEBHOOK_SECRET})
    assert response.status_code==200
    process.assert_awaited_once()
