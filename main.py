import os
import io
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from google import genai

app = FastAPI()

# ดึง Keys จาก Environment Variables บน Render
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

ADMIN_LINE_USER_ID = ""

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# System Prompt สำหรับตรวจคุมกลุ่ม
MODERATOR_PROMPT = """
คุณคือระบบดูแลความปลอดภัยใน LINE Group
วิเคราะห์ข้อความว่าเข้าข่ายละเมิดกฎหรือไม่ (คำหยาบ, สแปม, พนัน, NSFW)
- ถ้าปกติ ตอบ: "SAFE"
- ถ้าละเมิด ตอบ: "VIOLATION: [บอกสาเหตุสั้นๆ]"
"""

# System Prompt สำหรับคุยทักทาย
CHAT_PROMPT = """
คุณคือผู้ช่วยประจำกลุ่ม LINE ชื่อ Calyx เป็นมิตร สุภาพ ตอบสั้นกระชับ เป็นกันเอง
"""

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
    
    try:
        # 1. ให้ Gemini ตรวจความปลอดภัยโดยรวม System Prompt ไว้ในข้อความเดียว
        mod_response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{MODERATOR_PROMPT}\n\nข้อความที่จะตรวจ: {user_text}"
        )
        mod_result = mod_response.text.strip()
        
        # ถ้าพบข้อความผิดกฎ ให้เตือนทันที
        if "VIOLATION" in mod_result:
            sender_id = event.source.user_id
            warning_msg = (
                f"⚠️ ตรวจพบเนื้อหาละเมิดกฎกลุ่ม!\n"
                f"👤 ผู้ส่ง: {sender_id}\n"
                f"📋 เหตุผล: {mod_result}\n\n"
                f"🔔 แจ้งเตือนแอดมิน โปรดตรวจสอบครับ"
            )
            send_reply(event.reply_token, warning_msg)
            return

        # 2. แปลงข้อความเพื่อเช็กว่ามีการเรียกชื่อบอทหรือไม่
        text_lower = user_text.lower()
        bot_keywords = ["บอท", "bot", "calyx", "แคลกซ์", "@calyx"]
        
        # ถ้ามีชื่อบอท ให้ Gemini ตอบคุยกลับ
        if any(keyword in text_lower for keyword in bot_keywords):
            chat_response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"{CHAT_PROMPT}\n\nผู้ใช้พิมพ์ว่า: {user_text}"
            )
            send_reply(event.reply_token, chat_response.text.strip())

    except Exception as e:
        print(f"Error handling message: {e}")

def send_reply(reply_token, text):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)]
            )
        )
