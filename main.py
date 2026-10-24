import os
import threading
from flask import Flask
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import asyncio

# --- Web server ẩn để duy trì và phục vụ UptimeRobot ---
app = Flask('')

@app.route('/')
def home():
    return "Bot Music is running 24/7!"

def run_web():
    app.run(host='0.0.0.0', port=7860)

threading.Thread(target=run_web).start()

# --- Khởi tạo Discord Bot ---
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

ADMIN_ID = 1263023620523950091

blocked_users = set()
music_queues = {}
loop_status = {}
current_song = {}
volume_settings = {}
afk_tasks = {}

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

def check_not_blocked(interaction: discord.Interaction) -> bool:
    return interaction.user.id not in blocked_users

def play_next(guild, interaction):
    guild_id = guild.id
    voice_client = guild.voice_client
    if not voice_client:
        return

    if loop_status.get(guild_id, False) and guild_id in current_song:
        song = current_song[guild_id]
    else:
        if guild_id in music_queues and len(music_queues[guild_id]) > 0:
            song = music_queues[guild_id].pop(0)
            current_song[guild_id] = song
        else:
            current_song.pop(guild_id, None)
            return

    vol = volume_settings.get(guild_id, 1.0)
    source = discord.FFmpegPCMAudio(song['stream_url'], **FFMPEG_OPTIONS)
    transformed_source = discord.PCMVolumeTransformer(source, volume=vol)
    voice_client.play(transformed_source, after=lambda e: play_next(guild, interaction))

    asyncio.run_coroutine_threadsafe(
        interaction.channel.send(f"🎵 Đang phát: **{song['title']}**"),
        bot.loop
    )

@bot.event
async def on_ready():
    print(f"Bot đã đăng nhập thành công với tên: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Đã đồng bộ thành công {len(synced)} lệnh Slash (/).")
    except Exception as e:
        print(f"Lỗi khi đồng bộ Slash Commands: {e}")

@bot.tree.command(name="play", description="Phát video từ YouTube hoặc thêm vào danh sách phát")
@app_commands.describe(url="Link YouTube hoặc từ khóa tìm kiếm")
async def play(interaction: discord.Interaction, url: str):
    if not check_not_blocked(interaction):
        await interaction.response.send_message("❌ Bạn đã bị cấm sử dụng các lệnh của bot!", ephemeral=True)
        return
    if not interaction.user.voice:
        await interaction.response.send_message("❌ Bạn cần vào một kênh voice trước đã!", ephemeral=True)
        return

    await interaction.response.defer()
    voice_channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client

    if voice_client is None:
        voice_client = await voice_channel.connect()
    elif voice_client.channel != voice_channel:
        await voice_client.move_to(voice_channel)

    guild_id = interaction.guild.id
    if guild_id in afk_tasks:
        afk_tasks[guild_id].cancel()
        del afk_tasks[guild_id]

    try:
        data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
        if 'entries' in data:
            data = data['entries'][0]

        song_data = {
            'stream_url': data['url'],
            'webpage_url': data.get('webpage_url', url),
            'title': data.get('title', 'Video YouTube')
        }

        if voice_client.is_playing() or voice_client.is_paused():
            if guild_id not in music_queues:
                music_queues[guild_id] = []
            music_queues[guild_id].append(song_data)
            await interaction.followup.send(f"📋 Đã thêm vào danh sách phát sau: **{song_data['title']}**")
        else:
            current_song[guild_id] = song_data
            vol = volume_settings.get(guild_id, 1.0)
            source = discord.FFmpegPCMAudio(song_data['stream_url'], **FFMPEG_OPTIONS)
            transformed_source = discord.PCMVolumeTransformer(source, volume=vol)
            voice_client.play(transformed_source, after=lambda e: play_next(interaction.guild, interaction))
            await interaction.followup.send(f"🎵 Đang phát: **{song_data['title']}**")
    except Exception as e:
        await interaction.followup.send(f"❌ Không thể xử lý video này. Lỗi: `{e}`")

@bot.tree.command(name="stop", description="Dừng nhạc, xóa hàng chờ và ngắt kết nối voice")
async def stop(interaction: discord.Interaction):
    if not check_not_blocked(interaction):
        await interaction.response.send_message("❌ Bạn đã bị cấm sử dụng các lệnh của bot!", ephemeral=True)
        return
    guild_id = interaction.guild.id
    voice_client = interaction.guild.voice_client
    music_queues.pop(guild_id, None)
    current_song.pop(guild_id, None)
    loop_status.pop(guild_id, None)
    if guild_id in afk_tasks:
        afk_tasks[guild_id].cancel()
        del afk_tasks[guild_id]
    if voice_client:
        await voice_client.disconnect()
        await interaction.response.send_message("⏹️ Đã dừng phát nhạc, xóa danh sách chờ và rời kênh voice.")
    else:
        await interaction.response.send_message("❌ Bot hiện không ở trong kênh voice nào.")

@bot.tree.command(name="loop", description="Bật/Tắt chế độ lặp lại bài hát hiện tại")
async def loop(interaction: discord.Interaction):
    if not check_not_blocked(interaction):
        await interaction.response.send_message("❌ Bạn đã bị cấm sử dụng các lệnh của bot!", ephemeral=True)
        return
    guild_id = interaction.guild.id
    current_state = loop_status.get(guild_id, False)
    new_state = not current_state
    loop_status[guild_id] = new_state
    status_str = "🔂 **ĐÃ BẬT**" if new_state else "🔁 **ĐÃ TẮT**"
    await interaction.response.send_message(f"Chế độ lặp lại bài hát hiện tại: {status_str}")

@bot.tree.command(name="listvideo", description="Xem danh sách phát nhạc tiếp theo")
async def listvideo(interaction: discord.Interaction):
    if not check_not_blocked(interaction):
        await interaction.response.send_message("❌ Bạn đã bị cấm sử dụng các lệnh của bot!", ephemeral=True)
        return
    guild_id = interaction.guild.id
    queue = music_queues.get(guild_id, [])
    msg = "🎶 **DANH SÁCH PHÁT TIẾP THEO** 🎶\n"
    if guild_id in current_song:
        msg += f"👉 **Đang phát:** {current_song[guild_id]['title']}\n\n"
    if not queue:
        msg += "*(Danh sách phát tiếp theo đang trống)*"
    else:
        for idx, item in enumerate(queue, 1):
            msg += f"**{idx}.** {item['title']}\n"
    await interaction.response.send_message(msg)

@bot.tree.command(name="delvideo", description="Xóa một video khỏi danh sách phát theo URL hoặc từ khóa")
@app_commands.describe(url="URL hoặc từ khóa bài hát muốn xóa")
async def delvideo(interaction: discord.Interaction, url: str):
    if not check_not_blocked(interaction):
        await interaction.response.send_message("❌ Bạn đã bị cấm sử dụng các lệnh của bot!", ephemeral=True)
        return
    guild_id = interaction.guild.id
    queue = music_queues.get(guild_id, [])
    if not queue:
        await interaction.response.send_message("❌ Danh sách phát hiện tại đang trống!")
        return
    removed_item = None
    for item in queue:
        if url.lower() in item['webpage_url'].lower() or url.lower() in item['title'].lower():
            removed_item = item
            queue.remove(item)
            break
    if removed_item:
        await interaction.response.send_message(f"🗑️ Đã xóa **{removed_item['title']}** khỏi danh sách phát.")
    else:
        await interaction.response.send_message("❌ Không tìm thấy video trùng khớp trong danh sách phát.")

@bot.tree.command(name="dont", description="Chặn người dùng sử dụng các lệnh của bot (Chỉ Admin)")
@app_commands.describe(user_id="ID Discord của người dùng cần chặn")
async def dont(interaction: discord.Interaction, user_id: str):
    if interaction.user.id != ADMIN_ID:
        await interaction.response.send_message("❌ Bạn không có quyền sử dụng lệnh quản trị này!", ephemeral=True)
        return
    try:
        target_id = int(user_id)
        if target_id in blocked_users:
            blocked_users.remove(target_id)
            await interaction.response.send_message(f"🔓 Đã bỏ chặn người dùng có ID: `{target_id}`")
        else:
            blocked_users.add(target_id)
            await interaction.response.send_message(f"🚫 Đã chặn người dùng có ID: `{target_id}` khỏi các lệnh của bot.")
    except ValueError:
        await interaction.response.send_message("❌ Vui lòng nhập ID người dùng hợp lệ dạng số!")

@bot.tree.command(name="afk", description="Giữ bot trong kênh voice trong khoảng thời gian nhất định")
@app_commands.describe(phut="Số phút (nhập 'inf' để ở vô hạn)")
async def afk(interaction: discord.Interaction, phut: str):
    if not check_not_blocked(interaction):
        await interaction.response.send_message("❌ Bạn đã bị cấm sử dụng các lệnh của bot!", ephemeral=True)
        return
    if not interaction.user.voice:
        await interaction.response.send_message("❌ Bạn cần vào kênh voice để gọi bot!", ephemeral=True)
        return
    voice_channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client
    if voice_client is None:
        voice_client = await voice_channel.connect()
    elif voice_client.channel != voice_channel:
        await voice_client.move_to(voice_channel)

    guild_id = interaction.guild.id
    if guild_id in afk_tasks:
        afk_tasks[guild_id].cancel()
        del afk_tasks[guild_id]

    if phut.lower() == "inf":
        await interaction.response.send_message("♾️ Bot sẽ treo trong kênh voice **vô hạn** thời gian.")
    else:
        try:
            minutes = float(phut)
            seconds = minutes * 60
            await interaction.response.send_message(f"⏱️ Bot sẽ giữ treo trong kênh voice trong **{minutes} phút**.")
            async def afk_timeout():
                await asyncio.sleep(seconds)
                if interaction.guild.voice_client:
                    await interaction.guild.voice_client.disconnect()
                    await interaction.channel.send("⏰ Đã hết thời gian AFK, bot tự động rời kênh voice.")
            afk_tasks[guild_id] = bot.loop.create_task(afk_timeout())
        except ValueError:
            await interaction.response.send_message("❌ Vui lòng nhập số phút hợp lệ hoặc nhập `inf`!")

@app_commands.describe(muc_do="Mức âm lượng từ 1 đến 100")
@bot.tree.command(name="audio", description="Tăng/Giảm âm lượng của bot (từ 1 đến 100)")
async def audio(interaction: discord.Interaction, muc_do: int):
    if not check_not_blocked(interaction):
        await interaction.response.send_message("❌ Bạn đã bị cấm sử dụng các lệnh của bot!", ephemeral=True)
        return
    if muc_do < 1 or muc_do > 100:
        await interaction.response.send_message("❌ Vui lòng nhập mức âm lượng từ **1 đến 100**!", ephemeral=True)
        return
    guild_id = interaction.guild.id
    vol_float = muc_do / 100.0
    volume_settings[guild_id] = vol_float
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.source:
        if isinstance(voice_client.source, discord.PCMVolumeTransformer):
            voice_client.source.volume = vol_float
    await interaction.response.send_message(f"🔊 Đã chỉnh âm lượng bot thành: **{muc_do}%**")

@bot.tree.command(name="help", description="Xem danh sách chi tiết tất cả các lệnh của bot")
async def help_command(interaction: discord.Interaction):
    if not check_not_blocked(interaction):
        await interaction.response.send_message("❌ Bạn đã bị cấm sử dụng các lệnh của bot!", ephemeral=True)
        return
    help_text = """
📌 **DANH SÁCH CÁC CÂU LỆNH CỦA BOT MUSIC** 📌
🔹 `/play <url yt>`: Phát nhạc hoặc thêm vào danh sách chờ.
🔹 `/stop`: Dừng nhạc, xóa hàng chờ và rời kênh.
🔹 `/loop`: Bật/Tắt lặp lại bài hát.
🔹 `/listvideo`: Xem danh sách phát tiếp theo.
🔹 `/delvideo <tên/url>`: Xóa bài hát khỏi danh sách chờ.
🔹 `/audio <1-100>`: Chỉnh âm lượng bot.
🔹 `/afk <phút / inf>`: Giữ bot trong kênh voice.
🔹 `/dont <id user>`: Chặn/bỏ chặn người dùng (Admin).
🔹 `/help`: Xem hướng dẫn lệnh.
    """
    await interaction.response.send_message(help_text)

# Thay token của bạn vào đây
TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
