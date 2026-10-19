"""
Baixa do banco PostgreSQL todas as camadas usadas pelo projeto Atlas_WS_Gerencial
e grava em um único GeoPackage (data/dados_locais.gpkg).

Rode no computador com acesso à VPN, na pasta do projeto:

    pip install sqlalchemy psycopg2-binary
    python scripts/baixar_dados.py                        # baixa todas as camadas
    python scripts/baixar_dados.py dados_gerais vw_obra   # atualiza só essas tabelas

Na primeira vez o script pergunta host, porta e nome do banco e salva em
config_banco.json (fora do Git). Usuário e senha são pedidos a cada execução.

As consultas abaixo são exatamente as que estão no projeto QGIS. Se você
mudar uma consulta no projeto original, atualize aqui também.

Não depende de GDAL/geopandas: o GeoPackage é escrito direto com sqlite3,
com índice espacial (R-tree), e o QGIS lê normalmente.
"""
import datetime as dt
import decimal
import getpass
import json
import os
import shutil
import sqlite3
import struct
import sys
import time

ARQUIVO_SAIDA = "dados_locais.gpkg"   # gravado em data/
CONFIG_BANCO = "config_banco.json"    # host/porta/banco — local, fora do Git
LOTE = 5000

# ---------------------------------------------------------------------------
# Camadas do projeto
#   tabela   -> nome da tabela no GeoPackage (o projeto local aponta para ele)
#   fonte    -> ("tabela", "schema", "nome") ou ("sql", "<consulta>")
#   geom     -> (coluna, tipo, srid) ou None para camadas sem geometria
# Filtros de camada (ex.: municípios) ficam no projeto QGIS, então as tabelas
# são baixadas inteiras.
# ---------------------------------------------------------------------------
CAMADAS = [
    dict(tabela="areas_quilombolas_incra",
         fonte=("tabela", "externos", "AreasQuilomblasINCRA"),
         geom=("geom", "MULTIPOLYGON", 4674)),
    dict(tabela="areas_urbanizadas_ibge",
         fonte=("tabela", "externos", "AreasUrbanizadasIBGE"),
         geom=("geom", "MULTIPOLYGON", 4674)),
    dict(tabela="terras_indigenas_funai",
         fonte=("tabela", "externos", "TerrasIndigenasFUNAI"),
         geom=("geom", "MULTIPOLYGON", 4674)),
    dict(tabela="unidades_conservacao_ana",
         fonte=("tabela", "externos", "UnidadesConservacaoANA"),
         geom=("geom", "MULTIPOLYGON", 4674)),
    dict(tabela="unidade_federacao",
         fonte=("tabela", "ambiente", "unidade_federacao"),
         geom=("geom", "MULTIPOLYGON", 4674)),
    dict(tabela="municipio_geom_sede",
         fonte=("tabela", "ambiente", "municipio"),
         geom=("geom_sede", "POINT", 4674)),
    dict(tabela="vw_obra_geo_linha",
         fonte=("tabela", "carteira", "vw_obra_geo"),
         geom=("geom_linha", "MULTILINESTRING", 4674)),
    dict(tabela="vw_obra_geo_ponto",
         fonte=("tabela", "carteira", "vw_obra_geo"),
         geom=("geom_ponto", "MULTIPOINT", 4674)),
    dict(tabela="camada_questao",
         fonte=("sql", """select
	id_obra,
	id_empreendimento,
	descricao_obra,
	id_intervencao,
	extensao_km from carteira.vw_obra
"""),
         geom=None),
    dict(tabela="alocacao_duto",
         fonte=("sql", """SELECT row_number() over () AS _uid_,* FROM (select
	d.id_empreendimento,
	sum(d.volume_2055) as volume_2055,
	sum(d.volume_2055) * meg.extensao_km as tku from dutoviario.demanda_duto_2055 d join carteira.mvw_empreendimento_geo meg on d.id_empreendimento = meg.id_empreendimento group by d.id_empreendimento, meg.extensao_km
) AS _subq_1_
"""),
         geom=None),
    dict(tabela="alocacao_empreendimento",
         fonte=("sql", """select *
from cenario_recomendado_2.alocacao_geral
order by id_empreendimento asc, id_cenario asc"""),
         geom=None),
    dict(tabela="alocacao_ferro_pessoas",
         fonte=("sql", """SELECT row_number() over () AS _uid_,* FROM (select  mcf.id_empreendimento, mcf.demanda_ano  from ferroviario_passageiros.mvw_28_consolidacao_final mcf  where mcf.cenario = 'demanda_2055'
) AS _subq_1_
"""),
         geom=None),
    dict(tabela="dados_gerais",
         fonte=("sql", """SELECT row_number() over () AS _uid_,* FROM (SELECT
	a.id_empreendimento,
	a.nome_empreendimento,
	a.setor,
	a.origem_ajustada,
	a.descr_status_empreendimento,
	a.natureza_empreendimento,
	a.esfera_acao,
	a.fonte_financiamento,
	a.grupo_modelagem,
	a.responsavel_gestao_infraestrutura,
	a.tirm,
	a.viabilidade,
	a.dimensao_financeira,
	a.dimensao_socioeconomica_pond,
	a.dimensao_estrategica,
	a.dimensao_comercial,
	a.dimensao_gerencial,
	a.ic_3_pond,
	a.impacto_avaliado_3_pond_cenario,
	eg.extensao_km,
	a.capex AS capex_empreendimento_atualizado,
	a.opex AS opex_empreendimento_atualizado,
	(a.capex + a.opex) as valor_total,
	a.receita,
	vo.data_inicio AS ano_inicio,
    vo.data_conclusao AS ano_conclusao,
	eg.geom_linha
FROM
	cenario_recomendado_2.vw_dadosgerais_plataformaonline a
LEFT JOIN carteira.vw_empreendimento_custo_economico_lp vcc ON
	vcc.id_empreendimento = a.id_empreendimento
LEFT JOIN carteira.mvw_empreendimento_geo eg ON
	a.id_empreendimento = eg.id_empreendimento
left join carteira.vw_empreendimento vo ON
	a.id_empreendimento = vo.id_empreendimento
WHERE a.id_setor = 3 ) AS _subq_1_"""),
         geom=("geom_linha", "MULTILINESTRING", 4674)),
    dict(tabela="obras",
         fonte=("sql", """SELECT row_number() over () AS _uid_,* FROM (select o.id_obra, o.descricao_obra, i.intervencao, ti.tipo_infraestrutura , o.valor_global, og.extensao_km  from carteira.obra o  join priorizacao_peltlp.mvw_4_calcula_impacto_1_pond_cenario a on a.id_empreendimento = o.id_empreendimento  join carteira.intervencao i on o.id_intervencao = i.id_intervencao join carteira.tipo_infraestrutura ti on ti.id_tipo_infraestrutura = o.id_tipo_infraestrutura  join carteira.obra_geo og on o.id_obra = og.id_obra where a.status_empreendimento <6 and a.origem_ajustada NOT IN ('DER-MG', 'CODEMGE/DER-MG')
) AS _subq_1_
"""),
         geom=None),
    dict(tabela="vw_obra",
         fonte=("sql", """WITH custo_obra AS
(SELECT
	tce.id_empreendimento,
	tce.id_obra,
	max(tce.valor_adotado) AS valor_obra
FROM cenario_recomendado_2.vw_custo_economico tce
GROUP BY tce.id_empreendimento, tce.id_obra)
SELECT
	vo.id_obra,
	vo.descricao_obra,
	vo.id_empreendimento,
	vo.intervencao,
	vo.tipo_infraestrutura,
	vo.status,
	vo.descricao_obra_padronizada,
	vog.extensao_km,
	cb.valor_obra
FROM
	carteira.vw_obra vo
LEFT JOIN carteira.vw_obra_geo vog ON
	vog.id_obra = vo.id_obra
LEFT JOIN custo_obra cb ON
	cb.id_obra = vo.id_obra
ORDER BY cb.id_empreendimento, cb.valor_obra DESC"""),
         geom=None),
]

# WKT do SIRGAS 2000, usado só se o banco não devolver a definição
WKT_4674 = (
    'GEOGCS["SIRGAS 2000",DATUM["Sistema_de_Referencia_Geocentrico_para_las_AmericaS_2000",'
    'SPHEROID["GRS 1980",6378137,298.257222101,AUTHORITY["EPSG","7019"]],'
    'TOWGS84[0,0,0,0,0,0,0],AUTHORITY["EPSG","6674"]],PRIMEM["Greenwich",0,'
    'AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4674"]]'
)


# ===========================================================================
# Escrita do GeoPackage (sqlite3 puro)
# ===========================================================================
def q(nome):
    """Identificador entre aspas (SQLite e PostgreSQL)."""
    return '"' + nome.replace('"', '""') + '"'


def criar_gpkg(caminho):
    con = sqlite3.connect(caminho)
    con.execute("PRAGMA application_id = 1196444487")  # 'GPKG'
    con.execute("PRAGMA user_version = 10300")          # versão 1.3
    con.executescript("""
    CREATE TABLE IF NOT EXISTS gpkg_spatial_ref_sys (
        srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY,
        organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
        definition TEXT NOT NULL, description TEXT);
    CREATE TABLE IF NOT EXISTS gpkg_contents (
        table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL,
        identifier TEXT UNIQUE, description TEXT DEFAULT '',
        last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE,
        srs_id INTEGER, CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id)
        REFERENCES gpkg_spatial_ref_sys(srs_id));
    CREATE TABLE IF NOT EXISTS gpkg_geometry_columns (
        table_name TEXT NOT NULL, column_name TEXT NOT NULL,
        geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL,
        z TINYINT NOT NULL, m TINYINT NOT NULL,
        CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
        CONSTRAINT uk_gc_table_name UNIQUE (table_name),
        CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
        CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id));
    CREATE TABLE IF NOT EXISTS gpkg_extensions (
        table_name TEXT, column_name TEXT, extension_name TEXT NOT NULL,
        definition TEXT NOT NULL, scope TEXT NOT NULL,
        CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name));
    INSERT OR IGNORE INTO gpkg_spatial_ref_sys VALUES
        ('Undefined cartesian SRS', -1, 'NONE', -1, 'undefined', 'undefined cartesian coordinate reference system'),
        ('Undefined geographic SRS', 0, 'NONE', 0, 'undefined', 'undefined geographic coordinate reference system');
    """)
    garantir_srs(con, 4326, 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
                 'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,'
                 'AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
                 'AUTHORITY["EPSG","4326"]]', "WGS 84")
    return con


def garantir_srs(con, srid, wkt, nome=None):
    con.execute(
        "INSERT OR IGNORE INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)",
        (nome or f"EPSG:{srid}", srid, "EPSG", srid, wkt or "undefined", None),
    )


def remover_camada(con, tabela):
    rtree = [r[0] for r in con.execute(
        "SELECT 'rtree_' || table_name || '_' || column_name FROM gpkg_geometry_columns "
        "WHERE table_name = ?", (tabela,))]
    for r in rtree:
        con.execute(f"DROP TABLE IF EXISTS {q(r)}")
    con.execute(f"DROP TABLE IF EXISTS {q(tabela)}")
    for meta in ("gpkg_geometry_columns", "gpkg_extensions", "gpkg_contents"):
        con.execute(f"DELETE FROM {meta} WHERE table_name = ?", (tabela,))


def blob_gpkg(wkb, srid, env):
    """Geometria no formato GeoPackage: cabeçalho 'GP' + envelope + WKB."""
    if wkb is None:
        return None
    wkb = bytes(wkb)
    if env is None or env[0] is None:  # geometria vazia
        return b"GP" + struct.pack("<BBi", 0, 0b00010001, srid) + wkb
    return b"GP" + struct.pack("<BBi4d", 0, 0b00000011, srid, *env) + wkb


def escrever_camada(con, tabela, colunas, geom, linhas):
    """
    colunas: [(nome, tipo_gpkg), ...]
    geom:    (coluna, tipo, srid) ou None
    linhas:  iterável de tuplas; com geometria, cada tupla termina com
             (wkb, minx, maxx, miny, maxy)
    """
    remover_camada(con, tabela)
    nomes = [c[0] for c in colunas]
    pk = "fid" if "fid" not in nomes else "fid_gpkg"
    defs = [f"{q(pk)} INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL"]
    if geom:
        defs.append(f"{q(geom[0])} {geom[1]}")
    defs += [f"{q(n)} {t}" for n, t in colunas]
    con.execute(f"CREATE TABLE {q(tabela)} ({', '.join(defs)})")

    cols_insert = ([geom[0]] if geom else []) + nomes
    sql = (f"INSERT INTO {q(tabela)} ({', '.join(q(c) for c in cols_insert)}) "
           f"VALUES ({', '.join('?' * len(cols_insert))})")
    n_atrib = len(nomes)
    bbox = [None, None, None, None]  # minx, miny, maxx, maxy
    envs = []
    total = 0
    cur = con.cursor()
    lote = []

    def gravar(lote):
        cur.executemany(sql, lote)

    for linha in linhas:
        if geom:
            atrib = linha[:n_atrib]
            wkb, minx, maxx, miny, maxy = linha[n_atrib:]
            env = None if minx is None else (minx, maxx, miny, maxy)
            lote.append((blob_gpkg(wkb, geom[2], env),) + tuple(atrib))
            if env:
                envs.append((total + 1, minx, maxx, miny, maxy))
                bbox = [v if b is None else f(b, v) for b, v, f in
                        zip(bbox, (minx, miny, maxx, maxy), (min, min, max, max))]
        else:
            lote.append(tuple(linha))
        total += 1
        if len(lote) >= LOTE:
            gravar(lote)
            lote = []
            print(f"    {total} registros...", flush=True)
    if lote:
        gravar(lote)

    if geom:
        con.execute(
            "INSERT INTO gpkg_contents (table_name, data_type, identifier, min_x, min_y, max_x, max_y, srs_id) "
            "VALUES (?, 'features', ?, ?, ?, ?, ?, ?)", (tabela, tabela, *bbox, geom[2]))
        con.execute("INSERT INTO gpkg_geometry_columns VALUES (?, ?, ?, ?, 0, 0)",
                    (tabela, geom[0], geom[1], geom[2]))
        criar_indice_espacial(con, tabela, pk, geom[0], envs)
    else:
        con.execute(
            "INSERT INTO gpkg_contents (table_name, data_type, identifier) VALUES (?, 'attributes', ?)",
            (tabela, tabela))
    con.commit()
    return total


def criar_indice_espacial(con, tabela, pk, gcol, envs):
    """R-tree no padrão GeoPackage (o mesmo que o GDAL/QGIS cria)."""
    rt = f"rtree_{tabela}_{gcol}"
    t, g, i = q(tabela), q(gcol), q(pk)
    con.execute(f"CREATE VIRTUAL TABLE {q(rt)} USING rtree(id, minx, maxx, miny, maxy)")
    con.executemany(f"INSERT INTO {q(rt)} VALUES (?,?,?,?,?)", envs)
    # Gatilhos do padrão para manter o índice se a camada for editada no QGIS
    gatilhos = {
        "insert": f"AFTER INSERT ON {t} WHEN (new.{g} NOT NULL AND NOT ST_IsEmpty(NEW.{g})) BEGIN "
                  f"INSERT OR REPLACE INTO {q(rt)} VALUES (NEW.{i}, ST_MinX(NEW.{g}), ST_MaxX(NEW.{g}), "
                  f"ST_MinY(NEW.{g}), ST_MaxY(NEW.{g})); END",
        "update1": f"AFTER UPDATE OF {g} ON {t} WHEN OLD.{i} = NEW.{i} AND (NEW.{g} NOTNULL AND NOT "
                   f"ST_IsEmpty(NEW.{g})) BEGIN INSERT OR REPLACE INTO {q(rt)} VALUES (NEW.{i}, "
                   f"ST_MinX(NEW.{g}), ST_MaxX(NEW.{g}), ST_MinY(NEW.{g}), ST_MaxY(NEW.{g})); END",
        "update2": f"AFTER UPDATE OF {g} ON {t} WHEN OLD.{i} = NEW.{i} AND (NEW.{g} ISNULL OR "
                   f"ST_IsEmpty(NEW.{g})) BEGIN DELETE FROM {q(rt)} WHERE id = OLD.{i}; END",
        "update3": f"AFTER UPDATE ON {t} WHEN OLD.{i} != NEW.{i} AND (NEW.{g} NOTNULL AND NOT "
                   f"ST_IsEmpty(NEW.{g})) BEGIN DELETE FROM {q(rt)} WHERE id = OLD.{i}; INSERT OR REPLACE "
                   f"INTO {q(rt)} VALUES (NEW.{i}, ST_MinX(NEW.{g}), ST_MaxX(NEW.{g}), ST_MinY(NEW.{g}), "
                   f"ST_MaxY(NEW.{g})); END",
        "update4": f"AFTER UPDATE ON {t} WHEN OLD.{i} != NEW.{i} AND (NEW.{g} ISNULL OR "
                   f"ST_IsEmpty(NEW.{g})) BEGIN DELETE FROM {q(rt)} WHERE id IN (OLD.{i}, NEW.{i}); END",
        "delete": f"AFTER DELETE ON {t} WHEN old.{g} NOT NULL BEGIN DELETE FROM {q(rt)} "
                  f"WHERE id = OLD.{i}; END",
    }
    for nome, corpo in gatilhos.items():
        con.execute(f"CREATE TRIGGER {q(rt + '_' + nome)} {corpo}")
    con.execute(
        "INSERT INTO gpkg_extensions VALUES (?, ?, 'gpkg_rtree_index', "
        "'http://www.geopackage.org/spec120/#extension_rtree', 'write-only')", (tabela, gcol))


# ===========================================================================
# Leitura do PostgreSQL
# ===========================================================================
def tipo_gpkg(nome_tipo_pg):
    t = nome_tipo_pg.lower()
    if t == "int2":
        return "SMALLINT"
    if t == "int4":
        return "MEDIUMINT"   # GDAL lê como inteiro 32 bits
    if t == "int8":
        return "INTEGER"     # GDAL lê como inteiro 64 bits
    if t == "float4":
        return "FLOAT"
    if t in ("float8", "numeric", "money"):
        return "REAL"
    if t == "bool":
        return "BOOLEAN"
    if t == "date":
        return "DATE"
    if t in ("timestamp", "timestamptz"):
        return "DATETIME"
    return "TEXT"


def converter(v):
    if v is None or isinstance(v, (int, float, str)):
        return v
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, dt.datetime):
        if v.tzinfo is not None:
            v = v.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return v.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, list):  # arrays do PostgreSQL: mesmo texto que o QGIS exibe, ex. {a,b}
        return "{" + ",".join("" if x is None else str(x) for x in v) + "}"
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False, default=str)
    if isinstance(v, (bytes, memoryview)):
        return bytes(v).hex()
    return str(v)


def consulta_base(cfg):
    tipo = cfg["fonte"][0]
    if tipo == "tabela":
        _, schema, nome = cfg["fonte"]
        return f"{q(schema)}.{q(nome)}"
    return f"({cfg['fonte'][1]})"


def descrever_colunas(pg, cfg):
    """[(nome, nome_do_tipo_pg)] na ordem em que o QGIS mostra."""
    with pg.cursor() as cur:
        cur.execute(f"SELECT * FROM {consulta_base(cfg)} AS _q LIMIT 0")
        desc = [(d[0], d[1]) for d in cur.description]
        cur.execute("SELECT oid, typname FROM pg_type WHERE oid = ANY(%s)",
                    (list({d[1] for d in desc}),))
        tipos = dict(cur.fetchall())
    pg.rollback()
    return [(nome, tipos.get(oid, "text")) for nome, oid in desc]


def filtro_tipo_qgis(pg, cfg):
    """
    Reproduz o filtro que o QGIS aplica sozinho: quando a coluna de geometria
    de uma tabela/view é genérica (GEOMETRY, comum em views), o QGIS só mostra
    as feições da família do tipo da camada (ex.: LineString e MultiLineString)
    e descarta as geometrias nulas. Colunas com tipo definido não são filtradas.
    """
    if cfg["fonte"][0] != "tabela" or not cfg["geom"]:
        return None
    _, schema, nome = cfg["fonte"]
    coluna, tipo, _ = cfg["geom"]
    with pg.cursor() as cur:
        cur.execute("SELECT upper(type) FROM geometry_columns WHERE f_table_schema = %s "
                    "AND f_table_name = %s AND f_geometry_column = %s", (schema, nome, coluna))
        r = cur.fetchone()
    pg.rollback()
    if not r or r[0] != "GEOMETRY":
        return None
    simples = tipo.replace("MULTI", "")
    familia = [simples, "MULTI" + simples]
    familia += [t + "M" for t in familia]
    return f"upper(GeometryType(_q.{q(coluna)})) IN ({', '.join(repr(t) for t in familia)})"


def ler_camada(pg, cfg):
    colunas_pg = descrever_colunas(pg, cfg)
    geom = cfg["geom"]
    # Outras colunas geometry/geography não cabem no GeoPackage (1 geometria
    # por tabela); nenhum estilo/rótulo do projeto usa essas colunas.
    atrib = [(n, t) for n, t in colunas_pg
             if t not in ("geometry", "geography") and not (geom and n == geom[0])]

    select = [f"_q.{q(n)}" for n, _ in atrib]
    if geom:
        g = f"_q.{q(geom[0])}"
        if geom[1].startswith("MULTI"):
            g = f"ST_Multi({g})"
        g = f"ST_Force2D({g})"
        select += [f"ST_AsBinary({g})",
                   f"CASE WHEN ST_IsEmpty({g}) THEN NULL ELSE ST_XMin({g}) END",
                   f"ST_XMax({g})", f"ST_YMin({g})", f"ST_YMax({g})"]
    sql = f"SELECT {', '.join(select)} FROM {consulta_base(cfg)} AS _q"
    filtro = filtro_tipo_qgis(pg, cfg)
    if filtro:
        sql += f" WHERE {filtro}"

    colunas = [(n, tipo_gpkg(t)) for n, t in atrib]
    n_atrib = len(colunas)

    def linhas():
        with pg.cursor(name="exportacao") as cur:  # cursor no servidor: não carrega tudo na memória
            cur.itersize = LOTE
            cur.execute(sql)
            for r in cur:
                yield tuple(converter(v) for v in r[:n_atrib]) + tuple(r[n_atrib:])
        pg.rollback()

    return colunas, linhas()


def wkt_srs(pg, srid):
    try:
        with pg.cursor() as cur:
            cur.execute("SELECT srtext FROM spatial_ref_sys WHERE srid = %s", (srid,))
            r = cur.fetchone()
        pg.rollback()
        if r and r[0]:
            return r[0]
    except Exception:
        pg.rollback()
    return WKT_4674 if srid == 4674 else None


# ===========================================================================
def ler_config_banco(raiz):
    """Host, porta e nome do banco: de config_banco.json; na falta dele, pergunta e salva."""
    caminho = os.path.join(raiz, CONFIG_BANCO)
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        print(f"Primeira execução: informe o banco (fica salvo em {CONFIG_BANCO}, fora do Git).")
        cfg = {"host": input("Host do banco: ").strip(),
               "port": int(input("Porta [5432]: ").strip() or 5432),
               "database": input("Nome do banco: ").strip()}
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    return cfg["host"], int(cfg.get("port", 5432)), cfg["database"]


def main():
    from sqlalchemy import create_engine

    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/ -> pasta do projeto
    os.makedirs(os.path.join(raiz, "data"), exist_ok=True)
    saida = os.path.join(raiz, "data", ARQUIVO_SAIDA)
    pedidas = set(sys.argv[1:])
    validas = {c["tabela"] for c in CAMADAS}
    if pedidas - validas:
        sys.exit(f"Tabela(s) desconhecida(s): {', '.join(sorted(pedidas - validas))}\n"
                 f"Opções: {', '.join(sorted(validas))}")
    camadas = [c for c in CAMADAS if not pedidas or c["tabela"] in pedidas]

    # Parâmetros do banco: lidos de config_banco.json (perguntados na 1ª vez)
    DB_HOST, DB_PORT, DB_NAME = ler_config_banco(raiz)

    # Inputs interativos
    DB_USER = input("Digite o usuário do banco: ")
    DB_PASSWORD = getpass.getpass("Digite a senha do banco: ")

    # Criação da engine (URL.create evita problemas com caracteres especiais na senha)
    from sqlalchemy.engine import URL
    engine = create_engine(URL.create(
        "postgresql+psycopg2", username=DB_USER, password=DB_PASSWORD,
        host=DB_HOST, port=DB_PORT, database=DB_NAME))

    with engine.connect():
        print("Conexão com o banco realizada com sucesso.\n")

    bruta = engine.raw_connection()
    pg = getattr(bruta, "driver_connection", None) or bruta.connection  # conexão psycopg2

    # Grava num arquivo temporário e só substitui o final se tudo der certo
    temp = saida + ".tmp"
    if os.path.exists(temp):
        os.remove(temp)
    if pedidas and os.path.exists(saida):
        shutil.copy2(saida, temp)
    gpkg = criar_gpkg(temp)

    resumo = []
    inicio = time.time()
    try:
        for i, cfg in enumerate(camadas, 1):
            t0 = time.time()
            print(f"[{i}/{len(camadas)}] {cfg['tabela']}")
            if cfg["geom"]:
                garantir_srs(gpkg, cfg["geom"][2], wkt_srs(pg, cfg["geom"][2]))
            colunas, linhas = ler_camada(pg, cfg)
            n = escrever_camada(gpkg, cfg["tabela"], colunas, cfg["geom"], linhas)
            resumo.append((cfg["tabela"], n, time.time() - t0))
            print(f"    OK: {n} registros em {time.time() - t0:.1f}s")
        gpkg.execute("VACUUM")
    except BaseException:
        gpkg.close()
        bruta.close()
        print(f"\nERRO: nada foi alterado em {saida}. O arquivo parcial é {temp}.")
        raise
    gpkg.close()
    bruta.close()
    os.replace(temp, saida)

    print("\nResumo:")
    for tabela, n, s in resumo:
        print(f"  {tabela:28s} {n:>8d} registros  {s:6.1f}s")
    print(f"\nArquivo gerado: {saida}  ({os.path.getsize(saida) / 1e6:.1f} MB, "
          f"{time.time() - inicio:.0f}s no total)")


if __name__ == "__main__":
    main()
