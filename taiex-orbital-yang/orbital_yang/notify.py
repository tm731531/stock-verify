"""LINE Messaging API 推播 (重用 tdcc v7 的 LINE_CHANNEL_TOKEN / LINE_USER_ID)。"""
import json
import urllib.request
import urllib.error
from pathlib import Path

CONFIG = Path("/home/tom/stock-verify/tdcc-whale-accumulation/v7/scanner_config.json")
PUSH_URL = "https://api.line.me/v2/bot/message/push"


def load_line_cfg():
    d = json.load(open(CONFIG, encoding="utf-8"))
    return d.get("LINE_CHANNEL_TOKEN", ""), d.get("LINE_USER_ID", "")


def send_line(msg: str, dry: bool = False) -> bool:
    if dry:
        print(f"[DRY] LINE 訊息:\n{msg}\n")
        return True
    token, user_id = load_line_cfg()
    if not token or not user_id:
        print("[LINE] 無 token/user_id")
        return False
    body = json.dumps({"to": user_id, "messages": [{"type": "text", "text": msg}]}).encode("utf-8")
    req = urllib.request.Request(
        PUSH_URL, data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        r = urllib.request.urlopen(req, timeout=10)
        print(f"[LINE] ✅ 成功 ({r.status})")
        return True
    except urllib.error.HTTPError as e:
        print(f"[LINE] ❌ {e.code} {e.read().decode()[:200]}")
        return False
    except Exception as e:
        print(f"[LINE] 異常: {e}")
        return False
