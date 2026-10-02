import os
import io
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, MessagingApiBlob, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent
from google import genai
from PIL import Image

app = FastAPI()

# 1. ใส่ Key ทั้ง 3 ตัวตรงนี้ (หรือดึงจาก Environment Variables)
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "6a2cb56f5c5bc79cdc7337d676332899")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "+JRnWH/QUopWFr8MB2LZlEw/Ww9S7G3lLR37yk0fHewOFu7sH3Q32l8t2QsLR0h+WPQD4pdgsHCzE/iBQwLB6ZBxQrXovp2ajEL1nZgWupCDAjgMK3RP6mljs5C4Hijo2R7osYAK5PXO1JbIYVWBNAdB04t89/1O/w1cDnyilFU=")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "RathTan")

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
        config={"system_instruction": SYSTEM_INSTRUCTION}
    )
    
    result = response.text.strip()
    
    # ถ้า Gemini เตือนว่ามีการละเมิดกฎ ให้บอทตอบเตือนในกลุ่ม
    if "VIOLATION" in result:
        warning_msg = f"⚠️ เตือนความประพฤติ:\n{result}"
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=warning_msg)]
                )
            )

# ดักจับรูปภาพ
@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    message_id = event.message.id
    
    # โหลดไฟล์รูปจาก LINE
    with ApiClient(configuration) as api_client:
        line_bot_blob_api = MessagingApiBlob(api_client)
        image_bytes = line_bot_blob_api.get_message_content(message_id)
        
    image = Image.open(io.BytesIO(image_bytes))
    
    # ส่งรูปภาพไปให้ Gemini วิเคราะห์
    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[image, "วิเคราะห์รูปนี้ว่าปลอดภัยหรือขัดต่อกฎหรือไม่"],
        config={"system_instruction": SYSTEM_INSTRUCTION}
    )
    
    result = response.text.strip()
    
    if "VIOLATION" in result:
        warning_msg = f"⚠️ เตือนรูปภาพไม่อนุญาต:\n{result}"
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=warning_msg)]
                )
            )