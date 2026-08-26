# Auto Question Solver & Docs Converter

Solve exam PDFs/images with local ChatGPT OAuth → Excel + Word. Multi-paper queue, live progress, one-command start.

**Repo:** https://github.com/my-skills-app/auto-question-solver-and-docs-convter

## Clone + run (single command)

```powershell
git clone https://github.com/my-skills-app/auto-question-solver-and-docs-convter.git
cd auto-question-solver-and-docs-convter
.\START.bat
```

Mac / Linux:

```bash
git clone https://github.com/my-skills-app/auto-question-solver-and-docs-convter.git
cd auto-question-solver-and-docs-convter
python3 START.py
```

`START.bat` / `START.py` **khud** karega:
1. Setup tool (`uv`) download  
2. **Python auto-download** (manual Python install optional)  
3. Dependencies install  
4. ChatGPT login if needed (browser) — **success ke baad hi** server  
5. Open http://127.0.0.1:7860  

Pehli baar **internet** chahiye. Tokens local pe save hote hain — git me nahi jaate.

---

## Web UI

1. Multiple PDF/image upload  
2. Ek-ek paper solve (queue)  
3. Auto-save: `output\batches\batch_YYYYMMDD_HHMMSS_...`  
4. Excel (.xlsx) + Word (.docx) download  

---

## AI Question Solver (MVP CLI)

```powershell
cd "C:\Users\apple\Desktop\chat gpt oauth"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Auth (ek baar)
.\.venv\Scripts\python.exe main.py login
.\.venv\Scripts\python.exe main.py auth

# Solve
.\.venv\Scripts\python.exe main.py solve "input\paper.pdf"
.\.venv\Scripts\python.exe main.py solve "input\questions.png" --out output\run1
```

Output:
- `output/<name>/solved_questions.json`
- `output/<name>/solved_questions.docx`
- `output/<name>/processing_report.json`

Pipeline: `PDF/Image → extract+solve (local OpenAI auth) → validate JSON → Word`

Local cleanup (temp + partial CSV):

```powershell
.\.venv\Scripts\python.exe main.py clean
# full wipe of output/:
.\.venv\Scripts\python.exe main.py clean --deep
```

GUI (Phase 6) abhi nahi — pehle core pipeline.

---

# Local ChatGPT OAuth

Apne ChatGPT account (OAuth) **ya** OpenAI API key se kisi bhi Python project me local client use karo.

> **Note:** OAuth mode ChatGPT/Codex WHAM backend use karta hai (subscription). Ye official Platform API nahi hai — OpenAI change kar sakta hai. API-key mode official `api.openai.com` hai.

## Setup

```bash
cd "chat gpt oauth"
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

## Login (ek baar)

**Option A — ChatGPT browser login (Plus/Pro + Codex access):**

```bash
python -m local_chatgpt login
```

Browser khulega → ChatGPT se sign in → tokens `~/.local_chatgpt/auth.json` me save.

**Option B — Headless / SSH:**

```bash
python -m local_chatgpt login --headless
```

**Option C — OpenAI API key:**

```bash
python -m local_chatgpt login --api-key sk-...
# ya
$env:OPENAI_API_KEY = "sk-..."
```

Check:

```bash
python -m local_chatgpt status
python -m local_chatgpt test
```

## Kisi bhi project me use

Is folder ko path me add karo, ya package copy/install karo:

```bash
pip install -e "C:\Users\apple\Desktop\chat gpt oauth"
```

Phir code:

```python
from local_chatgpt import chat, LocalChatGPT, get_client

# Auto: pehle env API key, warna saved OAuth
print(chat("Hello!"))

bot = LocalChatGPT()
print(bot.chat("Write a Python fibonacci function", stream=True))

# Raw OpenAI SDK client
client = get_client()
```

### Auth modes

| Mode | Kaise |
|------|--------|
| Auto | `get_client()` — API key env → warna OAuth file |
| OAuth only | `get_client(auth="oauth")` |
| API key only | `get_client(auth="api_key", api_key="sk-...")` |

### Dusre project se path ke bina

```python
import sys
sys.path.insert(0, r"C:\Users\apple\Desktop\chat gpt oauth")

from local_chatgpt import chat
print(chat("hi"))
```

## CLI

```text
python -m local_chatgpt login
python -m local_chatgpt login --headless
python -m local_chatgpt login --api-key sk-...
python -m local_chatgpt status
python -m local_chatgpt test -p "hello"
python -m local_chatgpt models
python -m local_chatgpt logout
```

## Auth file

- Default: `~/.local_chatgpt/auth.json`
- Agar Codex CLI already login hai: `~/.codex/auth.json` bhi auto detect
- Custom: `$env:LOCAL_CHATGPT_AUTH = "D:\secrets\auth.json"`

**auth.json secret hai** — git me mat daalo, share mat karo.