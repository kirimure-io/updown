# updown-agent

> **Nota:** Este projeto é apenas um **experimento didático** para demonstrar como construir um agente de IA com *tool-calling* do zero usando apenas a biblioteca padrão do Python (zero dependências externas).

Agente de IA em Python que verifica se um site está online ou com downtime, diagnosticando HTTP, DNS e TLS.

## Funcionalidades

- **Zero dependências externas:** usa apenas biblioteca padrão (`urllib.request`, `socket`, `ssl`, `json`, `argparse`).
- **Ferramentas de diagnóstico:**
  - `check_http`: verifica status HTTP e latência (com headers padrão de navegador).
  - `check_dns`: resolve registros DNS (`socket.getaddrinfo`).
  - `check_tls`: valida handshake TLS e data de expiração do certificado.
- **Resiliência na API Gemini:** retry com *backoff* exponencial em erros `429`/`503` e fallback automático de `gemini-3.8-flash` para `gemini-3.5-flash-lite`.
- **Modo fallback sem IA:** se `GEMINI_API_KEY` não estiver definida, executa as checagens diretamente e retorna um JSON.
- **Modo verboso (`FALADOR=true`):** imprime no `stderr` cada passo do agente, chamadas de modelo, retries e resultados das ferramentas.

## Uso

### Com agente de IA (`GEMINI_API_KEY`)

```bash
export GEMINI_API_KEY="sua-chave"
uv run python agent.py https://example.com
```

### Modo verboso

```bash
FALADOR=true uv run python agent.py https://example.com
```

### Trocar o modelo

Via variável de ambiente:

```bash
GEMINI_MODEL=gemini-3.5-flash-lite uv run python agent.py https://example.com
```

Ou comentando/descomentando a linha correspondente no topo de `agent.py`.

### Sem `GEMINI_API_KEY` (modo fallback determinístico)

```bash
uv run python agent.py https://example.com
```

## Arquitetura

O agente funciona em um loop simples de **tool-calling** (chamada de ferramentas):

1. `main()` lê a URL e verifica se `GEMINI_API_KEY` está definida.
2. `run_ai_agent()` envia a pergunta para a API do Gemini junto com as declarações das ferramentas (`TOOL_DECLARATIONS`).
3. O modelo decide quais ferramentas chamar (`check_http`, `check_dns`, `check_tls`).
4. O script executa as funções Python correspondentes via `TOOLS_MAP` e devolve os resultados ao modelo.
5. Quando o modelo tem informação suficiente, ele retorna o diagnóstico final.

Se `GEMINI_API_KEY` não estiver configurada, `run_fallback()` executa as checagens diretamente e imprime um JSON.

## Como expandir este agente

### 1. Adicionar uma nova ferramenta

Exemplo: adicionar uma checagem de ping TCP em uma porta específica (`check_tcp`).

1. **Crie a função** em `agent.py` retornando um `dict` simples (serializável em JSON):

```python
def check_tcp(hostname: str, port: int = 80, timeout: int = 5) -> dict[str, Any]:
    """Check if a TCP port is reachable."""
    try:
        with socket.create_connection((hostname, port), timeout=timeout):
            return {"hostname": hostname, "port": port, "open": True, "error": None}
    except Exception as exc:
        return {"hostname": hostname, "port": port, "open": False, "error": str(exc)}
```

2. **Registre no `TOOLS_MAP`**:

```python
TOOLS_MAP["check_tcp"] = check_tcp
```

3. **Adicione o schema em `TOOL_DECLARATIONS`** para que o modelo saiba quando e como usar:

```python
{
    "name": "check_tcp",
    "description": "Check if a TCP port is open on a hostname.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "hostname": {"type": "STRING", "description": "Hostname without scheme."},
            "port": {"type": "INTEGER", "description": "TCP port to test."},
        },
        "required": ["hostname", "port"],
    },
}
```

### 2. Ajustar o comportamento do agente

- Edite `SYSTEM_PROMPT` em `agent.py` para mudar o tom, idioma ou critérios de diagnóstico.
- Ajuste `max_steps` em `run_ai_agent()` se adicionar muitas ferramentas encadeadas.
- Defina `GEMINI_MODEL` no ambiente para testar outros modelos sem alterar código.
