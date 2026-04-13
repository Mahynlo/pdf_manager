from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from langchain.agents import create_agent
from dotenv import load_dotenv
import os

load_dotenv() # Carga el archivo .env
os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY")

docuemnto = "Este es un ejemplo de documento."
# 1. Inicializar el modelo Gemini
# Puedes usar 'gemini-1.5-flash' o 'gemini-1.5-pro'
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")

# 2. Crear una consulta (Prompt)
mensaje = HumanMessage(content="Explícame qué es LangChain en una frase.")

# 3. Invocar al modelo
respuesta = llm.invoke([mensaje])

# 4. Mostrar respuesta
print(respuesta.content)

