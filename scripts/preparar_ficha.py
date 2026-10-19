"""
Gera ficha_pelt.gpkg a partir dos Parquet de data/processed (os mesmos da
aplicação web), aplicando as regras da especificação da ficha técnica.

Tudo sai já formatado (padrão brasileiro, "-" para ausentes), então o layout
do QGIS só exibe os textos — as regras ficam todas aqui, em um lugar só.

Tabelas geradas:
  ficha_empreendimento  1 linha por empreendimento (cobertura do atlas, com geometria)
  ficha_alocacao        linhas da tabela "Dados de Alocação 2055"

Uso (Python do QGIS, que já tem pandas e pyarrow):
    "C:\\Program Files\\QGIS 3.44.4\\bin\\python-qgis.bat" preparar_ficha.py
"""
import math
import os
import sys

import pandas as pd
from osgeo import ogr

PASTA = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(PASTA)  # pasta do projeto (scripts/ fica dentro dela)
DADOS = os.path.join(RAIZ, "data", "processed")
SAIDA = os.path.join(RAIZ, "data", "ficha_pelt.gpkg")
PASTA_CSV_OBRAS = os.path.join(RAIZ, "data")  # CSV de obras (id_obra, valor_obra, extensao_km, ...)
SRID = 4674  # SIRGAS 2000, o mesmo das camadas do projeto

sys.path.insert(0, PASTA)
from baixar_dados import criar_gpkg, escrever_camada, garantir_srs, WKT_4674  # noqa: E402

ORDEM_CARTEIRAS = [("recomendada", "Carteira Recomendada"),
                   ("otimizada", "Carteira Otimizada"),
                   ("analise", "Carteira de Análise")]
NOTAS = ["dimensao_estrategica", "dimensao_financeira", "dimensao_socioeconomica_pond",
         "dimensao_comercial", "dimensao_gerencial", "ic_3_pond", "impacto_avaliado_3_pond_cenario"]
CENARIOS = [1, 2, 3, 4, 8, 10]

# Variantes da tabela de alocação: colunas (rótulo, coluna de origem)
VARIANTES = {
    "rodo": [("Carga", "flt_vehcargafuturo"), ("Ônibus", "flt_vehonibusfuturo"),
             ("Automóvel", "flt_vehautofuturo"), ("Total Veículos", "flt_vehtotalfuturo"),
             ("TKU Total", "flt_tkutotalfuturo")],
    "ton": [("CGC", "flt_toncgcfuturo"), ("CGNC", "flt_toncgncfuturo"), ("GL", "flt_tonglfuturo"),
            ("GSA", "flt_tongsafuturo"), ("GSM", "flt_tongsmfuturo"), ("OGSM", "flt_tonogsmfuturo"),
            ("TON Total", "flt_tontotalfuturo")],
    "tku": [("CGC", "flt_tkucgcfuturo"), ("CGNC", "flt_tkucgncfuturo"), ("GL", "flt_tkuglfuturo"),
            ("GSA", "flt_tkugsafuturo"), ("GSM", "flt_tkugsmfuturo"), ("OGSM", "flt_tkuogsmfuturo"),
            ("TKU Total", "flt_tkutotalfuturo")],
    "aero": [("Demanda (Passageiros/Ano)", "demanda_pax_ano")],
    "ferro_pax": [("Demanda Anual (Passageiros/Ano)", "demanda_ano")],
    "duto": [("Tonelada Total", "volume_2055"), ("TKU Total", "tku")],
}


# ---------------------------------------------------------------------------
# Formatação (padrão brasileiro)
# ---------------------------------------------------------------------------
def vazio(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA


def br_num(v, casas):
    s = f"{v:,.{casas}f}"
    return s.replace(",", "#").replace(".", ",").replace("#", ".")


def fmt_dec(v, casas):
    return "-" if vazio(v) else br_num(float(v), casas)


def fmt_int_trunc(v):
    # zero (inclusive depois de truncar, ex.: 0,4) também aparece como "-"
    if vazio(v) or math.trunc(float(v)) == 0:
        return "-"
    return br_num(math.trunc(float(v)), 0)


def fmt_moeda(v):
    # sem "R$": o cabeçalho da coluna já diz (R$)
    return "-" if vazio(v) else br_num(float(v), 2)


def fmt_pct(v):
    return "-" if vazio(v) else br_num(float(v), 1) + "%"


def fmt_txt(v):
    return "-" if vazio(v) or str(v).strip() == "" else str(v)


def fmt_extensao(v):
    return "-" if vazio(v) or float(v) == 0 else br_num(float(v), 2)


def fmt_duracao(ini, fim):
    if vazio(ini) or vazio(fim):
        return "-"
    return f"{int(ini)} – {int(fim)}"


# ---------------------------------------------------------------------------
# Regras
# ---------------------------------------------------------------------------
_METRICA = None


def linhas_titulo(texto, largura_mm=197.7):
    """Quantas linhas o título ocupa no cabeçalho (Segoe UI 12 pt negrito)."""
    global _METRICA
    if _METRICA is None:
        from qgis.PyQt.QtGui import QFont, QFontMetricsF
        fonte = QFont("Segoe UI")
        fonte.setBold(True)
        fonte.setPointSizeF(12)
        _METRICA = QFontMetricsF(fonte)
    px_por_mm = 96 / 25.4
    n, atual = 1, ""
    for palavra in texto.split(" "):
        tentativa = (atual + " " + palavra).strip()
        if atual and _METRICA.horizontalAdvance(tentativa) / px_por_mm > largura_mm:
            n, atual = n + 1, palavra
        else:
            atual = tentativa
    return n


def ler_obras():
    """
    Tabela "Detalhamento das Obras": CSV mais recente em data/ com as colunas
    id_obra e valor_obra. Ordem: maior valor primeiro (sem valor por último).
    """
    import glob
    candidatos = []
    for arq in glob.glob(os.path.join(PASTA_CSV_OBRAS, "*.csv")):
        with open(arq, encoding="utf-8-sig") as h:
            cab = h.readline()
        if "id_obra" in cab and "valor_obra" in cab:
            candidatos.append(arq)
    if not candidatos:
        sys.exit(f"Nenhum CSV de obras (com id_obra e valor_obra) em {PASTA_CSV_OBRAS}")
    arq = max(candidatos, key=os.path.getmtime)
    df = pd.read_csv(arq, sep=";", encoding="utf-8-sig", decimal=".")
    padronizada = df["descricao_obra_padronizada"]
    df["descricao"] = padronizada.where(padronizada.notna() & (padronizada.astype(str).str.strip() != ""),
                                        df["descricao_obra"])
    df = df.sort_values(["id_empreendimento", "valor_obra", "id_obra"],
                        ascending=[True, False, True], na_position="last")
    linhas = []
    for id_emp, grupo in df.groupby("id_empreendimento", sort=False):
        for ordem, r in enumerate(grupo.itertuples()):
            valor = "-" if vazio(r.valor_obra) or float(r.valor_obra) == 0 else br_num(float(r.valor_obra), 2)
            linhas.append((int(id_emp), ordem, int(r.id_obra), fmt_txt(r.descricao), fmt_txt(r.intervencao),
                           fmt_txt(r.tipo_infraestrutura), fmt_extensao(r.extensao_km), valor))
    return os.path.basename(arq), linhas


def registro_base(linhas_carteira):
    """Seção 2: linha da carteira com maior precedência + complemento das notas."""
    por_carteira = {r["carteira"]: r for r in linhas_carteira}
    ordem = [(k, nome) for k, nome in ORDEM_CARTEIRAS if k in por_carteira]
    chave, nome_fonte = ordem[0]
    base = dict(por_carteira[chave])
    for campo in NOTAS:
        if vazio(base.get(campo)):
            for k, _ in ordem[1:]:
                if not vazio(por_carteira[k].get(campo)):
                    base[campo] = por_carteira[k][campo]
                    break
    return base, nome_fonte


def regra_alocacao(base):
    """Seção 3.5: (número da regra, variante)."""
    setor = base["id_setor"]
    passageiros = base.get("natureza_empreendimento") == "Transporte de Pessoas"
    grupo = base.get("id_grupo_modelagem")
    if setor == 4:
        return 0, None
    if setor == 1:
        return 1, "rodo"
    if setor == 2 and passageiros:
        return 2, "ferro_pax"
    if setor == 2 and grupo == 2:
        return 3, "ton"
    if setor == 2 and grupo == 1:
        return 4, "tku"
    if setor == 3:
        return 5, "ton"
    if setor == 5:
        return 6, "aero"
    if setor == 6:
        return 7, "duto"
    return 8, "tku"


def main():
    from qgis.core import QgsApplication
    app = QgsApplication([], True)  # necessário para medir texto com a fonte real
    ler = lambda nome: pd.read_parquet(os.path.join(DADOS, nome))  # noqa: E731
    carteiras = ler("carteiras.parquet")
    resumo = ler("resumo_financeiro.parquet")
    lp = ler("dados_financeiro.parquet")
    aloc = ler("alocacao_empreendimento.parquet")
    aero = ler("demanda_pax_aero_ano.parquet").dropna(subset=["id_empreendimento"])
    duto = ler("demanda_duto_ano.parquet")
    ferro_pax = ler("demanda_pax_ferro_ano.parquet")
    geo = ler("empreendimento_geo.parquet").set_index("id_empreendimento")

    resumo_idx = {(int(r.id_empreendimento), int(r.id_cenario)): r for r in resumo.itertuples()}
    lp_dup = set(lp.loc[lp.id_empreendimento.duplicated(), "id_empreendimento"])
    lp_idx = {int(r.id_empreendimento): r for r in lp.drop_duplicates("id_empreendimento").itertuples()}
    fontes_aloc = {
        "rodo": aloc, "ton": aloc, "tku": aloc,
        "aero": aero.astype({"id_empreendimento": "int64"}),
        "ferro_pax": ferro_pax, "duto": duto,
    }
    sem_cenario = {"ferro_pax", "duto"}

    fichas, linhas_aloc, avisos = [], [], []
    for id_emp, grupo_linhas in carteiras.groupby("id_empreendimento"):
        id_emp = int(id_emp)
        base, fonte_carteira = registro_base(grupo_linhas.to_dict("records"))

        # --- financeiro (3.4)
        if (id_emp, 10) in resumo_idx:
            fonte_fin, r = "Cenário Recomendado", resumo_idx[(id_emp, 10)]
        elif (id_emp, 8) in resumo_idx or (id_emp, 7) in resumo_idx:
            fonte_fin, r = "Cenário Otimizado", resumo_idx.get((id_emp, 8)) or resumo_idx[(id_emp, 7)]
        else:
            fonte_fin, r = "Custo Econômico LP", None
        if r is not None:
            capex, opex, receita = r.capex, r.opex, r.receita_codemge
            tirm = r.tirm_codemge if not vazio(r.tirm_codemge) else (
                None if vazio(base["tirm"]) else base["tirm"] * 100)
        else:
            l = lp_idx.get(id_emp)
            if id_emp in lp_dup:
                avisos.append(f"{id_emp}: dados_financeiro tem 2 linhas; usada a primeira")
            if l is None:
                avisos.append(f"{id_emp}: sem nenhuma fonte financeira")
            capex = None if l is None else l.capex_empreendimento_atualizado
            opex = None if l is None else l.opex_empreendimento_atualizado
            receita = None if l is None else l.receita
            tirm = None if vazio(base["tirm"]) else base["tirm"] * 100
        total = None if vazio(capex) or vazio(opex) else capex + opex

        # --- alocação (3.5)
        regra, variante = regra_alocacao(base)
        n_aloc = 0
        if variante:
            df = fontes_aloc[variante]
            df = df[df.id_empreendimento == id_emp]
            if variante not in sem_cenario:
                df = df[df.id_cenario.isin(CENARIOS)].sort_values("id_cenario")
            for ordem, row in enumerate(df.to_dict("records")):
                cen = "" if variante in sem_cenario else str(int(row["id_cenario"]))
                valores = [fmt_int_trunc(row[col]) for _, col in VARIANTES[variante]]
                valores += [""] * (7 - len(valores))
                linhas_aloc.append((id_emp, variante, ordem, cen, *valores))
                n_aloc += 1

        # --- geometria
        wkb, env = None, None
        if id_emp in geo.index:
            g = geo.loc[id_emp]
            wkt = g.geom_linha if not vazio(g.geom_linha) else g.geom_ponto
            if not vazio(wkt):
                og = ogr.CreateGeometryFromWkt(wkt)
                wkb = og.ExportToIsoWkb()
                minx, maxx, miny, maxy = og.GetEnvelope()
                env = (minx, maxx, miny, maxy)
        if wkb is None:
            avisos.append(f"{id_emp}: sem geometria em empreendimento_geo")

        # Nomes como "BR-040/BR-262/.../AMG-900" não têm espaços e vazariam do
        # cabeçalho (o QGIS só quebra linha em espaço). Só nesses trechos muito
        # longos o "/" ganha um espaço depois; os demais nomes ficam intactos.
        nome = " ".join(p.replace("/", "/ ") if len(p) > 40 else p
                        for p in fmt_txt(base["nome_empreendimento"]).split(" "))
        titulo = f"{id_emp} - {nome}"
        fichas.append((
            id_emp, titulo, linhas_titulo(titulo),
            f"Setor: {fmt_txt(base['setor'])}   |   Esfera: {fmt_txt(base['esfera_acao'])}",
            int(base["id_setor"]), fmt_txt(base["setor"]), fmt_txt(base["grupo_modelagem"]),
            None if vazio(base.get("id_grupo_modelagem")) else int(base["id_grupo_modelagem"]),
            fmt_txt(base["natureza_empreendimento"]),
            # metadados (3.2)
            fmt_txt(base["origem_ajustada"]), fmt_txt(base["descr_status_empreendimento"]),
            fmt_txt(base["natureza_empreendimento"]), fmt_extensao(base["extensao_km"]),
            fmt_txt(base["grupo_modelagem"]), fmt_txt(base["responsavel_gestao_infraestrutura"]),
            fmt_duracao(base["data_inicio"], base["data_conclusao"]),
            # priorização (3.3)
            fonte_carteira,
            fmt_dec(base["dimensao_estrategica"], 1), fmt_dec(base["dimensao_financeira"], 5),
            fmt_dec(base["dimensao_socioeconomica_pond"], 5), fmt_dec(base["dimensao_comercial"], 4),
            fmt_dec(base["dimensao_gerencial"], 4), fmt_dec(base["ic_3_pond"], 5),
            fmt_txt(base["impacto_avaliado_3_pond_cenario"]),
            # financeiro (3.4)
            fonte_fin, fmt_moeda(capex), fmt_moeda(opex), fmt_moeda(total), fmt_moeda(receita),
            fmt_pct(tirm), fmt_txt(base["viabilidade"]),
            # alocação (3.5)
            regra, variante or "", n_aloc,
            wkb, *(env or (None, None, None, None)),
        ))

    col_ficha = [
        ("id_empreendimento", "MEDIUMINT"), ("titulo", "TEXT"), ("titulo_linhas", "MEDIUMINT"),
        ("subtitulo", "TEXT"),
        ("id_setor", "MEDIUMINT"), ("setor", "TEXT"), ("grupo_modelagem", "TEXT"),
        ("id_grupo_modelagem", "MEDIUMINT"), ("natureza_empreendimento", "TEXT"),
        ("meta_origem", "TEXT"), ("meta_status", "TEXT"), ("meta_natureza", "TEXT"),
        ("meta_extensao", "TEXT"), ("meta_grupo", "TEXT"), ("meta_responsavel", "TEXT"),
        ("meta_duracao", "TEXT"),
        ("fonte_carteira", "TEXT"), ("nota_estrategica", "TEXT"), ("nota_financeira", "TEXT"),
        ("nota_socioeconomica", "TEXT"), ("nota_comercial", "TEXT"), ("nota_gerencial", "TEXT"),
        ("nota_ic", "TEXT"), ("nota_impacto", "TEXT"),
        ("fonte_financeiro", "TEXT"), ("fin_capex", "TEXT"), ("fin_opex", "TEXT"),
        ("fin_total", "TEXT"), ("fin_receita", "TEXT"), ("fin_tirm", "TEXT"),
        ("fin_viabilidade", "TEXT"),
        ("regra_alocacao", "MEDIUMINT"), ("aloc_variante", "TEXT"), ("aloc_linhas", "MEDIUMINT"),
    ]
    col_aloc = [("id_empreendimento", "MEDIUMINT"), ("variante", "TEXT"), ("ordem", "MEDIUMINT"),
                ("cenario", "TEXT")] + [(f"c{i}", "TEXT") for i in range(1, 8)]

    temp = SAIDA + ".tmp"
    if os.path.exists(temp):
        os.remove(temp)
    con = criar_gpkg(temp)
    garantir_srs(con, SRID, WKT_4674, "SIRGAS 2000")
    n1 = escrever_camada(con, "ficha_empreendimento", col_ficha, ("geom", "GEOMETRY", SRID), fichas)
    n2 = escrever_camada(con, "ficha_alocacao", col_aloc, None, linhas_aloc)
    con.execute("CREATE INDEX idx_aloc_emp ON ficha_alocacao(id_empreendimento)")
    arq_obras, linhas_obras = ler_obras()
    col_obras = [("id_empreendimento", "MEDIUMINT"), ("ordem", "MEDIUMINT"), ("id_obra", "MEDIUMINT"),
                 ("descricao", "TEXT"), ("intervencao", "TEXT"), ("tipo_infraestrutura", "TEXT"),
                 ("extensao", "TEXT"), ("valor", "TEXT")]
    n3 = escrever_camada(con, "ficha_obras", col_obras, None, linhas_obras)
    con.execute("CREATE INDEX idx_obras_emp ON ficha_obras(id_empreendimento)")
    con.commit()
    con.close()
    os.replace(temp, SAIDA)

    df = pd.DataFrame(fichas, columns=[c for c, _ in col_ficha] + ["_wkb", "_a", "_b", "_c", "_d"])
    print(f"{n1} empreendimentos, {n2} linhas de alocação, {n3} obras ({arq_obras}) -> {SAIDA}\n")
    print("Fonte da carteira:", df.fonte_carteira.value_counts().to_dict())
    print("Fonte financeira: ", df.fonte_financeiro.value_counts().to_dict())
    print("Regra de alocação:", df.regra_alocacao.value_counts().sort_index().to_dict())
    print("Sem dados de alocação (regras 1-8):", int(((df.regra_alocacao > 0) & (df.aloc_linhas == 0)).sum()))
    if avisos:
        print(f"\n{len(avisos)} aviso(s):")
        for a in avisos[:40]:
            print("  " + a)


if __name__ == "__main__":
    main()
