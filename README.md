# Atlas PELTMG — Ficha técnica por empreendimento (QGIS)

Gera, com o QGIS, a **ficha técnica de cada empreendimento** do PELTMG (Plano
Estadual de Logística e Transportes de Minas Gerais). São uma página por empreendimento,
com mapa, metadados, priorização, dados financeiros, alocação 2055 e detalhamento
das obras. A ficha reproduz a mesma lógica da aplicação web e usa **os mesmos
arquivos Parquet** que ela.

Tudo roda **sem conexão com o banco**: as camadas do mapa vêm de um GeoPackage
local, e os dados da ficha, dos Parquet e do CSV de obras.

---

## 1. Estrutura

```
gerar_tudo.py              ponto de entrada: gera todas as fichas com um comando
scripts/
  preparar_ficha.py        regras da ficha: Parquet + CSV de obras -> data/ficha_pelt.gpkg
  montar_ficha.py          layout "Ficha PELTMG" -> projetos/Atlas_Ficha_PELTMG.qgz
  exportar_atlas.py        exporta as páginas de um atlas (PNG ou PDF)
  baixar_dados.py          banco PostgreSQL -> data/dados_locais.gpkg (precisa de VPN)
  gerar_projeto_local.py   projeto original -> projetos/Atlas_WS_Gerencial_local.qgz
projetos/
  Atlas_Ficha_PELTMG.qgz           projeto da ficha (gerado por montar_ficha.py)
  Atlas_WS_Gerencial_local.qgz     projeto base, lendo de data/dados_locais.gpkg
logos/                     logos usados nos cabeçalhos
data/                      dados de entrada (não versionados, veja a seção 3)
atlas_saida/               fichas geradas (não versionadas)
```

## 2. Pré-requisitos

- **Windows** com **QGIS 3.44** instalado em `C:\Program Files\QGIS 3.44.x`.
  Os scripts usam o Python que vem com o QGIS, que já tem pandas e pyarrow.
- **Python 3** no PATH, só para rodar o `gerar_tudo.py`, que chama o Python do QGIS.
- Os **dados**, que não estão no repositório (veja a seção 3).

## 3. Dados (não versionados)

Os dados são internos e ficam fora do Git. Coloque-os nestes caminhos:

| Caminho | O que é | De onde vem |
|---|---|---|
| `data/dados_locais.gpkg` | Camadas do mapa: obras, áreas socioambientais, UF, municípios | `scripts/baixar_dados.py` (veja a seção 6) |
| `data/processed/carteiras.parquet` | Tabela mestra (dados gerais, notas, viabilidade, TIRM) | Aplicação web |
| `data/processed/resumo_financeiro.parquet` | Financeiro dos cenários Recomendado e Otimizado | Aplicação web |
| `data/processed/dados_financeiro.parquet` | Financeiro de reserva (Custo Econômico LP) | Aplicação web |
| `data/processed/alocacao_empreendimento.parquet` | Alocação 2055 (rodoviário, ferroviário de cargas, hidroviário) | Aplicação web |
| `data/processed/demanda_pax_aero_ano.parquet` | Alocação 2055 (aeroportuário) | Aplicação web |
| `data/processed/demanda_duto_ano.parquet` | Alocação 2055 (dutoviário) | Aplicação web |
| `data/processed/demanda_pax_ferro_ano.parquet` | Alocação 2055 (ferroviário de passageiros) | Aplicação web |
| `data/processed/empreendimento_geo.parquet` | Geometria de cada empreendimento (WKT) | Aplicação web |
| `data/*.csv` | Obras: `id_obra`, `id_empreendimento`, `descricao_obra(_padronizada)`, `intervencao`, `tipo_infraestrutura`, `extensao_km`, `valor_obra` (separador `;`, decimal `.`) | Consulta ao banco |

Do CSV de obras, vale **o mais recente** da pasta `data/` que tenha as colunas
`id_obra` e `valor_obra`. O arquivo `data/ficha_pelt.gpkg` é gerado pelo próprio fluxo.

## 4. Gerar as fichas (um comando)

Na pasta do projeto:

```
python gerar_tudo.py
```

O comando roda três etapas e salva uma imagem por empreendimento em
`atlas_saida/fichas_png/<id_empreendimento>.png`. Para os ~1.700 empreendimentos,
leva cerca de 30 minutos.

| Etapa | Script | O que faz |
|---|---|---|
| 1 | `scripts/preparar_ficha.py` | Lê os Parquet e o CSV de obras, aplica as regras e grava `data/ficha_pelt.gpkg` com os textos já formatados |
| 2 | `scripts/montar_ficha.py` | Cria `projetos/Atlas_Ficha_PELTMG.qgz` com o layout **"Ficha PELTMG"** |
| 3 | `scripts/exportar_atlas.py` | Exporta as páginas do atlas |

Opções úteis:

```
python gerar_tudo.py --ids 11,57,997     # só alguns empreendimentos (bom para testar)
python gerar_tudo.py --dpi 150           # mais qualidade (padrão: 80 dpi)
python gerar_tudo.py --formato pdf       # PDF em vez de PNG
```

Para **atualizar os dados**, troque os arquivos em `data/` e rode o comando de novo.

> Não deixe o `projetos/Atlas_Ficha_PELTMG.qgz` aberto no QGIS enquanto o comando
> roda, porque ele é regravado na etapa 2.

Para abrir e editar a ficha no QGIS, abra `projetos/Atlas_Ficha_PELTMG.qgz` e use o
layout **"Ficha PELTMG"**, que já vem com a pré-visualização do atlas.

## 5. Regras da ficha (resumo)

Todas as regras ficam em `scripts/preparar_ficha.py`. O layout só exibe os textos prontos.

- **Registro base:** vale a carteira Recomendada; na falta dela, a Otimizada; na falta das duas, a de Análise. Notas nulas são completadas pela próxima carteira que tiver o valor.
- **Financeiro:** usa o cenário 10 (Recomendado); na falta dele, o 8 ou o 7 (Otimizado); na falta deles, o Custo Econômico LP. O mês base é fixo em ago/24. A TIRM do `resumo_financeiro` já vem em %; a da carteira vem em fração e é multiplicada por 100.
- **Alocação 2055:** a tabela muda conforme o setor, a natureza e o grupo de modelagem: rodoviário, ferroviário de passageiros, ferroviário em toneladas ou TKU, hidroviário, aeroportuário ou dutoviário. Portuário não tem tabela. Aparecem só os cenários 1, 2, 3, 4, 8 e 10. As colunas se ajustam ao maior valor real e, se for preciso, a fonte diminui.
- **Obras:** do maior para o menor valor, quantas couberem na página.
- **Formato:** padrão brasileiro (`1.234,56`). Valor ausente ou zero aparece como `-`. Valores em reais vêm sem "R$", porque o cabeçalho já diz "(R$)".
- **Mapa:** enquadra a geometria do empreendimento com 20% de folga, nunca mais perto que 1:50.000. Isso vale também para pontos isolados.

## 6. Atualizar a cópia local do banco

O `data/dados_locais.gpkg` é a cópia local das camadas do mapa. Para atualizá-lo é
preciso ter acesso à rede interna (VPN):

```
pip install sqlalchemy psycopg2-binary
python scripts/baixar_dados.py                        # todas as camadas
python scripts/baixar_dados.py dados_gerais vw_obra   # só algumas tabelas
```

Na **primeira execução**, o script pergunta o host, a porta e o nome do banco e salva
essas informações em `config_banco.json`, na raiz do projeto. Esse arquivo é local e
fica fora do Git. O usuário e a senha são pedidos a cada execução. Se der erro no meio,
o `dados_locais.gpkg` anterior continua intacto.

**Recriar o projeto base.** Só é preciso fazer isto quando o projeto original mudar.
Coloque o projeto original, ligado ao banco e fora do Git, em
`projetos/Atlas_WS_Gerencial_format.qgz` e rode:

```
"C:\Program Files\QGIS 3.44.4\bin\python-qgis.bat" scripts\gerar_projeto_local.py
```

- Mudou uma **consulta SQL** no projeto original? Atualize `CAMADAS` em `scripts/baixar_dados.py`.
- Entrou uma **camada nova do banco**? Adicione-a em `CAMADAS` (`baixar_dados.py`) e em `TABELAS` (`gerar_projeto_local.py`).
