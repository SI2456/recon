import httpx

from app.core.config import settings


async def ask_ollama(question: str, context: str) -> str:
    prompt = f"Use this ReconAI context to answer briefly.\n\nContext:\n{context}\n\nQuestion: {question}"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/generate",
            json={"model": settings.ollama_model, "prompt": prompt, "stream": False},
        )
        response.raise_for_status()
        return response.json().get("response", "")
