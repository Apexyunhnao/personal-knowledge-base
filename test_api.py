"""测试 DeepSeek API 连接"""
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key or "替换" in api_key:
    print("❌ 请先在 .env 里填入 DEEPSEEK_API_KEY")
    exit(1)

client = OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com"
)

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "你好，用一句话介绍你自己"}],
)

print(f"✓ API 连接成功！")
print(f"  模型: {response.model}")
print(f"  回复: {response.choices[0].message.content}")
print(f"  Token用量: {response.usage}")
