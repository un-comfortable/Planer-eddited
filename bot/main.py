import discord
import os
import json
import random
import asyncio
import re
import shutil
import traceback
from pathlib import Path
from discord import ui, app_commands
from discord.ext import tasks, commands
from dotenv import load_dotenv
from datetime import datetime, timedelta

import core
from core import CATEGORY_KR, LIMIT_PERIOD_KR, PLAN_CATEGORIES, WEEKDAY_NAMES, day_str
from store import Store, make_clients

# 이 파일(main.py)이 있는 폴더. 어디서 실행하든 .env와 데이터 파일을 이 폴더에서 찾음
BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")
TOKEN = os.getenv('TOKEN')

#채널 아이디 (.env 파일에서 불러옴)
def get_id_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f".env 파일에 {name} 값이 없습니다. .env.example을 참고해 추가해주세요.")
    try:
        return int(value)
    except ValueError:
        raise RuntimeError(f".env 파일의 {name} 값은 숫자 ID여야 합니다. (현재 값: {value!r})")

ALERT_CHANNEL = get_id_env('ALERT_CHANNEL')
WELCOME_CHANNEL = get_id_env('WELCOME_CHANNEL')

# 입력 글자 수 제한 (디스코드 표시 제한을 넘지 않도록)
PlanText = app_commands.Range[str, 1, 80]       # 계획 이름 (앱 규칙과 같은 1~80자)
LongText = app_commands.Range[str, 1, 1000]     # 사유/코멘트 (임베드 칸 최대 1024자)

#정산 설정
SETTLEMENT_HOUR = 12  # 매일 이 시각(이후)에 어제 기록을 정산
FINE_AMOUNT = 3000    # 벌금 3,000원

# Firestore 저장소 (setup_hook에서 연결). 테스트에서는 직접 넣어줌
store: Store = None
bot_state = {}

#명령어를 쓸 때마다 멤버 정보(디스코드 표시 이름)를 Firestore에 맞춰 둠 → 앱 멤버 탭에서 이름 표시
class TonkatsuTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if store is not None and interaction.guild is not None and not interaction.user.bot:
            try:
                await store.ensure_member(interaction.user.id, interaction.user.display_name)
            except Exception:
                traceback.print_exc()
        return True

class TonkatsuBot(commands.Bot):
    async def setup_hook(self):
        global store, bot_state
        sync_client, async_client = make_clients()
        store = Store(sync_client, async_client)
        install_store_hooks(store)
        await store.start()
        print(f"🔥 Firestore 연결 완료: 계획 {len(store.data['plans'])}개, 멤버 {len(store.data['members'])}명")
        bot_state = await load_state()

intents = discord.Intents.default()
# 슬래시 명령어만 쓰므로 message_content 권한은 필요 없음
# members는 개발자 포털에서 "Server Members Intent"를 켜야 함
intents.members = True

bot = TonkatsuBot(command_prefix='!', intents=intents, tree_cls=TonkatsuTree)

#파일 저장 (백업용. 계획·인증 데이터는 Firestore)
def _atomic_write_text(path, text):
    # 임시 파일에 다 쓴 다음 한 번에 교체 → 저장 도중 꺼져도 기존 파일이 깨지지 않음
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

#정산·백업 기록 (Firestore botState/state)
async def load_state():
    state = await store.get_state()
    if not isinstance(state, dict):
        # 처음 실행: 이미 12시가 지났으면 오늘 정산은 기존 봇이 했다고 보고 건너뜀 (중복 벌금 방지)
        now = core.get_now()
        last = now if now.hour >= SETTLEMENT_HOUR else now - timedelta(days=1)
        state = {"last_settlement_date": day_str(last)}
        await store.save_state(state)
    return state

async def save_state():
    await store.save_state(bot_state)

#디스코드 글자 수 제한 대응
EMBED_FIELD_LIMIT = 1024   # 임베드 칸(field) 하나의 최대 글자 수
EMBED_TOTAL_LIMIT = 5500   # 임베드 전체 최대 6000자, 여유를 둠
EMBED_MAX_FIELDS = 25      # 임베드 하나에 들어가는 최대 칸 수
MESSAGE_LIMIT = 2000       # 일반 메시지 최대 글자 수

def split_text(text, limit):
    """줄 단위로 limit 글자 이하 덩어리로 나눔. 한 줄이 너무 길면 잘라냄."""
    chunks, current = [], ""
    for line in str(text).split("\n"):
        if len(line) > limit:
            line = line[:limit - 1] + "…"
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current or not chunks:
        chunks.append(current or "-")
    return chunks

def build_embeds(title, color, description=None, fields=(), footer=None, image_url=None, thumbnail_url=None):
    """fields: (이름, 내용, inline) 목록. 내용이 길면 칸을, 칸이 많으면 임베드를 나눔"""
    def new_embed(first):
        e = discord.Embed(title=title if first else f"{title} (계속)", color=color)
        if first and description:
            e.description = description[:4000]
        return e

    embeds = [new_embed(True)]
    for name, value, inline in fields:
        for i, chunk in enumerate(split_text(value, EMBED_FIELD_LIMIT)):
            field_name = (name if i == 0 else f"{name} (계속)")[:256]
            e = embeds[-1]
            if len(e.fields) >= EMBED_MAX_FIELDS or len(e) + len(field_name) + len(chunk) > EMBED_TOTAL_LIMIT:
                e = new_embed(False)
                embeds.append(e)
            e.add_field(name=field_name, value=chunk, inline=inline)

    if footer:
        embeds[-1].set_footer(text=footer[:300])
    if image_url:
        embeds[0].set_image(url=image_url)
    if thumbnail_url:
        embeds[0].set_thumbnail(url=thumbnail_url)
    return embeds

async def send_embeds(channel, embeds, content=None):
    for i, embed in enumerate(embeds):
        await channel.send(content=content if i == 0 else None, embed=embed)

async def respond_embeds(interaction, embeds, ephemeral=False):
    # 디스코드는 메시지 하나에 임베드 전체 6000자 제한이 있어서 하나씩 보냄
    await interaction.response.send_message(embed=embeds[0], ephemeral=ephemeral)
    for embed in embeds[1:]:
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)

async def send_long_message(channel, text):
    for chunk in split_text(text, MESSAGE_LIMIT):
        await channel.send(chunk)

def fit_choice(name):
    # 자동완성 선택지 이름은 최대 100자
    return name if len(name) <= 100 else name[:99] + "…"

def photo_icon(photo_required):
    return "📸 사진 필수" if photo_required else "📝 내용만"

# /인증, /인증취소의 '날짜' 옵션
DATE_CHOICES = [
    app_commands.Choice(name="오늘", value="today"),
    app_commands.Choice(name="어제 (깜빡한 인증)", value="yesterday"),
]

def alert_guild():
    channel = bot.get_channel(ALERT_CHANNEL)
    return channel.guild if channel else None

async def sync_server_info(guild):
    """앱 상단에 보여줄 디스코드 서버 이름·아이콘 저장"""
    if guild is None:
        return
    try:
        await store.set_server_info(guild.id, guild.name, guild.icon.url if guild.icon else None)
    except Exception:
        print("⚠️ 서버 정보 저장 실패:")
        traceback.print_exc()

#봇 준비
first_ready_done = False

@bot.event
async def on_ready():
    # on_ready는 연결이 끊겼다 다시 붙을 때도 실행됨
    # 명령어 동기화와 투표 버튼 복구는 처음 한 번만 (디스코드 요청 제한 방지)
    global first_ready_done
    is_first_ready = not first_ready_done
    first_ready_done = True

    guild = alert_guild()
    if is_first_ready:
        try:
            synced = await bot.tree.sync()
            print(f"🔁 슬래시 명령어 {len(synced)}개 동기화 완료")
        except discord.HTTPException as e:
            print(f"⚠️ 슬래시 명령어 동기화 실패: {e}")

        await sync_server_info(guild)
        # 이전 데이터에서 옮겨온 멤버는 이름이 비어 있으니, 서버 멤버 이름으로 채움
        if guild:
            for discord_id in list(store.data["members"]):
                member = guild.get_member(int(discord_id)) if discord_id.isdigit() else None
                if member and not member.bot:
                    try:
                        await store.ensure_member(member.id, member.display_name)
                    except Exception:
                        traceback.print_exc()

    for msg_id, data in (list(store.data["votes"].items()) if is_first_ready else []):
        try:
            req_votes = data.get("required_votes", 2)
            dates = data["target_dates"] if "target_dates" in data else [data.get("date_str", "")]
            view = ImmunityView(
                message_id=int(msg_id),
                target_id=int(data['target_id']),
                target_dates=dates,
                agreed_users=data.get('agreed_users', []),
                denied_users=data.get("denied_users", []),
                total_members=data.get("total_members", req_votes * 2),
                required_votes=req_votes,
                eligible_voters=data.get("eligible_voters"),  # 예전 투표는 없음 → 누구나 투표 가능
            )
            bot.add_view(view, message_id=int(msg_id))
        except Exception as e:
            print(f"⚠️ 투표 복구 실패 (ID: {msg_id}): {e}")

    if not hourly_check.is_running():
        hourly_check.start()

    print(f'로그인 성공! {bot.user} 봇이 준비되었습니다.')

@bot.event
async def on_guild_update(before, after):
    if after == alert_guild() and (before.name != after.name or before.icon != after.icon):
        await sync_server_info(after)

#입장
@bot.event
async def on_member_join(member):
    print(f'{member}님이 입장했습니다.')
    channel = bot.get_channel(WELCOME_CHANNEL)
    if channel:
        await channel.send(f'{member.mention} <- 바보 등장!!!')

#계획 등록
plan_group = app_commands.Group(name="계획", description="나만의 계획을 세웁니다.")

PHOTO_CHOICES = [
    app_commands.Choice(name="O (사진 필수)", value=1),
    app_commands.Choice(name="X (내용만 인증)", value=0)
]

async def register_plan(interaction: discord.Interaction, category: str, fields: dict) -> bool:
    """중복 이름을 검사하고 계획을 저장함. 중복이면 안내 메시지를 보내고 False를 돌려줌."""
    user_id = str(interaction.user.id)
    existing_category, _ = Store.find_plan(store.view(user_id), fields['content'])
    if existing_category:
        await interaction.response.send_message(f"✋ **'{fields['content']}'** 계획은 이미 [{CATEGORY_KR[existing_category]}] 카테고리에 등록되어 있어요! 이름은 다르게 지어주세요.", ephemeral=True)
        return False
    # 등록일은 오늘 (새벽 0~4시면 전날). 이전 기간은 정산하지 않음
    await store.add_plan(user_id, category, fields, day_str(core.get_base_date()))
    return True

#계획 등록 (매일/주간/월간 + 제한)
@plan_group.command(name="등록", description="매일/주간/월간 계획을 세웁니다. 제한 O면 'N회 이하로 참기' 계획이 돼요.")
@app_commands.describe(
    주기="매일 / 주간(월~일) / 월간",
    내용="내용 (예: 운동, 몬스터)",
    횟수="주간·월간: 목표 횟수 / 제한: 최대 횟수 (매일 목표는 입력 안 해도 됨)",
    제한="O: 횟수를 넘기면 벌금 (예: 몬스터 주 2회 이하) / X: 횟수 이상 하기 (기본)",
    사진인증="인증할 때 사진 필수 여부 (기본 X)",
)
@app_commands.choices(
    주기=[
        app_commands.Choice(name="매일", value="day"),
        app_commands.Choice(name="주간 (월~일)", value="week"),
        app_commands.Choice(name="월간", value="month"),
    ],
    제한=[
        app_commands.Choice(name="X (N회 이상 하기)", value=0),
        app_commands.Choice(name="O (N회 이하로 참기, 넘기면 벌금)", value=1),
    ],
    사진인증=PHOTO_CHOICES,
)
async def plan_register(interaction: discord.Interaction, 주기: app_commands.Choice[str], 내용: PlanText,
                        횟수: app_commands.Range[int, 0, 50] = None,
                        제한: app_commands.Choice[int] = None,
                        사진인증: app_commands.Choice[int] = None):
    period = 주기.value
    is_limit = bool(제한 and 제한.value)
    photo = bool(사진인증 and 사진인증.value)
    period_kr = {"day": "하루", "week": "일주일", "month": "한 달"}[period]

    # 1. 제한 계획: N회 이하
    if is_limit:
        if 횟수 is None:
            await interaction.response.send_message("❌ 제한 계획은 `횟수`(최대 몇 번까지 괜찮은지)를 입력해주세요! 0이면 한 번만 해도 벌금이에요.", ephemeral=True)
            return
        if await register_plan(interaction, "Limit", {"content": 내용, "photo": False, "period": period, "limit": 횟수}):
            await interaction.response.send_message(
                f"🚫 **[제한] 계획 등록 완료!**\n- **내용:** {내용}\n- **제한:** {period_kr}에 **{횟수}회 이하**\n"
                f"할 때마다 `/인증`으로 기록하세요. {횟수}회를 넘기면 정산 때 벌금이에요!"
            )
        return

    # 2. 매일 계획: 하루 한 번
    if period == "day":
        if await register_plan(interaction, "Daily", {"content": 내용, "photo": photo}):
            await interaction.response.send_message(f"📅 **[일일] 계획 등록 완료!** ({photo_icon(photo)})\n- **내용:** {내용}")
        return

    # 3. 주간/월간 계획: N회 이상
    max_count = 7 if period == "week" else 31
    if 횟수 is None or not 1 <= 횟수 <= max_count:
        await interaction.response.send_message(f"❌ {주기.name} 계획은 `횟수`를 **1~{max_count}** 사이로 입력해주세요!", ephemeral=True)
        return

    category, type_kr, unit = ("Weekly", "주간", "주") if period == "week" else ("Monthly", "월간", "월")
    if await register_plan(interaction, category, {"count": 횟수, "content": 내용, "photo": photo}):
        await interaction.response.send_message(f"📅 **[{type_kr}] 계획 등록 완료!** ({photo_icon(photo)})\n- **목표:** {unit} {횟수}회\n- **내용:** {내용}")

#요일 계획
@plan_group.command(name="요일", description="특정 요일에만 반복할 계획을 세웁니다.")
@app_commands.describe(내용="내용", 요일="예: 월수금, 토일 (원하는 요일을 붙여서 적으세요)", 사진인증="사진 인증 여부 (기본 X)")
@app_commands.choices(사진인증=PHOTO_CHOICES)
async def plan_routine(interaction: discord.Interaction, 내용: PlanText, 요일: str, 사진인증: app_commands.Choice[int] = None):
    selected_days = [day for day in WEEKDAY_NAMES if day in 요일]
    if not selected_days:
        await interaction.response.send_message("❌ 요일을 제대로 인식하지 못했어요! **'월수금'**, **'토일'** 처럼 요일 글자를 포함해서 적어주세요.", ephemeral=True)
        return

    photo = bool(사진인증 and 사진인증.value)
    if await register_plan(interaction, "Routine", {"content": 내용, "photo": photo, "days": selected_days}):
        await interaction.response.send_message(f"✅ **[요일] 계획 등록 완료!** ({photo_icon(photo)})\n- **내용:** {내용}\n- **수행 요일:** {', '.join(selected_days)}요일")

#n일계획
@plan_group.command(name="n일", description="N일마다 반복하는 계획을 세웁니다")
@app_commands.describe(간격="며칠마다 할까요? (1~365)", 내용="내용", 사진인증="사진 인증 여부 (기본 X)")
@app_commands.choices(사진인증=PHOTO_CHOICES)
async def plan_interval(interaction: discord.Interaction, 간격: app_commands.Range[int, 1, 365], 내용: PlanText, 사진인증: app_commands.Choice[int] = None):
    photo = bool(사진인증 and 사진인증.value)
    if await register_plan(interaction, "Interval", {"interval": 간격, "content": 내용, "photo": photo}):
        await interaction.response.send_message(f"📅 **[{간격}일마다] 계획 등록!** ({photo_icon(photo)})\n- **내용:** {내용}")

#일회성 목표
@plan_group.command(name="목표", description="특정 날짜까지 완수해야 하는 1회성 목표를 세웁니다.")
@app_commands.describe(마감일="YYYY-MM-DD 형식 (예: 2026-01-20)", 내용="목표 내용", 사진인증="사진 인증 여부 (기본 X)")
@app_commands.choices(사진인증=PHOTO_CHOICES)
async def plan_deadline(interaction: discord.Interaction, 마감일: str, 내용: PlanText, 사진인증: app_commands.Choice[int] = None):
    try:
        마감일 = day_str(datetime.strptime(마감일, "%Y-%m-%d"))
    except ValueError:
        await interaction.response.send_message("❌ 날짜 형식이 틀렸어요! **2026-01-20** 처럼 적어주세요.", ephemeral=True)
        return

    photo = bool(사진인증 and 사진인증.value)
    if await register_plan(interaction, "OneTime", {"deadline": 마감일, "content": 내용, "photo": photo}):
        await interaction.response.send_message(f"🎯 **[목표] 등록 완료!** ({photo_icon(photo)})\n- **마감:** {마감일}까지\n- **내용:** {내용}")

#자동완성 (인증할 수 있는 계획만 보여줌). 선택 값은 계획 ID
async def plan_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    view = store.view(interaction.user.id)
    target_date = core.resolve_target_date(getattr(interaction.namespace, "날짜", None))

    choices = []
    for category, plan in core.iter_plans(view):
        tag = core.autocomplete_tag(view, category, plan, target_date)
        if tag is None:
            continue
        photo_mark = "📸 " if plan.get('photo') else ""
        name = f"[{tag}] {photo_mark}{plan['content']}"
        if current.lower() in name.lower():
            choices.append(app_commands.Choice(name=fit_choice(name), value=plan['id']))
    return choices[:25]

#자동완성(삭제) - 모든 계획을 보여줌
async def plan_autocomplete_delete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    choices = []
    for category, plan in core.iter_plans(store.view(interaction.user.id)):
        if category == "Weekly": tag = f"주{plan.get('count', 1)}회"
        elif category == "Interval": tag = f"{plan.get('interval', 1)}일장"
        elif category == "Limit": tag = f"제한 {LIMIT_PERIOD_KR.get(plan.get('period'), '')} {plan.get('limit', 0)}회"
        else: tag = CATEGORY_KR[category]
        name = f"[{tag}] {plan['content']}"
        if current.lower() in name.lower():
            choices.append(app_commands.Choice(name=fit_choice(name), value=plan['id']))
    return choices[:25]

#계획 삭제
@plan_group.command(name="삭제", description="등록된 계획 중 하나를 선택해 삭제합니다.")
@app_commands.describe(계획="삭제할 계획을 선택하세요?")
@app_commands.autocomplete(계획=plan_autocomplete_delete)
async def plan_delete(interaction: discord.Interaction, 계획: str):
    category, plan = Store.find_plan(store.view(interaction.user.id), 계획)
    if not plan:
        await interaction.response.send_message(f"❓ **'{계획}'**라는 계획을 못 찾겠어요. 이미 삭제됐나 봐요!", ephemeral=True)
        return

    await store.delete_plan(plan['id'])
    await interaction.response.send_message(f"🗑️ **[{CATEGORY_KR[category]}] {plan['content']}** 계획을 시원하게 삭제했습니다! 👋")

def install_store_hooks(s):
    """앱에서 계획 조건을 바꾸면 디스코드에 알림"""
    s.on_plan_edit = lambda old, new: asyncio.create_task(
        announce_plan_edit(new.get("ownerId"), new.get("content"), core.describe_plan_changes(old, new), "앱"))

async def announce_plan_edit(owner_id, content, changes, where):
    """계획 조건이 바뀌면 알림 채널에 공개 (벌금 피하려는 수정을 서로 볼 수 있게)"""
    channel = bot.get_channel(ALERT_CHANNEL)
    if not channel or not changes:
        return
    name = (store.data["members"].get(str(owner_id)) or {}).get("displayName") or f"<@{owner_id}>"
    try:
        await channel.send(f"✏️ **{name}**님이 **'{content}'** 계획을 바꿨어요 ({where}): " + ", ".join(changes),
                           allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        traceback.print_exc()

#계획 수정
@plan_group.command(name="수정", description="등록한 계획의 이름·사진 필수 여부·횟수·요일·간격·마감일을 바꿉니다.")
@app_commands.describe(
    계획="수정할 계획", 내용="새 이름", 사진인증="사진 필수 여부 (제한 계획은 해당 없음)",
    횟수="주간·월간: 목표 횟수 / 제한: 최대 횟수", 요일="요일 계획: 예) 월수금", 간격="N일 계획: 며칠마다", 마감일="목표: YYYY-MM-DD",
)
@app_commands.choices(사진인증=PHOTO_CHOICES)
@app_commands.autocomplete(계획=plan_autocomplete_delete)
async def plan_edit(interaction: discord.Interaction, 계획: str, 내용: PlanText = None, 사진인증: app_commands.Choice[int] = None,
                    횟수: app_commands.Range[int, 0, 50] = None, 요일: str = None,
                    간격: app_commands.Range[int, 1, 365] = None, 마감일: str = None):
    category, plan = Store.find_plan(store.view(interaction.user.id), 계획)
    if not plan:
        await interaction.response.send_message(f"❓ **'{계획}'** 계획을 못 찾겠어요.", ephemeral=True)
        return

    async def reject(msg):
        await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

    changes = {}
    if 내용 is not None and 내용.strip() != plan["content"]:
        if Store.find_plan(store.view(interaction.user.id), 내용.strip())[1]:
            return await reject(f"**'{내용}'** 이름의 계획이 이미 있어요.")
        changes["content"] = 내용.strip()
    if 사진인증 is not None:
        if category == "Limit":
            return await reject("제한 계획은 사진 인증을 쓰지 않아요.")
        changes["photo"] = bool(사진인증.value)
    if 횟수 is not None:
        if category == "Weekly" and 1 <= 횟수 <= 7: changes["count"] = 횟수
        elif category == "Monthly" and 1 <= 횟수 <= 31: changes["count"] = 횟수
        elif category == "Limit": changes["limit"] = 횟수
        else:
            return await reject("횟수는 주간(1~7)·월간(1~31)·제한(0~50) 계획에서만 바꿀 수 있어요.")
    if 요일 is not None:
        days = [d for d in WEEKDAY_NAMES if d in 요일]
        if category != "Routine" or not days:
            return await reject("요일은 요일 계획에서만, '월수금'처럼 적어주세요.")
        changes["days"] = days
    if 간격 is not None:
        if category != "Interval":
            return await reject("간격은 N일 계획에서만 바꿀 수 있어요.")
        changes["interval"] = 간격
    if 마감일 is not None:
        try:
            deadline = day_str(datetime.strptime(마감일, "%Y-%m-%d"))
        except ValueError:
            return await reject("마감일은 **2026-01-20** 처럼 적어주세요.")
        if category != "OneTime":
            return await reject("마감일은 목표 계획에서만 바꿀 수 있어요.")
        changes["deadline"] = deadline

    changes = {k: v for k, v in changes.items() if plan.get(k) != v}
    if not changes:
        await interaction.response.send_message("🤔 바뀐 내용이 없어요. 바꿀 항목을 입력해주세요.", ephemeral=True)
        return

    old = dict(plan)
    await store.edit_plan(plan["id"], changes)
    new = {**old, **changes}
    await interaction.response.send_message(
        f"✏️ **[{CATEGORY_KR[category]}] {new['content']}** 계획을 수정했어요. ({core.condition_text(new)}, 사진 {'필수' if new.get('photo') else 'X'})")
    await announce_plan_edit(interaction.user.id, new["content"], core.describe_plan_changes(old, new), "디스코드")

bot.tree.add_command(plan_group)

# --- 면책 ---
class ImmunityView(ui.View):
    """
    면책 투표 버튼.
    total_members: 요청자를 포함한 투표 대상 인원 (요청자 제외 투표 가능 인원 = total_members - 1)
    eligible_voters: 투표할 수 있는 유저 ID 목록. None이면 누구나 가능 (예전에 만든 투표 호환용)
    """
    def __init__(self, message_id: int, target_id: int, target_dates: list, agreed_users: list, denied_users: list,
                 total_members: int, required_votes: int, eligible_voters: list = None):
        super().__init__(timeout=None)
        self.message_id = str(message_id)
        self.target_id = int(target_id)
        self.target_dates = [target_dates] if isinstance(target_dates, str) else list(target_dates)

        self.agreed_users = {int(u) for u in agreed_users}
        self.denied_users = {int(u) for u in denied_users}
        self.total_members = total_members
        self.required_votes = required_votes
        self.eligible_voters = {int(u) for u in eligible_voters} if eligible_voters is not None else None

        self.update_button_label()

    def max_possible_yes(self):
        # 남은 사람이 전부 찬성해도 받을 수 있는 최대 찬성 수
        return self.total_members - 1 - len(self.denied_users)

    def update_button_label(self):
        agree_btn = [x for x in self.children if x.custom_id == "vote_agree"][0]
        deny_btn = [x for x in self.children if x.custom_id == "vote_deny"][0]

        agree_btn.label = f"인정합니다 ({len(self.agreed_users)}/{self.required_votes})"
        deny_btn.label = f"반대합니다 ({len(self.denied_users)})"

        if len(self.agreed_users) >= self.required_votes:
            agree_btn.label = "면책 통과됨 🎉"
            agree_btn.style = discord.ButtonStyle.primary
            agree_btn.disabled = True
            deny_btn.disabled = True
        elif self.max_possible_yes() < self.required_votes:
            deny_btn.label = "면책 거절됨 ❌"
            deny_btn.style = discord.ButtonStyle.danger
            deny_btn.disabled = True
            agree_btn.disabled = True

    async def save_status(self):
        current = store.data["votes"].get(self.message_id)
        if current is not None:
            await store.set_vote(self.message_id, {**current, 'agreed_users': sorted(self.agreed_users),
                                                   'denied_users': sorted(self.denied_users)})

    async def finish_vote(self):
        if self.message_id in store.data["votes"]:
            await store.delete_vote(self.message_id)

    def vote_error(self, user_id, is_agree):
        """투표할 수 없으면 안내 문구, 가능하면 None"""
        if user_id == self.target_id:
            return "❌ 본인 사유에는 투표할 수 없어요!" if is_agree else "❌ 본인 사유에 반대할 수 없어요! (하고 싶으신가요..?)"
        if self.eligible_voters is not None and user_id not in self.eligible_voters:
            return "❌ 계획을 등록한 참가자만 투표할 수 있어요!"
        if user_id in self.agreed_users:
            return "이미 찬성하셨습니다." if is_agree else "이미 '찬성'표를 던지셨네요! 취소할 수 없습니다."
        if user_id in self.denied_users:
            return "이미 '반대'표를 던지셨네요! 취소할 수 없습니다." if is_agree else "이미 '반대'하셨습니다."
        return None

    @ui.button(label="인정합니다 (0/2)", style=discord.ButtonStyle.success, emoji="👌", custom_id="vote_agree")
    async def agree_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        error = self.vote_error(user_id, is_agree=True)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        self.agreed_users.add(user_id)
        await self.save_status()
        self.update_button_label()

        await interaction.channel.send(f"🙆‍♂️ <@{user_id}>님이 **찬성**했습니다!")

        if len(self.agreed_users) < self.required_votes:
            await interaction.response.edit_message(view=self)
            return

        # 통과: 면책 날짜 등록
        await store.add_exemptions(self.target_id, self.target_dates)
        await self.finish_vote()

        if len(self.target_dates) > 1:
            period_str = f"{self.target_dates[0]} ~ {self.target_dates[-1]} ({len(self.target_dates)}일간)"
        else:
            period_str = self.target_dates[0]

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.blue()
        embed.set_footer(text="")
        embed.add_field(name="최종 결과", value=f"✅ **{len(self.agreed_users)}표** 찬성으로 면책되었습니다!", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(f"🛡️ <@{self.target_id}>님의 **{period_str}** 벌금이 면제되었습니다!")

    @ui.button(label="반대합니다", style=discord.ButtonStyle.secondary, emoji="🙅", custom_id="vote_deny")
    async def deny_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        error = self.vote_error(user_id, is_agree=False)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return

        self.denied_users.add(user_id)
        await self.save_status()
        self.update_button_label()

        await interaction.channel.send(f"🙅 <@{user_id}>님이 **반대**했습니다!")

        if self.max_possible_yes() >= self.required_votes:
            await interaction.response.edit_message(view=self)
            return

        # 거절: 남은 사람이 다 찬성해도 과반수가 안 됨
        await self.finish_vote()

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.set_footer(text="")
        embed.add_field(name="결과", value="❌ 반대가 너무 많아 **부결(거절)**되었습니다.", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(f"🚫 <@{self.target_id}>님의 면책 요청이 **거절**되었습니다.")

def get_eligible_voters(guild, requester_id):
    """투표할 수 있는 사람: 서버에 있는 사람 중 계획을 하나라도 등록한 참가자 (요청자, 봇 제외)"""
    return [m.id for m in guild.members
            if not m.bot and m.id != requester_id and core.has_active_plans(store.view(m.id))]

async def start_immunity_vote(interaction: discord.Interaction, dates: list, title: str, color: discord.Color, date_field: tuple, 사유: str):
    """면책 투표 메시지를 만들고 저장함 (하루/기간 면책 공통)"""
    requester_id = interaction.user.id
    voters = get_eligible_voters(interaction.guild, requester_id)

    if not voters:
        await interaction.response.send_message("❌ 투표해 줄 다른 참가자가 없어요! (계획을 등록한 다른 멤버가 있어야 해요)", ephemeral=True)
        return

    required_votes = len(voters) // 2 + 1  # 요청자를 뺀 참가자의 과반수

    embed = discord.Embed(title=title, description=f"**{interaction.user.display_name}**님이 면책을 요청했습니다.", color=color)
    embed.add_field(name=date_field[0], value=date_field[1], inline=False)
    embed.add_field(name="📝 사유", value=사유, inline=False)
    embed.set_footer(text=f"참가자 {len(voters)}명 중 과반수인 {required_votes}명의 동의가 필요합니다.")

    await interaction.response.send_message(content="@everyone", embed=embed)
    message = await interaction.original_response()

    view = ImmunityView(message.id, requester_id, dates, [], [], len(voters) + 1, required_votes, voters)
    await interaction.edit_original_response(view=view)

    # 재부팅 때 버튼을 복구할 수 있도록 저장 (앱에서도 진행 중인 투표를 볼 수 있음)
    await store.set_vote(message.id, {
        "target_id": requester_id,
        "target_dates": dates,
        "reason": 사유,
        "agreed_users": [],
        "denied_users": [],
        "total_members": len(voters) + 1,
        "required_votes": required_votes,
        "eligible_voters": voters,
    })

# --- 면책 요청 ---
@bot.tree.command(name="면책", description="벌금 면제를 요청합니다. 날짜를 비우면 오늘 하루 (참가자 과반수 동의 필요)")
@app_commands.describe(
    사유="면책을 요청하는 합당한 사유를 적어주세요.",
    시작일="기간 면책 시작일 YYYY-MM-DD (비우면 오늘)",
    종료일="기간 면책 종료일 YYYY-MM-DD (비우면 시작일 하루만)",
)
@app_commands.guild_only()
async def request_immunity(interaction: discord.Interaction, 사유: LongText, 시작일: str = None, 종료일: str = None):
    try:
        # 새벽 0~4시에 요청하면 전날 기준 (인증/정산과 같은 기준)
        start_dt = datetime.strptime(시작일 or day_str(core.get_base_date()), "%Y-%m-%d")
        end_dt = datetime.strptime(종료일, "%Y-%m-%d") if 종료일 else start_dt
    except ValueError:
        await interaction.response.send_message("❌ 날짜 형식이 올바르지 않습니다! **YYYY-MM-DD** (예: 2026-01-22) 형식으로 적어주세요.", ephemeral=True)
        return

    if start_dt > end_dt:
        await interaction.response.send_message("❌ 종료일이 시작일보다 빠를 수 없습니다!", ephemeral=True)
        return

    days = (end_dt - start_dt).days + 1
    if days > 30:
        await interaction.response.send_message("❌ 면책 기간은 최대 30일까지만 요청할 수 있어요.", ephemeral=True)
        return

    date_list = [day_str(start_dt + timedelta(days=i)) for i in range(days)]
    if days == 1:
        await start_immunity_vote(interaction, date_list, "🛡️ 면책 요청합니다!", discord.Color.orange(), ("📅 날짜", date_list[0]), 사유)
    else:
        period_str = f"{date_list[0]} ~ {date_list[-1]} (**총 {days}일**)"
        await start_immunity_vote(interaction, date_list, "🛡️ 장기 면책 요청합니다!", discord.Color.purple(), ("📅 기간", period_str), 사유)

#휴식 (월 1회)
@bot.tree.command(name="휴식", description="한 달에 한 번, 오늘을 휴식일로 지정합니다. (벌금 면제)")
@app_commands.describe(동작="사용하기(기본) / 오늘 쓴 휴식권 취소하기")
@app_commands.choices(동작=[
    app_commands.Choice(name="사용하기", value="use"),
    app_commands.Choice(name="취소하기 (오늘 쓴 휴식권 되돌리기)", value="cancel"),
])
async def take_rest(interaction: discord.Interaction, 동작: app_commands.Choice[str] = None):
    user_id = str(interaction.user.id)
    target_date = core.get_base_date()  # 새벽 0~4시는 전날
    target_date_str = day_str(target_date)

    if 동작 and 동작.value == "cancel":
        if not await store.cancel_rest(user_id, target_date_str):
            await interaction.response.send_message(f"❓ **{target_date_str}** 날짜로 사용된 휴식권이 없는데요?", ephemeral=True)
            return
        await interaction.response.send_message(f"↩️ **{target_date_str}** 날짜의 휴식 사용을 취소했습니다! 다시 횟수가 복구되었어요.", ephemeral=True)
        return

    # 사용 (이번 달에 쓴 적 있으면 거절. 앱에서 쓴 휴식도 포함)
    if core.count_in_month(store.view(user_id).get('rest_history', []), target_date) > 0 \
            or not await store.add_rest(user_id, target_date_str):
        await interaction.response.send_message("❌ **이번 달 휴식권을 이미 사용하셨어요!** (월 1회 제한)", ephemeral=True)
        return

    note = "(새벽🌙)" if core.is_dawn() else ""
    embed = discord.Embed(title="🛌 휴식권 사용!", description=f"**{target_date_str}** {note}\n오늘은 푹 쉬세요! 벌금이 부과되지 않습니다.", color=discord.Color.purple())
    embed.set_footer(text="⚠️ 월 1회만 가능하니 신중하게 사용하세요! (잘못 썼다면 /휴식 동작:취소하기)")
    await interaction.response.send_message(embed=embed)

#현황
@bot.tree.command(name="현황", description="이번 달 멤버들의 휴식 및 면책 사용 내역을 확인합니다.")
@app_commands.guild_only()
async def check_monthly_status(interaction: discord.Interaction):
    now = core.get_base_date()
    this_month_str = now.strftime('%Y-%m')

    def fmt_dates(dates):
        return ", ".join(f"**{d[8:]}일**" for d in dates) if dates else "없음"

    fields = []
    for member in (m for m in interaction.guild.members if not m.bot):
        data = store.view(member.id)
        month_rests = sorted(d for d in data.get('rest_history', []) if d.startswith(this_month_str))
        pure_immunity = sorted(d for d in data.get('exemptions', []) if d.startswith(this_month_str) and d not in month_rests)
        if not month_rests and not pure_immunity:
            continue
        rest_txt = f"🛌 **휴식({len(month_rests)}회):** {fmt_dates(month_rests)}"
        imm_txt = f"🛡️ **면책({len(pure_immunity)}회):** {fmt_dates(pure_immunity)}"
        fields.append((f"👤 {member.display_name}", f"{rest_txt}\n{imm_txt}", False))

    description = "이번 달 휴식 및 면책 사용 기록입니다." if fields else "✨ 이번 달은 아직 휴식이나 면책을 쓴 사람이 없네요! 성실해요! 🔥"
    embeds = build_embeds(
        title=f"📊 {now.month}월 현황판",
        color=discord.Color.blurple(),
        description=description,
        fields=fields,
        footer=f"기준: {now.strftime('%Y년 %m월')}",
    )
    await respond_embeds(interaction, embeds)

#인증 처리
async def process_verification(interaction: discord.Interaction, 계획: str, 내용: str, 사진: discord.Attachment, is_yesterday: bool):
    # content_type이 비어 있는(None) 첨부 파일도 있어서 안전하게 확인
    if 사진 and not (사진.content_type or "").startswith("image/"):
        await interaction.response.send_message("❌ 사진 파일만 올릴 수 있어요!", ephemeral=True)
        return

    target_date = core.resolve_target_date("yesterday" if is_yesterday else "today")
    display_note = "(어제 늦은 인증😅)" if is_yesterday else ("(새벽🌙)" if core.is_dawn() else "")
    target_date_str = day_str(target_date)

    user_id = str(interaction.user.id)
    category, plan = Store.find_plan(store.view(user_id), 계획)

    # 1. 인증 전에 확인 (조건이 안 맞으면 아무것도 저장하지 않음)
    if not plan:
        await interaction.response.send_message("❌ 해당 계획을 찾을 수 없어요! 목록에서 선택해주세요.", ephemeral=True)
        return

    if target_date_str < plan.get('created_at', '2000-01-01'):
        await interaction.response.send_message(f"❌ **'{plan['content']}'**은(는) {plan['created_at']}에 등록한 계획이라 그 전 날짜는 인증할 수 없어요.", ephemeral=True)
        return

    if category == "Routine":
        target_weekday = WEEKDAY_NAMES[target_date.weekday()]
        if plan.get('days') and target_weekday not in plan['days']:
            await interaction.response.send_message(f"❌ **'{plan['content']}'**은(는) **{target_weekday}요일**에 하는 날이 아닙니다!", ephemeral=True)
            return

    if plan.get('photo') and not 사진:
        await interaction.response.send_message(f"📸 **'{plan['content']}'**은(는) 사진 인증이 필요한 계획이에요! `사진` 칸에 인증샷을 첨부해주세요.", ephemeral=True)
        return

    # 2. 인증 기록 (Firestore). 목표 계획은 같은 요청에서 달성 처리
    check_in_id = await store.add_check_in(plan, target_date_str, user_id)
    view = store.view(user_id)

    extra_fields = []
    if category == "OneTime":
        verified_plan_name = f"🏆 [목표달성] {plan['content']}"
        extra_fields.append(("🎉 목표 달성!", "달성한 목표는 계획 목록에서 자동으로 정리했어요.", False))
    elif category == "Limit":
        _, fresh = Store.find_plan(view, plan['id'])
        count, limit, period_kr = core.limit_status(fresh or plan, target_date)
        verified_plan_name = f"[제한] {plan['content']} ({period_kr} {count}/{limit}회)"
        if count > limit:
            extra_fields.append(("🚨 제한 초과!", f"{period_kr} {limit}회 제한을 넘었어요. 정산 때 **{FINE_AMOUNT:,}원** 벌금이에요!", False))
        elif count == limit:
            extra_fields.append(("⚠️ 한도 도달", f"{period_kr} {limit}회를 다 썼어요. 한 번 더 하면 벌금이에요!", False))
    else:
        verified_plan_name = f"[{CATEGORY_KR[category]}] {plan['content']}"

    # 3. 현재 진행 상황
    plan_text_list = []
    for cat, p in core.iter_plans(view):
        mark, text = core.plan_progress_line(view, cat, p, target_date)
        content_display = f"**{p['content']}**" if p['id'] == plan['id'] else p['content']
        plan_text_list.append(f"{mark} {text} {content_display}")

    fields = [
        ("방금 인증함", verified_plan_name, False),
        ("인증 기준일", f"{target_date_str} {display_note}", False),
    ]
    fields.extend(extra_fields)
    if 내용: fields.append(("코멘트", 내용, False))
    fields.append(("📅 현재 진행 상황", "\n".join(plan_text_list) if plan_text_list else "계획 없음", False))

    embeds = build_embeds(
        title="🔥 인증 현황",
        color=discord.Color.green(),
        fields=fields,
        image_url=사진.url if 사진 else None,
    )
    await respond_embeds(interaction, embeds)

    # 4. 인증 메시지 링크 저장 → 앱에서 눌러서 사진 검수
    try:
        message = await interaction.original_response()
        await store.set_check_in_message(check_in_id, message.jump_url)
    except Exception:
        traceback.print_exc()

#계획 인증
@bot.tree.command(name="인증", description="한 내용을 인증하세요 (깜빡한 어제 인증은 날짜: 어제)")
@app_commands.describe(계획="인증할 계획 선택", 내용="코멘트 (선택)", 사진="인증샷 (선택)", 날짜="오늘(기본) / 어제")
@app_commands.choices(날짜=DATE_CHOICES)
@app_commands.autocomplete(계획=plan_autocomplete)
async def verify_study(interaction: discord.Interaction, 계획: str, 내용: LongText = None, 사진: discord.Attachment = None,
                       날짜: app_commands.Choice[str] = None):
    is_yesterday = bool(날짜 and 날짜.value == "yesterday")
    await process_verification(interaction, 계획, 내용, 사진, is_yesterday=is_yesterday)

#계획표
CATEGORY_TITLES = {
    "Daily": "🌞 매일 (Daily)",
    "Routine": "🔄 요일 (Routine)",
    "Weekly": "📅 주간 (Weekly)",
    "Monthly": "🗓️ 월간 (Monthly)",
    "Interval": "🔁 반복 (Interval)",
    "OneTime": "🎯 목표 (One-Time)",
    "Limit": "🚫 제한 (Limit)"
}

@bot.tree.command(name="계획표", description="나의 계획과 달성 현황을 확인합니다.")
async def check_my_plans(interaction: discord.Interaction):
    view = store.view(interaction.user.id)
    display_date = core.get_base_date()
    note_date = "(새벽🌙)" if core.is_dawn() else ""

    fields = []
    for category in PLAN_CATEGORIES:
        lines = [core.plan_status_line(view, category, plan, display_date) for _, plan in core.iter_plans(view, categories=[category])]
        if lines:
            fields.append((CATEGORY_TITLES[category], "\n".join(lines), False))

    if not fields:
        await interaction.response.send_message("📭 등록된 계획이 없어요! `/계획 등록` 명령어로 추가해보세요.", ephemeral=True)
        return

    rest_cnt = core.count_in_month(view.get('rest_history', []), display_date)
    exempt_cnt = core.count_in_month(view.get('exemptions', []), display_date)

    embeds = build_embeds(
        title=f"📋 {interaction.user.display_name}님의 계획표",
        color=discord.Color.blue(),
        fields=fields,
        footer=f"기준: {day_str(display_date)} {note_date} | 이번 달 휴식: {rest_cnt}회 / 면책: {exempt_cnt}회",
    )
    await respond_embeds(interaction, embeds)

#인증취소 (계획 하나의 기록 한 번만 되돌리기)
def find_cancelable(view, value, date_str):
    """그 날짜에 기록이 있는 계획(활성 계획 또는 그날 달성한 목표). 값은 계획 ID 또는 이름"""
    candidates = [p for _, p in core.iter_plans(view) if date_str in p.get('history', [])]
    candidates += [g for g in view.get('completed_goals', []) if g.get('completed_at') == date_str]
    for match in (lambda p: p['id'] == value, lambda p: p['content'] == value):
        for plan in candidates:
            if match(plan):
                return plan
    return None

async def cancel_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    view = store.view(interaction.user.id)
    date_str = day_str(core.resolve_target_date(getattr(interaction.namespace, "날짜", None)))

    names = []
    for category, plan in core.iter_plans(view):
        n = plan.get('history', []).count(date_str)
        if n:
            names.append((f"[{CATEGORY_KR[category]}] {plan['content']}" + (f" ({n}회 기록)" if category == "Limit" else ""), plan['id']))
    for goal in view.get('completed_goals', []):
        if goal.get('completed_at') == date_str:
            names.append((f"[목표달성] {goal['content']}", goal['id']))

    return [app_commands.Choice(name=fit_choice(n), value=v) for n, v in names if current.lower() in n.lower()][:25]

@bot.tree.command(name="인증취소", description="잘못 누른 인증을 한 번 되돌립니다 (제한 계획은 기록 1회만 취소)")
@app_commands.describe(계획="취소할 계획 선택", 날짜="오늘(기본) / 어제")
@app_commands.choices(날짜=DATE_CHOICES)
@app_commands.autocomplete(계획=cancel_autocomplete)
async def cancel_verification(interaction: discord.Interaction, 계획: str, 날짜: app_commands.Choice[str] = None):
    user_id = str(interaction.user.id)
    date_str = day_str(core.resolve_target_date(날짜.value if 날짜 else None))

    plan = find_cancelable(store.view(user_id), 계획, date_str)
    if not plan or not await store.cancel_check_in(plan, date_str):
        await interaction.response.send_message(f"❓ **{date_str}** 날짜에 **'{계획}'** 인증 기록이 없어요.", ephemeral=True)
        return

    msg = f"↩️ **{date_str}** **'{plan['content']}'** 인증을 한 번 취소했어요."
    if plan.get('completed'):
        msg += " 목표를 다시 계획 목록에 넣었어요."
    _, fresh = Store.find_plan(store.view(user_id), plan['id'])
    remaining = (fresh or {}).get('history', []).count(date_str)
    if remaining:
        msg += f" (이 날짜에 아직 {remaining}회 기록이 남아 있어요)"
    await interaction.response.send_message(msg, ephemeral=True)

#알림 시간 설정
@bot.tree.command(name="알림시간", description="인증 검사 알림 시간 설정")
@app_commands.describe(시간="0~23시")
async def set_alert_time(interaction: discord.Interaction, 시간: app_commands.Range[int, 0, 23]):
    await store.set_alert_hour(interaction.user.id, 시간)

    msg = f"⏰ 알림 설정 완료! 매일 **{시간}시**에 인증 여부를 검사할게요! 👀"
    if 시간 < core.DAY_START_HOUR:
        msg += f"\n💡 **참고:** 새벽(0~{core.DAY_START_HOUR - 1}시)은 **'어제 날짜'**의 기록을 검사합니다. (밤샘러를 위한 배려!)"
    await interaction.response.send_message(msg, ephemeral=True)

#Planer 앱 계정 연동
LINK_CODE_PATTERN = re.compile(r"^[A-HJ-NP-Z2-9]{8}$")   # 앱이 만드는 8자리 코드 (헷갈리는 I, O, 0, 1 제외)
LINK_FAIL_LIMIT = 5                                      # 10분에 틀린 코드 5번까지
link_failures = {}

def link_blocked(user_id):
    now = core.get_now().timestamp()
    recent = [t for t in link_failures.get(user_id, []) if now - t < 600]
    link_failures[user_id] = recent
    return len(recent) >= LINK_FAIL_LIMIT

@bot.tree.command(name="연동", description="Planer 앱과 연동합니다. 앱 설정에서 받은 코드를 입력하세요.")
@app_commands.describe(코드="앱 설정 → 디스코드 연동에서 받은 8자리 코드 (비우면 연동 상태 확인)",
                       동작="연결하기(기본) / 연동 해제")
@app_commands.choices(동작=[
    app_commands.Choice(name="연결하기", value="link"),
    app_commands.Choice(name="연동 해제", value="unlink"),
])
@app_commands.guild_only()
async def link_app(interaction: discord.Interaction, 코드: str = None, 동작: app_commands.Choice[str] = None):
    user_id = interaction.user.id

    if 동작 and 동작.value == "unlink":
        if await store.unlink_account(user_id):
            await interaction.response.send_message("🔌 Planer 앱 연동을 해제했어요. 앱에서는 더 이상 인증·멤버 정보가 보이지 않아요.", ephemeral=True)
        else:
            await interaction.response.send_message("❓ 연동된 Planer 앱 계정이 없어요.", ephemeral=True)
        return

    if not 코드:
        linked = bool((store.data["members"].get(str(user_id)) or {}).get("uid"))
        msg = ("✅ Planer 앱과 연동되어 있어요. 해제하려면 `/연동 동작:연동 해제`" if linked else
               "🔗 아직 연동 전이에요. Planer 앱 → ⚙ 설정 → **디스코드 연동**에서 코드를 받아 `/연동 코드:XXXXXXXX`로 입력하세요.")
        await interaction.response.send_message(msg, ephemeral=True)
        return

    if link_blocked(user_id):
        await interaction.response.send_message("⏳ 코드를 너무 많이 틀렸어요. 10분 뒤에 다시 시도해주세요.", ephemeral=True)
        return

    code = 코드.strip().upper().replace("-", "").replace(" ", "")
    result = "invalid"
    if LINK_CODE_PATTERN.match(code):
        result, _ = await store.link_account(user_id, code)

    if result == "linked":
        link_failures.pop(user_id, None)
        await interaction.response.send_message(
            f"🎉 Planer 앱과 연동됐어요! 앱에서 **{interaction.guild.name}** 멤버들의 진행 상황을 볼 수 있고, 앱에서도 인증할 수 있어요.\n"
            "(사진이 필요한 계획은 지금처럼 디스코드에서 인증해주세요)", ephemeral=True)
        return

    link_failures.setdefault(user_id, []).append(core.get_now().timestamp())
    msg = ("⌛ 만든 지 10분이 지난 코드예요. 앱에서 새 코드를 받아주세요." if result == "expired"
           else "❌ 코드를 찾을 수 없어요. 앱에 보이는 8자리 코드를 그대로 입력했는지 확인해주세요.")
    await interaction.response.send_message(msg, ephemeral=True)

#자동 백업 (하루 한 번, backups/날짜/ 폴더에 Firestore 공용 데이터 저장)
BACKUP_DIR = BASE_DIR / "backups"
BACKUP_KEEP_DAYS = 14  # 최근 14일치만 보관

def _write_backup(date_str, exported):
    folder = BACKUP_DIR / date_str
    folder.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(folder / "firestore.json", json.dumps(exported, indent=2, ensure_ascii=False))

    # 오래된 백업 삭제 (날짜 이름 폴더만 대상)
    dated = sorted(p for p in BACKUP_DIR.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name))
    for old in dated[:-BACKUP_KEEP_DAYS]:
        shutil.rmtree(old)

async def run_daily_backup(now):
    today_str = day_str(now)
    if bot_state.get("last_backup_date") == today_str:
        return
    exported = await store.export_all()
    await asyncio.get_running_loop().run_in_executor(None, _write_backup, today_str, exported)
    bot_state["last_backup_date"] = today_str
    await save_state()
    print(f"💾 데이터 백업 완료: backups/{today_str}/")

#감시자
@tasks.loop(minutes=60)
async def hourly_check():
    # 각 단계를 따로 감싸서, 한 곳에서 오류가 나도 반복 작업 자체는 멈추지 않게 함
    try:
        restarted = store.ensure_watching()
        if restarted:
            print(f"🔁 Firestore 실시간 연결 재시작: {', '.join(restarted)}")
    except Exception:
        traceback.print_exc()

    now = core.get_now()
    print(f"⏰ 점검 중... {now.month}/{now.day} {now.hour}시 (인증기준: {day_str(core.get_base_date(now))})")

    channel = bot.get_channel(ALERT_CHANNEL)
    if not channel:
        print("⚠️ 경고: ALERT_CHANNEL을 찾을 수 없어 정산/알림을 건너뜁니다. .env의 ID를 확인해주세요.")
        return

    for name, step in (("벌금 정산", run_daily_settlement), ("인증 알림 전송", send_hourly_alerts)):
        try:
            await step(channel, now)
        except Exception:
            print(f"🚨 {name} 중 오류:")
            traceback.print_exc()

    try:
        await run_daily_backup(now)
    except Exception:
        print("🚨 데이터 백업 중 오류:")
        traceback.print_exc()

    try:
        removed = await store.cleanup_link_codes()
        if removed:
            print(f"🧹 쓰지 않은 연동 코드 {removed}개 정리")
    except Exception:
        traceback.print_exc()

async def run_daily_settlement(channel, now):
    """하루 한 번, SETTLEMENT_HOUR시 이후 처음 도는 시점에 어제 기록을 정산"""
    today_str = day_str(now)
    if now.hour < SETTLEMENT_HOUR or bot_state.get("last_settlement_date") == today_str:
        return

    yesterday_str = day_str(now - timedelta(days=1))
    is_monday, is_first_day = now.weekday() == 0, now.day == 1

    fine_msg_list = []
    for user_id, view in list(store.all_views().items()):
        try:
            fined, kind, details = core.settle_user(view, now)
        except Exception:
            # 한 사람 데이터가 이상해도 나머지 사람 정산은 계속 진행
            print(f"🚨 정산 중 오류 (유저 {user_id}), 이 유저는 건너뜁니다:")
            traceback.print_exc()
            continue

        if fined:
            # 벌금 내역 ID를 날짜·사람으로 고정 → 정산이 두 번 돌아도 한 번만 매겨짐
            await store.add_fine(user_id, FINE_AMOUNT, ", ".join(details)[:500], yesterday_str, "settlement",
                                 event_id=f"settle_{yesterday_str}_{user_id}")
            fine_msg_list.append(f"💸 <@{user_id}>님 **{FINE_AMOUNT}원** 벌금! ({', '.join(details)})")
        elif kind == 'rest':
            fine_msg_list.append(f"🛌 <@{user_id}>님 **휴식권 사용!** (푹 쉬셨나요? 🍯)")
        elif kind == 'exempt':
            fine_msg_list.append(f"🛡️ <@{user_id}>님 면책 통과! ({', '.join(details)})")

    bot_state["last_settlement_date"] = today_str
    await save_state()
    print(f"💸 {yesterday_str} 정산 완료 ({len(fine_msg_list)}건)")

    if not fine_msg_list:
        return

    rank_lines = []
    for uid, view in sorted(store.all_views().items(), key=lambda kv: kv[1].get('fines', 0), reverse=True):
        fine = view.get('fines', 0)
        if fine > 0:
            rank = len(rank_lines) + 1
            icon = ["🥇", "🥈", "🥉"][rank-1] if rank <= 3 else f"{rank}."
            rank_lines.append(f"{icon} <@{uid}>: **{fine:,}원**")

    title_txt = f"💸 {yesterday_str} 정산"
    if is_monday: title_txt += " (주간결산 포함)"
    if is_first_day: title_txt += " (월간결산 포함)"

    fields = [("🧾 정산 결과", "\n".join(fine_msg_list), False)]
    if rank_lines: fields.append(("🏆 명예의 전당", "\n".join(rank_lines), False))

    embeds = build_embeds(
        title=title_txt,
        color=discord.Color.red(),
        description="**돈** 내기 싫으면 **까**먹지 말고 **스**스로 해라",
        fields=fields,
    )
    await send_embeds(channel, embeds)

async def send_hourly_alerts(channel, now):
    """각자 설정한 알림 시간(기본 2시)에 아직 인증 안 한 계획을 알려줌"""
    alert_date = core.get_base_date(now)  # 새벽 0~4시는 전날 기록을 검사
    alert_date_str = day_str(alert_date)

    for user_id, view in list(store.all_views().items()):
        if view.get('alert_time', 2) != now.hour:
            continue
        # 휴식/면책 날에는 알림 안 보냄
        if alert_date_str in view.get('exemptions', []) or alert_date_str in view.get('rest_history', []):
            continue
        try:
            todo = core.find_todo_plans(view, alert_date)
        except Exception:
            print(f"🚨 알림 확인 중 오류 (유저 {user_id}), 이 유저는 건너뜁니다:")
            traceback.print_exc()
            continue
        if not any(todo.values()):
            continue

        msg = f"🔔 <@{user_id}>님! 인증할 시간이에요!\n"
        for category in PLAN_CATEGORIES:
            if todo[category]:
                msg += f"- **[{CATEGORY_KR[category]}]** {', '.join(todo[category])}\n"
        await send_long_message(channel, msg)

#정각 대기
@hourly_check.before_loop
async def before_hourly_check():
    await bot.wait_until_ready()
    now = core.get_now()
    future = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    seconds_until_next_hour = (future - now).total_seconds()
    print(f"⏳ 다음 정각({future.hour}시)까지 {int(seconds_until_next_hour)}초 대기합니다...")
    await asyncio.sleep(seconds_until_next_hour)

#벌금 수정 (관리자, 3,000원씩 더하거나 빼기)
@bot.tree.command(name="벌금수정", description=f"[관리자] 특정 유저의 벌금을 {FINE_AMOUNT:,}원 더하거나 뺍니다.")
@app_commands.describe(유저="대상 유저", 동작=f"+{FINE_AMOUNT:,}원 / -{FINE_AMOUNT:,}원", 사유="수정 사유 (선택)")
@app_commands.choices(동작=[
    app_commands.Choice(name=f"+ {FINE_AMOUNT:,}원 (벌금 추가)", value=1),
    app_commands.Choice(name=f"- {FINE_AMOUNT:,}원 (벌금 차감, 예: 납부)", value=-1),
])
@app_commands.checks.has_permissions(administrator=True)
async def adjust_fine(interaction: discord.Interaction, 유저: discord.Member, 동작: app_commands.Choice[int], 사유: LongText = "관리자 수정"):
    await store.ensure_member(유저.id, 유저.display_name)
    old_fine = store.view(유저.id).get('fines', 0)

    if 동작.value < 0 and old_fine <= 0:
        await interaction.response.send_message(f"❌ **{유저.display_name}**님은 남은 벌금이 없어요.", ephemeral=True)
        return

    # 0원 아래로는 내려가지 않음
    amount = FINE_AMOUNT if 동작.value > 0 else -min(FINE_AMOUNT, old_fine)
    await store.add_fine(유저.id, amount, 사유, day_str(core.get_base_date()), "admin")
    new_fine = old_fine + amount

    embed = discord.Embed(title="🔧 벌금 조정 완료", color=discord.Color.gold())
    embed.add_field(name="대상", value=유저.mention, inline=True)
    embed.add_field(name="변경 전", value=f"{old_fine:,}원", inline=True)
    embed.add_field(name="변경 후", value=f"**{new_fine:,}원**", inline=True)
    embed.add_field(name="사유", value=사유, inline=False)
    await interaction.response.send_message(embed=embed)

#명령어 오류 공통 처리 (권한 없음, DM 사용, 예상 못 한 오류)
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ 관리자만 사용할 수 있는 명령어입니다!"
    elif isinstance(error, app_commands.NoPrivateMessage):
        msg = "❌ 이 명령어는 서버 채널에서만 사용할 수 있어요!"
    elif isinstance(error, app_commands.CheckFailure):
        msg = "❌ 이 명령어를 사용할 수 없어요."
    else:
        cmd_name = interaction.command.name if interaction.command else "알 수 없음"
        print(f"🚨 /{cmd_name} 명령어 실행 중 오류:")
        traceback.print_exception(type(error), error, error.__traceback__)
        msg = "⚠️ 명령어 처리 중 오류가 발생했어요. 잠시 후 다시 시도해주세요."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except discord.HTTPException:
        pass

#칭찬
@bot.tree.command(name="칭찬", description="무작위 칭찬 멘트로 자존감을 채워줍니다!")
async def praise_me(interaction: discord.Interaction):
    messages = [
        "오늘도 정말 멋져요! 😎",
        "포기하지 않는 모습이 정말 아름답습니다! ✨",
        "당신은 할 수 있어요! 아자아자! 🔥",
        "오늘 공부도 파이팅입니다! 📚",
        "숨만 쉬어도 멋진 당신... 최고야! 👍",
        "어제보다 오늘 더 성장했군요! 🌱",
        "당신의 끈기에 박수를 보냅니다! 👏👏",
        "힘든 순간도 결국 지나갈 거예요. 힘내세요! 🌈",
        "당신은 생각보다 훨씬 더 대단한 사람입니다! 💎"
    ]
    await interaction.response.send_message(f"📢 **{interaction.user.display_name}**님, {random.choice(messages)}")

if __name__ == "__main__":
    bot.run(TOKEN)
