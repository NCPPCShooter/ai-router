import os
from openai import OpenAI

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Send a simple test message
message = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "user", "content": "Say 'OpenAI API connection successful!' and nothing else."}
    ]
)

print(message.choices[0].message.content)