import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("AI_API_KEY"))

HOUSE_SYSTEM_PROMPT = (
    "Du bist 'Housebot', ein Telegram-Moderations- und Assistenz-Bot mit genau dem Charakter "
    "von Dr. Gregory House. Du bist hochintelligent, extrem zynisch, sarkastisch, hasst "
    "Inkompetenz und bist völlig genervt von dummen Fragen, Spam oder sinnlosen Nachrichten. "
    "Du hilfst zwar, wenn man dich fragst, aber du lässt den Nutzer bei jeder Gelegenheit spüren, "
    "wie intellektuell überlegen du bist. Du benutzt Phrasen wie 'Alle lügen' oder machst dich "
    "über die Unfähigkeit der Leute lustig. Antworte immer auf Deutsch."
)

async def process_message(text: str) -> dict:
    try:
        prompt = (
            f"Analysiere die folgende Nachricht im Kontext deines Charakters.\n"
            f"Nachricht des Users: \"{text}\"\n\n"
            "Gib deine Antwort AUSSCHLIESSLICH als JSON-Objekt im folgenden Format zurück:\n"
            "{\n"
            "  \"is_safe\": false (falls es reiner Spam, extreme Beleidigung oder NSFW ist, sonst true),\n"
            "  \"reply\": \"Deine zynische House-Antwort, falls der Bot direkt angesprochen wurde oder eine Frage gestellt wird. Wenn es normaler Smalltalk ist und der Bot nicht angesprochen wurde, lass es leer ('').\"\n"
            "}"
        )

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=HOUSE_SYSTEM_PROMPT,
                response_mime_type="application/json",
            ),
        )

        return json.loads(response.text)
    except Exception as e:
        print(f"Google AI Fehler: {e}")
        return {"is_safe": True, "reply": ""}
