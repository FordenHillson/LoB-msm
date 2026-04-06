import random
import sys
import os
import json
import openpyxl
import discord
from discord import app_commands
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

load_dotenv()

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OWNER_ID = int(os.getenv("DISCORD_OWNER_ID", 0))

DATA_FILE = "user_data.json"
EXCEL_FILE = "Cube_Bonus Potential Cube (Weapon).xlsx"

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
                stat = row[1].replace(',', '')
                if opt not in first_poten:
                    first_poten[opt] = []
                if stat not in first_poten[opt]:
                    first_poten[opt].append(stat)
            
            if row[4] and row[5] and row[4] != 'Option':
                opt = row[4]
                stat = row[5].replace(',', '')
                if opt not in second_poten:
                    second_poten[opt] = []
                if stat not in second_poten[opt]:
                    second_poten[opt].append(stat)
        
        for opt in first_poten:
            first_poten[opt].sort(key=lambda x: float(x.rstrip('%')) if '%' in x else float(x), reverse=True)
        for opt in second_poten:
            second_poten[opt].sort(key=lambda x: float(x.rstrip('%')) if '%' in x else float(x), reverse=True)
        
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
    await tree.sync(guild=None)
    print(f'Logged in as {client.user}')

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
    
    roll1_type = random.choice(list(LEGENDARY_FIRST.keys()))
    roll1_stats = LEGENDARY_FIRST[roll1_type]
    roll1_value = random.choice(roll1_stats)
    roll1_max = roll1_stats[0]
    roll1_min = roll1_stats[-1]
    
    roll2_type = random.choice(list(LEGENDARY_SECOND.keys()))
    roll2_stats = LEGENDARY_SECOND[roll2_type]
    roll2_value = random.choice(roll2_stats)
    roll2_max = roll2_stats[0]
    roll2_min = roll2_stats[-1]
    
    roll3_type = random.choice(list(LEGENDARY_SECOND.keys()))
    roll3_stats = LEGENDARY_SECOND[roll3_type]
    roll3_value = random.choice(roll3_stats)
    roll3_max = roll3_stats[0]
    roll3_min = roll3_stats[-1]
    
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

keep_alive()
client.run(BOT_TOKEN)
