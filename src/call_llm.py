import os
from google import genai

# It is recommended to set your API key as an environment variable (GEMINI_API_KEY)
# The client will automatically find it.
# client = genai.Client() 

# Alternatively, you can pass the key directly (replace YOUR_API_KEY):
client = genai.Client(api_key='YOUR_API_KEY') 

response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents='Explain the benefit of using the Gemini API.'
)

print(response.text)