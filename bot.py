import os
import asyncio
import logging
import base64
import xxtea
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

# Common XXTEA configurations for NapsternetV / NPV Tunnel
# Note: keys in xxtea library should be bytes
KEYS = [
    b"napsternetv",
    b"npv2",
    b"npv4",
    b"1234567890123456" 
]
# Standard delta is usually fixed in the library, but some implementations allow custom ones.
# The 'xxtea' library uses the standard delta 0x9E3779B9.

async def decrypt_nvpt_file(file_path: str):
    """
    Tries to decrypt the file using XXTEA with common keys.
    """
    try:
        with open(file_path, 'rb') as f:
            encrypted_data = f.read()

        # Handle Base64 if needed
        try:
            raw_data = base64.b64decode(encrypted_data)
        except Exception:
            raw_data = encrypted_data

        for key in KEYS:
            try:
                # xxtea.decrypt(data, key)
                decrypted = xxtea.decrypt(raw_data, key)
                if decrypted:
                    decoded = decrypted.decode('utf-8', errors='ignore')
                    # Heuristic: Configs usually look like JSON or have specific headers
                    if any(x in decoded for x in ['{', '"v":', '"ps":', '"add":']):
                        decrypted_path = file_path + ".decrypted.txt"
                        with open(decrypted_path, 'w') as df:
                            df.write(decoded)
                        return decrypted_path
            except Exception:
                continue
        
        # Fallback: check if it's already plain text
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
    
    if file_name.endswith(".nvpt") or file_name.endswith(".npvt"):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Decrypt 🔓", callback_data=f"decrypt:{document.file_id}")]
        ])
        await message.reply(f"Detected: `{file_name}`\nWould you like to decrypt it?", 
                           reply_markup=keyboard, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("decrypt:"))
async def process_decrypt(callback_query: CallbackQuery):
    file_id = callback_query.data.split(":")[1]
    
    await callback_query.answer("Decrypting...")
    status_msg = await callback_query.message.edit_text("⏳ Processing... please wait.")
    
    try:
        file = await bot.get_file(file_id)
        local_file_path = os.path.join(DOWNLOAD_PATH, f"{file_id}")
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
        await status_msg.edit_text(f"❌ Error: {str(e)}")

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
