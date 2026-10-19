"""
Gera as fichas PELTMG de ponta a ponta, com um comando só:

    python gerar_tudo.py                  # todos os empreendimentos (PNG, 80 dpi)
    python gerar_tudo.py --ids 11,57,997  # só alguns
    python gerar_tudo.py --dpi 150        # mais qualidade
    python gerar_tudo.py --formato pdf    # PDF em vez de PNG

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
    args = ap.parse_args()

    saida = args.saida or os.path.join(PASTA, "atlas_saida", f"fichas_{args.formato}")
    etapa("1/3 Preparando os dados", [os.path.join(PASTA, "scripts", "preparar_ficha.py")])
    etapa("2/3 Montando o layout", [os.path.join(PASTA, "scripts", "montar_ficha.py")])
    exportar = [os.path.join(PASTA, "scripts", "exportar_atlas.py"),
                "--projeto", os.path.join(PASTA, "projetos", "Atlas_Ficha_PELTMG.qgz"), "--layout", "Ficha PELTMG",
                "--formato", args.formato, "--dpi", str(args.dpi), "--saida", saida]
    if args.ids:
        exportar += ["--ids", args.ids]
    etapa("3/3 Exportando as fichas", exportar)
    print(f"\nPronto: {saida}")


if __name__ == "__main__":
    main()
