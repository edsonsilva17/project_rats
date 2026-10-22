"""
Indicadores por jogador a partir das séries de partidas da aba CSRats.

Nível:        média, mediana, média encolhida (bayesiana), IC 95% da média (bootstrap)
Consistência: desvio padrão, coeficiente de variação (CV), amplitude interquartil,
              piso (P10) e teto (P90), % de partidas acima da mediana da liga
Forma:        média das últimas 10 contra o resto da carreira (z), tendência
              (inclinação por 10 partidas), mudança de patamar (CUSUM)
Dinâmica:     autocorrelação lag 1, teste de sequências, maior sequência
              acima/abaixo da mediana, volatilidade recente
Formato:      assimetria

Testes de autocorrelação, tendência e mudança de patamar usam embaralhamento
da própria série (o p diz se a ordem das partidas importa). q é o p ajustado
por Benjamini-Hochberg, porque todos os jogadores são testados ao mesmo tempo.

Perfis (coluna "perfil"):
  Consistente / Oscilante  CV no quartil mais baixo / mais alto da liga
  Explosivo                assimetria > 0,75 (jogos normais e picos raros)
  Em alta / Em baixa       últimas 10 partidas com |z| > 2 contra o resto
  Evoluindo / Caindo       tendência com p < 0,05
  Joga em fases            autocorrelação positiva ou poucas sequências, p < 0,05
  Mudou de patamar         CUSUM com p < 0,05
Os perfis baseados em teste usam p < 0,05; confira o q antes de concluir algo.

Uso:
  python indicadores_csrats.py
  python indicadores_csrats.py --embaralhamentos 5000 --min-partidas 15
"""

import argparse
import csv
import math
import random
import statistics
from pathlib import Path

from hurst_csrats import CSV_PADRAO, benjamini_hochberg, ler_jogadores

PASTA = Path(__file__).resolve().parent
SAIDA_PADRAO = PASTA / "indicadores_resultados.csv"
FORMA_N = 10
MIN_SEGMENTO = 5


def percentil(valores, p):
    s = sorted(valores)
    pos = (len(s) - 1) * p
    baixo = math.floor(pos)
    alto = min(baixo + 1, len(s) - 1)
    return s[baixo] + (s[alto] - s[baixo]) * (pos - baixo)


def assimetria(x):
    m, dp = statistics.fmean(x), statistics.pstdev(x)
    if dp == 0:
        return 0.0
    return statistics.fmean([((v - m) / dp) ** 3 for v in x])


def autocorrelacao(x):
    m = statistics.fmean(x)
    den = sum((v - m) ** 2 for v in x)
    if den == 0:
        return 0.0
    return sum((x[i] - m) * (x[i + 1] - m) for i in range(len(x) - 1)) / den


def inclinacao(x):
    """Inclinação da regressão linear valor ~ número da partida."""
    n = len(x)
    mx, my = (n - 1) / 2, statistics.fmean(x)
    sxx = sum((i - mx) ** 2 for i in range(n))
    return sum((i - mx) * (v - my) for i, v in enumerate(x)) / sxx


def cusum(x):
    """Maior desvio acumulado padronizado e a partida em que o patamar muda."""
    n, m, dp = len(x), statistics.fmean(x), statistics.pstdev(x)
    if dp == 0:
        return 0.0, None
    acumulado, melhor, corte = 0.0, -1.0, None
    for k in range(1, n):
        acumulado += x[k - 1] - m
        if MIN_SEGMENTO <= k <= n - MIN_SEGMENTO and abs(acumulado) > melhor:
            melhor, corte = abs(acumulado), k
    return melhor / (dp * math.sqrt(n)), corte


def p_embaralhamento(x, estatistica, n_embaralhamentos, rng, bicaudal=True):
    observado = estatistica(x)
    serie = list(x)
    extremos = 0
    for _ in range(n_embaralhamentos):
        rng.shuffle(serie)
        valor = estatistica(serie)
        extremos += (abs(valor) >= abs(observado)) if bicaudal else (valor >= observado)
    return (extremos + 1) / (n_embaralhamentos + 1)


def teste_sequencias(x):
    """Wald-Wolfowitz em torno da mediana. z < 0: menos sequências que o acaso (fases)."""
    med = statistics.median(x)
    sinais = [v > med for v in x if v != med]
    n1, n2 = sum(sinais), len(sinais) - sum(sinais)
    if n1 == 0 or n2 == 0:
        return None, None
    corridas = 1 + sum(sinais[i] != sinais[i - 1] for i in range(1, len(sinais)))
    n = n1 + n2
    esperado = 2 * n1 * n2 / n + 1
    variancia = 2 * n1 * n2 * (2 * n1 * n2 - n) / (n ** 2 * (n - 1))
    z = (corridas - esperado) / math.sqrt(variancia)
    return z, math.erfc(abs(z) / math.sqrt(2))


def maior_sequencia(x, referencia, acima=True):
    maior = atual = 0
    for v in x:
        atual = atual + 1 if (v > referencia if acima else v < referencia) else 0
        maior = max(maior, atual)
    return maior


def ic_bootstrap(x, n_reamostras, rng):
    medias = sorted(statistics.fmean(rng.choices(x, k=len(x))) for _ in range(n_reamostras))
    return percentil(medias, 0.025), percentil(medias, 0.975)


def constante_encolhimento(jogadores, minimo):
    """k = variância dentro do jogador / variância real entre jogadores (Bayes empírico)."""
    grupos = [j["partidas"] for j in jogadores if len(j["partidas"]) >= minimo]
    dentro = sum(statistics.variance(g) * (len(g) - 1) for g in grupos) / sum(len(g) - 1 for g in grupos)
    medias = [statistics.fmean(g) for g in grupos]
    entre = statistics.variance(medias) - statistics.fmean([dentro / len(g) for g in grupos])
    return dentro / max(entre, 1e-9)


def indicadores(partidas, ctx, n_embaralhamentos, rng):
    x, n = partidas, len(partidas)
    media = statistics.fmean(x)
    r = {
        "partidas": n,
        "media": media,
        "mediana": statistics.median(x),
        "media_encolhida": (n * media + ctx["k"] * ctx["media_liga"]) / (n + ctx["k"]),
    }
    if n < 2:
        return r
    dp = statistics.stdev(x)
    r.update({
        "ic95_inf": None, "ic95_sup": None,
        "dp": dp,
        "cv": dp / media if media else None,
        "iqr": percentil(x, 0.75) - percentil(x, 0.25),
        "piso_p10": percentil(x, 0.10),
        "teto_p90": percentil(x, 0.90),
        "pct_acima_liga": sum(v > ctx["mediana_liga"] for v in x) / n,
        "assimetria": assimetria(x),
    })
    r["ic95_inf"], r["ic95_sup"] = ic_bootstrap(x, 2000, rng)
    if n < ctx["min_partidas"]:
        return r

    med = statistics.median(x)
    z_seq, p_seq = teste_sequencias(x)
    est_cusum, corte = cusum(x)
    r.update({
        "autocorr_lag1": autocorrelacao(x),
        "autocorr_p": p_embaralhamento(x, autocorrelacao, n_embaralhamentos, rng),
        "sequencias_z": z_seq,
        "sequencias_p": p_seq,
        "maior_seq_acima": maior_sequencia(x, med, acima=True),
        "maior_seq_abaixo": maior_sequencia(x, med, acima=False),
        "tendencia_10": inclinacao(x) * 10,
        "tendencia_p": p_embaralhamento(x, inclinacao, n_embaralhamentos, rng),
        "cusum": est_cusum,
        "cusum_p": p_embaralhamento(x, lambda s: cusum(s)[0], n_embaralhamentos, rng, bicaudal=False),
        "patamar_antes": statistics.fmean(x[:corte]) if corte else None,
        "patamar_depois": statistics.fmean(x[corte:]) if corte else None,
        "patamar_ha_partidas": n - corte if corte else None,
    })
    if n >= FORMA_N * 2:
        recente, resto = x[-FORMA_N:], x[:-FORMA_N]
        forma = statistics.fmean(recente)
        r.update({
            "forma_10": forma,
            "forma_vs_resto": forma - statistics.fmean(resto),
            "forma_z": (forma - statistics.fmean(resto)) / (dp * math.sqrt(1 / FORMA_N + 1 / len(resto))),
            "volatilidade_recente": statistics.stdev(recente) / dp,
        })
    return r


def perfis(r, cv_q1, cv_q3):
    p = []
    cv = r.get("cv")
    if cv is not None and r["partidas"] >= 15:
        if cv <= cv_q1:
            p.append("Consistente")
        elif cv >= cv_q3:
            p.append("Oscilante")
    if r.get("assimetria", 0) > 0.75 and r["partidas"] >= 15:
        p.append("Explosivo")
    if r.get("forma_z") is not None and abs(r["forma_z"]) > 2:
        p.append("Em alta" if r["forma_z"] > 0 else "Em baixa")
    if r.get("tendencia_p") is not None and r["tendencia_p"] < 0.05:
        p.append("Evoluindo" if r["tendencia_10"] > 0 else "Caindo")
    fases_ac = r.get("autocorr_p") is not None and r["autocorr_p"] < 0.05 and r["autocorr_lag1"] > 0
    fases_seq = r.get("sequencias_p") is not None and r["sequencias_p"] < 0.05 and r["sequencias_z"] < 0
    if fases_ac or fases_seq:
        p.append("Joga em fases")
    if r.get("cusum_p") is not None and r["cusum_p"] < 0.05:
        p.append("Mudou de patamar")
    return p


COLUNAS = [
    "partidas", "media", "mediana", "media_encolhida", "ic95_inf", "ic95_sup",
    "dp", "cv", "iqr", "piso_p10", "teto_p90", "pct_acima_liga", "assimetria",
    "forma_10", "forma_vs_resto", "forma_z", "volatilidade_recente",
    "tendencia_10", "tendencia_p", "tendencia_q",
    "autocorr_lag1", "autocorr_p", "autocorr_q",
    "sequencias_z", "sequencias_p", "sequencias_q", "maior_seq_acima", "maior_seq_abaixo",
    "cusum", "cusum_p", "cusum_q", "patamar_antes", "patamar_depois", "patamar_ha_partidas",
]


def main():
    parser = argparse.ArgumentParser(description="Indicadores por jogador (CSRats).")
    parser.add_argument("--csv", type=Path, default=CSV_PADRAO)
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    parser.add_argument("--embaralhamentos", type=int, default=2000)
    parser.add_argument("--min-partidas", type=int, default=12,
                        help="mínimo de partidas para os testes de forma e dinâmica")
    parser.add_argument("--semente", type=int, default=42)
    args = parser.parse_args()

    jogadores = ler_jogadores(args.csv)
    todas = [v for j in jogadores for v in j["partidas"]]
    ctx = {
        "media_liga": statistics.fmean(todas),
        "mediana_liga": statistics.median(todas),
        "k": constante_encolhimento(jogadores, args.min_partidas),
        "min_partidas": args.min_partidas,
    }
    rng = random.Random(args.semente)
    for j in jogadores:
        j["ind"] = indicadores(j["partidas"], ctx, args.embaralhamentos, rng)

    for teste in ("tendencia", "autocorr", "sequencias", "cusum"):
        qs = benjamini_hochberg([j["ind"].get(f"{teste}_p") for j in jogadores])
        for j, q in zip(jogadores, qs):
            j["ind"][f"{teste}_q"] = q

    cvs = [j["ind"]["cv"] for j in jogadores if j["ind"].get("cv") is not None and len(j["partidas"]) >= 15]
    cv_q1, cv_q3 = percentil(cvs, 0.25), percentil(cvs, 0.75)
    for j in jogadores:
        j["perfil"] = perfis(j["ind"], cv_q1, cv_q3)

    print(f"Liga: média {ctx['media_liga']:.1f}, mediana {ctx['mediana_liga']:.1f}, "
          f"k do encolhimento = {ctx['k']:.1f} partidas")
    print(f"CV: quartil inferior {cv_q1:.3f}, superior {cv_q3:.3f}\n")
    cab = (f"{'Nick':<18} {'N':>4} {'média':>6} {'encolh':>6} {'CV':>5} {'P10':>5} {'P90':>5} "
           f"{'assim':>5} {'forma':>6} {'tend10':>6} {'ac1':>5} {'p_ac':>5}  perfil")
    print(cab)
    print("-" * (len(cab) + 20))
    f = lambda v, fmt: "—" if v is None else format(v, fmt)
    ordenados = sorted(jogadores, key=lambda j: -j["ind"]["media_encolhida"])
    for j in ordenados:
        i = j["ind"]
        print(f"{j['nick'][:18]:<18} {i['partidas']:>4} {i['media']:>6.1f} {i['media_encolhida']:>6.1f} "
              f"{f(i.get('cv'), '.2f'):>5} {f(i.get('piso_p10'), '.0f'):>5} {f(i.get('teto_p90'), '.0f'):>5} "
              f"{f(i.get('assimetria'), '.2f'):>5} {f(i.get('forma_vs_resto'), '+.1f'):>6} "
              f"{f(i.get('tendencia_10'), '+.1f'):>6} {f(i.get('autocorr_lag1'), '+.2f'):>5} "
              f"{f(i.get('autocorr_p'), '.3f'):>5}  {', '.join(j['perfil'])}")

    print("\nTestes com q < 0,05 (resistem ao ajuste para vários jogadores):")
    algum = False
    for j in jogadores:
        for teste in ("tendencia", "autocorr", "sequencias", "cusum"):
            q = j["ind"].get(f"{teste}_q")
            if q is not None and q < 0.05:
                algum = True
                print(f"  {j['nick']}: {teste} (p = {j['ind'][f'{teste}_p']:.4f}, q = {q:.4f})")
    if not algum:
        print("  nenhum")

    br = lambda v: "" if v is None else (str(v) if isinstance(v, int) else f"{v:.4f}".replace(".", ","))
    with open(args.saida, "w", encoding="utf-8-sig", newline="") as arq:
        w = csv.writer(arq, delimiter=";")
        w.writerow(["Posicao", "Jogador", "Nick"] + COLUNAS + ["perfil"])
        for j in jogadores:
            w.writerow([j["posicao"], j["nome"], j["nick"]]
                       + [br(j["ind"].get(c)) for c in COLUNAS] + [", ".join(j["perfil"])])
    print(f"\nResultados salvos em: {args.saida}")


if __name__ == "__main__":
    main()
