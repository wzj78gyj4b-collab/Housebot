import os
import json
import logging
import asyncio
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

async def process_message(text: str, retries: int = 3, delay: int = 2) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        logging.error("Kein API-Key gefunden!")
        return {"is_safe": True, "reply": "Kein API-Key in der .env hinterlegt."}

    client = genai.Client(api_key=api_key)
    
    # Der bewährte, kurze Charakter-Prompt
    system_instruction = (
        "Du bist ein brillanter, aber extrem zynischer, misanthropischer Diagnostiker (wie Dr. House). "
        "Nenne NIEMALS deinen Namen und bleib anonym! "
        "Deine Antworten müssen EXTREM KURZ sein! Maximal 1 bis 2 Sätze. Maximal 15 bis 20 Wörter. "
        "Antworte AUSSCHLIESSLICH im JSON-Format mit genau zwei Schlüsseln:\n"
        '1. "is_safe": (boolean) false bei extremem Spam, sonst IMMER true.\n'
        '2. "reply": (string) Deine extrem kurze, genervte Antwort.'
    )
    
    # Zurück zu dem Modell, das bei deinem Anbieter nachweislich funktioniert hat
    model_name = "gemini-3.8-flash"
    
    for attempt in range(retries):
        try:
            response = await client.aio.models.generate_content(
                model=model_name,
                contents=text,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.7 
                )
            )
            
            raw_text = response.text.strip()
            
            # Falls die API unerlaubt Markdown mitsendet, wird es hier rasiert
            if raw_text.startswith("```json"): raw_text = raw_text[7:]
            if raw_text.startswith("```"): raw_text = raw_text[3:]
            if raw_text.endswith("```"): raw_text = raw_text[:-3]
                
            data = json.loads(raw_text.strip())
            
            return {
                "is_safe": data.get("is_safe", True),
                "reply": data.get("reply", "")
            }
            
        except json.JSONDecodeError as e:
            logging.error(f"JSON-Fehler: {e} | Text war: {response.text}")
            return {"is_safe": True, "reply": "Laborergebnisse unlesbar. Formatierungsfehler."}
            
        except Exception as e:
            error_str = str(e)
            
            # 503 = Server überlastet (normal) -> Kurz warten
            if "503" in error_str and attempt < retries - 1:
                logging.warning(f"Server 503. Versuch {attempt+1}...")
                await asyncio.sleep(delay)
                continue
                
            # 429 = Rate Limit (zu viele Fragen in kurzer Zeit) -> Länger warten!
            elif "429" in error_str and attempt < retries - 1:
                logging.warning(f"Rate Limit 429 erreicht! Warte {delay * 3} Sekunden...")
                await asyncio.sleep(delay * 3)
                continue
                
            else:
                logging.error(f"API Fehler abgewürgt: {error_str}")
                return {"is_safe": True, "reply": "Systemfehler. Wahrscheinlich Lupus."}
                
    return {"is_safe": True, "reply": "Systemfehler. Wahrscheinlich Lupus."}
