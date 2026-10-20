"""
Monta o PDF do atlas por carteira gerencial: capa, sumário com links, uma divisória por
grupo de carteiras, uma lista por carteira e as fichas, nessa ordem:
grupo de carteiras -> carteira (ordem de CARTEIRAS) -> id_empreendimento.

Mesma estrutura visual de montar_pdf_atlas.py (que organiza por setor e grupo de modelagem).

Uso (Python com PyMuPDF; o export das fichas roda com o Python do QGIS):
    python scripts/montar_pdf_carteiras.py                  # todos os empreendimentos
    python scripts/montar_pdf_carteiras.py --amostra 4      # até 4 por carteira (teste rápido)
    python scripts/montar_pdf_carteiras.py --fichas x.pdf   # reaproveita um PDF de fichas já exportado

Opções:
    --siglas data/siglacarteira.csv   id_empreendimento;sigla_carteira
    --csv data/x.csv                  nome e setor dos empreendimentos (padrão: cenário recomendado)
    --capa data/capa/x.pdf            primeira página desse PDF vira a capa
    --saida atlas_saida/x.pdf
    --dpi 150                         dpi do mapa nas fichas
"""
import argparse
import csv
import glob
import os
import re
import subprocess
import sys
import tempfile

import fitz  # PyMuPDF

PASTA = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(PASTA)

# Grupos de carteiras e carteiras, na ordem do documento: (nome, nome curto, [(sigla, descrição)])
CARTEIRAS = [
    ("Carteiras para Concessão, Parcerias Público-Privadas e Investimentos Privados", "Concessão e parcerias", [
        ("PPP1", "Empreendimentos rodoviários estaduais para contratação ou continuidade da estruturação "
                 "de concessão"),
        ("PPP2", "Empreendimentos rodoviários estaduais para contratação ou continuidade da estruturação "
                 "de concessão patrocinada"),
        ("PPP3", "Empreendimentos aeroportuários para contratação ou continuidade da estruturação de "
                 "concessão administrativa"),
        ("PPP4", "Empreendimentos hidroviários para contratação ou continuidade da estruturação de "
                 "concessão ou concessão patrocinada"),
        ("PPP5", "Empreendimentos dutoviários para início ou continuidade do investimento privado"),
    ]),
    ("Carteiras para Prospecção de Investimentos", "Prospecção de investimentos", [
        ("Plan1", "Empreendimentos rodoviários federais para alinhamento de investimentos"),
        ("Plan2", "Empreendimentos ferroviários federais para alinhamento de investimentos"),
        ("Plan3", "Empreendimentos aeroportuários federais para alinhamento de investimentos"),
        ("Plan4", "Empreendimentos ferroviários federais regionais de passageiros"),
    ]),
    ("Carteiras para Empreendimentos Contratados", "Empreendimentos contratados", [
        ("Reg/Monit1", "Empreendimentos rodoviários estaduais contratados ou em processo de contratação, "
                       "para gestão dos contratos e monitoramento da execução das obras"),
        ("Reg/Monit2", "Empreendimentos rodoviários federais contratados ou em processo de contratação, "
                       "para acompanhamento e monitoramento da execução das obras"),
        ("Reg/Monit3", "Empreendimentos ferroviários federais contratados ou em processo de contratação, "
                       "para acompanhamento e monitoramento da execução das obras"),
        ("Reg/Monit4", "Empreendimentos aeroportuários estaduais contratados ou em processo de contratação, "
                       "para gestão dos contratos e monitoramento da execução das obras"),
        ("Reg/Monit5", "Empreendimentos aeroportuários federais contratados ou em processo de contratação, "
                       "para acompanhamento e monitoramento da execução das obras"),
        ("Reg/Monit6", "Empreendimentos hidroviários e portuários federais contratados ou em processo de "
                       "contratação, para acompanhamento e monitoramento da execução das obras"),
        ("Reg/Monit7", "Empreendimentos dutoviários contratados ou em processo de contratação, para gestão "
                       "dos contratos e monitoramento da execução das obras"),
        ("Reg/Monit8", "Empreendimentos hidroviários e portuários estaduais contratados ou em processo de "
                       "contratação"),
    ]),
    ("Carteiras para Empreendimentos em Rodovias Estaduais de Execução Pública", "Rodovias estaduais de execução pública", [
        ("RodoPub1", "Empreendimentos rodoviários para contratação ou continuidade dos estudos/projetos "
                     "para execução com recursos públicos"),
        ("RodoPub2", "Empreendimentos rodoviários contratados ou em processo de contratação, para "
                     "acompanhamento e monitoramento da execução das obras"),
    ]),
]

ap = argparse.ArgumentParser()
ap.add_argument("--siglas", default=os.path.join(RAIZ, "data", "siglacarteira.csv"))
ap.add_argument("--csv", default=os.path.join(RAIZ, "data", "cenario_recomendado_2_vw_dadosgerais_plataformaonline.csv"))
ap.add_argument("--capa", default=os.path.join(RAIZ, "data", "capa", "capa_atlas_carteira_recomendada.pdf"))
ap.add_argument("--saida", default=os.path.join(RAIZ, "atlas_saida", "atlas_carteiras_gerenciais.pdf"))
ap.add_argument("--amostra", type=int, help="só os N primeiros empreendimentos de cada carteira")
ap.add_argument("--fichas", help="PDF de fichas já exportado (pula o export do QGIS)")
ap.add_argument("--dpi", type=int, default=150)
args = ap.parse_args()

# ---------------------------------------------------------------- dados e ordem
with open(args.csv, encoding="utf-8-sig", newline="") as f:
    dados = {int(float(l["id_empreendimento"])): l for l in csv.DictReader(f, delimiter=";")
             if l["id_empreendimento"]}
with open(args.siglas, encoding="utf-8-sig", newline="") as f:
    siglas = {int(float(l["id_empreendimento"])): l["sigla_carteira"].strip()
              for l in csv.DictReader(f, delimiter=";") if l["id_empreendimento"]}

conhecidas = {sig for _, _, cs in CARTEIRAS for sig, _ in cs}
erros = sorted({s for s in siglas.values() if s not in conhecidas})
if erros:
    sys.exit(f"Siglas sem carteira definida em CARTEIRAS: {erros}")
sem_dados = sorted(i for i in siglas if i not in dados)
if sem_dados:
    sys.exit(f"Ids de {os.path.basename(args.siglas)} que não estão em {os.path.basename(args.csv)}: {sem_dados[:20]}")
fora = len(set(dados) - set(siglas))
if fora:
    print(f"Aviso: {fora} empreendimentos do CSV não têm carteira e ficam fora do atlas")

grupos = []  # [{id, nome, curto, carteiras: [{sigla, desc, emps}]}]
for n, (nome, curto, cs) in enumerate(CARTEIRAS, 1):
    carteiras = []
    for sig, desc in cs:
        emps = [{"id": i, "sigla": sig, "nome": " ".join(dados[i]["nome_empreendimento"].split()),
                 "setor": dados[i]["setor"].strip()} for i in sorted(i for i, s in siglas.items() if s == sig)]
        if args.amostra:
            emps = emps[:args.amostra]
        if emps:
            carteiras.append({"sigla": sig, "desc": desc, "emps": emps})
    if carteiras:
        grupos.append({"id": n, "nome": nome, "curto": curto, "carteiras": carteiras})
emps = [e for g in grupos for c in g["carteiras"] for e in c["emps"]]
print(f"{len(emps)} empreendimentos, {len(grupos)} grupos, "
      f"{sum(len(g['carteiras']) for g in grupos)} carteiras")

# ---------------------------------------------------------------- fichas (QGIS)
if args.fichas:
    arq_fichas = args.fichas
else:
    qgis = sorted(glob.glob(r"C:\Program Files\QGIS *\bin\python-qgis.bat"))
    if not qgis:
        sys.exit("QGIS não encontrado em C:\\Program Files\\QGIS *")
    arq_fichas = os.path.join(tempfile.gettempdir(), "fichas_carteiras.pdf")
    r = subprocess.run([qgis[-1], os.path.join(PASTA, "exportar_atlas.py"), "--formato", "pdf", "--unico",
                        "--dpi", str(args.dpi), "--arquivo", arq_fichas,
                        "--ids", ",".join(str(e["id"]) for e in emps)], cwd=RAIZ)
    if r.returncode != 0:
        sys.exit("Falhou o export das fichas")

fichas = fitz.open(arq_fichas)
pag_ficha = {}  # id -> página no PDF de fichas (o título começa com "<id> - ")
for i, p in enumerate(fichas):
    m = re.match(r"\s*(\d+) - ", p.get_text())
    if m:
        pag_ficha[int(m.group(1))] = i
faltando = [e["id"] for e in emps if e["id"] not in pag_ficha]
if faltando:
    sys.exit(f"Fichas não encontradas no PDF: {faltando[:20]}")

# ---------------------------------------------------------------- estilo
W, H = 595.28, 841.89          # A4
M = 42                         # margem lateral
AZUL = (0x1b / 255, 0x2e / 255, 0x44 / 255)  # cabeçalho das fichas
AZUL_CLARO = (0.42, 0.55, 0.69)              # filete e detalhes
AZUL_SUAVE = (0.85, 0.89, 0.93)              # textos claros sobre o azul
VERDE_ESC = (0.16, 0.30, 0.24)
CINZA = (0.45, 0.45, 0.45)
TEXTO = (0.15, 0.15, 0.15)
URL_WEB = "https://peltws.codemge.com.br/"
URL_WEB_CURTA = "peltws.codemge.com.br"
CSS_TEXTO = """
@font-face {font-family: seg; src: url(segoeui.ttf);}
@font-face {font-family: seg; font-weight: bold; src: url(segoeuib.ttf);}
p {font-family: seg; font-size: 9.5pt; color: #4d4d4d; text-align: justify; line-height: 1.35; margin: 0 0 5pt 0;}
b {color: #1b2e44;}
"""
LINHA = (0.88, 0.88, 0.88)
FONTES = {"r": r"C:\Windows\Fonts\segoeui.ttf", "b": r"C:\Windows\Fonts\segoeuib.ttf"}
fontes = {k: fitz.Font(fontfile=v) for k, v in FONTES.items()}


def usar_fontes(pg):
    for k, v in FONTES.items():
        pg.insert_font(fontname="f" + k, fontfile=v)


def texto(pg, x, y, s, tam, peso="r", cor=AZUL, direita=False):
    if direita:
        x -= fontes[peso].text_length(s, tam)
    pg.insert_text((x, y), s, fontname="f" + peso, fontsize=tam, color=cor)


def cortar(s, tam, largura, peso="r"):
    if fontes[peso].text_length(s, tam) <= largura:
        return s
    while s and fontes[peso].text_length(s + "…", tam) > largura:
        s = s[:-1]
    return s.rstrip() + "…"


def quebrar(s, tam, largura, peso="r"):
    """Quebra o texto em linhas que cabem na largura."""
    linhas, atual = [], ""
    for p in s.split():
        teste = f"{atual} {p}".strip()
        if atual and fontes[peso].text_length(teste, tam) > largura:
            linhas.append(atual)
            atual = p
        else:
            atual = teste
    return linhas + [atual] if atual else linhas


def plural(n, s, p):
    return f"{n} {s if n == 1 else p}"


def n_br(n):
    return f"{n:,}".replace(",", ".")


# ---------------------------------------------------------------- plano de páginas
# Cada página é ("tipo", dados). Sumário e listas são paginados antes de desenhar, para
# que o sumário já saiba o número de página de tudo.
Y0_SUM, FIM, FIM_SUM = 248, H - 70, H - 46  # FIM_SUM: o sumário vai até perto do número da página
L_SUM_GRUPO = W - 2 * M - 60     # largura do título do grupo no sumário
L_SUM_CART = W - 2 * M - 18 - 60  # largura da descrição da carteira no sumário
T_GRUPO, T_CART, LH = 11.5, 9, 1.22


def altura_sum(nivel, item):
    if nivel == "grupo":
        return 6 + len(quebrar(f"{item['id']}. {item['nome']}", T_GRUPO, L_SUM_GRUPO, "b")) * T_GRUPO * LH + 3
    return len(quebrar(f"{item['sigla']} – {item['desc']}", T_CART, L_SUM_CART)) * T_CART * LH + 4


itens_sum = [("grupo", g) if c is None else ("carteira", c) for g in grupos for c in [None, *g["carteiras"]]]
pags_sum, y = [[]], Y0_SUM
for it in itens_sum:
    h = altura_sum(*it)
    if y + h > FIM_SUM:
        pags_sum.append([])
        y = 150  # páginas de continuação não têm o texto de apresentação
    pags_sum[-1].append(it)
    y += h

# lista de cada carteira: a descrição fica no topo e o resto da página vai para a tabela
PASSO_LISTA, T_DESC = 17, 10
for g in grupos:
    for c in g["carteiras"]:
        c["desc_linhas"] = quebrar(c["desc"], T_DESC, W - 2 * M)
        c["y0"] = 118 + len(c["desc_linhas"]) * T_DESC * 1.4 + 40
        c["por_pag"] = int((FIM - c["y0"]) // PASSO_LISTA)

plano = [("capa", None)] + [("sumario", (k, b)) for k, b in enumerate(pags_sum)]
for g in grupos:
    plano.append(("grupo", g))
    for c in g["carteiras"]:
        blocos = [c["emps"][i:i + c["por_pag"]] for i in range(0, len(c["emps"]), c["por_pag"])]
        for k, b in enumerate(blocos):
            plano.append(("lista", (g, c, k, len(blocos), b)))
        plano += [("ficha", (g, c, e)) for e in c["emps"]]

pag = {}  # chave -> índice da página (0-based)
for i, (tipo, d) in enumerate(plano):
    if tipo == "grupo":
        pag[("grupo", d["id"])] = i
    elif tipo == "lista" and d[2] == 0:
        pag[("carteira", d[1]["sigla"])] = i
    elif tipo == "ficha":
        pag[("ficha", d[2]["id"])] = i
PAG_SUMARIO = 1


links = []  # (página, retângulo, destino): inseridos no fim, quando todas as páginas existem


def link(pg, rect, destino):
    links.append((pg.number, fitz.Rect(rect), destino))


def cabecalho(pg, titulo, sub=None):
    pg.draw_rect(fitz.Rect(0, 0, W, 96), color=None, fill=AZUL)
    pg.draw_rect(fitz.Rect(0, 96, W, 99), color=None, fill=AZUL_CLARO)
    tam = 22
    while tam > 15 and fontes["b"].text_length(titulo, tam) > W - 2 * M:
        tam -= 0.5  # título longo: fonte menor
    texto(pg, M, 56, cortar(titulo, tam, W - 2 * M, "b"), tam, "b", (1, 1, 1))
    if sub:
        texto(pg, M, 78, cortar(sub, 10.5, W - 2 * M), 10.5, "r", AZUL_SUAVE)


def rodape(pg, i, voltar=True, cor=None):
    texto(pg, W - M, H - 28, str(i + 1), 8.5, "r", cor or CINZA, direita=True)
    if voltar:
        s = "↑ Sumário"
        texto(pg, M, H - 28, s, 8.5, "b", cor or VERDE_ESC)
        link(pg, (M - 2, H - 40, M + fontes["b"].text_length(s, 8.5) + 2, H - 22), PAG_SUMARIO)


def linha_pontilhada(pg, x0, x1, y):
    if x1 - x0 > 8:
        pg.draw_line((x0 + 3, y), (x1 - 3, y), color=LINHA, width=0.6, dashes="[1 2] 0")


def num_e_pagina(pg, y, n, destino, tam):
    """Coluna da direita do sumário: (n) e a página."""
    texto(pg, W - M - 34, y, f"({n})", 9, "r", CINZA, direita=True)
    texto(pg, W - M, y, str(destino + 1), tam, "b" if tam > 11 else "r", AZUL, direita=True)
    return W - M - 34 - fontes["r"].text_length(f"({n})", 9)


# ---------------------------------------------------------------- montagem
out = fitz.open()
capa = fitz.open(args.capa)
for i, (tipo, d) in enumerate(plano):
    if tipo == "capa":
        out.insert_pdf(capa, from_page=0, to_page=0)
        continue
    if tipo == "ficha":
        g, c, e = d
        out.insert_pdf(fichas, from_page=pag_ficha[e["id"]], to_page=pag_ficha[e["id"]])
        pg = out[-1]
        usar_fontes(pg)
        # no canto esquerdo do cabeçalho da ficha, que fica livre
        s = cortar(f"↑ Sumário   ·   {g['curto']}  ›  Carteira {c['sigla']}", 7, 300)
        texto(pg, 18, 92, s, 7, "r", (0.78, 0.84, 0.9))
        link(pg, (16, 84, 16 + fontes["r"].text_length("↑ Sumário", 7) + 4, 95), PAG_SUMARIO)
        texto(pg, W - 18, H - 5, str(i + 1), 7, "r", CINZA, direita=True)
        texto(pg, 18, H - 5, "↑ Sumário", 7, "b", VERDE_ESC)
        link(pg, (16, H - 13, 18 + fontes["b"].text_length("↑ Sumário", 7) + 2, H - 4), PAG_SUMARIO)
        continue

    pg = out.new_page(width=W, height=H)
    usar_fontes(pg)

    if tipo == "sumario":
        k, bloco = d
        cabecalho(pg, "Sumário" if k == 0 else "Sumário (continuação)",
                  f"Carteira Recomendada do PELTMG · resultados por carteira gerencial · "
                  f"{n_br(len(emps))} empreendimentos")
        if k == 0:
            apresentacao = f"""
<p>Como visão geral dos resultados do PELTMG de Longo Prazo, este atlas apresenta as fichas técnicas
dos {n_br(len(emps))} empreendimentos da Carteira Recomendada organizadas por carteira gerencial. As
carteiras estão reunidas em quatro grupos, conforme o encaminhamento previsto para os empreendimentos:
concessão, parcerias público-privadas e investimentos privados; prospecção de investimentos;
empreendimentos contratados; e rodovias estaduais de execução pública. Clique em um grupo, carteira ou
empreendimento para ir direto à página.</p>
<p>A versão web do Atlas, em <b>{URL_WEB_CURTA}</b>, complementa este documento: nela é possível
pesquisar, filtrar e ordenar a carteira; abrir a ficha de cada empreendimento com mapa interativo e a
lista completa de obras; comparar empreendimentos com seus pares no Painel de Indicadores &amp; BI
(impacto × viabilidade, panorama de investimentos e posição em cada dimensão da priorização); e tirar
dúvidas sobre dados, custos e cenários com o Assistente Virtual.</p>"""
            pg.insert_htmlbox(fitz.Rect(M, 112, W - M, Y0_SUM - 12), apresentacao, css=CSS_TEXTO,
                              archive=fitz.Archive(os.path.dirname(FONTES["r"])))
            for r in pg.search_for(URL_WEB_CURTA):  # insert_htmlbox não cria links
                pg.insert_link({"kind": fitz.LINK_URI, "uri": URL_WEB, "from": r})
        y = Y0_SUM if k == 0 else 150
        for nivel, item in bloco:
            if nivel == "grupo":
                y += 6
                destino = pag[("grupo", item["id"])]
                n = sum(len(c["emps"]) for c in item["carteiras"])
                linhas = quebrar(f"{item['id']}. {item['nome']}", T_GRUPO, L_SUM_GRUPO, "b")
                y0 = y
                for ln in linhas:
                    texto(pg, M, y, ln, T_GRUPO, "b", AZUL)
                    y += T_GRUPO * LH
                yl = y - T_GRUPO * LH
                x1 = num_e_pagina(pg, yl, n, destino, 12.5)
                linha_pontilhada(pg, M + fontes["b"].text_length(linhas[-1], T_GRUPO), x1, yl - 3)
                link(pg, (M - 4, y0 - 13, W - M + 4, yl + 5), destino)
                y += 3
            else:
                destino = pag[("carteira", item["sigla"])]
                linhas = quebrar(f"{item['sigla']} – {item['desc']}", T_CART, L_SUM_CART)
                y0 = y
                for j, ln in enumerate(linhas):
                    if j == 0:  # sigla em negrito
                        sig = item["sigla"]
                        texto(pg, M + 18, y, sig, T_CART, "b", AZUL)
                        texto(pg, M + 18 + fontes["b"].text_length(sig, T_CART), y, ln[len(sig):], T_CART, "r", TEXTO)
                    else:
                        texto(pg, M + 18, y, ln, T_CART, "r", TEXTO)
                    y += T_CART * LH
                yl = y - T_CART * LH
                x1 = num_e_pagina(pg, yl, len(item["emps"]), destino, 10)
                ult = linhas[-1] if len(linhas) > 1 else linhas[0]
                linha_pontilhada(pg, M + 18 + fontes["r"].text_length(ult, T_CART) + (
                    fontes["b"].text_length(item["sigla"], T_CART) - fontes["r"].text_length(item["sigla"], T_CART)
                    if len(linhas) == 1 else 0), x1, yl - 3)
                link(pg, (M - 4, y0 - 11, W - M + 4, yl + 4), destino)
                y += 4
        rodape(pg, i, voltar=False)

    elif tipo == "grupo":
        n = sum(len(c["emps"]) for c in d["carteiras"])
        linhas = quebrar(d["nome"], 28, W - 2 * M, "b")
        alt = 110 + len(linhas) * 34
        lista_h = sum(28 + 12 * len(quebrar(c["desc"], 9, W - 2 * M - 110)) for c in d["carteiras"])
        topo = max(40, min(H * 0.22, H - 60 - alt - 42 - lista_h))  # grupo com muitas carteiras sobe a faixa
        pg.draw_rect(fitz.Rect(0, topo, W, topo + alt), color=None, fill=AZUL)
        pg.draw_rect(fitz.Rect(0, topo + alt, W, topo + alt + 3), color=None, fill=AZUL_CLARO)
        texto(pg, M, topo + 46, f"Grupo de carteiras {d['id']}", 13, "r", AZUL_SUAVE)
        y = topo + 84
        for ln in linhas:
            texto(pg, M, y, ln, 28, "b", (1, 1, 1))
            y += 34
        texto(pg, M, y + 4,
              f"{plural(n, 'empreendimento', 'empreendimentos')} · "
              f"{plural(len(d['carteiras']), 'carteira', 'carteiras')}", 11, "r", AZUL_SUAVE)
        y = topo + alt + 42
        texto(pg, M, y - 16, "Carteiras", 8.5, "b", CINZA)
        texto(pg, W - M, y - 16, "Empreend.  ·  Página", 8.5, "b", CINZA, direita=True)
        for c in d["carteiras"]:
            destino = pag[("carteira", c["sigla"])]
            pg.draw_line((M, y - 13), (W - M, y - 13), color=LINHA, width=0.6)
            y0 = y
            texto(pg, M, y + 3, f"›  Carteira {c['sigla']}", 11, "b", AZUL)
            texto(pg, W - M, y + 3, f"{len(c['emps'])}  ·  {destino + 1}", 10, "r", AZUL_CLARO, direita=True)
            y += 18
            for ln in quebrar(c["desc"], 9, W - 2 * M - 110):
                texto(pg, M + 14, y, ln, 9, "r", CINZA)
                y += 12
            link(pg, (M - 4, y0 - 12, W - M + 4, y - 6), destino)
            y += 10
        pg.draw_line((M, y - 13), (W - M, y - 13), color=LINHA, width=0.6)
        rodape(pg, i)

    elif tipo == "lista":
        g, c, k, total, bloco = d
        sub = f"{g['curto']} · {plural(len(c['emps']), 'empreendimento', 'empreendimentos')}"
        if total > 1:
            sub += f" · lista {k + 1}/{total}"
        cabecalho(pg, f"Carteira {c['sigla']}", sub)
        y = 126
        for ln in c["desc_linhas"]:
            texto(pg, M, y, ln, T_DESC, "r", TEXTO)
            y += T_DESC * 1.4
        y = c["y0"] - 18
        x_setor = W - M - 140
        texto(pg, M, y, "Id", 8.5, "b", CINZA)
        texto(pg, M + 46, y, "Empreendimento", 8.5, "b", CINZA)
        texto(pg, x_setor, y, "Setor", 8.5, "b", CINZA)
        texto(pg, W - M, y, "Página", 8.5, "b", CINZA, direita=True)
        pg.draw_line((M, y + 5), (W - M, y + 5), color=AZUL, width=0.8)
        y = c["y0"]
        for j, e in enumerate(bloco):
            destino = pag[("ficha", e["id"])]
            if j % 2:
                pg.draw_rect(fitz.Rect(M, y - 12, W - M, y + 5), color=None, fill=(0.96, 0.97, 0.98))
            texto(pg, M + 4, y, str(e["id"]), 9, "b", AZUL)
            texto(pg, M + 46, y, cortar(e["nome"], 9, x_setor - M - 54), 9, "r", TEXTO)
            texto(pg, x_setor, y, e["setor"], 9, "r", CINZA)
            texto(pg, W - M - 4, y, str(destino + 1), 9, "r", AZUL, direita=True)
            link(pg, (M, y - 12, W - M, y + 5), destino)
            y += PASSO_LISTA
        rodape(pg, i)

for n, rect, destino in links:
    out[n].insert_link({"kind": fitz.LINK_GOTO, "from": rect, "page": destino, "to": fitz.Point(0, 0)})

# ---------------------------------------------------------------- marcadores
toc = [[1, "Capa", 1], [1, "Sumário", PAG_SUMARIO + 1]]
for g in grupos:
    toc.append([1, f"{g['id']}. {g['nome']}", pag[("grupo", g["id"])] + 1])
    for c in g["carteiras"]:
        toc.append([2, f"Carteira {c['sigla']}", pag[("carteira", c["sigla"])] + 1])
        toc += [[3, f"{e['id']} - {e['nome']}", pag[("ficha", e["id"])] + 1] for e in c["emps"]]
out.set_toc(toc)
out.set_metadata({"title": "PELTMG — Atlas de empreendimentos — Carteira Recomendada por carteira gerencial",
                  "author": "CODEMGE / PELTMG"})
out.subset_fonts()
os.makedirs(os.path.dirname(os.path.abspath(args.saida)), exist_ok=True)
out.save(args.saida, garbage=4, deflate=True)  # 4: junta os logos repetidos em cada ficha
print(f"{len(out)} páginas, {os.path.getsize(args.saida) / 1e6:.1f} MB -> {args.saida}")
