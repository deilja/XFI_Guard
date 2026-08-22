import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

from config import BOT_TOKEN, ADMIN_ID
from database import init_db, save_mapping, get_user_by_admin_message

bot = Bot(token=BOT_TOKEN, default_parse_mode=ParseMode.HTML)
dp = Dispatcher()

support_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="✉️ Написать в поддержку")]],
    resize_keyboard=True,
)


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Добро пожаловать!\n\n"
        "Если возникли вопросы по VPN, нажмите кнопку ниже и отправьте сообщение.",
        reply_markup=support_keyboard,
    )


@dp.message(F.chat.id == ADMIN_ID)
async def admin_reply(message: Message):
    if not message.reply_to_message:
        return

    user_id = await get_user_by_admin_message(message.reply_to_message.message_id)
    if not user_id:
        await message.answer("❌ Не удалось определить пользователя.")
        return

    if message.text:
        await bot.send_message(user_id, f"💬 <b>Ответ поддержки</b>\n\n{message.text}")
    elif message.photo:
        await bot.send_photo(user_id, message.photo[-1].file_id, caption=message.caption)
    elif message.document:
        await bot.send_document(user_id, message.document.file_id, caption=message.caption)
    elif message.video:
        await bot.send_video(user_id, message.video.file_id, caption=message.caption)
    elif message.voice:
        await bot.send_voice(user_id, message.voice.file_id, caption=message.caption)
    elif message.audio:
        await bot.send_audio(user_id, message.audio.file_id, caption=message.caption)
    else:
        await message.answer("❌ Этот тип сообщения пока не поддерживается.")
        return

    await message.answer("✅ Ответ отправлен пользователю.")


@dp.message()
async def user_message(message: Message):
    if message.chat.id == ADMIN_ID:
        return

    forwarded = await bot.forward_message(
        chat_id=ADMIN_ID,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )

    await save_mapping(ADMIN_ID, forwarded.message_id, message.chat.id)

    await message.answer("✅ Ваше сообщение отправлено в поддержку.\nОжидайте ответа оператора.")


async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
