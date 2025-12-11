import logging
import os
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext


load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    print("Error: set TELEGRAM_BOT_TOKEN in environment or .env file")
    raise SystemExit(1)

DB_CHANNEL_ID = os.getenv("DB_CHANNEL_ID")
if DB_CHANNEL_ID:
    try:
        DB_CHANNEL_ID = int(DB_CHANNEL_ID)
        logger.info(f"Database channel configured: {DB_CHANNEL_ID}")
    except ValueError:
        logger.warning("DB_CHANNEL_ID is not a valid integer")
        DB_CHANNEL_ID = None
else:
    logger.warning("DB_CHANNEL_ID not configured - database forwarding disabled")


# In-memory per-chat state
pending_media = {}  # chat_id -> list of (type, file_id, original_caption, filename)
pending_job = {}  # chat_id -> Job


def start(update: Update, context: CallbackContext):
    text = (
        "🐱 Neko Album Maker\n\n"
        "Welcome! Send your media and I'll create beautiful albums for you.\n\n"
        "📸 How to use:\n"
        "1. Send as many media files as you want (photos, videos, etc.)\n"
        "2. Click 'Done✅, Make album!' button\n"
        "3. Your media will be organized into albums (max 10 items per group)\n\n"
        "Let's go! Send your media! 🚀"
    )
    update.message.reply_text(text)


def _append_media(chat_id, media_item):
    lst = pending_media.get(chat_id)
    if lst is None:
        lst = []
        pending_media[chat_id] = lst
    lst.append(media_item)


def _get_filename(msg, media_type):
    try:
        if media_type == "photo":
            return f"photo_{msg.photo[-1].file_unique_id}.jpg"
        elif media_type == "video":
            return msg.video.file_name or f"video_{msg.video.file_unique_id}.mp4"
        elif media_type == "document":
            return msg.document.file_name or f"document_{msg.document.file_unique_id}"
        elif media_type == "animation":
            return msg.animation.file_name or f"animation_{msg.animation.file_unique_id}.gif"
        elif media_type == "audio":
            return msg.audio.file_name or f"audio_{msg.audio.file_unique_id}.mp3"
        elif media_type == "voice":
            return f"voice_{msg.voice.file_unique_id}.ogg"
    except Exception:
        return "unknown_file"


def _get_file_size(msg, media_type):
    """Get file size in bytes"""
    try:
        if media_type == "photo":
            return msg.photo[-1].file_size or 0
        elif media_type == "video":
            return msg.video.file_size or 0
        elif media_type == "document":
            return msg.document.file_size or 0
        elif media_type == "animation":
            return msg.animation.file_size or 0
        elif media_type == "audio":
            return msg.audio.file_size or 0
        elif media_type == "voice":
            return msg.voice.file_size or 0
    except Exception:
        return 0


def _format_file_size(bytes_size):
    """Format file size to human readable format"""
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.2f} KB"
    elif bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.2f} MB"
    else:
        return f"{bytes_size / (1024 * 1024 * 1024):.2f} GB"


def forward_to_database(context: CallbackContext, msg, media_type, file_id):
    """Forward media to database channel with user info"""
    if not DB_CHANNEL_ID:
        logger.warning("DB_CHANNEL_ID not set - skipping database forward")
        return
    
    try:
        user = msg.from_user
        user_name = user.first_name
        if user.last_name:
            user_name += f" {user.last_name}"
        user_id = user.id
        
        # Get filename and file size
        filename = _get_filename(msg, media_type)
        file_size = _get_file_size(msg, media_type)
        formatted_size = _format_file_size(file_size)
        
        # Get current date
        date_str = datetime.now().strftime("%Y-%m-%d")

        # Build our info block
        info_block = (
            f"📂 ɴᴀᴍᴇ: {filename}\n"
            f"📦 sɪᴢᴇ: {formatted_size}\n"
            f"👤 ᴜsᴇʀ: {user_name} ({user_id})\n"
            f"📅 ᴅᴀᴛᴇ: {date_str}"
        )

        # Preserve original caption (if any) and then append our info block
        original_caption = msg.caption or ""
        if original_caption:
            caption = f"{original_caption}\n\n━━━━━━━━━━━━━━━━━━━━━━\n\n{info_block}"
        else:
            caption = info_block
        
        logger.info(f"Forwarding {media_type} to database channel {DB_CHANNEL_ID}")
        
        # Forward based on media type
        if media_type == "photo":
            context.bot.send_photo(chat_id=DB_CHANNEL_ID, photo=file_id, caption=caption)
        elif media_type == "video":
            context.bot.send_video(chat_id=DB_CHANNEL_ID, video=file_id, caption=caption)
        elif media_type == "document":
            context.bot.send_document(chat_id=DB_CHANNEL_ID, document=file_id, caption=caption)
        elif media_type == "animation":
            context.bot.send_animation(chat_id=DB_CHANNEL_ID, animation=file_id, caption=caption)
        elif media_type == "audio":
            context.bot.send_audio(chat_id=DB_CHANNEL_ID, audio=file_id, caption=caption)
        elif media_type == "voice":
            context.bot.send_voice(chat_id=DB_CHANNEL_ID, voice=file_id, caption=caption)
        
        logger.info(f"Successfully forwarded {media_type} to database channel")
    except Exception as e:
        logger.exception(f"Failed to forward to database channel: {e}")


def save_media(update: Update, context: CallbackContext):
    msg = update.message
    if not msg:
        logger.warning("Received update without message")
        return
        
    chat_id = msg.chat_id
    original_caption = msg.caption or ""

    media_type = None
    file_id = None
    
    if msg.photo:
        media_type = "photo"
        file_id = msg.photo[-1].file_id
    elif msg.video:
        media_type = "video"
        file_id = msg.video.file_id
    elif msg.document:
        media_type = "document"
        file_id = msg.document.file_id
    elif msg.animation:
        media_type = "animation"
        file_id = msg.animation.file_id
    elif msg.audio:
        media_type = "audio"
        file_id = msg.audio.file_id
    elif msg.voice:
        media_type = "voice"
        file_id = msg.voice.file_id
    else:
        return

    filename = _get_filename(msg, media_type)
    _append_media(chat_id, (media_type, file_id, original_caption, filename))
    
    # Forward to database channel
    forward_to_database(context, msg, media_type, file_id)

    # Cancel any existing job
    job = pending_job.get(chat_id)
    if job:
        try:
            job.schedule_removal()
        except Exception:
            pass

    # Schedule notification after 2 seconds of no new media
    job = context.job_queue.run_once(show_done_button, 2.0, context=chat_id)
    pending_job[chat_id] = job


def show_done_button(context: CallbackContext):
    """Show Done button after 2 seconds of no new media"""
    chat_id = context.job.context
    items = pending_media.get(chat_id, [])
    
    if not items:
        return
    
    keyboard = [[KeyboardButton("Done✅, Make album!")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    try:
        context.bot.send_message(
            chat_id=chat_id,
            text=f"📦 Received {len(items)} media. Send more or click Done✅, Make album!",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.exception("Failed to show done button: %s", e)
    
    pending_job.pop(chat_id, None)


def ask_for_mode(context: CallbackContext, chat_id: int = None):
    pass


def button_callback(update: Update, context: CallbackContext):
    pass


def handle_text(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    text = update.message.text or ""
    
    # Check if user clicked Done button
    if text == "Done✅, Make album!":
        items = pending_media.get(chat_id, [])
        if items:
            from telegram import ReplyKeyboardRemove
            update.message.reply_text(f"📚 Creating album from {len(items)} media...", reply_markup=ReplyKeyboardRemove())
            send_media_as_album(context, chat_id)
        else:
            update.message.reply_text("No media found. Send media first.")
        return


def send_media_with_mode(context: CallbackContext, chat_id: int, mode: str, user_text: str):
    pass


def send_media_as_album(context: CallbackContext, chat_id: int):
    """Send media as albums with max 10 items per group"""
    from telegram import InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio, InputMediaAnimation
    
    items = pending_media.get(chat_id, [])
    if not items:
        return
    
    # Group items into chunks of 10
    chunk_size = 10
    for i in range(0, len(items), chunk_size):
        chunk = items[i:i + chunk_size]
        media_group = []
        
        for typ, file_id, original_caption, filename in chunk:
            try:
                if typ == "photo":
                    media_group.append(InputMediaPhoto(media=file_id))
                elif typ == "video":
                    media_group.append(InputMediaVideo(media=file_id))
                elif typ == "document":
                    media_group.append(InputMediaDocument(media=file_id))
                elif typ == "animation":
                    media_group.append(InputMediaAnimation(media=file_id))
                elif typ == "audio":
                    media_group.append(InputMediaAudio(media=file_id))
                elif typ == "voice":
                    context.bot.send_voice(chat_id=chat_id, voice=file_id)
            except Exception as e:
                logger.exception("Failed to prepare media: %s", e)
        
        # Send the media group if we have items
        if media_group:
            try:
                context.bot.send_media_group(chat_id=chat_id, media=media_group)
            except Exception as e:
                logger.exception("Failed to send media group: %s", e)
    
    pending_media.pop(chat_id, None)


def generate_caption(mode: str, user_text: str, original_caption: str, filename: str) -> str:
    pass


def apply_global_replacements(chat_id: int, text: str) -> str:
    pass


def clear_command(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    
    job = pending_job.get(chat_id)
    if job:
        try:
            job.schedule_removal()
        except Exception:
            pass
    
    pending_media.pop(chat_id, None)
    pending_job.pop(chat_id, None)
    
    update.message.reply_text("🗑️ Cleared! Send new media when ready.")


def global_replacement_command(update: Update, context: CallbackContext):
    pass


def list_global_command(update: Update, context: CallbackContext):
    pass


def remove_replacement_command(update: Update, context: CallbackContext):
    pass


def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🐱 *Neko Album Maker Help*\n\n"
        "📸 *How to use:*\n"
        "1. Send any media (photos, videos, documents, etc.)\n"
        "2. Keep sending as much as you want\n"
        "3. Wait ~2 seconds or tap 'Done✅, Make album!'\n"
        "4. Your media will be organized into albums (max 10 per group)\n\n"
        "💡 *Note:* Media is grouped into albums with a maximum of 10 items each.\n\n"
        "/clear - Clear all pending media\n"
        "/help - Show this help",
        parse_mode='Markdown'
    )


def main():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("clear", clear_command))

    media_filter = Filters.photo | Filters.video | Filters.document | Filters.animation | Filters.audio | Filters.voice
    dp.add_handler(MessageHandler(media_filter, save_media))

    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))

    updater.start_polling()
    logger.info("🐱 Neko Album Maker Bot started")
    updater.idle()


if __name__ == '__main__':
    main()
