"""
Exporta as páginas de um atlas do projeto local, sem abrir o QGIS.

Uso:
    "C:\\Program Files\\QGIS 3.44.4\\bin\\python-qgis.bat" exportar_atlas.py [opções]

Opções:
    --projeto projetos/x.qgz           projeto (padrão: projetos/Atlas_Ficha_PELTMG.qgz)
    --layout "Ficha PELTMG"            layout a exportar (padrão)
    --saida pasta                      pasta de saída (padrão: atlas_saida/<layout>)
    --ids 101,102                      só esses id_empreendimento
    --max 5                            só as N primeiras páginas
    --formato pdf|png                  pdf = um arquivo por empreendimento (padrão)
    --unico                            um PDF só com todas as páginas
    --dpi 300
"""
import argparse
import os
import sys
import time

from qgis.core import QgsApplication, QgsLayoutExporter, QgsProject

PASTA = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(PASTA)  # pasta do projeto (scripts/ fica dentro dela)

ap = argparse.ArgumentParser()
ap.add_argument("--projeto", default=os.path.join(RAIZ, "projetos", "Atlas_Ficha_PELTMG.qgz"))
ap.add_argument("--layout", default="Ficha PELTMG")
ap.add_argument("--saida")
ap.add_argument("--ids")
ap.add_argument("--max", type=int)
ap.add_argument("--formato", choices=("pdf", "png"), default="pdf")
ap.add_argument("--unico", action="store_true")
ap.add_argument("--dpi", type=int, default=300)
args = ap.parse_args()

app = QgsApplication([], False)
app.initQgis()
projeto = QgsProject.instance()
if not projeto.read(args.projeto):
    sys.exit(f"Não consegui abrir {args.projeto}")
invalidas = [l.name() for l in projeto.mapLayers().values() if not l.isValid()]
if invalidas:
    sys.exit(f"Camadas inválidas (dados_locais.gpkg está na pasta?): {invalidas}")

layout = projeto.layoutManager().layoutByName(args.layout)
if layout is None:
    sys.exit(f"Layout não encontrado. Opções: {[l.name() for l in projeto.layoutManager().layouts()]}")
atlas = layout.atlas()

filtro = atlas.filterExpression() if atlas.filterFeatures() else ""
if args.ids:
    extra = f'"id_empreendimento" IN ({args.ids})'
    filtro = f"({filtro}) AND {extra}" if filtro else extra
    atlas.setFilterFeatures(True)
    atlas.setFilterExpression(filtro)

saida = args.saida or os.path.join(RAIZ, "atlas_saida", args.layout)
os.makedirs(saida, exist_ok=True)

atlas.beginRender()
total = atlas.count() if not args.max else min(args.max, atlas.count())
print(f"{args.layout}: {atlas.count()} páginas no atlas, exportando {total} -> {saida}")
exportador = QgsLayoutExporter(layout)
inicio = time.time()

if args.unico and args.formato == "pdf":
    atlas.endRender()
    cfg = QgsLayoutExporter.PdfExportSettings()
    cfg.dpi = args.dpi
    arquivo = os.path.join(saida, f"{args.layout}.pdf")
    res, erro = QgsLayoutExporter.exportToPdf(atlas, arquivo, cfg)
    print("OK" if res == QgsLayoutExporter.Success else f"ERRO {res}: {erro}", arquivo)
else:
    for i in range(total):
        atlas.seekTo(i)
        nome = atlas.currentFilename() or f"pagina_{i + 1}"
        arquivo = os.path.join(saida, f"{nome}.{args.formato}")
        if args.formato == "pdf":
            cfg = QgsLayoutExporter.PdfExportSettings()
            cfg.dpi = args.dpi
            res = exportador.exportToPdf(arquivo, cfg)
        else:
            cfg = QgsLayoutExporter.ImageExportSettings()
            cfg.dpi = args.dpi
            res = exportador.exportToImage(arquivo, cfg)
        status = "OK" if res == QgsLayoutExporter.Success else f"ERRO {res}"
        print(f"  [{i + 1}/{total}] {status} {os.path.basename(arquivo)}", flush=True)
    atlas.endRender()

print(f"Concluído em {time.time() - inicio:.0f}s")
