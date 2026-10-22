"""
Expoente de Hurst (análise R/S) por jogador, a partir do CSV da aba CSRats.

Para cada escala tau (tamanho da janela, em partidas):
  1. A série do jogador é cortada em janelas de tau partidas
     (deslizantes por padrão, ou disjuntas com --disjuntas).
  2. Em cada janela calcula-se R/S (amplitude ajustada / desvio padrão).
  3. R/S médio das janelas -> expoente:
       H_bruto     = log(R/S) / log(tau)
       H_corrigido = 0.5 + [log(R/S) - log(E[R/S])] / log(tau)
     onde E[R/S] é o valor esperado para ruído branco (Anis-Lloyd-Peters).
     Em janelas curtas o H_bruto é viesado; o corrigido vale ~0.5 para
     uma série sem memória, então é o mais indicado para interpretar.

Interpretação: H > 0.5 persistente (fases boas/ruins se prolongam),
H < 0.5 anti-persistente (alterna jogo bom/ruim), H ~ 0.5 sem memória.

Teste de embaralhamento (--embaralhamentos N): para cada jogador, a ordem
das partidas é embaralhada N vezes e o H é recalculado. Isso mantém os valores
do jogador e destrói só a memória, então dá o "sem memória" daquela série.
Compara H do menor tau, H do maior tau e a diferença delta = H(maior) - H(menor):
  z = (observado - média embaralhada) / desvio embaralhado
  p = bicaudal; q = p ajustado por Benjamini-Hochberg (muitos jogadores testados)
Delta fora do acaso sugere memória que muda com a escala:
  delta < 0: fases curtas que não se sustentam; delta > 0: tendências mais lentas.

Uso:
  python hurst_csrats.py
  python hurst_csrats.py --taus 8 12 --disjuntas --csv "outro.csv"
  python hurst_csrats.py --embaralhamentos 2000
"""

import argparse
import csv
import math
import random
import statistics
from pathlib import Path

PASTA = Path(__file__).resolve().parent
CSV_PADRAO = PASTA / "Liga CS Cepedi.xlsx - CSRats.csv"
SAIDA_PADRAO = PASTA / "hurst_resultados.csv"

COL_NOME, COL_NICK, COL_MEDIA, COL_PRIMEIRA_PARTIDA = 3, 4, 5, 7


def numero_br(texto):
    return float(texto.strip().replace(",", "."))


def ler_jogadores(caminho):
    """Lê só o bloco do ranking (linhas cuja 1ª coluna é a posição)."""
    jogadores = []
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        for linha in csv.reader(f):
            if not linha or not linha[0].strip().isdigit():
                continue
            partidas = [numero_br(v) for v in linha[COL_PRIMEIRA_PARTIDA:] if v.strip()]
            # A partida mais recente fica na primeira coluna: inverte para ordem cronológica.
            partidas.reverse()
            jogadores.append({
                "posicao": int(linha[0]),
                "nome": linha[COL_NOME].strip(),
                "nick": linha[COL_NICK].strip(),
                "media": numero_br(linha[COL_MEDIA]) if linha[COL_MEDIA].strip() else None,
                "partidas": partidas,
            })
    return jogadores


def rs_janela(janela):
    n = len(janela)
    media = sum(janela) / n
    acumulado, minimo, maximo = 0.0, 0.0, 0.0
    for x in janela:
        acumulado += x - media
        minimo = min(minimo, acumulado)
        maximo = max(maximo, acumulado)
    desvio = math.sqrt(sum((x - media) ** 2 for x in janela) / n)
    if desvio == 0:
        return None
    return (maximo - minimo) / desvio


def rs_esperado(n):
    """E[R/S] de ruído branco para janelas de tamanho n (Anis-Lloyd com correção de Peters)."""
    gamma = math.exp(math.lgamma((n - 1) / 2) - math.lgamma(n / 2)) / math.sqrt(math.pi)
    soma = sum(math.sqrt((n - i) / i) for i in range(1, n))
    return (n - 0.5) / n * gamma * soma


def hurst(partidas, tau, disjuntas=False):
    if len(partidas) < tau:
        return None
    passo = tau if disjuntas else 1
    valores = [rs_janela(partidas[i:i + tau])
               for i in range(0, len(partidas) - tau + 1, passo)]
    valores = [v for v in valores if v is not None]
    if not valores:
        return None
    rs = sum(valores) / len(valores)
    return {
        "janelas": len(valores),
        "rs": rs,
        "h_bruto": math.log(rs) / math.log(tau),
        "h_corrigido": 0.5 + (math.log(rs) - math.log(rs_esperado(tau))) / math.log(tau),
    }


def teste_embaralhamento(partidas, tau_curto, tau_longo, n_embaralhamentos, disjuntas=False, rng=random):
    """Compara H(tau_curto), H(tau_longo) e delta com a própria série embaralhada."""
    curto, longo = hurst(partidas, tau_curto, disjuntas), hurst(partidas, tau_longo, disjuntas)
    if curto is None or longo is None:
        return None
    observado = {"h_curto": curto["h_corrigido"], "h_longo": longo["h_corrigido"]}
    observado["delta"] = observado["h_longo"] - observado["h_curto"]

    nulos = {chave: [] for chave in observado}
    serie = list(partidas)
    for _ in range(n_embaralhamentos):
        rng.shuffle(serie)
        c, l = hurst(serie, tau_curto, disjuntas), hurst(serie, tau_longo, disjuntas)
        if c is None or l is None:
            continue
        nulos["h_curto"].append(c["h_corrigido"])
        nulos["h_longo"].append(l["h_corrigido"])
        nulos["delta"].append(l["h_corrigido"] - c["h_corrigido"])

    resultado = {}
    for chave, valor in observado.items():
        nulo = nulos[chave]
        media, desvio = statistics.fmean(nulo), statistics.pstdev(nulo)
        extremos = sum(abs(x - media) >= abs(valor - media) for x in nulo)
        cortes = statistics.quantiles(nulo, n=40)
        resultado[chave] = {
            "obs": valor,
            "esperado": media,
            "faixa95": (cortes[0], cortes[-1]),
            "z": (valor - media) / desvio if desvio else None,
            "p": (extremos + 1) / (len(nulo) + 1),
        }
    return resultado


def benjamini_hochberg(pvalores):
    """q-valores (FDR) na mesma ordem da lista; None continua None."""
    indices = sorted((i for i, p in enumerate(pvalores) if p is not None), key=lambda i: pvalores[i])
    q = [None] * len(pvalores)
    menor = 1.0
    for posicao in range(len(indices) - 1, -1, -1):
        i = indices[posicao]
        menor = min(menor, pvalores[i] * len(indices) / (posicao + 1))
        q[i] = menor
    return q


def fmt(valor, casas=3):
    return "—" if valor is None else f"{valor:.{casas}f}"


def main():
    parser = argparse.ArgumentParser(description="Expoente de Hurst por jogador (R/S).")
    parser.add_argument("--csv", type=Path, default=CSV_PADRAO)
    parser.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    parser.add_argument("--taus", type=int, nargs="+", default=[8, 12])
    parser.add_argument("--disjuntas", action="store_true",
                        help="janelas sem sobreposição (padrão: deslizantes)")
    parser.add_argument("--embaralhamentos", type=int, default=0,
                        help="roda o teste de embaralhamento com N repetições (0 desliga)")
    parser.add_argument("--semente", type=int, default=42)
    args = parser.parse_args()

    jogadores = ler_jogadores(args.csv)
    for j in jogadores:
        j["hurst"] = {tau: hurst(j["partidas"], tau, args.disjuntas) for tau in args.taus}

    tau_curto, tau_longo = min(args.taus), max(args.taus)
    chaves_teste = ("h_curto", "h_longo", "delta")
    if args.embaralhamentos:
        rng = random.Random(args.semente)
        for j in jogadores:
            j["teste"] = teste_embaralhamento(j["partidas"], tau_curto, tau_longo,
                                              args.embaralhamentos, args.disjuntas, rng)
        for chave in chaves_teste:
            qs = benjamini_hochberg([j["teste"] and j["teste"][chave]["p"] for j in jogadores])
            for j, q in zip(jogadores, qs):
                if j["teste"]:
                    j["teste"][chave]["q"] = q

    tipo = "disjuntas" if args.disjuntas else "deslizantes"
    print(f"Janelas {tipo}. E[R/S] ruído branco: "
          + ", ".join(f"tau={t}: {rs_esperado(t):.3f}" for t in args.taus))
    cabecalho = f"{'#':>3} {'Nick':<18} {'N':>4}"
    for tau in args.taus:
        cabecalho += f" | {'H'+str(tau)+' corr':>9} {'bruto':>6} {'jan':>4}"
    print(cabecalho)
    print("-" * len(cabecalho))
    for j in jogadores:
        linha = f"{j['posicao']:>3} {j['nick'][:18]:<18} {len(j['partidas']):>4}"
        for tau in args.taus:
            h = j["hurst"][tau]
            linha += (f" | {fmt(h and h['h_corrigido']):>9} {fmt(h and h['h_bruto']):>6} "
                      f"{(h['janelas'] if h else 0):>4}")
        print(linha)

    if args.embaralhamentos:
        print(f"\nTeste de embaralhamento ({args.embaralhamentos}x por jogador), "
              f"delta = H{tau_longo} - H{tau_curto}, ordenado por p do delta")
        cabecalho = (f"{'Nick':<18} {'N':>4} | {'delta':>7} {'esper.':>7} {'z':>6} {'p':>6} {'q':>6}"
                     f" | {'p H'+str(tau_curto):>6} {'p H'+str(tau_longo):>6}")
        print(cabecalho)
        print("-" * len(cabecalho))
        testados = sorted((j for j in jogadores if j["teste"]), key=lambda j: j["teste"]["delta"]["p"])
        for j in testados:
            t = j["teste"]
            d = t["delta"]
            print(f"{j['nick'][:18]:<18} {len(j['partidas']):>4} | {d['obs']:>+7.3f} {d['esperado']:>+7.3f} "
                  f"{fmt(d['z'], 2):>6} {d['p']:>6.3f} {d['q']:>6.3f} | "
                  f"{t['h_curto']['p']:>6.3f} {t['h_longo']['p']:>6.3f}")

    # CSV no padrão do Excel em português (";" e vírgula decimal).
    br = lambda v: "" if v is None else f"{v:.4f}".replace(".", ",")
    with open(args.saida, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        colunas = ["Posicao", "Jogador", "Nick", "Partidas"]
        for tau in args.taus:
            colunas += [f"H_corrigido_tau{tau}", f"H_bruto_tau{tau}", f"RS_medio_tau{tau}", f"Janelas_tau{tau}"]
        if args.embaralhamentos:
            for chave in chaves_teste:
                colunas += [f"{chave}_esperado", f"{chave}_faixa95_inf", f"{chave}_faixa95_sup",
                            f"{chave}_z", f"{chave}_p", f"{chave}_q"]
        w.writerow(colunas)
        for j in jogadores:
            linha = [j["posicao"], j["nome"], j["nick"], len(j["partidas"])]
            for tau in args.taus:
                h = j["hurst"][tau]
                linha += ([br(h["h_corrigido"]), br(h["h_bruto"]), br(h["rs"]), h["janelas"]]
                          if h else ["", "", "", 0])
            if args.embaralhamentos:
                for chave in chaves_teste:
                    t = j["teste"] and j["teste"][chave]
                    linha += ([br(t["esperado"]), br(t["faixa95"][0]), br(t["faixa95"][1]),
                               br(t["z"]), br(t["p"]), br(t["q"])]
                              if t else [""] * 6)
            w.writerow(linha)
    print(f"\nResultados salvos em: {args.saida}")


if __name__ == "__main__":
    main()
