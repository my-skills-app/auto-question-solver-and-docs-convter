"""
Example: kisi bhi project me local ChatGPT use karo.

Pehle ek baar login:
  pip install -r requirements.txt
  python -m local_chatgpt login
"""

from local_chatgpt import LocalChatGPT, chat, get_client

# --- 1) Simple one-liner ---
print(chat("Python me list reverse ka shortest way?"))

# --- 2) Class style ---
bot = LocalChatGPT(system="You are a concise coding tutor.")
print(bot.chat("Explain decorators in 3 lines.", stream=True))

# --- 3) Raw OpenAI client (auto auth) ---
client = get_client()  # OAuth ya OPENAI_API_KEY
# API-key mode example (Chat Completions):
# r = client.chat.completions.create(
#     model="gpt-4o-mini",
#     messages=[{"role": "user", "content": "hi"}],
# )
# print(r.choices[0].message.content)

# Force API key:
# client = get_client(api_key="sk-...", auth="api_key")

# Force ChatGPT subscription OAuth:
# client = get_client(auth="oauth")