import os
import io
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, MessagingApiBlob, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent
from google import genai
from google.genai import types
from PIL import Image

app = FastAPI()

# 1. ดึง Keys จาก Environment Variables บน Render
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 2. ใส่ LINE User ID ของ Admin กลุ่มที่นี่ (เว้นว่างไว้ก่อนได้ครับ)
ADMIN_LINE_USER_ID = ""

# ตั้งค่า LINE SDK
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ตั้งค่า Gemini Client
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# System Prompt กำหนดบทบาทให้ Gemini ตรวจสอบเนื้อหา
SYSTEM_INSTRUCTION = """
คุณคือระบบผู้ช่วยดูแลความปลอดภัยใน LINE Group (Moderator Bot)
หน้าที่ของคุณคือวิเคราะห์ข้อความหรือรูปภาพว่าเข้าข่ายละเมิดกฎกลุ่มหรือไม่:
1. คำหยาบคาย รุนแรง หรือสร้างความเกลียดชัง (Hate Speech)
2. โฆษณาสแปม พนันออนไลน์ หลอกลวง (Spam / Scam)
3. ภาพอนาจาร / สื่อลามก (NSFW)

คำตอบของคุณต้องกระชับ สั้น และตรงประเด็น
- หากเป็นเนื้อหาปกติ ตอบเพียง: "SAFE"
- หากละเมิดกฎ ตอบสั้นๆ บอกสาเหตุ เช่น: "VIOLATION: พบคำหยาบคาย/สแปม"
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

# ดักจับข้อความตัวอักษร
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    user_text = event.message.text
    
    # ส่งข้อความไปให้ Gemini วิเคราะห์
    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_text,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION
        )
    )
    
    result = response.text.strip()
    
    # กรณีตรวจพบการละเมิดกฎ (VIOLATION)
    if "VIOLATION" in result:
        sender_id = event.source.user_id
        
        warning_msg = (
            f"⚠️ ตรวจพบเนื้อหาละเมิดกฎกลุ่ม!\n"
            f"👤 ผู้ส่ง: {sender_id}\n"
            f"📋 เหตุผล: {result}\n\n"
            f"🔔 แจ้งเตือนแอดมิน: @{ADMIN_LINE_USER_ID} โปรดตรวจสอบและจัดการครับ"
        )
        
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=warning_msg)]
                )
            )
    else:
        # กรณีข้อความปกติ (SAFE)
        reply_txt = f"🤖 ผลการตรวจสอบ:\n{result}"
        
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_txt)]
                )
            )
