"""
Gera as fichas PELTMG de ponta a ponta, com um comando só:

    python gerar_tudo.py                  # todos os empreendimentos (PNG, 80 dpi)
    python gerar_tudo.py --ids 11,57,997  # só alguns
    python gerar_tudo.py --dpi 150        # mais qualidade
    python gerar_tudo.py --formato pdf    # PDF em vez de PNG (um por empreendimento)

    # PDF único do cenário recomendado: 150 dpi, texto como texto, mapa rasterizado
    python gerar_tudo.py --pdf-cenario-recomendado
    python gerar_tudo.py --pdf-cenario-recomendado --so-exportar   # sem refazer as etapas 1 e 2

Etapas (cada uma roda com o Python do QGIS):
  1. scripts/preparar_ficha.py — Parquet + CSV de obras -> data/ficha_pelt.gpkg (regras da ficha)
  2. scripts/montar_ficha.py   — monta o layout "Ficha PELTMG" em projetos/Atlas_Ficha_PELTMG.qgz
  3. scripts/exportar_atlas.py — exporta as páginas para atlas_saida/fichas_<formato>/

Para atualizar os dados: troque os arquivos em data/processed (e o CSV de obras
em data/) e rode este script de novo.
"""
import argparse
import glob
import os
import subprocess
import sys
import time

PASTA = os.path.dirname(os.path.abspath(__file__))
CSV_RECOMENDADO = os.path.join(PASTA, "data", "cenario_recomendado_2_vw_dadosgerais_plataformaonline.csv")


def python_qgis():
    """Localiza o python-qgis.bat da instalação do QGIS."""
    achados = sorted(glob.glob(r"C:\Program Files\QGIS *\bin\python-qgis.bat"))
    if not achados:
        sys.exit("QGIS não encontrado em C:\\Program Files\\QGIS *")
    return achados[-1]


def etapa(nome, args):
    print(f"\n=== {nome} ===", flush=True)
    inicio = time.time()
    r = subprocess.run([python_qgis(), *args], cwd=PASTA)
    if r.returncode != 0:
        sys.exit(f"Falhou em: {nome}")
    print(f"({time.time() - inicio:.0f}s)")


def main():
    ap = argparse.ArgumentParser(description="Gera as fichas PELTMG")
    ap.add_argument("--ids", help="só esses id_empreendimento, separados por vírgula")
    ap.add_argument("--formato", choices=("png", "pdf"), default="png")
    ap.add_argument("--dpi", type=int, default=80)
    ap.add_argument("--saida", help="pasta de saída (padrão: atlas_saida/fichas_<formato>)")
    ap.add_argument("--pdf-cenario-recomendado", action="store_true",
                    help="um PDF só, 150 dpi, com os empreendimentos do CSV do cenário recomendado")
    ap.add_argument("--csv", default=CSV_RECOMENDADO,
                    help="CSV com a coluna id_empreendimento usado por --pdf-cenario-recomendado")
    ap.add_argument("--so-exportar", action="store_true", help="pula as etapas 1 e 2 (dados e layout)")
    args = ap.parse_args()

    if args.so_exportar:
        print("Pulando as etapas 1 e 2 (usando data/ficha_pelt.gpkg e o .qgz atuais)")
    else:
        etapa("1/3 Preparando os dados", [os.path.join(PASTA, "scripts", "preparar_ficha.py")])
        etapa("2/3 Montando o layout", [os.path.join(PASTA, "scripts", "montar_ficha.py")])

    if args.pdf_cenario_recomendado:
        if not os.path.exists(args.csv):
            sys.exit(f"CSV do cenário não encontrado: {args.csv}")
        arquivo = os.path.join(PASTA, "atlas_saida", "fichas_peltmg_cenario_recomendado.pdf")
        os.makedirs(os.path.dirname(arquivo), exist_ok=True)
        etapa("3/3 Exportando o PDF do cenário recomendado", [
            os.path.join(PASTA, "scripts", "exportar_atlas.py"),
            "--projeto", os.path.join(PASTA, "projetos", "Atlas_Ficha_PELTMG.qgz"), "--layout", "Ficha PELTMG",
            "--formato", "pdf", "--unico", "--dpi", "150", "--ids-csv", args.csv, "--arquivo", arquivo])
        print(f"\nPronto: {arquivo}")
        return

    saida = args.saida or os.path.join(PASTA, "atlas_saida", f"fichas_{args.formato}")
    exportar = [os.path.join(PASTA, "scripts", "exportar_atlas.py"),
                "--projeto", os.path.join(PASTA, "projetos", "Atlas_Ficha_PELTMG.qgz"), "--layout", "Ficha PELTMG",
                "--formato", args.formato, "--dpi", str(args.dpi), "--saida", saida]
    if args.ids:
        exportar += ["--ids", args.ids]
    etapa("3/3 Exportando as fichas", exportar)
    print(f"\nPronto: {saida}")


if __name__ == "__main__":
    main()
