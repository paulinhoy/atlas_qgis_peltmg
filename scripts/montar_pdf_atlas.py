"""
Monta o PDF do atlas da carteira recomendada: capa, sumário com links, uma divisória
por setor, uma lista por grupo de modelagem e as fichas, nessa ordem:
id_setor -> grupo_modelagem -> id_empreendimento.

Uso (Python com PyMuPDF; o export das fichas roda com o Python do QGIS):
    python scripts/montar_pdf_atlas.py                    # todos os empreendimentos do CSV
    python scripts/montar_pdf_atlas.py --amostra 6        # até 6 por grupo (teste rápido)
    python scripts/montar_pdf_atlas.py --fichas x.pdf     # reaproveita um PDF de fichas já exportado

Opções:
    --csv data/x.csv        empreendimentos (padrão: cenário recomendado)
    --capa data/capa/x.pdf  primeira página desse PDF vira a capa
    --saida atlas_saida/x.pdf
    --dpi 150               dpi do mapa nas fichas
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

ap = argparse.ArgumentParser()
ap.add_argument("--csv", default=os.path.join(RAIZ, "data", "cenario_recomendado_2_vw_dadosgerais_plataformaonline.csv"))
ap.add_argument("--capa", default=os.path.join(RAIZ, "data", "capa", "capa_atlas_carteira_recomendada.pdf"))
ap.add_argument("--saida", default=os.path.join(RAIZ, "atlas_saida", "atlas_carteira_recomendada.pdf"))
ap.add_argument("--amostra", type=int, help="só os N primeiros empreendimentos de cada grupo")
ap.add_argument("--fichas", help="PDF de fichas já exportado (pula o export do QGIS)")
ap.add_argument("--dpi", type=int, default=150)
args = ap.parse_args()

# ---------------------------------------------------------------- dados e ordem
with open(args.csv, encoding="utf-8-sig", newline="") as f:
    linhas = [l for l in csv.DictReader(f, delimiter=";") if l["id_empreendimento"]]
emps = sorted(({"id": int(float(l["id_empreendimento"])), "id_setor": int(float(l["id_setor"])),
                "setor": l["setor"].strip(), "grupo": l["grupo_modelagem"].strip(),
                "nome": " ".join(l["nome_empreendimento"].split())} for l in linhas),
              key=lambda e: (e["id_setor"], e["grupo"], e["id"]))

setores = []  # [{nome, grupos: [{nome, emps}]}]
for e in emps:
    if not setores or setores[-1]["id"] != e["id_setor"]:
        setores.append({"id": e["id_setor"], "nome": e["setor"], "grupos": []})
    grupos = setores[-1]["grupos"]
    if not grupos or grupos[-1]["nome"] != e["grupo"]:
        grupos.append({"nome": e["grupo"], "emps": []})
    grupos[-1]["emps"].append(e)
if args.amostra:
    for s in setores:
        for g in s["grupos"]:
            g["emps"] = g["emps"][:args.amostra]
emps = [e for s in setores for g in s["grupos"] for e in g["emps"]]
print(f"{len(emps)} empreendimentos, {len(setores)} setores, "
      f"{sum(len(s['grupos']) for s in setores)} grupos")

# ---------------------------------------------------------------- fichas (QGIS)
if args.fichas:
    arq_fichas = args.fichas
else:
    qgis = sorted(glob.glob(r"C:\Program Files\QGIS *\bin\python-qgis.bat"))
    if not qgis:
        sys.exit("QGIS não encontrado em C:\\Program Files\\QGIS *")
    arq_fichas = os.path.join(tempfile.gettempdir(), "fichas_atlas.pdf")
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


def plural(n, s, p):
    return f"{n} {s if n == 1 else p}"


# ---------------------------------------------------------------- plano de páginas
# Cada página é ("tipo", dados). As listas são paginadas antes de desenhar, para que o
# sumário já saiba o número de página de tudo.
Y0, Y0_SUM, PASSO_SUM, PASSO_LISTA = 150, 236, 19, 17  # Y0_SUM: abaixo do texto de apresentação
POR_PAG_SUM = int((H - 70 - Y0_SUM) // PASSO_SUM)
POR_PAG_LISTA = int((H - 70 - Y0) // PASSO_LISTA)

itens_sum = [("setor", s) if g is None else ("grupo", g) for s in setores for g in [None, *s["grupos"]]]
pags_sum = [itens_sum[i:i + POR_PAG_SUM] for i in range(0, len(itens_sum), POR_PAG_SUM)]

plano = [("capa", None)] + [("sumario", (k, b)) for k, b in enumerate(pags_sum)]
for s in setores:
    plano.append(("setor", s))
    for g in s["grupos"]:
        blocos = [g["emps"][i:i + POR_PAG_LISTA] for i in range(0, len(g["emps"]), POR_PAG_LISTA)]
        for k, b in enumerate(blocos):
            plano.append(("lista", (s, g, k, len(blocos), b)))
        plano += [("ficha", e) for e in g["emps"]]

pag = {}  # chave -> índice da página (0-based)
for i, (tipo, d) in enumerate(plano):
    if tipo == "setor":
        pag[("setor", d["id"])] = i
    elif tipo == "lista" and d[2] == 0:
        pag[("grupo", d[0]["id"], d[1]["nome"])] = i
    elif tipo == "ficha":
        pag[("ficha", d["id"])] = i
PAG_SUMARIO = 1


links = []  # (página, retângulo, destino): inseridos no fim, quando todas as páginas existem


def link(pg, rect, destino):
    links.append((pg.number, fitz.Rect(rect), destino))


def cabecalho(pg, titulo, sub=None):
    pg.draw_rect(fitz.Rect(0, 0, W, 96), color=None, fill=AZUL)
    pg.draw_rect(fitz.Rect(0, 96, W, 99), color=None, fill=AZUL_CLARO)
    tam = 22
    while tam > 15 and fontes["b"].text_length(titulo, tam) > W - 2 * M:
        tam -= 0.5  # nome de grupo longo: título menor
    texto(pg, M, 56, cortar(titulo, tam, W - 2 * M, "b"), tam, "b", (1, 1, 1))
    if sub:
        texto(pg, M, 78, sub, 10.5, "r", AZUL_SUAVE)


def rodape(pg, i, voltar=True, cor=None):
    texto(pg, W - M, H - 28, str(i + 1), 8.5, "r", cor or CINZA, direita=True)
    if voltar:
        s = "↑ Sumário"
        texto(pg, M, H - 28, s, 8.5, "b", cor or VERDE_ESC)
        link(pg, (M - 2, H - 40, M + fontes["b"].text_length(s, 8.5) + 2, H - 22), PAG_SUMARIO)


def linha_pontilhada(pg, x0, x1, y):
    if x1 - x0 > 8:
        pg.draw_line((x0 + 3, y), (x1 - 3, y), color=LINHA, width=0.6, dashes="[1 2] 0")


# ---------------------------------------------------------------- montagem
out = fitz.open()
capa = fitz.open(args.capa)
for i, (tipo, d) in enumerate(plano):
    if tipo == "capa":
        out.insert_pdf(capa, from_page=0, to_page=0)
        continue
    if tipo == "ficha":
        out.insert_pdf(fichas, from_page=pag_ficha[d["id"]], to_page=pag_ficha[d["id"]])
        pg = out[-1]
        usar_fontes(pg)
        # no canto esquerdo do cabeçalho da ficha, que fica livre
        s = f"↑ Sumário   ·   {d['setor']}  ›  {d['grupo']}"
        s = cortar(s, 7, 300)
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
        n_emps = f"{len(emps):,}".replace(",", ".")
        cabecalho(pg, "Sumário" if k == 0 else "Sumário (continuação)",
                  f"Carteira Recomendada do PELTMG · {n_emps} empreendimentos")
        apresentacao = f"""
<p>Este atlas reúne as fichas técnicas dos {n_emps} empreendimentos que compõem a Carteira Recomendada
do PELTMG, divididos por setor e, dentro de cada setor, por grupo de modelagem. Clique em um setor,
grupo ou empreendimento para ir direto à página.</p>
<p>A versão web do Atlas, em <b>{URL_WEB_CURTA}</b>, complementa este documento: nela é possível
pesquisar, filtrar e ordenar a carteira; abrir a ficha de cada empreendimento com mapa interativo e a
lista completa de obras; comparar empreendimentos com seus pares no Painel de Indicadores &amp; BI
(impacto × viabilidade, panorama de investimentos e posição em cada dimensão da priorização); e tirar
dúvidas sobre dados, custos e cenários com o Assistente Virtual.</p>"""
        pg.insert_htmlbox(fitz.Rect(M, 114, W - M, Y0_SUM - 20), apresentacao, css=CSS_TEXTO,
                          archive=fitz.Archive(os.path.dirname(FONTES["r"])))
        for r in pg.search_for(URL_WEB_CURTA):  # insert_htmlbox não cria links
            pg.insert_link({"kind": fitz.LINK_URI, "uri": URL_WEB, "from": r})
        y = Y0_SUM
        for nivel, item in bloco:
            if nivel == "setor":
                y += 6
                destino = pag[("setor", item["id"])]
                n = sum(len(g["emps"]) for g in item["grupos"])
                rot = f"{item['id']}. {item['nome']}"
                texto(pg, M, y, rot, 12.5, "b", AZUL)
                texto(pg, W - M - 34, y, f"({n})", 9, "r", CINZA, direita=True)
                texto(pg, W - M, y, str(destino + 1), 12.5, "b", AZUL, direita=True)
                linha_pontilhada(pg, M + fontes["b"].text_length(rot, 12.5),
                                 W - M - 34 - fontes["r"].text_length(f"({n})", 9), y - 3)
            else:
                destino = pag[("grupo", item["emps"][0]["id_setor"], item["nome"])]
                rot = cortar(item["nome"], 10, W - 2 * M - 110)
                texto(pg, M + 18, y, rot, 10, "r", (0.15, 0.15, 0.15))
                n = f"({len(item['emps'])})"
                texto(pg, W - M - 34, y, n, 9, "r", CINZA, direita=True)
                texto(pg, W - M, y, str(destino + 1), 10, "r", AZUL, direita=True)
                linha_pontilhada(pg, M + 18 + fontes["r"].text_length(rot, 10),
                                 W - M - 34 - fontes["r"].text_length(n, 9), y - 3)
            link(pg, (M - 4, y - 13, W - M + 4, y + 5), destino)
            y += PASSO_SUM
        rodape(pg, i, voltar=False)

    elif tipo == "setor":
        n = sum(len(g["emps"]) for g in d["grupos"])
        topo = H * 0.30
        pg.draw_rect(fitz.Rect(0, topo, W, topo + 170), color=None, fill=AZUL)
        pg.draw_rect(fitz.Rect(0, topo + 170, W, topo + 173), color=None, fill=AZUL_CLARO)
        texto(pg, M, topo + 52, f"Setor {d['id']}", 13, "r", AZUL_SUAVE)
        texto(pg, M, topo + 100, d["nome"], 36, "b", (1, 1, 1))
        texto(pg, M, topo + 135,
              f"{plural(n, 'empreendimento', 'empreendimentos')} · "
              f"{plural(len(d['grupos']), 'grupo de modelagem', 'grupos de modelagem')}",
              11, "r", AZUL_SUAVE)
        y = topo + 212
        texto(pg, M, y - 16, "Grupos de modelagem", 8.5, "b", CINZA)
        texto(pg, W - M, y - 16, "Empreend.  ·  Página", 8.5, "b", CINZA, direita=True)
        for g in d["grupos"]:
            destino = pag[("grupo", d["id"], g["nome"])]
            pg.draw_line((M, y - 13), (W - M, y - 13), color=LINHA, width=0.6)
            rot = cortar(g["nome"], 11, W - 2 * M - 110)
            texto(pg, M, y + 3, "›  " + rot, 11, "b", AZUL)
            texto(pg, W - M, y + 3, f"{len(g['emps'])}  ·  {destino + 1}", 10, "r", AZUL_CLARO, direita=True)
            link(pg, (M - 4, y - 12, W - M + 4, y + 10), destino)
            y += 26
        pg.draw_line((M, y - 13), (W - M, y - 13), color=LINHA, width=0.6)
        rodape(pg, i)

    elif tipo == "lista":
        s, g, k, total, bloco = d
        sub = f"{s['nome']} · {plural(len(g['emps']), 'empreendimento', 'empreendimentos')}"
        if total > 1:
            sub += f" · lista {k + 1}/{total}"
        cabecalho(pg, g["nome"], sub)
        y = Y0 - 18
        texto(pg, M, y, "Id", 8.5, "b", CINZA)
        texto(pg, M + 46, y, "Empreendimento", 8.5, "b", CINZA)
        texto(pg, W - M, y, "Página", 8.5, "b", CINZA, direita=True)
        pg.draw_line((M, y + 5), (W - M, y + 5), color=AZUL, width=0.8)
        y = Y0
        for j, e in enumerate(bloco):
            destino = pag[("ficha", e["id"])]
            if j % 2:
                pg.draw_rect(fitz.Rect(M, y - 12, W - M, y + 5), color=None, fill=(0.96, 0.97, 0.98))
            texto(pg, M + 4, y, str(e["id"]), 9, "b", AZUL)
            texto(pg, M + 46, y, cortar(e["nome"], 9, W - 2 * M - 100), 9, "r", (0.15, 0.15, 0.15))
            texto(pg, W - M - 4, y, str(destino + 1), 9, "r", AZUL, direita=True)
            link(pg, (M, y - 12, W - M, y + 5), destino)
            y += PASSO_LISTA
        rodape(pg, i)

for n, rect, destino in links:
    out[n].insert_link({"kind": fitz.LINK_GOTO, "from": rect, "page": destino, "to": fitz.Point(0, 0)})

# ---------------------------------------------------------------- marcadores
toc = [[1, "Capa", 1], [1, "Sumário", PAG_SUMARIO + 1]]
for s in setores:
    toc.append([1, f"{s['id']}. {s['nome']}", pag[("setor", s["id"])] + 1])
    for g in s["grupos"]:
        toc.append([2, g["nome"], pag[("grupo", s["id"], g["nome"])] + 1])
        toc += [[3, f"{e['id']} - {e['nome']}", pag[("ficha", e["id"])] + 1] for e in g["emps"]]
out.set_toc(toc)
out.set_metadata({"title": "PELTMG — Atlas de empreendimentos — Carteira Recomendada",
                  "author": "CODEMGE / PELTMG"})
out.subset_fonts()
os.makedirs(os.path.dirname(os.path.abspath(args.saida)), exist_ok=True)
out.save(args.saida, garbage=4, deflate=True)  # 4: junta os logos repetidos em cada ficha
print(f"{len(out)} páginas, {os.path.getsize(args.saida) / 1e6:.1f} MB -> {args.saida}")
