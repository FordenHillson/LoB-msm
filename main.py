import asyncio
import random
import sys
import os
import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import openpyxl
import discord
from discord import app_commands
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

load_dotenv()

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OWNER_ID = int(os.getenv("DISCORD_OWNER_ID", 0))
PATCH_NOTES_CHANNEL_ID = int(os.getenv("PATCH_NOTES_CHANNEL_ID", "1459937589812531354"))

DATA_FILE = "user_data.json"
SEEN_PATCH_NOTES_FILE = "seen_patch_notes.json"
EXCEL_FILE = "Cube_Bonus Potential Cube (Weapon).xlsx"

PATCH_NOTES_ALIAS = "MapleStoryMGlobal-th"
PATCH_NOTES_BOARD_ID = "2777"
PATCH_NOTES_POLL_SECONDS = int(os.getenv("PATCH_NOTES_POLL_SECONDS", "900"))
PATCH_NOTES_API_URL = (
    f"https://forum.nexon.com/api/v1/board/{PATCH_NOTES_BOARD_ID}/threads?"
    + urlencode({
        "alias": PATCH_NOTES_ALIAS,
        "paginationType": "PAGING",
        "pageNo": 1,
        "pageSize": 15,
        "blockSize": 5,
    })
)
PATCH_NOTES_VIEW_BASE = (
    f"https://forum.nexon.com/{PATCH_NOTES_ALIAS}/board_view"
    f"?board={PATCH_NOTES_BOARD_ID}&thread="
)

def parse_stat(stat_str):
    stat_str = stat_str.replace(',', '')
    is_percent = '%' in stat_str
    value = float(stat_str.rstrip('%'))
    return value, is_percent

def load_legendary_potential():
    try:
        wb = openpyxl.load_workbook(EXCEL_FILE)
        ws = wb['poten_wep']
        rows = list(ws.iter_rows(min_row=391, max_row=530, values_only=True))
        
        first_poten = {}
        second_poten = {}
        
        for row in rows:
            if row[0] and row[1] and row[0] != 'Option':
                opt = row[0]
                stat_str = row[1].replace(',', '')
                value, is_percent = parse_stat(stat_str)
                if opt not in first_poten:
                    first_poten[opt] = {'flat': [], 'percent': []}
                key = 'percent' if is_percent else 'flat'
                if stat_str not in first_poten[opt][key]:
                    first_poten[opt][key].append(stat_str)
            
            if row[4] and row[5] and row[4] != 'Option':
                opt = row[4]
                stat_str = row[5].replace(',', '')
                value, is_percent = parse_stat(stat_str)
                if opt not in second_poten:
                    second_poten[opt] = {'flat': [], 'percent': []}
                key = 'percent' if is_percent else 'flat'
                if stat_str not in second_poten[opt][key]:
                    second_poten[opt][key].append(stat_str)
        
        for opt in first_poten:
            for key in ['flat', 'percent']:
                first_poten[opt][key].sort(key=lambda x: parse_stat(x)[0], reverse=True)
        for opt in second_poten:
            for key in ['flat', 'percent']:
                second_poten[opt][key].sort(key=lambda x: parse_stat(x)[0], reverse=True)
        
        return first_poten, second_poten
    except Exception as e:
        print(f"Error loading Excel: {e}")
        return {}, {}

LEGENDARY_FIRST, LEGENDARY_SECOND = load_legendary_potential()

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

def load_seen_patch_notes():
    if os.path.exists(SEEN_PATCH_NOTES_FILE):
        with open(SEEN_PATCH_NOTES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "seen_ids" in data:
                return set(str(x) for x in data["seen_ids"])
            if isinstance(data, list):
                return set(str(x) for x in data)
    return None

def save_seen_patch_notes(seen_ids):
    with open(SEEN_PATCH_NOTES_FILE, "w", encoding="utf-8") as f:
        json.dump({"seen_ids": sorted(seen_ids)}, f, ensure_ascii=False, indent=2)

def fetch_patch_note_threads():
    req = Request(
        PATCH_NOTES_API_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": f"https://forum.nexon.com/{PATCH_NOTES_ALIAS}/board_list?board={PATCH_NOTES_BOARD_ID}",
        },
    )
    with urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    threads = []
    for item in payload.get("threads", []):
        thread_id = str(item.get("threadId", "")).strip()
        title = (item.get("title") or "").strip()
        if not thread_id or not title:
            continue
        create_date = item.get("createDate")
        threads.append({
            "id": thread_id,
            "title": title,
            "create_date": create_date,
            "url": f"{PATCH_NOTES_VIEW_BASE}{thread_id}",
        })
    return threads

def format_patch_note_date(create_date):
    if create_date is None:
        return None
    try:
        return datetime.fromtimestamp(int(create_date), tz=timezone.utc).strftime("%Y.%m.%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return None

async def announce_patch_note(channel, note):
    date_str = format_patch_note_date(note.get("create_date"))
    description = f"**[{note['title']}]({note['url']})**"
    if date_str:
        description += f"\nวันที่: {date_str}"
    embed = discord.Embed(
        title="Patch Note",
        description=description,
        color=discord.Color.blue(),
        url=note["url"],
    )
    await channel.send(content="Hey maple m have a new patch note !", embed=embed)

async def check_and_announce_patch_notes():
    try:
        threads = await asyncio.to_thread(fetch_patch_note_threads)
    except Exception as e:
        print(f"Patch notes fetch failed: {e}")
        return

    if not threads:
        print("Patch notes: no threads returned")
        return

    seen = load_seen_patch_notes()
    current_ids = {t["id"] for t in threads}

    # Cold start: remember current posts without announcing
    if seen is None:
        save_seen_patch_notes(current_ids)
        print(f"Patch notes: seeded {len(current_ids)} existing thread(s), no announce")
        return

    new_notes = [t for t in threads if t["id"] not in seen]
    new_notes.sort(key=lambda t: (t.get("create_date") is None, t.get("create_date") or 0, t["id"]))

    if not new_notes:
        return

    channel = client.get_channel(PATCH_NOTES_CHANNEL_ID)
    if channel is None:
        try:
            channel = await client.fetch_channel(PATCH_NOTES_CHANNEL_ID)
        except Exception as e:
            print(f"Patch notes: cannot access channel {PATCH_NOTES_CHANNEL_ID}: {e}")
            return

    for note in new_notes:
        try:
            await announce_patch_note(channel, note)
            seen.add(note["id"])
            save_seen_patch_notes(seen)
            print(f"Patch notes: announced thread {note['id']}")
        except Exception as e:
            print(f"Patch notes: failed to announce {note['id']}: {e}")
            break

async def patch_notes_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        await check_and_announce_patch_notes()
        await asyncio.sleep(PATCH_NOTES_POLL_SECONDS)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

def get_luck(good_chance: int):
    roll = random.randint(1, 100)
    is_good = roll <= good_chance
    return roll, is_good

async def send_luck(interaction: discord.Interaction, good_chance: int, bad_chance: int, title: str, show_strikes: int | None = -1, image_url: str | None = None, image_file: str | None = None):
    roll, is_good = get_luck(good_chance)
    if is_good:
        luck_type = "Good Luck"
        emoji = "🎉"
        color = discord.Color.green()
    else:
        luck_type = "Bad Luck"
        emoji = "😢"
        color = discord.Color.red()
    
    desc = f"{title}\nGood: {good_chance}% | Bad: {bad_chance}%\nRoll: **{roll}%**"
    if show_strikes is not None:
        desc += f"\nStrikes: {show_strikes}/7"
    
    embed = discord.Embed(
        title=f"{emoji} {luck_type}",
        description=desc,
        color=color
    )
    try:
        if image_url and is_good:
            embed.set_image(url=image_url)
        if image_file and is_good and os.path.exists(image_file):
            file = discord.File(image_file)
            embed.set_image(url=f"attachment://{os.path.basename(image_file)}")
            await interaction.response.send_message(embed=embed, file=file)
        else:
            await interaction.response.send_message(embed=embed)
    except discord.errors.NotFound:
        pass

@client.event
async def on_ready():
    print("----------------------------------------")
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print("----------------------------------------")
    await tree.sync(guild=None)
    
    if not hasattr(client, "patch_notes_task") or client.patch_notes_task.done():
        client.patch_notes_task = asyncio.create_task(patch_notes_loop())
        print(f"Patch notes poller started (every {PATCH_NOTES_POLL_SECONDS}s)")

async def check_and_announce_patch_notes():
    print("[Patch Notes] Checking for updates...") # เพิ่มเพื่อดูว่าลูปทำงานหรือไม่
    try:
        threads = await asyncio.to_thread(fetch_patch_note_threads)
    except Exception as e:
        print(f"Patch notes fetch failed: {e}")
        return

    if not threads:
        print("Patch notes: no threads returned")
        return

    seen = load_seen_patch_notes()
    current_ids = {t["id"] for t in threads}

    if seen is None:
        save_seen_patch_notes(current_ids)
        print(f"Patch notes: seeded {len(current_ids)} existing thread(s), no announce")
        return

    new_notes = [t for t in threads if t["id"] not in seen]
    new_notes.sort(key=lambda t: (t.get("create_date") is None, t.get("create_date") or 0, t["id"]))

    if not new_notes:
        print("[Patch Notes] No new patch notes found.")
        return

    channel = client.get_channel(PATCH_NOTES_CHANNEL_ID)
    if channel is None:
        try:
            channel = await client.fetch_channel(PATCH_NOTES_CHANNEL_ID)
        except Exception as e:
            print(f"Patch notes: cannot access channel {PATCH_NOTES_CHANNEL_ID}: {e}")
            return

    for note in new_notes:
        try:
            await announce_patch_note(channel, note)
            seen.add(note["id"])
            save_seen_patch_notes(seen)
            print(f"Patch notes: announced thread {note['id']}")
        except Exception as e:
            print(f"Patch notes: failed to announce {note['id']}: {e}")
            break

@tree.command(name="luck-anc", description="Check your luck on Crafting Ancient (base 30%)")
async def luck_anc_command(interaction: discord.Interaction, bonus: int = 0):
    base_good = 30
    good_chance = min(base_good + bonus, 100)
    bad_chance = 100 - good_chance
    await send_luck(interaction, good_chance=good_chance, bad_chance=bad_chance, title=f"Ancient Craft (Base: {base_good}% + Bonus: {bonus}%)", show_strikes=None, image_file="anc.png")

@tree.command(name="luck-necro", description="Check your luck on Necromancer (base 4%)")
async def luck_necro_command(interaction: discord.Interaction, bonus: int = 0):
    base_good = 4
    good_chance = min(base_good + bonus, 100)
    bad_chance = 100 - good_chance
    await send_luck(interaction, good_chance=good_chance, bad_chance=bad_chance, title=f"Necromancer (Base: {base_good}% + Bonus: {bonus}%)", show_strikes=None)

@tree.command(name="luck-abso", description="Check your luck on Absolab (base 12%)")
async def luck_abso_command(interaction: discord.Interaction, bonus: int = 0):
    base_good = 12
    good_chance = min(base_good + bonus, 100)
    bad_chance = 100 - good_chance
    await send_luck(interaction, good_chance=good_chance, bad_chance=bad_chance, title=f"Absolab (Base: {base_good}% + Bonus: {bonus}%)", show_strikes=None)

@tree.command(name="luck-exalt", description="Check your luck on Exaltation (base 50%)")
async def luck_exalt_command(interaction: discord.Interaction, bonus: int = 0):
    user_id = str(interaction.user.id)
    data = load_data()
    
    if user_id not in data:
        data[user_id] = {"exalt_strikes": 0}
    
    strikes = data[user_id].get("exalt_strikes", 0)
    
    if strikes >= 7:
        embed = discord.Embed(
            title="❌ Cannot Use /luck-exalt",
            description=f"You have {strikes}/7 strikes!\nUse `/fail-exalted-reduce` to reduce strikes.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
        return
    
    base_good = 50
    good_chance = min(base_good + bonus, 100)
    bad_chance = 100 - good_chance
    
    roll, is_good = get_luck(good_chance)
    
    if is_good:
        luck_type = "Good Luck"
        emoji = "🎉"
        color = discord.Color.green()
    else:
        luck_type = "Bad Luck"
        emoji = "😢"
        color = discord.Color.red()
        data[user_id]["exalt_strikes"] = strikes + 1
        strikes = strikes + 1
        save_data(data)
    
    desc = f"Exaltation (Base: {base_good}% + Bonus: {bonus}%)\nGood: {good_chance}% | Bad: {bad_chance}%\nRoll: **{roll}%**\nStrikes: {strikes}/7"
    
    embed = discord.Embed(
        title=f"{emoji} {luck_type}",
        description=desc,
        color=color
    )
    await interaction.response.send_message(embed=embed)

def roll_potential(poten_data):
    roll_type = random.choice(list(poten_data.keys()))
    type_data = poten_data[roll_type]
    available_keys = [k for k in ['flat', 'percent'] if type_data[k]]
    key = random.choice(available_keys)
    value = random.choice(type_data[key])
    max_val = type_data[key][0]
    min_val = type_data[key][-1]
    return roll_type, value, max_val, min_val

@tree.command(name="luck-poten-wep", description="Roll weapon potential from Legendary rank")
async def luck_poten_wep_command(interaction: discord.Interaction):
    if not LEGENDARY_FIRST:
        embed = discord.Embed(
            title="❌ Error",
            description="Could not load Legendary potential data.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
        return
    
    roll1_type, roll1_value, roll1_max, roll1_min = roll_potential(LEGENDARY_FIRST)
    roll2_type, roll2_value, roll2_max, roll2_min = roll_potential(LEGENDARY_SECOND)
    roll3_type, roll3_value, roll3_max, roll3_min = roll_potential(LEGENDARY_SECOND)
    
    embed = discord.Embed(
        title="🎲 Weapon Potential Roll (Legendary)",
        description=(
            f"**1. {roll1_type} {roll1_value}**\n"
            f"   Max High: `{roll1_max}` | Max Low: `{roll1_min}`\n\n"
            f"**2. {roll2_type} {roll2_value}**\n"
            f"   Max High: `{roll2_max}` | Max Low: `{roll2_min}`\n\n"
            f"**3. {roll3_type} {roll3_value}**\n"
            f"   Max High: `{roll3_max}` | Max Low: `{roll3_min}`"
        ),
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)

@tree.command(name="fail-exalted-reduce", description="Reduce Exaltation strikes (need good luck %)")
async def luck_reduc_exalt_command(interaction: discord.Interaction, amount: int):
    user_id = str(interaction.user.id)
    data = load_data()
    
    if user_id not in data:
        data[user_id] = {"exalt_strikes": 0}
    
    strikes = data[user_id].get("exalt_strikes", 0)
    
    if strikes == 0:
        embed = discord.Embed(
            title="ℹ️ No Strikes",
            description="You have 0/7 strikes. You can use /luck-exalt directly!",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)
        return
    
    roll, is_good = get_luck(amount)
    
    if is_good:
        data[user_id]["exalt_strikes"] = max(0, strikes - 1)
        new_strikes = data[user_id]["exalt_strikes"]
        save_data(data)
        
        embed = discord.Embed(
            title="✅ Fail Exalted Reduce !",
            description=f"Roll: {roll}% (needed ≤ {amount}%)\nStrikes: {new_strikes}/7",
            color=discord.Color.green()
        )
    else:
        embed = discord.Embed(
            title="❌ Failed to Reduce",
            description=f"Roll: {roll}% (needed ≤ {amount}%)\nExalt remain: {strikes}/7",
            color=discord.Color.red()
        )
    
    await interaction.response.send_message(embed=embed)

@tree.command(name="restart", description="Restart the bot (owner only)")
async def restart_command(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ You are not the bot owner!", ephemeral=True)
        return
    await interaction.response.send_message("🔄 Restarting bot...")
    await client.close()
    os.execv(sys.executable, [sys.executable] + [__file__])

app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

if __name__ == "__main__":
    keep_alive()
    client.run(BOT_TOKEN)
