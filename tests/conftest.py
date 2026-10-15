import os
import pytest

# Set safe values before dotenv or any application imports.
os.environ['BOT_TOKEN']='123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk'
os.environ['ADMIN_USER_ID']='123456789,987654321'
os.environ['CHANNEL_ID']='me'
os.environ['LEARNER_USER_ID']='0'
os.environ['NOTION_TOKEN']=''
os.environ['NOTION_PARENT_PAGE_ID']=''
# The historical handlers have regression tests; production defaults to the website.
os.environ['LEGACY_TELEGRAM_POLLS']='true'


@pytest.fixture(autouse=True)
def isolated_database(tmp_path,monkeypatch):
    from app import database
    from app.services import notion_sync
    monkeypatch.setattr(notion_sync, 'WORKSPACE_CONFIG_PATH', tmp_path / 'notion-workspace.json')
    monkeypatch.setattr(database,'DATABASE_PATH',str(tmp_path/'quizbot.db'))
    database.init_db()
