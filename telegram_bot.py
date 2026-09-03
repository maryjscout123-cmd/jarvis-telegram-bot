"""
telegram_bot.py — Local JARVIS Telegram poller (runs beside Jarvis_Local.bat).
Polls @AyomideJarvis_bot via getUpdates and replies via Muse Spark brain.
Use this when HF n8n -> Telegram is slow (30s timeout). Works when PC is on.
"""

import os, time, json, requests

def load_env(p=".env"):
    try:
        if not os.path.exists(p):
            return
        for line in open(p,encoding="utf-8"):
            line=line.strip()
            if line and not line.startswith("#") and "=" in line:
                k,v=line.split("=",1); k=k.strip(); v=v.strip().strip('"').strip("'")
                if k and v and k not in os.environ: os.environ[k]=v
    except Exception:
        pass
for _p in (".env",):
    load_env(_p)

_poll_status = {"last_poll": "never", "last_err": "", "offset": 0, "polls": 0}
_last_chat_id = None
# Reminder checker — runs every 15s, sends due reminders via Telegram
def _reminder_loop():
    while True:
        try:
            if _rem:
                due = _rem.check_due()
                for task in due:
                    cid = _last_chat_id
                    if cid:
                        try:
                            requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage", json={"chat_id": cid, "text": f"⏰ Reminder, sir: {task}"}, timeout=10)
                        except Exception as e:
                            print("reminder send err", e)
                    print(f"⏰ Reminder due: {task}")
        except Exception as e:
            print("reminder loop err", e)
        time.sleep(15)
import threading as _th
_th.Thread(target=_reminder_loop, daemon=True).start()
# HF health check: Docker Spaces must listen on 7860
def _health():
    try:
        from http.server import BaseHTTPRequestHandler, HTTPServer
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    import requests as rq
                    # Test Telegram reachability from HF
                    try:
                        r=rq.get(f"https://api.telegram.org/bot{BOT}/getMe", timeout=5)
                        tg_ok = f"tg getMe {r.status_code}"
                    except Exception as e:
                        tg_ok = f"tg err {e}"
                except Exception as e:
                    tg_ok = f"err {e}"
                body = f"JARVIS Telegram bot running\nModel {MODEL}\nKey {'yes' if KEY else 'no'}\nPolls {_poll_status['polls']} last:{_poll_status['last_poll']} err:{_poll_status['last_err']}\nTG:{tg_ok}\nOffset {_poll_status['offset']}".encode()
                self.send_response(200); self.send_header("Content-type","text/plain"); self.end_headers(); self.wfile.write(body)
            def log_message(self, *a): pass
        s=HTTPServer(("0.0.0.0", 7860), H)
        import threading; threading.Thread(target=s.serve_forever, daemon=True).start()
        print("Health server on :7860")
    except Exception as e:
        print("health err", e)
_health()

BOT=(os.environ.get("TELEGRAM_BOT_TOKEN") or "8825546647:AAGxv77FD5xEEk-yQOFZg7_OXBPRwAGv3gs").strip()
ZEN_URL="https://opencode.ai/zen/v1/responses"
MODEL=os.environ.get("OPENCODE_MODEL","muse-spark-1.2-contributor-free")
KEY=(os.environ.get("OPENCODE_API_KEY") or "").strip()

# Reminders support (Firebase or local fallback)
try:
    import reminders as _rem
except Exception:
    _rem = None

def _pc_status():
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        if not firebase_admin._apps:
            cred=os.path.join(os.path.dirname(__file__),"firebase_service_account.json")
            if os.path.exists(cred):
                firebase_admin.initialize_app(credentials.Certificate(cred))
        db=firestore.client()
        doc=db.collection("jarvis_status").document("pc").get()
        if doc.exists:
            d=doc.to_dict()
            age=time.time()-d.get("last_seen",0)
            on = age < 90
            return on, d, age
    except Exception as e:
        return None, {"error": str(e)}, 9999
    return False, {}, 9999

PC_BRIDGE_URL=(os.environ.get("PC_BRIDGE_URL") or "").strip()
ALLOWED_UID=(os.environ.get("JARVIS_TG_UID") or "").strip()

def _try_pc_bridge(text):
    """Route a PC-action request to the local bridge (works only when PC is ON)."""
    low=text.lower()
    trigger = any(k in low for k in [" open ", " open ", "create a file", "screenshot",
                                     "play ", "pause", "youtube", "stop music", "close ",
                                     "search youtube", "open app", "control", "volume"])
    if not trigger or not PC_BRIDGE_URL:
        return None
    try:
        r=requests.post(PC_BRIDGE_URL, json={"text": text}, timeout=25)
        if r.status_code==200:
            return (r.json() or {}).get("reply")
    except Exception as e:
        pass
    return None

def brain(text):
    # When running on the PC itself, use the full local brain (MCP, Chrome, screenshots)
    try:
        import local_brain as lb
        ans = lb.handle(text)
        if ans:
            return ans
    except Exception as e:
        pass
    # On cloud/server: route PC-actions to the local bridge if the PC is on
    pcb = _try_pc_bridge(text)
    if pcb:
        return pcb
    # Task requires the PC but we're on the cloud — check if PC is reachable
    low = text.lower()
    needs_pc = any(k in low for k in [
        "downloads folder", "desktop folder", "documents folder", "what's in my",
        "what is in my", "list my files", "my files", "open my", "open the",
        "screenshot", "play video", "play music", "stop music", "volume",
        "search youtube", "open app", "open application", "create a file",
        "what is on my screen", "control my pc", "close the", "start the",
        "run program", "my pc's", "my pc ", "navigate to",
    ])
    if needs_pc:
        on, d, age = _pc_status()
        if on is True:
            # PC on but bridge couldn't reach it / not configured
            if not PC_BRIDGE_URL:
                return "Your PC is ON, sir, but the cloud bridge isn't configured, so I can't reach your folders from here. Ask me on the PC itself, or set up the bridge."
            return "Your PC is ON, sir, but I couldn't reach it for that task right now."
        if on is False:
            return "Your PC is OFF, sir, so I can't access your files or control apps. Turn it on (with Jarvis running) and ask again."
    if not KEY: return "Missing OPENCODE_API_KEY, sir."
    low=text.lower()
    # Reminders (Telegram bot is the JARVIS on HF — must handle them)
    if _rem and ("remind me" in low or "wake me up in" in low):
        try:
            confirm, _task = _rem.parse_and_add(text)
            if confirm: return confirm
        except Exception as e:
            return f"Couldn't set reminder, sir: {e}"
    if _rem and ("pending reminders" in low or "list reminders" in low or "what are my reminders" in low):
        try: return _rem.list_pending()
        except Exception as e: return f"Couldn't list reminders: {e}"
    # Memory / save to database
    if "save this to" in low and "database" in low:
        try:
            import memory_cloud
            # Try to save last user message as memory; if phrase is generic, save it
            ok = memory_cloud.remember(text)
            return "Saved to your database, sir." if ok else "I couldn't save that, sir — database offline."
        except Exception as e:
            return f"Save failed: {e}"
    if "remember that" in low:
        try:
            import memory_cloud
            fact = text.lower().split("remember that",1)[1].strip(" .")
            ok = memory_cloud.remember(fact)
            return "Right away, I'll remember that, sir." if ok else "Couldn't save, sir."
        except Exception: pass
    # PC status queries
    if "is my pc on" in low or "is pc on" in low or "pc status" in low:
        on, d, age = _pc_status()
        if on is None: return f"I couldn't check PC status, sir: {d.get('error')}"
        if on: return f"Yes, your PC is ON, sir — last heartbeat {int(age)}s ago ({d.get('last_seen_str')}). {d.get('details','')}"
        return f"Your PC is OFF, sir — last seen {int(age)}s ago at {d.get('last_seen_str','unknown')}."
    if "where" in low and "conversation" in low and ("save" in low or "store" in low):
        on, d, age = _pc_status()
        loc = d.get("conversation_saved","Firebase jarvis_memory + local history") if d else "Firebase jarvis_memory"
        return f"Conversations are saved in {loc}, sir. PC is {'ON' if on else 'OFF'}."
    if "collect" in low and "details" in low and "pc" in low:
        on, d, age = _pc_status()
        if on: return f"Collected from your PC (ON): {d.get('details','')} — heartbeat {int(age)}s ago, sir."
        return "Your PC is OFF, sir — I can't collect fresh details until it's on. Last details: " + d.get("details","none")
    if "what time" in low or "time is it" in low:
        return f"It is {time.strftime('%I:%M %p on %A, %B %d, %Y').lstrip('0')}, sir."
    if "hello" in low and len(low)<20: return "At your service, sir. What do you need?"
    payload={"model": MODEL, "input": [{"role":"user","content": text}], "instructions": "You are J.A.R.V.I.S., witty loyal assistant. Under 2 sentences."}
    headers={"Authorization": f"Bearer {KEY}", "Content-Type":"application/json"}
    r=requests.post(ZEN_URL, json=payload, headers=headers, timeout=45)
    data=r.json()
    out=[]
    for item in data.get("output") or []:
        if item.get("type")=="message":
            for c in item.get("content") or []:
                if c.get("type")=="output_text": out.append(c.get("text",""))
    return "".join(out).strip() or "(no reply)"

def main():
    global _last_chat_id
    offset=0
    print(f"JARVIS Telegram poller live (model {MODEL}) - polling @AyomideJarvis_bot")
    while True:
        try:
            _poll_status["polls"]+=1; _poll_status["last_poll"]=time.strftime("%H:%M:%S")
            r=requests.get(f"https://api.telegram.org/bot{BOT}/getUpdates", params={"offset": offset, "timeout": 5}, timeout=10)
            _poll_status["last_err"]=""
            data=r.json()
            for upd in data.get("result") or []:
                offset=upd["update_id"]+1; _poll_status["offset"]=offset
                msg=upd.get("message") or {}
                chat=msg.get("chat") or {}; text=msg.get("text") or ""
                uid=str((msg.get("from") or {}).get("id") or chat.get("id") or "")
                cid=chat.get("id")
                if not text or not cid: continue
                if ALLOWED_UID and uid != ALLOWED_UID:
                    requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage", json={"chat_id": cid, "text": "Access denied, sir."}, timeout=10)
                    continue
                _last_chat_id = cid
                print(f"📩 {text} from {cid}")
                reply=brain(text)
                requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage", json={"chat_id": cid, "text": reply}, timeout=10)
                print(f"📤 {reply[:80]}")
        except Exception as e:
            _poll_status["last_err"]=str(e)[:120]
            print("poll err", e)
            time.sleep(3)

if __name__=="__main__":
    main()
