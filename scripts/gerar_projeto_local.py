"""
Gera Atlas_WS_Gerencial_local.qgz a partir do projeto original, trocando
todas as camadas PostgreSQL pelas tabelas de dados_locais.gpkg.

Não precisa do banco: o projeto original é aberto sem conectar nas camadas.
Simbologia, rótulos, filtros, IDs das camadas e layouts/atlas são mantidos.

Só é preciso rodar de novo se o projeto ORIGINAL mudar (novas camadas,
estilos etc.). Para atualizar os DADOS, basta rodar baixar_dados.py.

Uso (com o Python do QGIS):
    "C:\\Program Files\\QGIS 3.44.4\\bin\\python-qgis.bat" gerar_projeto_local.py
        [projeto_original.qgz] [dados_locais.gpkg] [saida.qgz]
"""
import os
import sys

from qgis.core import QgsApplication, QgsDataProvider, QgsDataSourceUri, QgsProject

PASTA = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(PASTA)  # pasta do projeto (scripts/ fica dentro dela)

# nome da camada no QGIS -> tabela no GeoPackage (ver CAMADAS em baixar_dados.py)
TABELAS = {
    "AreasQuilomblasINCRA": "areas_quilombolas_incra",
    "AreasUrbanizadasIBGE": "areas_urbanizadas_ibge",
    "TerrasIndigenasFUNAI": "terras_indigenas_funai",
    "UnidadesConservacaoANA": "unidades_conservacao_ana",
    "unidade_federacao": "unidade_federacao",
    "municipio.geom_sede": "municipio_geom_sede",
    "vw_obra_geo.geom_linha": "vw_obra_geo_linha",
    "vw_obra_geo.geom_ponto": "vw_obra_geo_ponto",
    "CamadaQuestão": "camada_questao",
    "alocacao_duto": "alocacao_duto",
    "alocacao_empreendimento": "alocacao_empreendimento",
    "alocacao_ferro_pessoas": "alocacao_ferro_pessoas",
    "dados_gerais": "dados_gerais",
    "obras": "obras",
    "vw_obra": "vw_obra",
}


def apontar_logos(projeto):
    """Logos de todos os layouts passam a vir da pasta logos/ do projeto (antes: drive de rede)."""
    from qgis.core import QgsLayoutItemPicture
    pasta_logos = os.path.join(RAIZ, "logos")
    disponiveis = {" ".join(a.split()): a for a in os.listdir(pasta_logos)}
    faltando = set()
    for layout in projeto.layoutManager().layouts():
        for item in layout.items():
            if isinstance(item, QgsLayoutItemPicture) and "logo" in item.picturePath().lower():
                # compara ignorando espaços repetidos ("codemge -  branco" no projeto original)
                nome = " ".join(os.path.basename(item.picturePath().replace("\\", "/")).split())
                if nome in disponiveis:
                    item.setPicturePath(os.path.join(pasta_logos, disponiveis[nome]))
                else:
                    faltando.add(nome)
    if faltando:
        print(f"ATENÇÃO: logos não encontrados em logos/: {sorted(faltando)}")


def main():
    original = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "projetos", "Atlas_WS_Gerencial_format.qgz")
    gpkg = sys.argv[2] if len(sys.argv) > 2 else os.path.join(RAIZ, "data", "dados_locais.gpkg")
    saida = sys.argv[3] if len(sys.argv) > 3 else os.path.join(RAIZ, "projetos", "Atlas_WS_Gerencial_local.qgz")
    if not os.path.exists(gpkg):
        sys.exit(f"GeoPackage não encontrado: {gpkg}")

    app = QgsApplication([], False)
    app.initQgis()
    projeto = QgsProject.instance()
    if not projeto.read(original, QgsProject.ReadFlag.FlagDontResolveLayers):
        sys.exit(f"Não consegui abrir {original}")

    pendentes = []
    for lyr in projeto.mapLayers().values():
        if lyr.providerType() != "postgres":
            continue
        tabela = TABELAS.get(lyr.name())
        if not tabela:
            pendentes.append(lyr.name())
            continue
        # Filtro da camada (ex.: "id_municipio" in (...)). Com as camadas não
        # resolvidas ele só existe dentro da fonte (sql=...), então lemos de lá.
        filtro = QgsDataSourceUri(lyr.source()).sql() or lyr.subsetString()
        # o filtro vai na própria fonte (|subset=): aplicar setSubsetString depois
        # atrapalhava a conexão com o GeoPackage nas camadas seguintes
        fonte = f"{gpkg}|layername={tabela}" + (f"|subset={filtro}" if filtro else "")
        lyr.setDataSource(fonte, lyr.name(), "ogr", QgsDataProvider.ProviderOptions())
        estado = "ok" if lyr.isValid() else "INVÁLIDA"
        print(f"  {lyr.name():26s} -> {tabela:26s} {estado}" + (f"  filtro: {filtro[:40]}..." if filtro else ""))
        if not lyr.isValid():
            pendentes.append(lyr.name())

    if pendentes:
        sys.exit(f"Camadas sem tabela correspondente ou inválidas: {pendentes}")

    apontar_logos(projeto)
    projeto.writeEntry("Paths", "/Absolute", False)  # caminho relativo: dados_locais.gpkg ao lado do .qgz
    if not projeto.write(saida):
        sys.exit("Falha ao salvar o projeto")
    app.exitQgis()

    n = limpar_referencias_ao_banco(saida)
    print(f"\n{n} referências antigas ao banco (layouts/GPS) atualizadas para o GeoPackage")
    print(f"Projeto local salvo em {saida}")


def limpar_referencias_ao_banco(qgz):
    """
    Layouts (atlas e tabelas) e as configurações de GPS guardam, além do ID da
    camada, a fonte antiga como "reserva". O QGIS usa o ID, mas trocamos a
    reserva também para não sobrar nenhuma referência ao PostgreSQL.
    """
    import re
    import zipfile
    from xml.sax.saxutils import escape, quoteattr, unescape

    with zipfile.ZipFile(qgz) as z:
        arquivos = {i: z.read(i) for i in z.namelist()}
    nome_qgs = next(n for n in arquivos if n.endswith(".qgs"))
    xml = arquivos[nome_qgs].decode("utf-8")

    fontes = {}
    for m in re.finditer(r"<maplayer\b.*?</maplayer>", xml, re.S):
        bloco = m.group(0)
        lid = re.search(r"<id>(.*?)</id>", bloco).group(1)
        ds = re.search(r"<datasource>(.*?)</datasource>", bloco, re.S).group(1)
        prov = re.search(r"<provider[^>]*>(.*?)</provider>", bloco).group(1)
        fontes[lid] = (unescape(ds, {"&quot;": '"', "&apos;": "'"}), prov)

    trocas = 0

    def corrigir_tag(m):
        nonlocal trocas
        tag = m.group(0)
        for pref in ("vectorLayer", "coverageLayer", "destinationLayer"):
            fonte = re.search(rf'\b{pref}Source="([^"]*)"', tag)
            lid = re.search(rf'\b{pref}="([^"]*)"', tag)
            if not (fonte and lid and "dbname=" in fonte.group(1) and lid.group(1) in fontes):
                continue
            ds, prov = fontes[lid.group(1)]
            tag = tag.replace(fonte.group(0), f"{pref}Source={quoteattr(ds, {chr(10): '&#xa;'})}")
            tag = re.sub(rf'\b{pref}Provider="[^"]*"', f'{pref}Provider="{escape(prov)}"', tag)
            trocas += 1
        return tag

    xml = re.sub(r"<[A-Za-z][^<>]*Source=\"[^\"]*dbname=[^<>]*>", corrigir_tag, xml)
    # pasta da última exportação (caminho de outra máquina): não interessa ao projeto
    xml = re.sub(r"<lastLayoutExportDir[^>]*>[^<]*</lastLayoutExportDir>", "", xml)
    restos = xml.count("dbname=")
    if restos:
        print(f"ATENÇÃO: ainda há {restos} referência(s) a 'dbname=' no projeto")

    arquivos[nome_qgs] = xml.encode("utf-8")
    with zipfile.ZipFile(qgz, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, dados in arquivos.items():
            z.writestr(nome, dados)
    return trocas


if __name__ == "__main__":
    main()
