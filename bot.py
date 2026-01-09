import logging
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ParseMode, InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio, InputMediaAnimation
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
# chat_id -> list of (type, file_id, original_caption, filename, file_size, user_info)
pending_media = {}
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


def _get_user_info(msg):
    """Extract user info from message"""
    user = msg.from_user
    user_name = user.first_name
    if user.last_name:
        user_name += f" {user.last_name}"
    user_id = user.id
    user_username = user.username
    return {
        'name': user_name,
        'id': user_id,
        'username': user_username
    }


def _build_album_caption(items, date_str):
    """Build caption for the first media in album with all media info"""
    if not items:
        return ""
    
    # Get user info from first item
    first_user = items[0][5]  # user_info is at index 5
    if first_user['username']:
        user_line = f"👤 ᴜsᴇʀ: {first_user['name']} (@{first_user['username']}) ({first_user['id']})"
    else:
        user_line = f"👤 ᴜsᴇʀ: {first_user['name']} ({first_user['id']})"
    
    caption_parts = []
    caption_parts.append(f"📦 ᴀʟʙᴜᴍ ᴡɪᴛʜ {len(items)} ᴍᴇᴅɪᴀ")
    caption_parts.append("━━━━━━━━━━━━━━━━━━━━━━")
    
    # Add file list in expandable blockquote
    caption_parts.append("<blockquote expandable>")
    for idx, (typ, file_id, original_caption, filename, file_size, user_info) in enumerate(items, 1):
        formatted_size = _format_file_size(file_size)
        caption_parts.append(f"{idx}. {filename} ({formatted_size})")
    caption_parts.append("</blockquote>")
    
    caption_parts.append("━━━━━━━━━━━━━━━━━━━━━━")
    caption_parts.append(user_line)
    caption_parts.append(f"📅 ᴅᴀᴛᴇ: {date_str}")
    
    # Check for original captions
    original_captions = [item[2] for item in items if item[2]]
    if original_captions:
        caption_parts.append("━━━━━━━━━━━━━━━━━━━━━━")
        caption_parts.append("📝 ᴏʀɪɢɪɴᴀʟ ᴄᴀᴘᴛɪᴏɴs:")
        for cap in original_captions[:3]:  # Limit to first 3 to avoid caption length limit
            caption_parts.append(f"• {cap[:100]}")  # Truncate long captions
    
    final_caption = "\n".join(caption_parts)
    # Telegram caption limit is 1024 chars
    if len(final_caption) > 1024:
        final_caption = final_caption[:1020] + "..."
    return final_caption


def _send_with_retry(send_func, max_retries=3, delay=2.0):
    """Retry sending with exponential backoff"""
    for attempt in range(max_retries):
        try:
            send_func()
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = delay * (2 ** attempt)  # Exponential backoff
                logger.warning(f"Send failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                time.sleep(wait_time)
            else:
                logger.exception(f"Failed after {max_retries} attempts: {e}")
                return False
    return False


def forward_album_to_database(context: CallbackContext, items, chat_id=None):
    """Forward media as album to database channel with retry logic and progress tracking"""
    if not DB_CHANNEL_ID:
        logger.warning("DB_CHANNEL_ID not set - skipping database forward")
        return
    
    if not items:
        return
    
    total_items = len(items)
    logger.info(f"Starting to forward {total_items} items to database channel")
    
    try:
        date_str = datetime.now().strftime("%Y-%m-%d")
        
        # Separate groupable and non-groupable media
        groupable_items = []  # photos and videos only
        non_groupable_items = []  # documents, audio, voice, animation
        
        for item in items:
            typ = item[0]
            if typ in ("photo", "video"):
                groupable_items.append(item)
            else:
                non_groupable_items.append(item)
        
        total_albums = (len(groupable_items) + 9) // 10  # Ceiling division
        sent_count = 0
        failed_count = 0
        
        # Send groupable items as albums (max 10 per album)
        chunk_size = 10
        for album_idx, i in enumerate(range(0, len(groupable_items), chunk_size), 1):
            chunk = groupable_items[i:i + chunk_size]
            media_group = []
            
            # Build caption for first item only
            album_caption = _build_album_caption(chunk, date_str)
            
            for idx, (typ, file_id, original_caption, filename, file_size, user_info) in enumerate(chunk):
                try:
                    # Only first item gets caption
                    caption = album_caption if idx == 0 else None
                    
                    if typ == "photo":
                        media_group.append(InputMediaPhoto(media=file_id, caption=caption, parse_mode='HTML'))
                    elif typ == "video":
                        media_group.append(InputMediaVideo(media=file_id, caption=caption, parse_mode='HTML'))
                except Exception as e:
                    logger.exception(f"Failed to prepare media for DB: {e}")
                    failed_count += 1
            
            if media_group:
                def send_album():
                    context.bot.send_media_group(chat_id=DB_CHANNEL_ID, media=media_group)
                
                success = _send_with_retry(send_album)
                if success:
                    sent_count += len(media_group)
                    logger.info(f"✓ Forwarded album {album_idx}/{total_albums} ({len(media_group)} items) to database channel")
                    
                    # Progress update to user every 5 albums for large batches
                    if chat_id and total_albums > 10 and album_idx % 5 == 0:
                        try:
                            context.bot.send_message(
                                chat_id=chat_id,
                                text=f"📤 Progress: {sent_count}/{total_items} items forwarded to database..."
                            )
                        except Exception:
                            pass
                else:
                    failed_count += len(media_group)
                
                # Dynamic delay based on batch size
                if total_albums > 50:
                    time.sleep(1.0)  # Longer delay for huge batches
                elif total_albums > 20:
                    time.sleep(0.7)
                else:
                    time.sleep(0.5)
        
        # Send non-groupable items individually with caption
        for item_idx, (typ, file_id, original_caption, filename, file_size, user_info) in enumerate(non_groupable_items, 1):
            try:
                # Build single item caption
                formatted_size = _format_file_size(file_size)
                if user_info['username']:
                    user_line = f"👤 ᴜsᴇʀ: {user_info['name']} (@{user_info['username']}) ({user_info['id']})"
                else:
                    user_line = f"👤 ᴜsᴇʀ: {user_info['name']} ({user_info['id']})"
                
                caption = (
                    f"📂 ɴᴀᴍᴇ: {filename}\n"
                    f"📦 sɪᴢᴇ: {formatted_size}\n"
                    f"{user_line}\n"
                    f"📅 ᴅᴀᴛᴇ: {date_str}"
                )
                
                if original_caption:
                    caption = f"📝 ᴄᴀᴘᴛɪᴏɴ: {original_caption[:200]}\n━━━━━━━━━━━━━━━━━━━━━━\n{caption}"
                
                def send_item():
                    if typ == "document":
                        context.bot.send_document(chat_id=DB_CHANNEL_ID, document=file_id, caption=caption)
                    elif typ == "animation":
                        context.bot.send_animation(chat_id=DB_CHANNEL_ID, animation=file_id, caption=caption)
                    elif typ == "audio":
                        context.bot.send_audio(chat_id=DB_CHANNEL_ID, audio=file_id, caption=caption)
                    elif typ == "voice":
                        context.bot.send_voice(chat_id=DB_CHANNEL_ID, voice=file_id, caption=caption)
                
                success = _send_with_retry(send_item)
                if success:
                    sent_count += 1
                    logger.info(f"✓ Forwarded {typ} ({item_idx}/{len(non_groupable_items)}) to database channel")
                else:
                    failed_count += 1
                
                time.sleep(0.4)  # Delay for individual items
            except Exception as e:
                logger.exception(f"Failed to forward {typ} to database channel: {e}")
                failed_count += 1
        
        # Final summary
        logger.info(f"✓ Database forwarding complete: {sent_count}/{total_items} sent, {failed_count} failed")
        
        # Send completion message to user
        if chat_id:
            try:
                if failed_count > 0:
                    context.bot.send_message(
                        chat_id=chat_id,
                        text=f"✅ Forwarded {sent_count}/{total_items} items to database\n⚠️ {failed_count} items failed"
                    )
                else:
                    context.bot.send_message(
                        chat_id=chat_id,
                        text=f"✅ All {sent_count} items successfully forwarded to database!"
                    )
            except Exception:
                pass
    
    except Exception as e:
        logger.exception(f"Failed to forward album to database channel: {e}")


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
    file_size = _get_file_size(msg, media_type)
    user_info = _get_user_info(msg)
    
    # Store all info needed for later forwarding
    _append_media(chat_id, (media_type, file_id, original_caption, filename, file_size, user_info))
    
    logger.info(f"Received {media_type} from user {user_info['id']} - queued for processing")

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
            total = len(items)
            
            if total > 100:
                update.message.reply_text(
                    f"📚 Processing {total} media files...\n⏳ This may take a few minutes.",
                    reply_markup=ReplyKeyboardRemove()
                )
            else:
                update.message.reply_text(
                    f"📚 Creating album from {total} media...",
                    reply_markup=ReplyKeyboardRemove()
                )
            
            # Send album to user
            send_media_as_album(context, chat_id)
            
            # Forward to database channel as album with progress tracking
            items_copy = list(items)  # Copy before clearing
            forward_album_to_database(context, items_copy, chat_id=chat_id)
        else:
            update.message.reply_text("No media found. Send media first.")
        return


def send_media_with_mode(context: CallbackContext, chat_id: int, mode: str, user_text: str):
    pass


def send_media_as_album(context: CallbackContext, chat_id: int):
    """Send media as albums with max 10 items per group, caption on first item only"""
    items = pending_media.get(chat_id, [])
    if not items:
        return
    
    # Separate groupable and non-groupable media
    groupable_items = []  # photos and videos only
    non_groupable_items = []  # documents, audio, voice, animation
    
    for item in items:
        typ = item[0]
        if typ in ("photo", "video"):
            groupable_items.append(item)
        else:
            non_groupable_items.append(item)
    
    # Send groupable items as albums (max 10 per album)
    chunk_size = 10
    for i in range(0, len(groupable_items), chunk_size):
        chunk = groupable_items[i:i + chunk_size]
        media_group = []
        
        # Get caption from first item that has one, use it as album caption
        album_caption = None
        for item in chunk:
            if item[2]:  # original_caption at index 2
                album_caption = item[2]
                break
        
        for idx, (typ, file_id, original_caption, filename, file_size, user_info) in enumerate(chunk):
            try:
                # Only first item gets caption (becomes album caption)
                caption = album_caption if idx == 0 else None
                
                if typ == "photo":
                    media_group.append(InputMediaPhoto(media=file_id, caption=caption))
                elif typ == "video":
                    media_group.append(InputMediaVideo(media=file_id, caption=caption))
            except Exception as e:
                logger.exception("Failed to prepare media: %s", e)
        
        # Send the media group if we have items
        if media_group:
            try:
                context.bot.send_media_group(chat_id=chat_id, media=media_group)
                time.sleep(0.3)  # Small delay between albums
            except Exception as e:
                logger.exception("Failed to send media group: %s", e)
    
    # Send non-groupable items individually
    for typ, file_id, original_caption, filename, file_size, user_info in non_groupable_items:
        try:
            if typ == "document":
                context.bot.send_document(chat_id=chat_id, document=file_id, caption=original_caption)
            elif typ == "animation":
                context.bot.send_animation(chat_id=chat_id, animation=file_id, caption=original_caption)
            elif typ == "audio":
                context.bot.send_audio(chat_id=chat_id, audio=file_id, caption=original_caption)
            elif typ == "voice":
                context.bot.send_voice(chat_id=chat_id, voice=file_id, caption=original_caption)
            time.sleep(0.2)
        except Exception as e:
            logger.exception(f"Failed to send {typ}: %s", e)
    
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
