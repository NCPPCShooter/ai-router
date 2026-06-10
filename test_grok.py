import os
from openai import OpenAI

# Grok uses OpenAI-compatible API
client = OpenAI(
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1"
)

message = client.chat.completions.create(
    model="grok-3",
    messages=[
        {"role": "user", "content": "Say 'Grok API connection successful!' and nothing else."}
    ]
)

print(message.choices[0].message.content)