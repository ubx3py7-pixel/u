# pip install playwright python-telegram-bot
# playwright install chromium

import asyncio, random, re
from pathlib import Path
from datetime import datetime

from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

# ───────── CONFIG ─────────
BOT_TOKEN = "8375060248:AAEOCPp8hU2lBYqDGt1SYwluQDQgqmDfWWA"
SIGNUP_URL = "https://www.instagram.com/accounts/emailsignup/"
HEADLESS = False

SCREENSHOTS = Path("ig_signup_shots")
SCREENSHOTS.mkdir(exist_ok=True)

EMAIL, NAME, PASSWORD, USERNAME, OTP = range(5)

# ───────── HUMAN BEHAVIOR ─────────
async def human_delay(a=0.4, b=1.4):
    await asyncio.sleep(random.uniform(a, b))

async def human_type(page, selector, text):
    el = await page.wait_for_selector(selector, timeout=15000)
    await el.scroll_into_view_if_needed()
    await el.click(force=True)
    await asyncio.sleep(0.3)

    # clear input
    await page.keyboard.down("Control")
    await page.keyboard.press("A")
    await page.keyboard.up("Control")
    await page.keyboard.press("Backspace")

    for ch in text:
        await page.keyboard.type(ch)
        await asyncio.sleep(random.uniform(0.06, 0.16))

# ───────── HELPERS ─────────
def rnd_dob():
    return random.randint(1,28), random.randint(1,12), random.randint(1990,2005)

async def snap(page, chat_id, ctx, tag):
    p = SCREENSHOTS / f"{chat_id}_{tag}.png"
    await page.screenshot(path=p)
    await ctx.bot.send_photo(chat_id, photo=p, caption=tag)

async def auto_accept_cookies(page):
    for _ in range(6):
        try:
            await page.evaluate("""
                document.querySelectorAll(
                    '[role="dialog"], [aria-modal="true"]'
                ).forEach(e => e.remove());
            """)
        except:
            pass

        for txt in ["allow all", "accept all", "accept cookies", "allow cookies"]:
            try:
                btn = page.get_by_role("button", name=re.compile(txt, re.I))
                if await btn.is_visible():
                    await btn.click(force=True, timeout=2000)
                    await asyncio.sleep(0.8)
                    return True
            except:
                pass
        await asyncio.sleep(0.8)
    return False

# ───────── PAGE DETECTORS ─────────
async def otp_page(page):
    return bool(await page.query_selector(
        'input[autocomplete="one-time-code"], text=/enter.*code/i'
    ))

async def success_page(page):
    return any(x in page.url for x in [
        "/accounts/onetap/",
        "/accounts/welcome",
        "/accounts/edit/",
        "/feed/"
    ])

# ───────── FLOW ─────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📧 Send email")
    return EMAIL

async def email_step(update, ctx):
    ctx.user_data["email"] = update.message.text.strip()
    await update.message.reply_text("👤 Send full name")
    return NAME

async def name_step(update, ctx):
    ctx.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("🔑 Send password")
    return PASSWORD

async def password_step(update, ctx):
    ctx.user_data["password"] = update.message.text.strip()

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=HEADLESS,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
    )
    page = await browser.new_page()
    await page.set_viewport_size({"width": 1366, "height": 900})

    ctx.user_data.update({"pw": pw, "browser": browser, "page": page})

    await page.goto(SIGNUP_URL, timeout=60000)
    await auto_accept_cookies(page)

    await human_type(page, 'input[name="emailOrPhone"]', ctx.user_data["email"])
    await human_type(page, 'input[name="fullName"]', ctx.user_data["name"])
    await human_type(page, 'input[type="password"]', ctx.user_data["password"])

    d,m,y = rnd_dob()
    for sel,val in zip(["month","day","year"], [m,d,y]):
        try:
            await page.select_option(f'select[name="{sel}"]', str(val))
        except:
            pass

    await snap(page, update.effective_chat.id, ctx, "details_filled")
    await update.message.reply_text("🆔 Send username or **yes** for random")
    return USERNAME

async def username_step(update, ctx):
    page = ctx.user_data["page"]
    chat_id = update.effective_chat.id

    base = update.message.text.strip()
    if base.lower() == "yes":
        base = "user"

    for _ in range(10):
        username = f"{base}{random.randint(1000,999999)}"

        await human_type(page, 'input[name="username"]', username)
        await page.keyboard.press("Tab")
        await human_delay(2,3)

        await auto_accept_cookies(page)

        try:
            btn = page.get_by_role("button", name=re.compile("Next", re.I))
            if not await btn.get_attribute("disabled"):
                await btn.click(force=True)
                await human_delay(4,5)
                break
        except:
            continue
    else:
        await update.message.reply_text("❌ Username rejected. Send another.")
        return USERNAME

    await snap(page, chat_id, ctx, "username_ok")

    if await otp_page(page):
        await update.message.reply_text("📩 Send **6-digit OTP**")
        return OTP

    await update.message.reply_text("Waiting for OTP page…")
    return OTP

async def otp_step(update, ctx):
    page = ctx.user_data["page"]
    chat_id = update.effective_chat.id
    otp = update.message.text.strip()

    if not otp.isdigit() or len(otp) != 6:
        await update.message.reply_text("❌ Send valid 6-digit OTP")
        return OTP

    for sel in [
        'input[autocomplete="one-time-code"]',
        'input[name*="confirmation"]'
    ]:
        try:
            await human_type(page, sel, otp)
            break
        except:
            continue

    await page.keyboard.press("Enter")
    await human_delay(6,7)

    await snap(page, chat_id, ctx, "otp_entered")

    if await success_page(page):
        await update.message.reply_text("🎉 **Account CREATED successfully**")
    else:
        await update.message.reply_text(
            "⚠️ OTP submitted, but success not detected.\nCheck browser."
        )

    # browser intentionally NOT closed
    return ConversationHandler.END

# ───────── MAIN ─────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            EMAIL: [MessageHandler(filters.TEXT, email_step)],
            NAME: [MessageHandler(filters.TEXT, name_step)],
            PASSWORD: [MessageHandler(filters.TEXT, password_step)],
            USERNAME: [MessageHandler(filters.TEXT, username_step)],
            OTP: [MessageHandler(filters.TEXT, otp_step)],
        },
        fallbacks=[],
    )

    app.add_handler(conv)
    print("🤖 Bot running")
    app.run_polling()

if __name__ == "__main__":
    main()
