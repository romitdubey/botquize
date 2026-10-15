"""Create/resume the hub using deployment env, without changing Telegram's webhook.

Run: python -m app.notion_setup
"""
import asyncio
from app import database
from app.services.notion_sync import NotionClient, NotionError, setup_hub


async def main():
    database.init_db()
    try:
        async with NotionClient() as client:
            print(await setup_hub(client))
    except NotionError as exc:
        raise SystemExit(str(exc)) from None


if __name__=='__main__':
    asyncio.run(main())
