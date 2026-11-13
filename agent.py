#!/usr/bin/env python3
"""Lightweight AI agent to check website uptime and diagnose downtime.

Uses Python standard library only. Connects to Gemini API for tool-calling
reasoning when GEMINI_API_KEY is set, with a deterministic fallback otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
FALLBACK_MODEL = "gemini-3.5-flash-lite"
FALADOR = os.environ.get("FALADOR", "").lower() == "true"

SYSTEM_PROMPT = (
    "You are an SRE uptime diagnostic agent. "
    "Given a target URL, use the available tools (check_http, check_dns, check_tls) "
    "to determine whether the site is ONLINE or experiencing DOWNTIME. "
    "If check_http fails or returns 5xx, use check_dns and check_tls to isolate the root cause. "
    "Respond concisely in Portuguese with: Status (ONLINE/DOWNTIME), HTTP code, latency, and cause."
)


def log_step(msg: str) -> None:
    """Print verbose step logs when FALADOR=true."""
    if FALADOR:
        print(f"[FALADOR] {msg}", file=sys.stderr)


def check_http(url: str, timeout: int = 10) -> dict[str, Any]:
    """Perform an HTTP GET request and measure status code and latency."""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            return {
                "url": resp.geturl(),
                "status_code": resp.status,
                "online": 200 <= resp.status < 400,
                "latency_ms": latency_ms,
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        latency_ms = round((time.monotonic() - start) * 1000, 2)
        return {
            "url": url,
            "status_code": exc.code,
            "online": False,
            "latency_ms": latency_ms,
            "error": f"HTTP {exc.code}: {exc.reason}",
        }
    except urllib.error.URLError as exc:
        latency_ms = round((time.monotonic() - start) * 1000, 2)
        return {
            "url": url,
            "status_code": None,
            "online": False,
            "latency_ms": latency_ms,
            "error": str(exc.reason),
        }
    except Exception as exc:
        latency_ms = round((time.monotonic() - start) * 1000, 2)
        return {
            "url": url,
            "status_code": None,
            "online": False,
            "latency_ms": latency_ms,
            "error": str(exc),
        }


def check_dns(hostname: str) -> dict[str, Any]:
    """Resolve DNS A/AAAA records for a hostname."""
    try:
        infos = socket.getaddrinfo(hostname, None)
        ips = sorted({info[4][0] for info in infos})
        return {"hostname": hostname, "resolved": True, "ips": ips, "error": None}
    except socket.gaierror as exc:
        return {"hostname": hostname, "resolved": False, "ips": [], "error": str(exc)}


def check_tls(hostname: str, port: int = 443, timeout: int = 5) -> dict[str, Any]:
    """Check TLS handshake and certificate expiration for a hostname."""
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((hostname, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                return {
                    "hostname": hostname,
                    "tls_ok": True,
                    "not_after": cert.get("notAfter") if cert else None,
                    "error": None,
                }
    except Exception as exc:
        return {"hostname": hostname, "tls_ok": False, "not_after": None, "error": str(exc)}


# Mapeia o nome da ferramenta (usado pelo modelo) para a função Python correspondente.
# Para adicionar uma nova ferramenta:
# 1. Crie a função acima retornando um dict serializável em JSON.
# 2. Registre-a aqui em TOOLS_MAP.
# 3. Adicione o schema dela em TOOL_DECLARATIONS abaixo.
TOOLS_MAP = {
    "check_http": check_http,
    "check_dns": check_dns,
    "check_tls": check_tls,
}

TOOL_DECLARATIONS = [
    {
        "name": "check_http",
        "description": "Check if a URL responds to HTTP GET, returning status_code, online, latency_ms, and error.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "Full URL or domain to check."},
                "timeout": {"type": "INTEGER", "description": "Timeout in seconds (default 10)."},
            },
            "required": ["url"],
        },
    },
    {
        "name": "check_dns",
        "description": "Resolve DNS records for a hostname.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "hostname": {"type": "STRING", "description": "Hostname without scheme (e.g. example.com)."},
            },
            "required": ["hostname"],
        },
    },
    {
        "name": "check_tls",
        "description": "Check TLS handshake and certificate expiration for a hostname.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "hostname": {"type": "STRING", "description": "Hostname without scheme."},
                "port": {"type": "INTEGER", "description": "TCP port (default 443)."},
            },
            "required": ["hostname"],
        },
    },
]


def _post_with_retry(model: str, data: bytes, api_key: str, retries: int = 3) -> dict[str, Any]:
    """POST payload to a Gemini model with exponential backoff on transient errors."""
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    for attempt in range(retries):
        log_step(f"Chamando Gemini ({model}, tentativa {attempt + 1}/{retries})...")
        req = urllib.request.Request(
            endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503):
                raise
            log_step(f"Gemini retornou HTTP {exc.code}.")
        except (TimeoutError, urllib.error.URLError) as exc:
            log_step(f"Erro de rede/timeout no Gemini: {exc}")

        if attempt < retries - 1:
            wait = 2**attempt
            log_step(f"Aguardando {wait}s para tentar novamente...")
            time.sleep(wait)
    raise RuntimeError(f"Falha ao chamar {model} após {retries} tentativas.")


def call_gemini(contents: list[dict[str, Any]], api_key: str, retries: int = 3) -> dict[str, Any]:
    """Send a generateContent request to Gemini REST API with model fallback."""
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "tools": [{"functionDeclarations": TOOL_DECLARATIONS}],
    }
    data = json.dumps(payload).encode("utf-8")
    models = [GEMINI_MODEL]
    if GEMINI_MODEL != FALLBACK_MODEL:
        models.append(FALLBACK_MODEL)

    for model in models:
        try:
            return _post_with_retry(model, data, api_key, retries=retries)
        except Exception:
            if model == models[-1]:
                raise
            log_step(f"Fallback para {models[-1]}...")
    raise RuntimeError("Unreachable")


def run_ai_agent(target: str, api_key: str, max_steps: int = 6) -> str:
    """Run the tool-calling loop with Gemini until a final answer is produced."""
    # Histórico da conversa enviado a cada iteração para manter contexto entre chamadas.
    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": f"Check if this site is online or has downtime: {target}"}]}
    ]

    for step in range(1, max_steps + 1):
        log_step(f"Passo {step}/{max_steps} do agente...")
        response = call_gemini(contents, api_key)
        candidate = response["candidates"][0]["content"]
        contents.append(candidate)

        parts = candidate.get("parts", [])
        function_calls = [p["functionCall"] for p in parts if "functionCall" in p]

        # Se o modelo não pediu nenhuma ferramenta, ele já gerou a resposta final.
        if not function_calls:
            log_step("Modelo concluiu o diagnóstico.")
            texts = [p["text"] for p in parts if "text" in p]
            return "\n".join(texts).strip()

        # Executa cada ferramenta solicitada e devolve o resultado como "functionResponse".
        tool_responses = []
        for fc in function_calls:
            name = fc["name"]
            args = fc.get("args", {})
            log_step(f"Executando ferramenta {name}({args})...")
            fn = TOOLS_MAP.get(name)
            result = fn(**args) if fn else {"error": f"Unknown tool: {name}"}
            log_step(f"Resultado de {name}: {result}")
            tool_responses.append(
                {
                    "functionResponse": {
                        "name": name,
                        "response": {"result": result},
                    }
                }
            )
        contents.append({"role": "user", "parts": tool_responses})

    return "Agent reached max steps without final response."


def run_fallback(target: str) -> str:
    """Deterministic check when GEMINI_API_KEY is not set."""
    log_step(f"Modo fallback: checando HTTP para {target}...")
    http_res = check_http(target)
    parsed = urllib.parse.urlparse(http_res["url"])
    hostname = parsed.hostname or target
    log_step(f"Modo fallback: checando DNS para {hostname}...")
    dns_res = check_dns(hostname)
    tls_res = None
    if parsed.scheme == "https":
        log_step(f"Modo fallback: checando TLS para {hostname}...")
        tls_res = check_tls(hostname)

    report = {
        "mode": "fallback (set GEMINI_API_KEY for AI agent)",
        "status": "ONLINE" if http_res["online"] else "DOWNTIME",
        "http": http_res,
        "dns": dns_res,
        "tls": tls_res,
    }
    return json.dumps(report, indent=2, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="AI agent to check website uptime/downtime.")
    parser.add_argument("url", help="Target URL or domain (e.g. https://example.com)")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        print(run_ai_agent(args.url, api_key))
    else:
        print(run_fallback(args.url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
