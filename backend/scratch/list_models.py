import os
import json
import urllib.request
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("LLM_API_KEY")

if not api_key:
    print("No API key")
    exit(1)

url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
try:
    with urllib.request.urlopen(url) as response:
        result = json.loads(response.read().decode('utf-8'))
        for model in result.get("models", []):
            print(f"- {model['name']}: {model.get('supportedGenerationMethods', [])}")
except Exception as e:
    print(f"Error: {e}")
