# updown-agent

Agente de IA em Python (apenas biblioteca padrão) que verifica se um site está online ou com downtime.

## Uso

Com `GEMINI_API_KEY` (modo agente de IA com tool-calling):

```bash
export GEMINI_API_KEY="sua-chave"
uv run python agent.py https://example.com
```

Sem `GEMINI_API_KEY` (modo fallback determinístico):

```bash
uv run python agent.py https://example.com
```
