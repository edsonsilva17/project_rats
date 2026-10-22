"""
Servidor Flask do painel CSRats.

Serve só o painel (nenhum outro arquivo da pasta fica acessível). Se o CSV da
planilha ou o modelo da página forem mais novos que o painel.html, o painel é
gerado de novo antes de responder.

Rotas:
  /           o painel
  /atualizar  força a geração do painel e volta para / (só para acessos locais;
              quem chega pelo túnel da Cloudflare recebe 403)

Todas as rotas pedem login (usuário "csrats" e a senha PAINEL_SENHA do .env).
Sem PAINEL_SENHA no .env o servidor não sobe.

Uso:
  .venv/bin/python servidor.py              só neste computador (127.0.0.1:5000)
  .venv/bin/python servidor.py --rede       acessível por outros aparelhos da rede
  .venv/bin/python servidor.py --porta 8080

Link público (Cloudflare Tunnel), com o servidor rodando em outro terminal:
  cloudflared tunnel --url http://127.0.0.1:5000
"""

import argparse
import secrets
import threading

from flask import Flask, Response, abort, redirect, request, send_file
from waitress import serve

from baixar_prints import PASTA, ler_env
from gerar_pagina import MODELO, SAIDA_PADRAO, gerar
from hurst_csrats import CSV_PADRAO

USUARIO = "csrats"
SENHA = ler_env(PASTA / ".env").get("PAINEL_SENHA", "")

app = Flask(__name__)
trava = threading.Lock()


@app.before_request
def exigir_login():
    auth = request.authorization
    if not (auth and auth.password is not None
            and secrets.compare_digest(auth.username or "", USUARIO)
            and secrets.compare_digest(auth.password, SENHA)):
        return Response("Login necessário.", 401, {"WWW-Authenticate": 'Basic realm="CSRats"'})


def painel_desatualizado():
    if not SAIDA_PADRAO.exists():
        return True
    gerado = SAIDA_PADRAO.stat().st_mtime
    return any(f.stat().st_mtime > gerado for f in (CSV_PADRAO, MODELO))


def garantir_painel(forcar=False):
    with trava:
        if forcar or painel_desatualizado():
            gerar()


@app.get("/")
def painel():
    garantir_painel()
    return send_file(SAIDA_PADRAO, mimetype="text/html", max_age=0)


@app.get("/atualizar")
def atualizar():
    if "Cf-Connecting-IP" in request.headers:  # veio pelo túnel, não é local
        abort(403)
    garantir_painel(forcar=True)
    return redirect("/")


def main():
    parser = argparse.ArgumentParser(description="Servidor do painel CSRats.")
    parser.add_argument("--rede", action="store_true",
                        help="aceita conexões de outros aparelhos da rede (0.0.0.0)")
    parser.add_argument("--porta", type=int, default=5000)
    args = parser.parse_args()
    if not SENHA:
        parser.error("defina PAINEL_SENHA no .env antes de subir o servidor")

    garantir_painel()
    host = "0.0.0.0" if args.rede else "127.0.0.1"
    print(f"Painel em http://{host}:{args.porta}")
    serve(app, host=host, port=args.porta)


if __name__ == "__main__":
    main()
