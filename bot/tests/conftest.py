"""
봇 테스트 공통 설정. Firestore 에뮬레이터가 필요합니다 (FIRESTORE_EMULATOR_HOST).
  저장소 루트에서: npm run test:bot
"""
import asyncio
import os
import sys
import urllib.request
from pathlib import Path

import pytest

BOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_DIR))

PROJECT = "demo-planer-security"
os.environ.update(TOKEN="test", ALERT_CHANNEL="2", WELCOME_CHANNEL="4",
                  FIREBASE_PROJECT_ID=PROJECT)
if not os.getenv("FIRESTORE_EMULATOR_HOST"):
    pytest.exit("FIRESTORE_EMULATOR_HOST가 없습니다. 에뮬레이터에서 실행하세요: npm run test:bot", returncode=2)

import main  # noqa: E402
from store import Store, make_clients  # noqa: E402

def clear_emulator():
    url = f"http://{os.environ['FIRESTORE_EMULATOR_HOST']}/emulator/v1/projects/{PROJECT}/databases/(default)/documents"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    opener.open(urllib.request.Request(url, method="DELETE"), timeout=10).read()

@pytest.fixture
async def store():
    clear_emulator()
    sync_client, async_client = make_clients(project_id=PROJECT)
    s = Store(sync_client, async_client)
    await s.start()
    main.store = s
    main.bot_state = {}
    yield s
    s.stop()

@pytest.fixture
def raw():
    """앱처럼 Firestore에 직접 쓰기 위한 동기 클라이언트"""
    sync_client, _ = make_clients(project_id=PROJECT)
    return sync_client

async def until(predicate, timeout=10):
    """리스너가 변경을 반영할 때까지 기다림"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("시간 안에 조건이 맞지 않음")
        await asyncio.sleep(0.05)

# ---------- 가짜 디스코드 객체 ----------

class FakeUser:
    def __init__(self, id, name=None, bot=False):
        self.id = id
        self.display_name = name or f"user{id}"
        self.mention = f"<@{id}>"
        self.bot = bot

class FakeGuild:
    def __init__(self, users):
        self.members = list(users)

class FakeMessage:
    def __init__(self, id=4242, embed=None):
        self.id = id
        self.jump_url = f"https://discord.com/channels/9/2/{id}"
        self.embeds = [embed] if embed else []

class FakeChannel:
    def __init__(self):
        self.sent = []
    async def send(self, content=None, embed=None, **_):
        self.sent.append((content, embed))

class FakeResponse:
    def __init__(self, it):
        self.it = it
        self._done = False
    def is_done(self):
        return self._done
    async def send_message(self, content=None, embed=None, ephemeral=False, **_):
        self.it.sent.append((content, embed, ephemeral))
        self._done = True
        if embed is not None:
            self.it.message = FakeMessage(self.it.message_id, embed)
    async def edit_message(self, **_):
        self._done = True

class FakeFollowup:
    def __init__(self, it):
        self.it = it
    async def send(self, content=None, embed=None, ephemeral=False, **_):
        self.it.sent.append((content, embed, ephemeral))

class NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)

class FakeInteraction:
    def __init__(self, user, guild=None, message=None, message_id=4242, **namespace):
        self.user = user
        self.guild = guild or FakeGuild([user])
        self.message = message
        self.message_id = message_id
        self.namespace = NS(**namespace)
        self.command = None
        self.sent = []
        self.channel = FakeChannel()
        self.response = FakeResponse(self)
        self.followup = FakeFollowup(self)
    async def original_response(self):
        return self.message or FakeMessage(self.message_id)
    async def edit_original_response(self, **_):
        pass
    def text(self):
        return (self.sent[0][0] or "") if self.sent else ""
    def fields(self):
        return {f.name: f.value for _, e, _ in self.sent if e is not None for f in e.fields}

class Choice:
    def __init__(self, value, name=None):
        self.value = value
        self.name = name or str(value)

class Attachment:
    content_type = "image/png"
    url = "https://cdn.discordapp.com/x.png"
