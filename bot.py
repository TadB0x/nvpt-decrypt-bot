import os
import asyncio
import logging
import base64
import xxtea
import hashlib
import zlib
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.filters import Command
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize bot and dispatcher
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Directory for temporary files
DOWNLOAD_PATH = "downloads"
os.makedirs(DOWNLOAD_PATH, exist_ok=True)

# In-memory mapping to avoid long callback data
file_cache = {}

# Common XXTEA configurations
COMMON_KEYS = [
    b"napsternetv",
    b"npv2",
    b"npv4",
    b"1234567890123456"
]

def decode_b64(s):
    s = s.strip()
    # Remove potentially invalid leading chars like 'u' or 'v' if present in data part
    if len(s) % 4 == 1:
        s = s[1:]
    return base64.b64decode(s + '=' * (-len(s) % 4))

async def decrypt_nvpt_file(file_path: str):
    try:
        with open(file_path, 'rb') as f:
            raw_content = f.read().decode('utf-8', errors='ignore').strip()

        # Handle NPVT1 format
        if raw_content.startswith("NPVT1"):
            lines = raw_content.splitlines()
            data_line = lines[1] if len(lines) > 1 else lines[0][5:]
            parts = data_line.split(',')
            if len(parts) < 2:
                return None
            
            # part[0] is often key material, part[1] is data
            key_raw = decode_b64(parts[0])
            data_raw = decode_b64(parts[1])
            
            # The key might be the first 16 bytes or last 16 bytes of part[0]
            # or it might be a fixed key and part[0] is just a salt/IV
            candidate_keys = [key_raw[:16], key_raw[-16:]] + COMMON_KEYS
            
            for key in candidate_keys:
                for padding in [True, False]:
                    try:
                        decrypted = xxtea.decrypt(data_raw, key, padding=padding)
                        if decrypted:
                            # Configs are often Zlib compressed after XXTEA
                            try:
                                decrypted = zlib.decompress(decrypted)
                            except:
                                pass
                            
                            decoded = decrypted.decode('utf-8', errors='ignore')
                            if "{" in decoded and any(x in decoded for x in ['"v":', '"ps":', '"add":', '"outbounds":']):
                                decrypted_path = file_path + ".decrypted.json"
                                with open(decrypted_path, 'w') as df:
                                    df.write(decoded)
                                return decrypted_path
                    except:
                        continue
        
        # Fallback for old XXTEA-only formats
        try:
            data_raw = decode_b64(raw_content)
        except:
            data_raw = raw_content.encode()

        for key in COMMON_KEYS:
            for padding in [True, False]:
                try:
                    decrypted = xxtea.decrypt(data_raw, key, padding=padding)
                    if decrypted:
                        try:
                            decrypted = zlib.decompress(decrypted)
                        except:
                            pass
                        decoded = decrypted.decode('utf-8', errors='ignore')
                        if "{" in decoded:
                            decrypted_path = file_path + ".decrypted.json"
                            with open(decrypted_path, 'w') as df:
                                df.write(decoded)
                            return decrypted_path
                except:
                    continue

        return None
    except Exception as e:
        logger.error(f"Decryption error: {e}")
        return None

@dp.message(F.document)
async def handle_document(message: types.Message):
    document = message.document
    file_name = document.file_name.lower() if document.file_name else ""
    
    if file_name.endswith(".nvpt") or file_name.endswith(".npvt"):
        short_id = hashlib.md5(document.file_id.encode()).hexdigest()[:10]
        file_cache[short_id] = document.file_id
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Decrypt 🔓", callback_data=f"dec:{short_id}")]
        ])
        
        await message.reply(
            f"📄 **File Detected:** `{file_name}`\nFormat: `NPVT1` (XXTEA + Zlib detected)\nClick below to decrypt.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

@dp.callback_query(F.data.startswith("dec:"))
async def process_decrypt(callback_query: CallbackQuery):
    short_id = callback_query.data.split(":")[1]
    file_id = file_cache.get(short_id)
    
    if not file_id:
        await callback_query.answer("❌ Error: File ID expired or not found.")
        return

    await callback_query.answer("Processing...")
    status_msg = await callback_query.message.edit_text("⏳ Decrypting using multi-stage logic...")
    
    local_file_path = os.path.join(DOWNLOAD_PATH, f"{short_id}")
    decrypted_file_path = None
    
    try:
        file = await bot.get_file(file_id)
        await bot.download_file(file.file_path, destination=local_file_path)
        
        decrypted_file_path = await decrypt_nvpt_file(local_file_path)
        
        if decrypted_file_path:
            input_file = FSInputFile(decrypted_file_path, filename="decrypted_config.json")
            await callback_query.message.answer_document(input_file, caption="✅ Decryption successful!\nFormat: XXTEA + Zlib")
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ Failed to decrypt. The file might use a hardware-bound key or an unknown protocol variation.")
            
    except Exception as e:
        logger.exception("Error in process_decrypt")
        await status_msg.edit_text(f"❌ An error occurred during processing.")
    
    finally:
        try:
            if os.path.exists(local_file_path):
                os.remove(local_file_path)
            if decrypted_file_path and os.path.exists(decrypted_file_path):
                os.remove(decrypted_file_path)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Ready to decrypt `.nvpt` and `.npvt` files. Just drop them here!")

async def main():
    while True:
        try:
            logger.info("Bot starting...")
            await dp.start_polling(bot)
        except Exception as e:
            logger.error(f"Bot crashed: {e}. Restarting in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
