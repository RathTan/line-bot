import os
import time
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from google import genai

app = FastAPI()

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# LINE User ID ของแอดมินสำหรับรับข้อความเตือนส่วนตัว
ADMIN_LINE_USER_ID = "Ce6d78c2ac3b5d00bc369a54ae6fe2921"

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# 1. รายการคำหยาบ/ข้อความต้องห้าม
BAD_WORDS = ["ควย", "สัส", "เหี้ย", "เย็ด", "มึง", "กู", "fuck", "shit"]

CHAT_PROMPT = """
คุณคือผู้ช่วยประจำกลุ่ม LINE ชื่อ Calyx เป็นมิตร สุภาพ ตอบสั้นกระชับ เป็นกันเอง
"""

def generate_gemini_content(prompt_text, retries=1):
    for attempt in range(retries + 1):
        try:
            response = gemini_client.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt_text
            )
            return response.text.strip()
        except Exception as e:
            print(f"Error calling Gemini API: {e}")
            if attempt < retries:
                time.sleep(1)
            else:
                return None

@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    user_text = event.message.text
    text_lower = user_text.lower()

    try:
        # 🟢 1. ตรวจคำหยาบด้วย Python
        found_bad_word = [word for word in BAD_WORDS if word in text_lower]
        if found_bad_word:
            sender_id = event.source.user_id
            
            # ข้อความเตือนตอบกลับลงในกลุ่ม
            group_warning = (
                f"⚠️ ตรวจพบเนื้อหาไม่เหมาะสม!\n"
                f"👤 ผู้ส่ง: {sender_id}\n"
                f"📋 คำที่พบ: {', '.join(found_bad_word)}\n\n"
                f"🔔 ระบบได้แจ้งเตือนแอดมินเรียบร้อยแล้วครับ"
            )
            send_reply(event.reply_token, group_warning)

            # 🚨 ข้อความด่วนส่งตรงเข้าแชทส่วนตัวของแอดมิน
            if ADMIN_LINE_USER_ID:
                private_alert = (
                    f"🚨 [เตือนด่วนแอดมิน]\n"
                    f"พบการพิมพ์คำไม่เหมาะสมในกลุ่ม!\n"
                    f"👤 ผู้ส่ง (User ID): {sender_id}\n"
                    f"💬 ข้อความ: \"{user_text}\"\n"
                    f"📋 คำหยาบที่พบ: {', '.join(found_bad_word)}"
                )
                send_private_push(ADMIN_LINE_USER_ID, private_alert)
            return

        # 🟢 2. คุยตอบเมื่อทักชื่อบอท
        bot_keywords = ["บอท", "bot", "calyx", "แคลกซ์", "@calyx"]
        if any(keyword in text_lower for keyword in bot_keywords):
            chat_result = generate_gemini_content(f"{CHAT_PROMPT}\n\nผู้ใช้พิมพ์ว่า: {user_text}")
            if chat_result:
                send_reply(event.reply_token, chat_result)

    except Exception as e:
        print(f"Error handling message: {e}")

# ฟังก์ชันส่งข้อความตอบกลับในกลุ่ม
def send_reply(reply_token, text):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)]
            )
        )

# ฟังก์ชันส่งข้อความเตือนส่วนตัวถึงแอดมิน (Push Message)
def send_private_push(to_user_id, text):
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=to_user_id,
                    messages=[TextMessage(text=text)]
                )
            )
    except Exception as e:
        print(f"Error sending push message to admin: {e}")
