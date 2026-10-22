"""
Ficha de características por jogador: junta indicadores e Hurst em poucas
dimensões comparáveis, cada uma como percentil (0-100) dentro da liga.

Dimensões (percentil alto = mais daquela característica):
  Nível         média encolhida (já desconta a sorte de quem tem poucas partidas)
  Consistência  inverso do coeficiente de variação
  Piso          P10: o ADR dos jogos ruins
  Teto          P90: o ADR dos jogos bons
  Explosão      assimetria: jogos normais com picos raros
  Momento       últimas 10 partidas contra o resto (z)
  Evolução      tendência por 10 partidas
  Fases         Hurst corrigido (tau 8): fases boas/ruins que se prolongam

O percentil é calculado contra os jogadores com pelo menos --min-referencia
partidas (a referência). Quem tem menos aparece com a confiabilidade "baixa".
Destaques: dimensões >= 80 (forte) e <= 20 (fraco).

Uso:
  python caracteristicas_csrats.py
  python caracteristicas_csrats.py --min-referencia 30
"""

import argparse
import csv
from pathlib import Path

from hurst_csrats import CSV_PADRAO, hurst, ler_jogadores
from indicadores_csrats import calcular

PASTA = Path(__file__).resolve().parent
SAIDA_PADRAO = PASTA / "caracteristicas_resultados.csv"

# (nome, função que extrai o valor bruto; maior = mais da característica)
DIMENSOES = [
    ("Nível", lambda j: j["ind"].get("media_encolhida")),
    ("Consistência", lambda j: -j["ind"]["cv"] if j["ind"].get("cv") is not None else None),
    ("Piso", lambda j: j["ind"].get("piso_p10")),
    ("Teto", lambda j: j["ind"].get("teto_p90")),
    ("Explosão", lambda j: j["ind"].get("assimetria")),
    ("Momento", lambda j: j["ind"].get("forma_z")),
    ("Evolução", lambda j: j["ind"].get("tendencia_10")),
    ("Fases", lambda j: j["hurst8"] and j["hurst8"]["h_corrigido"]),
]
FORTE, FRACO = 80, 20


def percentil_de(valor, referencia):
    """Posição de valor dentro da referência (empates contam meio)."""
    abaixo = sum(r < valor for r in referencia)
    iguais = sum(r == valor for r in referencia)
    return 100 * (abaixo + 0.5 * iguais) / len(referencia)


def confiabilidade(n):
    return "alta" if n >= 40 else "média" if n >= 20 else "baixa"


def caracterizar(jogadores, n_embaralhamentos=2000, min_referencia=20, semente=42):
    """Preenche ind, perfil, pct, fortes e fracos; devolve o contexto da liga."""
    ctx = calcular(jogadores, n_embaralhamentos, semente=semente)
    for j in jogadores:
        j["hurst8"] = hurst(j["partidas"], 8)

    referencia = [j for j in jogadores if len(j["partidas"]) >= min_referencia]
    ctx["n_referencia"] = len(referencia)
    for nome, valor in DIMENSOES:
        ref = [v for v in map(valor, referencia) if v is not None]
        for j in jogadores:
            v = valor(j)
            j.setdefault("pct", {})[nome] = None if v is None else percentil_de(v, ref)

    for j in jogadores:
        pct = {k: v for k, v in j["pct"].items() if v is not None}
        j["fortes"] = [k for k, v in sorted(pct.items(), key=lambda kv: -kv[1]) if v >= FORTE]
        j["fracos"] = [k for k, v in sorted(pct.items(), key=lambda kv: kv[1]) if v <= FRACO]
    return ctx


def main():
    parser = argparse.ArgumentParser(description="Ficha de características por jogador (CSRats).")
    parser.add_argument("--csv", type=Path, default=CSV_PADRAO)
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    parser.add_argument("--embaralhamentos", type=int, default=2000)
    parser.add_argument("--min-referencia", type=int, default=20,
                        help="mínimo de partidas para entrar na referência dos percentis")
    parser.add_argument("--semente", type=int, default=42)
    args = parser.parse_args()

    jogadores = ler_jogadores(args.csv)
    ctx = caracterizar(jogadores, args.embaralhamentos, args.min_referencia, args.semente)

    nomes = [nome for nome, _ in DIMENSOES]
    print(f"Percentis contra {ctx['n_referencia']} jogadores com >= {args.min_referencia} partidas\n")
    cab = f"{'Nick':<18} {'N':>4} {'conf':<5} " + " ".join(f"{n[:6]:>6}" for n in nomes)
    print(cab)
    print("-" * len(cab))
    fmt = lambda v: "—" if v is None else f"{v:.0f}"
    for j in sorted(jogadores, key=lambda j: -j["ind"]["media_encolhida"]):
        print(f"{j['nick'][:18]:<18} {len(j['partidas']):>4} {confiabilidade(len(j['partidas'])):<5} "
              + " ".join(f"{fmt(j['pct'][n]):>6}" for n in nomes))

    print("\nDestaques (forte >= 80, fraco <= 20):")
    for j in sorted(jogadores, key=lambda j: -j["ind"]["media_encolhida"]):
        if len(j["partidas"]) >= args.min_referencia and (j["fortes"] or j["fracos"]):
            print(f"  {j['nick']}: forte em {', '.join(j['fortes']) or '—'}; "
                  f"fraco em {', '.join(j['fracos']) or '—'}")

    br = lambda v: "" if v is None else f"{v:.1f}".replace(".", ",")
    with open(args.saida, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Posicao", "Jogador", "Nick", "Partidas", "Confiabilidade"]
                   + [f"pct_{n}" for n in nomes] + ["Fortes", "Fracos", "Perfil"])
        for j in jogadores:
            w.writerow([j["posicao"], j["nome"], j["nick"], len(j["partidas"]),
                        confiabilidade(len(j["partidas"]))]
                       + [br(j["pct"][n]) for n in nomes]
                       + [", ".join(j["fortes"]), ", ".join(j["fracos"]), ", ".join(j["perfil"])])
    print(f"\nResultados salvos em: {args.saida}")


if __name__ == "__main__":
    main()
