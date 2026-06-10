import anthropic
import os

# Keys come directly from Windows Environment Variables
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Send a simple test message
message = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Say 'Claude API connection successful!' and nothing else."}
    ]
)

print(message.content[0].text)