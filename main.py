import random
import sys
import os
import json
import discord
from discord import app_commands
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

load_dotenv()

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OWNER_ID = int(os.getenv("DISCORD_OWNER_ID", 0))

DATA_FILE = "user_data.json"

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

async def send_luck(interaction: discord.Interaction, good_chance: int, bad_chance: int, title: str, show_strikes: int | None = -1, image_url: str | None = None):
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
    if image_url and is_good:
        embed.set_image(url=image_url)
    await interaction.response.send_message(embed=embed)

@client.event
async def on_ready():
    await tree.sync(guild=None)
    print(f'Logged in as {client.user}')

@tree.command(name="luck-anc", description="Check your luck on Crafting Ancient (base 30%)")
async def luck_anc_command(interaction: discord.Interaction, bonus: int = 0):
    base_good = 30
    good_chance = min(base_good + bonus, 100)
    bad_chance = 100 - good_chance
    await send_luck(interaction, good_chance=good_chance, bad_chance=bad_chance, title=f"Ancient Craft (Base: {base_good}% + Bonus: {bonus}%)", show_strikes=None, image_url="https://kommodo.ai/i/GzxkY1OwFfX6ZXQv5sCu")

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
