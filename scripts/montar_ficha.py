"""
Monta o projeto Atlas_Ficha_PELTMG.qgz com o layout "Ficha PELTMG" (uma
página por empreendimento), a partir do layout "Atlas Geral rodo final" do
projeto local e das tabelas de ficha_pelt.gpkg (geradas por preparar_ficha.py).

Uso:
    "C:\\Program Files\\QGIS 3.44.4\\bin\\python-qgis.bat" montar_ficha.py
"""
import os
import sys

from qgis.core import (
    QgsApplication, QgsLayoutFrame, QgsLayoutItemAttributeTable, QgsLayoutItemLabel,
    QgsLayoutItemLegend, QgsLayoutItemMap, QgsLegendStyle, QgsLayoutItemPicture, QgsLayoutItemShape,
    QgsLayoutMultiFrame, QgsLayoutObject, QgsLayoutPoint, QgsLayoutSize, QgsLayoutTable,
    QgsLayoutTableColumn, QgsProject, QgsProperty, QgsRenderContext, QgsTextFormat, QgsTextRenderer, QgsUnitTypes, QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont

PASTA = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(PASTA)  # pasta do projeto (scripts/ fica dentro dela)
PROJETO_BASE = os.path.join(RAIZ, "projetos", "Atlas_WS_Gerencial_local.qgz")
GPKG_FICHA = os.path.join(RAIZ, "data", "ficha_pelt.gpkg")
SAIDA = os.path.join(RAIZ, "projetos", "Atlas_Ficha_PELTMG.qgz")
LAYOUT_BASE = "Atlas Geral rodo final"
LAYOUT_NOVO = "Ficha PELTMG"

# ---------------------------------------------------------------------------
# Grade do layout (mm) — tudo alinhado à faixa azul do cabeçalho
# ---------------------------------------------------------------------------
X0, X1 = 3.5, 206.2
LARG = X1 - X0
PAGINA_FIM = 293.0                   # limite inferior do conteúdo (margem de 4 mm)
AZUL = QColor("#192e40")
BRANCO = QColor("#f8f8f8")
FONTE = "Segoe UI"
TITULO_H = 5.2                       # linha de título de seção
GAP_TITULO_TABELA = 0.8              # título -> tabela (igual em todas as seções)
GAP_SECAO = 2.5                      # fim de uma tabela -> próximo título
MARGEM_CELULA = 1.0
BORDA_VISUAL = 1.45                  # quanto a moldura da faixa azul/legenda avança além da caixa
GRADE_EXTERNA = 0.45                 # linha de grade branca na borda externa das tabelas
TX0 = X0 - BORDA_VISUAL - GRADE_EXTERNA          # tabelas: o fundo azul do cabeçalho alinha com a
TX1 = X1 + BORDA_VISUAL + GRADE_EXTERNA          # borda visível dos painéis (2,0 a 207,6 mm)
TLARG = TX1 - TX0
CAB_TABELA = 6.3                     # altura do cabeçalho de tabela (medida)
LINHA_TABELA = 6.05                  # altura de uma linha de conteúdo (medida)
FOLGA_MOLDURA = 3.0                  # a moldura da tabela é maior que o conteúdo (o QGIS não desenha linha que não cabe)
ALTURA_LEGENDA = 28.0
OBRAS_MAX = 40                       # teto técnico; na prática vale o que couber na página
ESCALA_MINIMA = 50000                # mapa nunca mais próximo que 1:50.000
MARGEM_MAPA = 0.2                    # folga em volta da geometria (20%, como no atlas atual)

# Cabeçalho: logos (y 6,5–16,3) / título (até 2 linhas; a 3ª, rara, fica à esquerda) / subtítulo à direita
CAB_Y, CAB_H = 5.4, 28.8
TITULO_Y, TITULO_ALT = 16.4, 16.0
SUBTITULO_Y = 28.7
CORPO_Y = CAB_Y + CAB_H + 2.2        # início do mapa e do painel de metadados

FILTRO_ATLAS = '"id_empreendimento" = @atlas_pagename'
C, R = Qt.AlignHCenter, Qt.AlignRight


def mm(x, y):
    return QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters)


def tam(w, h):
    return QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters)


def formato(tamanho, negrito=False, cor=QColor("black")):
    f = QgsTextFormat()
    fonte = QFont(FONTE)
    fonte.setBold(negrito)
    f.setFont(fonte)
    f.setSize(tamanho)
    f.setSizeUnit(QgsUnitTypes.RenderPoints)
    f.setColor(cor)
    return f


def novo_label(layout, texto, x, y, w, h, fmt, alinh=Qt.AlignLeft, valinh=Qt.AlignVCenter):
    lb = QgsLayoutItemLabel(layout)
    lb.setText(texto)
    lb.setTextFormat(fmt)
    lb.setHAlign(alinh)
    lb.setVAlign(valinh)
    lb.setMarginX(0)
    lb.setMarginY(0)
    lb.setFrameEnabled(False)
    lb.setBackgroundEnabled(False)
    layout.addLayoutItem(lb)
    lb.attemptMove(mm(x, y))
    lb.attemptResize(tam(w, h))
    return lb


def mover(item, x, y, w=None, h=None):
    item.attemptMove(mm(x, y))
    if w is not None:
        item.attemptResize(tam(w, h))


def dd(item, propriedade, expressao):
    item.dataDefinedProperties().setProperty(propriedade, QgsProperty.fromExpression(expressao))


def ocultar_quando(item, expressao):
    dd(item, QgsLayoutObject.ExcludeFromExports, expressao)


def colunas(t, specs):
    """specs: [(cabeçalho, campo, peso, alinhamento)] — as larguras preenchem LARG exatamente."""
    n = len(specs)
    grade = t.gridStrokeWidth() if t.showGrid() and t.verticalGrid() else 0
    util = TLARG - n * 2 * MARGEM_CELULA - (n + 1) * grade
    soma = sum(s[2] for s in specs)
    cols = []
    for cab, campo, peso, al in specs:
        c = QgsLayoutTableColumn(cab)
        c.setAttribute(campo)
        c.setWidth(util * peso / soma)
        c.setHAlignment(al)
        c.setVAlignment(Qt.AlignVCenter)
        cols.append(c)
    t.setColumns(cols)


def largura_texto(texto, fmt):
    """Largura do texto em mm, medida com a fonte real."""
    ctx = QgsRenderContext()
    ctx.setScaleFactor(96 / 25.4)
    return QgsTextRenderer.textWidth(ctx, fmt, [texto]) / ctx.scaleFactor()


def ajustar_colunas(t, specs, valores, fonte_minima=8.0):
    """
    Larguras pelo maior texto real de cada coluna (cabeçalho ou valor). Se não
    couber na largura da página, reduz a fonte do conteúdo só o necessário.
    Devolve o tamanho de fonte usado.
    """
    n = len(specs)
    grade = t.gridStrokeWidth() if t.showGrid() and t.verticalGrid() else 0
    util = TLARG - n * 2 * MARGEM_CELULA - (n + 1) * grade
    cab, conteudo = t.headerTextFormat(), QgsTextFormat(t.contentTextFormat())
    tamanho = conteudo.size()
    # só os 20 textos mais longos de cada coluna precisam ser medidos
    candidatos = {campo: sorted({str(v) for v in valores.get(campo, [])} | {""}, key=len)[-20:]
                  for _, campo, _, _ in specs}
    while True:
        conteudo.setSize(tamanho)
        maiores = [max(candidatos[campo], key=lambda v: largura_texto(v, conteudo)) for _, campo, _, _ in specs]
        precisa = [max(largura_texto(c[0], cab), largura_texto(m, conteudo)) + 1.5 for c, m in zip(specs, maiores)]
        if sum(precisa) <= util or tamanho <= fonte_minima:
            break
        tamanho -= 0.25
    t.setContentTextFormat(conteudo)
    sobra = util - sum(precisa)
    larguras = [p + sobra * p / sum(precisa) for p in precisa]
    colunas(t, [(c[0], c[1], w, c[3]) for c, w in zip(specs, larguras)])
    return tamanho


def copiar_estilo(origem, destino):
    destino.setHeaderTextFormat(origem.headerTextFormat())
    destino.setContentTextFormat(origem.contentTextFormat())
    destino.setHeaderHAlignment(QgsLayoutTable.HeaderCenter)
    destino.setShowGrid(origem.showGrid())
    destino.setGridStrokeWidth(origem.gridStrokeWidth())
    destino.setGridColor(origem.gridColor())
    destino.setHorizontalGrid(origem.horizontalGrid())
    destino.setVerticalGrid(origem.verticalGrid())
    destino.setBackgroundColor(origem.backgroundColor())
    for grupo in (QgsLayoutTable.OddColumns, QgsLayoutTable.EvenColumns, QgsLayoutTable.OddRows,
                  QgsLayoutTable.EvenRows, QgsLayoutTable.FirstColumn, QgsLayoutTable.LastColumn,
                  QgsLayoutTable.HeaderRow, QgsLayoutTable.FirstRow, QgsLayoutTable.LastRow):
        estilo = origem.cellStyle(grupo)
        if estilo is not None:
            destino.setCellStyle(grupo, estilo)
    destino.setCellMargin(MARGEM_CELULA)
    destino.setWrapBehavior(QgsLayoutTable.WrapText)


def nova_tabela(layout, modelo, camada, filtro, y, h, specs, max_linhas, vazio_msg=None):
    t = QgsLayoutItemAttributeTable(layout)
    layout.addMultiFrame(t)
    t.setVectorLayer(camada)
    copiar_estilo(modelo, t)
    t.setFilterFeatures(True)
    t.setFeatureFilter(filtro)
    t.setMaximumNumberOfFeatures(max_linhas)
    t.setResizeMode(QgsLayoutMultiFrame.UseExistingFrames)
    colunas(t, specs)
    if vazio_msg:
        t.setEmptyTableBehavior(QgsLayoutTable.ShowMessage)
        t.setEmptyTableMessage(vazio_msg)
    frame = QgsLayoutFrame(layout, t)
    frame.setBackgroundEnabled(False)  # a moldura tem folga; sem fundo ela não cobre o título seguinte
    frame.setFrameEnabled(False)
    mover(frame, TX0, y, TLARG, h)
    t.addFrame(frame)
    return t, frame


def expr_extensao_mapa(lado, largura_mm, altura_mm):
    """
    Extensão do mapa calculada a partir da geometria do empreendimento (em
    EPSG:3857): bbox + 20% de folga, na proporção da moldura, nunca mais
    próxima que 1:50.000. Funciona também para um ponto isolado.
    """
    razao = largura_mm / altura_mm
    # meia-largura mínima em metros de projeção (escala real corrigida pela latitude)
    min_meia = f"({ESCALA_MINIMA} * {largura_mm / 1000 / 2} / cos(radians(y(centroid(@atlas_geometry)))))"
    g = "transform(@atlas_geometry, 'EPSG:4674', 'EPSG:3857')"
    meia_w = (f"max({min_meia}, bounds_width(@g) * {0.5 + MARGEM_MAPA}, "
              f"bounds_height(@g) * {0.5 + MARGEM_MAPA} * {razao})")
    cx, cy = "x(centroid(bounds(@g)))", "y(centroid(bounds(@g)))"
    corpo = {
        "xmin": f"{cx} - @mw", "xmax": f"{cx} + @mw",
        "ymin": f"{cy} - @mw / {razao}", "ymax": f"{cy} + @mw / {razao}",
    }[lado]
    return f"with_variable('g', {g}, with_variable('mw', {meia_w}, {corpo}))"


def caminhos_relativos(qgz):
    """
    O QGIS grava em caminho absoluto as fontes de reserva das tabelas do layout
    (vectorLayerSource). Troca a pasta do projeto por "../" (o .qgz fica em projetos/) para funcionar
    (e não expor o caminho local) em qualquer máquina.
    """
    import zipfile
    with zipfile.ZipFile(qgz) as z:
        arquivos = {n: z.read(n) for n in z.namelist()}
    nome = next(n for n in arquivos if n.endswith(".qgs"))
    xml = arquivos[nome].decode("utf-8")
    for pasta in {RAIZ.replace("\\", "/"), RAIZ}:
        xml = xml.replace(pasta.rstrip("/\\") + "/", "../").replace(pasta.rstrip("/\\") + "\\", "../")
    arquivos[nome] = xml.encode("utf-8")
    with zipfile.ZipFile(qgz, "w", zipfile.ZIP_DEFLATED) as z:
        for n, dados in arquivos.items():
            z.writestr(n, dados)


def main():
    app = QgsApplication([], True)  # necessário para medir texto com a fonte real
    app.initQgis()
    projeto = QgsProject.instance()
    if not projeto.read(PROJETO_BASE):
        sys.exit(f"Não consegui abrir {PROJETO_BASE}")

    # --- camadas da ficha
    ficha = QgsVectorLayer(f"{GPKG_FICHA}|layername=ficha_empreendimento", "ficha_empreendimento", "ogr")
    aloc = QgsVectorLayer(f"{GPKG_FICHA}|layername=ficha_alocacao", "ficha_alocacao", "ogr")
    obras = QgsVectorLayer(f"{GPKG_FICHA}|layername=ficha_obras", "ficha_obras", "ogr")
    if not (ficha.isValid() and aloc.isValid() and obras.isValid()):
        sys.exit("ficha_pelt.gpkg não encontrado/inválido — rode preparar_ficha.py antes")
    raiz = projeto.layerTreeRoot()
    for camada in (ficha, aloc, obras):
        projeto.addMapLayer(camada, False)
        raiz.insertLayer(0, camada).setItemVisibilityChecked(False)

    # --- layout: cópia do rodo final
    gerente = projeto.layoutManager()
    if gerente.layoutByName(LAYOUT_NOVO):
        gerente.removeLayout(gerente.layoutByName(LAYOUT_NOVO))
    layout = gerente.duplicateLayout(gerente.layoutByName(LAYOUT_BASE), LAYOUT_NOVO)

    itens = list(layout.items())
    labels = [i for i in itens if isinstance(i, QgsLayoutItemLabel)]
    tabelas = [m for m in layout.multiFrames() if isinstance(m, QgsLayoutItemAttributeTable)]
    mapa = next(i for i in itens if isinstance(i, QgsLayoutItemMap))
    legenda = next(i for i in itens if isinstance(i, QgsLayoutItemLegend))
    faixa = next(i for i in itens if isinstance(i, QgsLayoutItemShape))
    seta = next(i for i in itens if isinstance(i, QgsLayoutItemPicture) and i.id() == "Seta Norte")
    for fig in itens:  # logos: da pasta logos/ do projeto (antes vinham do drive R:)
        if isinstance(fig, QgsLayoutItemPicture) and "logo" in fig.picturePath().lower():
            # compara ignorando espaços repetidos ("codemge -  branco" no projeto original)
            nome = " ".join(os.path.basename(fig.picturePath().replace("\\", "/")).split())
            achados = [a for a in os.listdir(os.path.join(RAIZ, "logos")) if " ".join(a.split()) == nome]
            if not achados:
                sys.exit(f"Logo não encontrado em logos/: {nome}")
            fig.setPicturePath(os.path.join(RAIZ, "logos", achados[0]))
            print(f"  logo: {achados[0]}")

    def label_com(trecho):
        return next(lb for lb in labels if trecho in lb.text())

    # --- atlas
    atlas = layout.atlas()
    atlas.setCoverageLayer(ficha)
    atlas.setPageNameExpression('"id_empreendimento"')
    atlas.setFilenameExpression('"id_empreendimento"')
    atlas.setSortFeatures(True)
    atlas.setSortExpression("lpad(to_string(\"id_setor\"), 2, '0') || lpad(to_string(\"id_empreendimento\"), 6, '0')")
    atlas.setSortAscending(True)
    atlas.setFilterFeatures(False)
    atlas.setHideCoverage(True)
    atlas.setEnabled(True)

    # --- cabeçalho: faixa um pouco mais alta para título de até 3 linhas + subtítulo próprio
    mover(faixa, faixa.positionWithUnits().x(), CAB_Y, faixa.sizeWithUnits().width(), CAB_H)
    titulo = label_com('"nome_empreendimento"')
    titulo.setText('[%"titulo"%]')
    titulo.setVAlign(Qt.AlignTop)
    mover(titulo, X0 + 2.5, TITULO_Y, LARG - 5, TITULO_ALT)
    subtitulo = label_com("Setor:")
    subtitulo.setText('[%"subtitulo"%]')
    subtitulo.setHAlign(Qt.AlignRight)
    subtitulo.setVAlign(Qt.AlignVCenter)
    mover(subtitulo, X1 - 2.5 - 90, SUBTITULO_Y, 90, 4.6)
    # título com 3 linhas (raro): o subtítulo sobe para a faixa dos logos, à esquerda do logo da direita
    dd(subtitulo, QgsLayoutObject.PositionY, f"if(\"titulo_linhas\" >= 3, 9.0, {SUBTITULO_Y})")
    dd(subtitulo, QgsLayoutObject.PositionX, f"if(\"titulo_linhas\" >= 3, {150.5 - 90}, {X1 - 2.5 - 90})")

    # --- corpo: metadados + mapa descem para abrir espaço ao cabeçalho
    meta = label_com("Origem")
    meta.setText(
        "Origem\n[%\"meta_origem\"%]\n\n"
        "Status\n[%\"meta_status\"%]\n\n"
        "Natureza\n[%\"meta_natureza\"%]\n\n"
        "Extensão (Km)\n[%\"meta_extensao\"%]\n\n"
        "Grupo de Modelagem\n[%\"meta_grupo\"%]\n\n"
        "Resp. atual da infraestrutura\n[%\"meta_responsavel\"%]\n\n"
        "Duração\n[%\"meta_duracao\"%]"
    )
    fmt_meta = meta.textFormat()
    fmt_meta.setLineHeight(0.93)
    meta.setTextFormat(fmt_meta)
    desloc = CORPO_Y - mapa.positionWithUnits().y()
    altura_corpo = mapa.sizeWithUnits().height() - desloc
    for it in itens:  # fundo do painel de metadados e outros itens do bloco do corpo
        if it is mapa or it is meta:
            continue
        if isinstance(it, QgsLayoutItemShape) and it is not faixa:
            p, s = it.positionWithUnits(), it.sizeWithUnits()
            if p.y() > 30 and p.y() < mapa.positionWithUnits().y() + 5:
                mover(it, p.x(), p.y() + desloc, s.width(), s.height() - desloc)
    # a faixa azul e a legenda têm moldura grossa que avança ~1,45 mm além da caixa;
    # o mapa (sem moldura) vai até a borda visível delas
    mover(mapa, mapa.positionWithUnits().x(), CORPO_Y, X1 + BORDA_VISUAL - mapa.positionWithUnits().x(), altura_corpo)
    p = meta.positionWithUnits()
    direita_meta = p.x() + meta.sizeWithUnits().width()
    mover(meta, X0, p.y() + desloc, direita_meta - X0, meta.sizeWithUnits().height() - desloc)
    p = seta.positionWithUnits()
    mover(seta, p.x(), p.y())

    # --- mapa: extensão calculada (substitui o enquadramento automático do atlas)
    mapa.setAtlasDriven(False)
    lw, lh = mapa.sizeWithUnits().width(), mapa.sizeWithUnits().height()
    for prop, lado in ((QgsLayoutObject.MapXMin, "xmin"), (QgsLayoutObject.MapXMax, "xmax"),
                       (QgsLayoutObject.MapYMin, "ymin"), (QgsLayoutObject.MapYMax, "ymax")):
        dd(mapa, prop, expr_extensao_mapa(lado, lw, lh))

    # --- remove títulos e tabelas antigos das seções (recriados na grade)
    modelo = next(t for t in tabelas if t.vectorLayer().name() == "dados_gerais")
    obras_antiga = next(t for t in tabelas if t.vectorLayer().name() == "vw_obra")
    obras_fmt = QgsTextFormat(obras_antiga.contentTextFormat())
    for trecho in ("Resultados da Prioriza", "Dados Financeiros", "Dados de Aloca", "Detalhamento das Obras"):
        layout.removeLayoutItem(label_com(trecho))
    for t in tabelas:
        if t is not modelo:
            layout.removeMultiFrame(t)

    fmt_titulo = formato(10, negrito=True, cor=AZUL)

    def titulo_secao(texto, y):
        return novo_label(layout, texto, TX0 + GRADE_EXTERNA, y, TLARG, TITULO_H, fmt_titulo)

    # legenda alinhada à grade
    p = legenda.positionWithUnits()
    legenda.setBoxSpace(2.5)
    for estilo in (QgsLegendStyle.Symbol, QgsLegendStyle.SymbolLabel):  # itens mais próximos
        st = legenda.style(estilo)
        st.setMargin(QgsLegendStyle.Top, st.margin(QgsLegendStyle.Top) * 0.45)
        legenda.setStyle(estilo, st)
    mover(legenda, X0, mapa.positionWithUnits().y() + mapa.sizeWithUnits().height() + 2.6, LARG, ALTURA_LEGENDA)
    y = legenda.positionWithUnits().y() + ALTURA_LEGENDA + GAP_SECAO

    # --- Priorização
    titulo_secao("Resultados da Priorização", y)
    y += TITULO_H + GAP_TITULO_TABELA
    t_prio, f_prio = nova_tabela(layout, modelo, ficha, FILTRO_ATLAS, y, 20, [
        ("Estratégica", "nota_estrategica", 23, C), ("Financeira", "nota_financeira", 23, C),
        ("Socioeconômica", "nota_socioeconomica", 29.5, C), ("Comercial", "nota_comercial", 23, C),
        ("Gerencial", "nota_gerencial", 23, C), ("Índice de Classificação", "nota_ic", 40, C),
        ("Impacto", "nota_impacto", 26, C)], 1)
    y_prio = y

    # --- Financeiro
    t_fin, f_fin = nova_tabela(layout, modelo, ficha, FILTRO_ATLAS, 0, 20, [
        ("CAPEX (R$)", "fin_capex", 1.25, R), ("OPEX (R$)", "fin_opex", 1.25, R),
        ("Valor Total (R$)", "fin_total", 1.25, R), ("Receita Total (R$)", "fin_receita", 1.25, R),
        ("TIRM (%)", "fin_tirm", 0.62, C), ("Viabilidade", "fin_viabilidade", 0.98, C)], 1)

    # --- Alocação: uma tabela por variante no mesmo lugar; só a do caso aparece
    msg = "Sem dados de alocação para este empreendimento."
    cen = [("Cenário", "cenario", 1, C)]
    num = lambda rot, i, p=1.0: (rot, f"c{i}", p, R)  # noqa: E731
    seis = ["CGC", "CGNC", "GL", "GSA", "GSM", "OGSM"]
    variantes = {
        "rodo": cen + [num("Carga", 1), num("Ônibus", 2), num("Automóvel", 3), num("Total Veículos", 4),
                       num("TKU Total", 5, 1.25)],
        "ton": cen + [num(r, i + 1) for i, r in enumerate(seis)] + [num("TON Total", 7, 1.2)],
        "tku": cen + [num(r, i + 1) for i, r in enumerate(seis)] + [num("TKU Total", 7, 1.3)],
        "aero": cen + [num("Demanda (Passageiros/Ano)", 1, 3.0)],
        "ferro_pax": [num("Demanda Anual (Passageiros/Ano)", 1)],
        "duto": [num("Tonelada Total", 1), num("TKU Total", 2)],
    }
    t_aloc, linha_variante = {}, {}
    for variante, specs in variantes.items():
        filtro = f"{FILTRO_ATLAS} AND \"variante\" = '{variante}'"
        t_aloc[variante] = nova_tabela(layout, modelo, aloc, filtro, 0, 40, specs, 6, msg)
        valores = {}
        for f in aloc.getFeatures(f"\"variante\" = '{variante}'"):
            for _, campo, _, _ in specs:
                valores.setdefault(campo, []).append(f[campo] or "")
        tamanho = ajustar_colunas(t_aloc[variante][0], specs, valores)
        linha_variante[variante] = 2 * MARGEM_CELULA + (LINHA_TABELA - 2 * MARGEM_CELULA) * tamanho / 10
        print(f"  alocação '{variante}': fonte {tamanho:g} pt")
        ocultar_quando(t_aloc[variante][1], f"attribute(@atlas_feature, 'aloc_variante') <> '{variante}'")

    # --- Obras: CSV de obras (via preparar_ficha.py), maior valor primeiro
    t_obras, f_obras = nova_tabela(layout, modelo, obras, FILTRO_ATLAS, 0, 30, [
        ("Descrição da Obra", "descricao", 76, Qt.AlignLeft), ("Intervenção", "intervencao", 27, C),
        ("Tipo da Infraestrutura", "tipo_infraestrutura", 39, C), ("Extensão (Km)", "extensao", 26, R),
        ("Valor Obra (R$)", "valor", 30, R)],
        OBRAS_MAX)  # sem limite fixo: aparecem as que couberem até o fim da página
    ordem = QgsLayoutTableColumn()
    ordem.setAttribute('"ordem"')
    ordem.setSortOrder(Qt.AscendingOrder)
    t_obras.setSortColumns([ordem])
    t_obras.setContentTextFormat(obras_fmt)
    layout.removeMultiFrame(modelo)

    # --- alturas medidas na página renderizada (fonte 10 pt, margem de célula 1 mm):
    #     cabeçalho 6,2 mm e 6,05 mm por linha de conteúdo
    cab, linha = CAB_TABELA, LINHA_TABELA
    h_prio = h_fin = cab + linha

    # --- posiciona as seções na grade
    mover(f_prio, TX0, y_prio, TLARG, h_prio + FOLGA_MOLDURA)
    y = y_prio + h_prio + GAP_SECAO
    titulo_secao("Dados Financeiros — Mês Base: ago/24", y)
    y += TITULO_H + GAP_TITULO_TABELA
    mover(f_fin, TX0, y, TLARG, h_fin + FOLGA_MOLDURA)
    y += h_fin + GAP_SECAO

    y_aloc_titulo = y
    t_tit = titulo_secao("Dados de Alocação 2055", y)
    ocultar_quando(t_tit, "attribute(@atlas_feature, 'regra_alocacao') = 0")
    y_aloc = y + TITULO_H + GAP_TITULO_TABELA
    for t, frame in t_aloc.values():
        mover(frame, TX0, y_aloc, TLARG, cab + 6 * linha + FOLGA_MOLDURA)

    # Obras sobem/descem conforme o número de linhas da alocação (sem buracos)
    n_linhas = "max(attribute(@atlas_feature, 'aloc_linhas'), 1)"
    linha_expr = "CASE " + " ".join(f"WHEN attribute(@atlas_feature, 'aloc_variante') = '{v}' THEN {h}"
                                    for v, h in linha_variante.items()) + f" ELSE {linha} END"
    y_obras = (f"if(attribute(@atlas_feature, 'regra_alocacao') = 0, {y_aloc_titulo}, "
               f"{y_aloc + cab} + {n_linhas} * ({linha_expr}) + {GAP_SECAO})")
    t_ob = titulo_secao("Detalhamento das Obras", 250)
    dd(t_ob, QgsLayoutObject.PositionY, y_obras)
    y_tab_obras = f"({y_obras}) + {TITULO_H + GAP_TITULO_TABELA}"
    dd(f_obras, QgsLayoutObject.PositionY, y_tab_obras)
    dd(f_obras, QgsLayoutObject.ItemHeight, f"{PAGINA_FIM} - ({y_tab_obras})")
    mover(f_obras, TX0, 260, TLARG, 30)

    projeto.writeEntry("Paths", "/Absolute", False)
    if not projeto.write(SAIDA):
        sys.exit("Falha ao salvar")
    caminhos_relativos(SAIDA)
    print(f"Layout '{LAYOUT_NOVO}' salvo em {SAIDA}")
    print(f"Pior caso (6 cenários): obras começam em {y_aloc + cab + 6 * linha + GAP_SECAO:.1f} mm "
          f"-> {PAGINA_FIM - (y_aloc + cab + 6 * linha + GAP_SECAO + TITULO_H + GAP_TITULO_TABELA):.1f} mm para a tabela")
    app.exitQgis()


if __name__ == "__main__":
    main()
