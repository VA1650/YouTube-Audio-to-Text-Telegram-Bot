# 🎥 YouTube Audio to Text Telegram Bot

An asynchronous Telegram bot built with `aiogram 3` and `Faster-Whisper` for automated YouTube audio extraction (including Shorts) and real-time transcription. The architecture is optimized for stable CPU inference under high loads using an industrial-grade task queue.

## ✨ System Features

* High-Performance Inference (Faster-Whisper): Utilizes a C++ engine with `int8` quantization, allowing CPU-based text recognition that outperforms the original OpenAI Whisper on GPU, while eliminating memory leaks and CUDA driver dependencies.
* Robust Concurrency Control: Uses an `asyncio.Semaphore` to strictly throttle CPU usage. Concurrent link submissions are queued, with users notified of their position in the task pool.
* Network Isolation (yt-dlp): Includes built-in socket hang protection, retry limits for media segments, and a strict `noplaylist` flag for individual video processing.
* Automatic Chunking: Delivers transcriptions in blocks of up to 4,000 characters to bypass Telegram API message length limits.
* Data Security: Employs cryptographically secure tokens for temporary file naming and ensures forced disk cleanup (via `finally` blocks) regardless of transcription outcome.

## 🛠 Technical Stack

* Language: Python 3.10+
* Framework: Aiogram 3.x (Asyncio)
* Engine: Faster-Whisper (Model: base / int8)
* Media Downloader: yt-dlp
* Core Utility: FFmpeg (for audio container post-processing)

## 📋 Environment Requirements

FFmpeg must be installed on the system to run the bot.

### Installing FFmpeg:
* Windows (Conda): `conda install ffmpeg -c defaults` (or download binaries from gyan.dev and add to system PATH).
* Linux (Ubuntu/Debian): `sudo apt update && sudo apt install ffmpeg`
* macOS: `brew install ffmpeg`

## 🚀 Quick Start

### 1. Clone the repository
```bash
git clone https://github.com/VA1650/YouTube-Audio-to-Text-Telegram-Bot.git
cd YouTube-Audio-to-Text-Telegram-Bot 
```
### 2. Install dependencies
```bash
pip install aiogram yt-dlp faster-whisper torch
```
### 3. Set the bot token
```bash
# Windows (CMD)
set TELEGRAM_BOT_TOKEN=your_token_here
# Linux/macOS
export TELEGRAM_BOT_TOKEN="your_token_here"
```
### 4. Launch the bot
```bash
python bot.py
```
## ⚙️ Configuration & Limits

Main limits are defined in the `_download_audio` configuration function within `bot.py`:

* match_filter: Limits processing to 15-minute videos (900 seconds) to prevent CPU saturation.
* socket_timeout: Set to 15 seconds for YouTube server response timeouts.

## 📝 License
MIT License. See the LICENSE file for details.
