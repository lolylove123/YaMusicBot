import discord
from discord.ext import commands
from yandex_music import Client
import asyncio
import os
import traceback
import threading
from dotenv import load_dotenv

load_dotenv()

# === ПРИОРИТЕТ ПРОЦЕССА (Windows) ===
if os.name == 'nt':
    try:
        import win32api, win32process, win32con
        pid = win32api.GetCurrentProcessId()
        handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, True, pid)
        win32process.SetPriorityClass(handle, win32process.HIGH_PRIORITY_CLASS)
    except: pass

# === КОНФИГУРАЦИЯ ===
TOKEN_DISCORD = os.getenv('BOT_TOKEN')
TOKEN_YANDEX = os.getenv('YA_TOKEN')

CACHE_DIR = "cache"
if not os.path.exists(CACHE_DIR): os.makedirs(CACHE_DIR)

y_client = Client(TOKEN_YANDEX).init()
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='ya!', intents=intents, help_command=None) # Отключаем стандартный help

queues = {}

# Оптимизация для HQ
FFMPEG_OPTS = {
    'before_options': '-nostdin',
    'options': '-vn -ac 2 -ar 48000 -b:a 320k'
}

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def get_track_info(url):
    try:
        url = url.split('?')[0]
        if 'playlists/' in url:
            playlist_id = url.split('playlists/')[1].strip('/')
            if playlist_id.startswith('lk.'):
                liked = y_client.users_likes_tracks()
                return [item.track for item in liked if item.track]
            if '/users/' in url:
                parts = url.split('/')
                user = parts[parts.index('users') + 1]
                p_id = parts[parts.index('playlists') + 1]
                playlist = y_client.users_playlists(p_id, user)
            else:
                playlist = y_client.users_playlists(playlist_id)
            if isinstance(playlist, list): playlist = playlist[0]
            return [item.track for item in playlist.tracks if item.track]
        if 'artist/' in url:
            artist_id = url.split('artist/')[1].split('/')[0]
            return y_client.artists_tracks(artist_id).tracks
        if 'track/' in url:
            t_id = url.split('track/')[1].split('/')[0]
            return y_client.tracks([t_id])
        if 'album/' in url:
            a_id = url.split('album/')[1].split('/')[0]
            album = y_client.albums_with_tracks(a_id)
            return [t for vol in album.volumes for t in vol]
    except Exception as e:
        print(f"Ошибка парсинга: {e}")
    return []

def download_sync(track):
    path = os.path.abspath(f"{CACHE_DIR}/{track.id}.mp3")
    if not os.path.exists(path):
        track.download(path)
    return path

async def auto_clean_cache(ctx):
    files = [f for f in os.listdir(CACHE_DIR) if f.endswith('.mp3')]
    if len(files) < 50: return
    
    status = await ctx.send("🧹 **Чистка кэша...**", delete_after=10)
    protected = []
    for q in queues.values():
        protected.extend([f"{t.id}.mp3" for t in q])
    
    deleted = 0
    for f in files:
        if f not in protected:
            try: os.remove(os.path.join(CACHE_DIR, f)); deleted += 1
            except: continue
    
    await status.edit(content=f"✅ **Кэш очищен!** Удалено треков: `{deleted}`")

# === ЛОГИКА ПЛЕЕРА ===

async def play_music(ctx):
    guild_id = ctx.guild.id
    if guild_id not in queues or not queues[guild_id]:
        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="ya!help"))
        return

    await auto_clean_cache(ctx)

    if not ctx.voice_client:
        try:
            await ctx.author.voice.channel.connect()
        except Exception as e:
            return await ctx.send(f"❌ Не удалось подключиться к каналу: {e}")

    track = queues[guild_id].pop(0)
    file_path = os.path.abspath(f"{CACHE_DIR}/{track.id}.mp3")

    try:
        # Загрузка трека
        if not os.path.exists(file_path):
            await ctx.send(f"📥 Загрузка: **{track.title}**", delete_after=5)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, download_sync, track)

        # Создание источника звука
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(file_path, executable="ffmpeg", **FFMPEG_OPTS)
        )

        def after_playing(e):
            if e: print(f"Ошибка FFmpeg: {e}")
            bot.loop.create_task(play_music(ctx))

        ctx.voice_client.play(source, after=after_playing)

        # Статус и Embed
        await bot.change_presence(
            activity=discord.Activity(type=discord.ActivityType.listening, name=f"{track.title}")
        )

        artist_name = ", ".join([a.name for a in track.artists])
        album_id = track.albums[0].id if track.albums else "unknown"
        track_url = f"https://music.yandex.ru/album/{album_id}/track/{track.id}"

        embed = discord.Embed(title=track.title, description=f"👤 **{artist_name}**", url=track_url, color=0xffd700)
        cover_url = track.get_cover_url(size='400x400')
        if cover_url:
            if not cover_url.startswith('http'): cover_url = f"https://{cover_url}"
            embed.set_image(url=cover_url)
        
        embed.set_author(name="Сейчас играет")
        await ctx.send(embed=embed)

        # Предзагрузка следующего трека
        if queues[guild_id]:
            threading.Thread(target=download_sync, args=(queues[guild_id][0],), daemon=True).start()

    except Exception as e:
        print("--- ОШИБКА ВОСПРОИЗВЕДЕНИЯ ---")
        traceback.print_exc()
        await ctx.send(f"⚠️ Ошибка при воспроизведении {track.title}. Перехожу к следующему...")
        bot.loop.create_task(play_music(ctx))

# === КОМАНДЫ ===

@bot.command(name='help')
async def help_command(ctx):
    embed = discord.Embed(
        title="🎵 Команды Музыкального Бота",
        description="Управляйте музыкой с помощью префикса `ya!`",
        color=0xffd700
    )
    embed.add_field(name="▶️ `ya!play [песня/ссылка]`", value="Запустить песню по названию или ссылке на Яндекс.Музыку. Не принимает личные плейлисты, только публичные.", inline=False)
    embed.add_field(name="⏭️ `ya!skip`", value="Пропустить текущую композицию.", inline=False)
    embed.add_field(name="⏹️ `ya!stop`", value="Остановить плеер, очистить очередь и выйти из канала.", inline=False)
    embed.add_field(name="📋 `ya!tracks`", value="Посмотреть список первых 10 песен в очереди.", inline=False)
    embed.add_field(name="🗑️ `ya!delete [номер]`", value="Удалить конкретную песню из очереди по её номеру.", inline=False)
    embed.add_field(name="🏓 `ya!ping`", value="Проверить задержку сети и API.", inline=False)
    embed.set_footer(text="Бот использует HQ поток 320kbps")
    await ctx.send(embed=embed)

@bot.command(name='play')
async def play(ctx, *, query):
    if not ctx.author.voice: return await ctx.send("Зайдите в голосовой канал!")
    search_msg = await ctx.send(f"🔎 Ищу: `{query}`", delete_after=5)
    
    tracks_found = []
    if query.startswith('http'): tracks_found = get_track_info(query)
    else:
        search = y_client.search(query, type_='track')
        if search.tracks and search.tracks.results: tracks_found = [search.tracks.results[0]]

    if not tracks_found: return await ctx.send("❌ Ничего не найдено.", delete_after=10)

    if ctx.guild.id not in queues: queues[ctx.guild.id] = []
    
    is_playing = ctx.voice_client and ctx.voice_client.is_playing()
    queues[ctx.guild.id].extend(tracks_found)
    
    if is_playing:
        if len(tracks_found) == 1:
            track = tracks_found[0]
            artist = track.artists[0].name if track.artists else "Неизвестен"
            await ctx.send(f"✅ **Добавлено в очередь (№{len(queues[ctx.guild.id])}):**\n`{track.title} — {artist}`", delete_after=15)
        else:
            await ctx.send(f"✅ Добавлено треков в очередь: **{len(tracks_found)}**", delete_after=10)

    if not is_playing: await play_music(ctx)

@bot.command(name='delete')
async def delete(ctx, index: int):
    guild_id = ctx.guild.id
    if guild_id not in queues or not queues[guild_id]: return await ctx.send("Очередь пуста.", delete_after=10)
    try:
        if 1 <= index <= len(queues[guild_id]):
            removed = queues[guild_id].pop(index - 1)
            artist = removed.artists[0].name if removed.artists else "Неизвестен"
            await ctx.send(f"🗑️ Удалено: **{removed.title} — {artist}**", delete_after=15)
        else:
            await ctx.send(f"❌ Неверный номер (всего треков: {len(queues[guild_id])})", delete_after=10)
    except: await ctx.send("Ошибка при удалении.", delete_after=10)

@bot.command()
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏭️ Пропускаю...", delete_after=5)

@bot.command()
async def stop(ctx):
    if ctx.guild.id in queues: queues[ctx.guild.id] = []
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("⏹️ Плеер остановлен.", delete_after=10)

@bot.command()
async def ping(ctx):
    bot_lat = round(bot.latency * 1000)
    embed = discord.Embed(description=f"🛰️ API: `{bot_lat}ms`", color=0x2f3136)
    if ctx.voice_client: embed.description += f"  |  🎤 Voice: `{round(ctx.voice_client.latency * 1000)}ms`"
    await ctx.send(embed=embed)

@bot.command()
async def tracks(ctx):
    if ctx.guild.id not in queues or not queues[ctx.guild.id]: return await ctx.send("Очередь пуста.")
    text = "**Список очереди:**\n"
    for i, track in enumerate(queues[ctx.guild.id][:10], 1):
        artist = track.artists[0].name if track.artists else "Неизвестен"
        text += f"{i}. {track.title} — {artist}\n"
    await ctx.send(text)

@bot.event
async def on_ready():
    print(f'--- Бот {bot.user.name} готов к раздаче стиля! ---')

bot.run(TOKEN_DISCORD)