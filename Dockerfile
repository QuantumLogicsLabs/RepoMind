FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir fastapi uvicorn pydantic pydantic-settings python-dotenv langchain langchain-openai langchain-community langchain-core gitpython PyGithub httpx pytest pytest-asyncio

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
