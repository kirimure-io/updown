# Logbook — updown-agent

Registro técnico das decisões e evoluções do projeto para contexto rápido de outros agentes de IA.

## 2026-11-13

### 1. Criação inicial (`2e0ae9f`)
- **Decisão de arquitetura:** Zero dependências externas. Tudo implementado com a biblioteca padrão do Python (`urllib.request`, `socket`, `ssl`, `json`, `argparse`) para manter footprint mínimo e execução simples via `uv run python agent.py <url>`.
- **Ferramentas implementadas em `agent.py`:**
  - `check_http`: GET com medição de latência (`time.monotonic()`) e classificação de `HTTPError` / `URLError`.
  - `check_dns`: resolução via `socket.getaddrinfo`.
  - `check_tls`: handshake e leitura de `notAfter` do certificado via `ssl`.
- **Modo dual:** Se `GEMINI_API_KEY` estiver definida, `run_ai_agent()` executa loop de tool-calling (até `max_steps=6`) contra a API REST do Gemini. Sem chave, `run_fallback()` executa as checagens diretamente e retorna JSON.

### 2. Documentação para expansão (`6d86307`)
- Adicionados comentários em `agent.py` explicando o contrato de extensão (`TOOLS_MAP` + `TOOL_DECLARATIONS`) e o fluxo de `functionCall` / `functionResponse` em `run_ai_agent()`.
- Adicionada seção de arquitetura e guia prático no `README.md` com exemplo de nova ferramenta (`check_tcp`).

### 3. Atualização de modelo (`f3471ab`, `ae244f7`)
- Modelo padrão atualizado de `gemini-2.5-flash` para `gemini-3.8-flash` (após verificação dos modelos ativos na API Gemini).
- Adicionada linha comentada para `gemini-3.5-flash-lite` logo abaixo de `GEMINI_MODEL` para troca rápida sem alterar lógica.

### 4. Resiliência, modo verboso e documentação (`a24c09a`, `a581c9e`, `70c4c3f`)
- **Headers de navegador em `check_http`:** evita bloqueios `503` de WAF/CDN que rejeitam `User-Agent` genérico.
- **Retry + fallback de modelo em `call_gemini`:** 3 tentativas com *backoff* exponencial para `429`, `503`, `TimeoutError` e `URLError`, com fallback automático para `gemini-3.5-flash-lite`.
- **Modo verboso (`FALADOR=true`):** `log_step()` imprime passos, retries e resultados de ferramentas em `stderr`, mantendo `stdout` limpo para o diagnóstico final.
- **Documentação:** `README.md` atualizado com aviso de experimento didático, todas as features e instruções de uso via Antigravity CLI / harness.
