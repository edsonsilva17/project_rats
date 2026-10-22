"""
Gera painel.html: página local com a tabela de características de todos os
jogadores e a ficha de cada um (radar das dimensões, série de ADR, comparação).

A página não precisa de internet nem de servidor: os dados vão embutidos no
HTML. Para atualizar, rode de novo depois de trocar o CSV da planilha.

Uso:
  python gerar_pagina.py
  python gerar_pagina.py --csv "outro.csv" --saida painel.html
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from caracteristicas_csrats import DIMENSOES, caracterizar, confiabilidade
from hurst_csrats import CSV_PADRAO, ler_jogadores

PASTA = Path(__file__).resolve().parent
MODELO = PASTA / "pagina_modelo.html"
SAIDA_PADRAO = PASTA / "painel.html"
TESTES = {"tendencia": "Tendência", "autocorr": "Autocorrelação",
          "sequencias": "Joga em fases (sequências)", "cusum": "Mudança de patamar"}


def arred(v, casas=1):
    return None if v is None else round(v, casas)


def gerar(csv_entrada=CSV_PADRAO, saida=SAIDA_PADRAO, n_embaralhamentos=2000, semente=42):
    jogadores = ler_jogadores(csv_entrada)
    ctx = caracterizar(jogadores, n_embaralhamentos, semente=semente)

    dados = {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "media_liga": arred(ctx["media_liga"]),
        "n_referencia": ctx["n_referencia"],
        "total_partidas": sum(len(j["partidas"]) for j in jogadores),
        "dimensoes": [nome for nome, _ in DIMENSOES],
        "jogadores": [],
    }
    for j in jogadores:
        i = j["ind"]
        dados["jogadores"].append({
            "nick": j["nick"], "nome": j["nome"], "posicao": j["posicao"],
            "n": len(j["partidas"]), "conf": confiabilidade(len(j["partidas"])),
            "partidas": j["partidas"],
            "media": arred(i["media"]), "media_encolhida": arred(i["media_encolhida"]),
            "dp": arred(i.get("dp")), "cv": arred(i.get("cv"), 3),
            "p10": arred(i.get("piso_p10")), "p90": arred(i.get("teto_p90")),
            "forma_10": arred(i.get("forma_10")), "tendencia_10": arred(i.get("tendencia_10")),
            "pct": {k: arred(v, 0) for k, v in j["pct"].items()},
            "fortes": j["fortes"], "fracos": j["fracos"], "perfil": j["perfil"],
            "solidos": [nome for teste, nome in TESTES.items()
                        if i.get(f"{teste}_q") is not None and i[f"{teste}_q"] < 0.05],
        })

    json_dados = json.dumps(dados, ensure_ascii=False).replace("</", "<\\/")
    html = MODELO.read_text(encoding="utf-8").replace("/*DADOS*/null", json_dados)
    saida.write_text(html, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Gera o painel HTML dos jogadores (CSRats).")
    parser.add_argument("--csv", type=Path, default=CSV_PADRAO)
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    parser.add_argument("--embaralhamentos", type=int, default=2000)
    parser.add_argument("--semente", type=int, default=42)
    args = parser.parse_args()

    gerar(args.csv, args.saida, args.embaralhamentos, args.semente)
    print(f"Painel salvo em: {args.saida}")


if __name__ == "__main__":
    main()
