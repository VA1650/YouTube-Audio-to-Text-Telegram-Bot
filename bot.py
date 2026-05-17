import os
import asyncio
import logging
import secrets
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import CommandStart
import yt_dlp
from faster_whisper import WhisperModel

# ==========================================
# 1. НАСТРОЙКА ЛОГИРОВАНИЯ И ОКРУЖЕНИЯ
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN = "Ваш_токен"
if not TOKEN:
    raise ValueError("Критическая ошибка: Переменная окружения TELEGRAM_BOT_TOKEN не задана!")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ==========================================
# 2. ИНИЦИАЛИЗАЦИЯ ИИ-МОДЕЛИ И СЕМАФОРА
# ==========================================
# Насильно используем CPU + int8, чтобы полностью избежать ада с CUDA/DLL на Windows
device = "cpu"
compute_type = "int8"

logger.info(f"Загрузка модели Faster-Whisper 'base' на {device} ({compute_type})...")
model = WhisperModel("base", device=device, compute_type=compute_type)
logger.info("Модель Faster-Whisper успешно загружена и готова к работе.")

# Семафор ограничивает одновременную работу (скачивание + ИИ) до 1 задачи.
# Все остальные запросы гарантированно встают в очередь и не перегружают CPU.
transcription_semaphore = asyncio.Semaphore(1)
active_tasks = 0  # Глобальный счетчик задач в пуле

# ==========================================
# 3. СИНХРОННЫЕ BLOCKING-ФУНКЦИИ (ДЛЯ ПОТОКОВ)
# ==========================================
def _download_audio(video_url: str, output_path: str) -> str:
    """
    Синхронное скачивание аудиодорожки через yt_dlp.
    Добавлен запрет на скачивание плейлистов.
    """
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_path,
        'quiet': False,         
        'no_warnings': False,
        'noplaylist': True,     
        'socket_timeout': 15,   
        'retries': 3,           
        'fragment_retries': 3,  
        'match_filter': lambda info, *, incomplete: (
            'Видео слишком длинное (более 15 минут)!' 
            if info.get('duration') and info.get('duration') > 900 
            else None
        ),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'm4a',  
        }],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])
    return f"{output_path}.m4a"


def _transcribe_audio(file_path: str) -> str:
    """Синхронный тяжелый инференс модели Faster-Whisper."""
    if not os.path.exists(file_path) or os.path.getsize(file_path) < 1000:
        raise ValueError("Скачанный файл поврежден, пуст или отсутствует на диске.")
    
    # beam_size=5 дает оптимальный баланс скорости и качества распознавания
    segments, _ = model.transcribe(file_path, beam_size=5)
    return " ".join([seg.text for seg in segments]).strip()

# ==========================================
# 4. ОБРАБОТЧИКИ ТЕЛЕГРАМ-СОБЫТИЙ (AIOGRAM)
# ==========================================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Ответ на команду /start."""
    await message.answer(
        "🦾 Бот запущен в промышленном режиме очереди!\n\n"
        "Отправляй мне ссылки на YouTube видео или Shorts (пачками или по одной). "
        "Процессор больше не зависнет, а задачи обработаются строго друг за другом.",
        parse_mode="Markdown"
    )


@dp.message(F.text.regexp(r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+'))
async def handle_youtube_link(message: Message):
    """Основной хэндлер для обработки входящих YouTube-ссылок."""
    global active_tasks
    video_url = message.text.strip()
    
    # Генерируем уникальное имя файла для изоляции параллельных сессий
    unique_id = secrets.token_hex(8)
    m4a_path = f"audio_{unique_id}.m4a"

    status_message = await message.answer("⏳ Добавление вашей задачи в пул...")
    active_tasks += 1

    try:
        # Если семафор заблокирован другой задачей, уведомляем пользователя о его позиции
        if transcription_semaphore.locked():
            await status_message.edit_text(
                f"⏳ Бот сейчас обрабатывает другой запрос.\n"
                f"Вы добавлены в очередь. Ваша позиция: {active_tasks - 1}. Ожидайте..."
            )

        # Вход в критическую секцию семафора (строго по одному)
        async with transcription_semaphore:
            await status_message.edit_text("📥 Очередь подошла! Начинаю скачивание аудиодорожки...")
            logger.info(f"Старт скачивания: {video_url}")
            
            # Запускаем скачивание в отдельном потоке, чтобы не вешать event loop бота
            await asyncio.to_thread(_download_audio, video_url, f"audio_{unique_id}")
            
            await status_message.edit_text("🧠 Аудио успешно загружено. Нейросеть распознает текст...")
            logger.info(f"Старт транскрибации: {m4a_path}")
            
            # Запускаем инференс ИИ в отдельном потоке
            text = await asyncio.to_thread(_transcribe_audio, m4a_path)

        # Успешно вышли из семафора — декрементируем счетчик живых задач
        active_tasks -= 1

        if not text:
            await status_message.edit_text("❌ В данном видео речь не обнаружена или аудиозапись пуста.")
            return

        # Удаляем сервисное сообщение перед отправкой результата
        await status_message.delete()
        
        # Нарезка под жесткие лимиты сообщений Telegram (макс. 4096 символов на пост)
        max_length = 4000
        if len(text) <= max_length:
            await message.reply(f"📝 Результат расшифровки:\n\n{text}")
        else:
            await message.reply("📝 Результат расшифровки (текст слишком длинный, разбит на части):")
            for i in range(0, len(text), max_length):
                await message.answer(text[i:i + max_length])

    except Exception as e:
        # Корректно уменьшаем счетчик пула при падении ЛЮБОЙ задачи в try-блоке
        active_tasks = max(0, active_tasks - 1)
        logger.error(f"Сбой обработки запроса: {e}", exc_info=True)
        
        err_msg = str(e)
        if "Видео слишком длинное" in err_msg:
            await status_message.edit_text("❌ Ошибка: Видео превышает лимит длины (максимум 15 минут).")
        elif "DownloadError" in err_msg or "Incomplete" in err_msg:
            await status_message.edit_text("💥 Сбой сети: YouTube разорвал соединение. Попробуйте отправить ссылку позже.")
        else:
            await status_message.edit_text(f"💥 Ошибка при обработке: {err_msg}")
    
    finally:
        # Жесткая и гарантированная зачистка диска от временных файлов в любом исходе
        if os.path.exists(m4a_path):
            try:
                os.remove(m4a_path)
                logger.info(f"Временный файл успешно удален с диска: {m4a_path}")
            except OSError as os_err:
                logger.error(f"Не удалось удалить файл {m4a_path}: {os_err}")


async def main():
    logger.info("Запуск бота и старт polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот полностью остановлен оператором.")
