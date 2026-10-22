"""
Baixa as imagens (prints das partidas) dos canais do Discord e gera um manifesto.

Lê do .env: DISCORD_TOKEN, DISCORD_CANAL_ID_LIGA e DISCORD_CANAL_ID_AMISTOSO.
Percorre o histórico inteiro de cada canal, da mensagem mais antiga para a mais
nova, e salva cada imagem (anexo ou imagem de embed) em prints/<canal>/.
O nome do arquivo começa pela data e hora (horário de Brasília), então a ordem
alfabética da pasta já é a ordem cronológica.

Arquivos que já existem não são baixados de novo: rodar outra vez só pega o que
é novo. O manifesto é reescrito a cada execução com todas as imagens encontradas:
  canal, data_hora, mensagem_id, autor_id, autor, texto, origem, arquivo, link
autor_id é o ID do Discord, o mesmo da coluna G da planilha CSRats.

Também salva prints/mensagens.jsonl com todas as mensagens dos canais (texto,
embeds completos, se o autor é bot), uma por linha. É de lá que saem as
divisões de times feitas pelo bot de balanceamento.

Uso:
  .venv/bin/python baixar_prints.py
  .venv/bin/python baixar_prints.py --canais liga --limite 50
"""

import argparse
import asyncio
import csv
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
import discord

PASTA = Path(__file__).resolve().parent
SAIDA_PADRAO = PASTA / "prints"
FUSO = ZoneInfo("America/Sao_Paulo")
EXTENSOES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
CANAIS = {"liga": "DISCORD_CANAL_ID_LIGA", "amistoso": "DISCORD_CANAL_ID_AMISTOSO"}


def ler_env(caminho):
    env = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            env[chave.strip()] = valor.strip().strip("\"'")
    return env


def extensao(nome, content_type=None):
    ext = Path(nome.split("?")[0]).suffix.lower()
    if ext in EXTENSOES:
        return ext
    if content_type and content_type.startswith("image/"):
        return "." + content_type.split("/")[1].split(";")[0].replace("jpeg", "jpg")
    return None


def imagens_da_mensagem(msg):
    """Lista (origem, url, extensão, anexo ou None) de cada imagem da mensagem."""
    imagens = []
    for anexo in msg.attachments:
        ext = extensao(anexo.filename, anexo.content_type)
        if ext:
            imagens.append(("anexo", anexo.url, ext, anexo))
    for embed in msg.embeds:
        for parte in (embed.image, embed.thumbnail):
            if parte and parte.url:
                ext = extensao(parte.url) or ".png"
                imagens.append(("embed", parte.url, ext, None))
                break
    return imagens


async def baixar_canal(client, sessao, nome_canal, canal_id, pasta, limite):
    canal = await client.fetch_channel(int(canal_id))
    destino = pasta / nome_canal
    destino.mkdir(parents=True, exist_ok=True)
    linhas, todas, novos, mensagens = [], [], 0, 0
    async for msg in canal.history(limit=limite, oldest_first=True):
        mensagens += 1
        data = msg.created_at.astimezone(FUSO)
        todas.append({
            "canal": nome_canal,
            "data_hora": data.strftime("%Y-%m-%d %H:%M:%S"),
            "mensagem_id": msg.id,
            "autor_id": msg.author.id,
            "autor": msg.author.display_name,
            "bot": msg.author.bot,
            "texto": msg.content,
            "embeds": [e.to_dict() for e in msg.embeds],
            "anexos": [a.filename for a in msg.attachments],
            "responde_a": msg.reference.message_id if msg.reference else None,
            "link": msg.jump_url,
        })
        for i, (origem, url, ext, anexo) in enumerate(imagens_da_mensagem(msg)):
            arquivo = destino / f"{data:%Y%m%d_%H%M%S}_{msg.id}_{i}{ext}"
            if not arquivo.exists():
                if anexo:
                    await anexo.save(arquivo)
                else:
                    async with sessao.get(url) as resp:
                        if resp.status != 200:
                            print(f"  falhou ({resp.status}): {msg.jump_url}")
                            continue
                        arquivo.write_bytes(await resp.read())
                novos += 1
            linhas.append({
                "canal": nome_canal,
                "data_hora": data.strftime("%Y-%m-%d %H:%M:%S"),
                "mensagem_id": msg.id,
                "autor_id": msg.author.id,
                "autor": msg.author.display_name,
                "texto": msg.content.replace("\n", " "),
                "origem": origem,
                "arquivo": arquivo.relative_to(pasta).as_posix(),
                "link": msg.jump_url,
            })
        if mensagens % 500 == 0:
            print(f"  {nome_canal}: {mensagens} mensagens lidas, {len(linhas)} imagens")
    print(f"{nome_canal} (#{canal.name}): {mensagens} mensagens, "
          f"{len(linhas)} imagens, {novos} baixadas agora")
    return linhas, todas


async def principal(args):
    env = ler_env(PASTA / ".env")
    client = discord.Client(intents=discord.Intents.default())
    await client.login(env["DISCORD_TOKEN"])
    linhas, todas = [], []
    try:
        async with aiohttp.ClientSession() as sessao:
            for nome in args.canais:
                imagens, msgs = await baixar_canal(client, sessao, nome, env[CANAIS[nome]],
                                                   args.saida, args.limite)
                linhas += imagens
                todas += msgs
    finally:
        await client.close()

    with open(args.saida / "mensagens.jsonl", "w", encoding="utf-8") as f:
        for m in todas:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    manifesto = args.saida / "manifesto.csv"
    with open(manifesto, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]) if linhas else ["canal"], delimiter=";")
        w.writeheader()
        w.writerows(linhas)
    print(f"\nManifesto salvo em: {manifesto}")


def main():
    parser = argparse.ArgumentParser(description="Baixa os prints dos canais do Discord.")
    parser.add_argument("--canais", nargs="+", choices=list(CANAIS), default=list(CANAIS))
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    parser.add_argument("--limite", type=int, default=None,
                        help="máximo de mensagens por canal (padrão: todas)")
    asyncio.run(principal(parser.parse_args()))


if __name__ == "__main__":
    main()
