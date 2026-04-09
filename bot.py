import os
import asyncio
import logging
import base64
import xxtea
import hashlib
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
KEYS = [
    b"napsternetv",
    b"npv2",
    b"npv4",
    b"1234567890123456" 
]

async def decrypt_nvpt_file(file_path: str):
    try:
        with open(file_path, 'rb') as f:
            encrypted_data = f.read()

        try:
            raw_data = base64.b64decode(encrypted_data)
        except Exception:
            raw_data = encrypted_data

        for key in KEYS:
            try:
                decrypted = xxtea.decrypt(raw_data, key)
                if decrypted:
                    decoded = decrypted.decode('utf-8', errors='ignore')
                    if any(x in decoded for x in ['{', '"v":', '"ps":', '"add":']):
                        decrypted_path = file_path + ".decrypted.txt"
                        with open(decrypted_path, 'w') as df:
                            df.write(decoded)
                        return decrypted_path
            except Exception:
                continue
        
        try:
            decoded = raw_data.decode('utf-8', errors='ignore')
            if "{" in decoded:
                decrypted_path = file_path + ".decrypted.txt"
                with open(decrypted_path, 'w') as df:
                    df.write(decoded)
                return decrypted_path
        except:
            pass

        return None
    except Exception as e:
        logger.error(f"Decryption error: {e}")
        return None

@dp.message(F.document)
async def handle_document(message: types.Message):
    document = message.document
    file_name = document.file_name.lower() if document.file_name else ""
    
    # Check for .nvpt or .npvt extension
    if file_name.endswith(".nvpt") or file_name.endswith(".npvt"):
        # Create a short hash of the file_id to keep callback data small
        short_id = hashlib.md5(document.file_id.encode()).hexdigest()[:10]
        file_cache[short_id] = document.file_id
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Decrypt 🔓", callback_data=f"dec:{short_id}")]
        ])
        
        try:
            await message.reply(
                f"📄 **File Detected:** `{file_name}`\nPress the button below to decrypt.",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to send reply: {e}")

@dp.callback_query(F.data.startswith("dec:"))
async def process_decrypt(callback_query: CallbackQuery):
    short_id = callback_query.data.split(":")[1]
    file_id = file_cache.get(short_id)
    
    if not file_id:
        await callback_query.answer("❌ Error: File ID expired or not found.")
        return

    await callback_query.answer("Processing...")
    status_msg = await callback_query.message.edit_text("⏳ Decrypting... please wait.")
    
    try:
        file = await bot.get_file(file_id)
        local_file_path = os.path.join(DOWNLOAD_PATH, f"{short_id}")
        await bot.download_file(file.file_path, destination=local_file_path)
        
        decrypted_file = await decrypt_nvpt_file(local_file_path)
        
        if decrypted_file:
            input_file = FSInputFile(decrypted_file, filename="decrypted_config.json")
            await callback_query.message.answer_document(input_file, caption="✅ Decryption successful!")
            await status_msg.delete()
            
            os.remove(local_file_path)
            os.remove(decrypted_file)
        else:
            await status_msg.edit_text("❌ Failed to decrypt. The file might be using a unique key or HWID lock.")
            if os.path.exists(local_file_path):
                os.remove(local_file_path)
            
    except Exception as e:
        logger.exception("Error in process_decrypt")
        await status_msg.edit_text(f"❌ Error during decryption.")

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
