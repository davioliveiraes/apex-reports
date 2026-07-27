# Gerador de Relatórios PDF — Apex (Meta Ads)

Aplicação Django que lê o export **.xlsx** do Meta Ads Manager e gera o
relatório em PDF no padrão visual da Apex.

## Fluxo
O painel inicial oferece quatro modos:

1. **Anexo único** — 1 `.xlsx` → relatório individual. A aplicação lê KPIs
   (investimento, resultados, custo/resultado, impressões, alcance,
   frequência, CPM), monta o funil e o desempenho por campanha e sugere a
   Análise do Período em linguagem de cliente (números e continuidade;
   status de veiculação nunca aparece no relatório) — tudo editável na
   etapa de revisão antes de gerar o PDF.
2. **Consolidado** — 2 a 20 `.xlsx` (um por conta/unidade) → soma os totais,
   recalcula as taxas sobre os totais e gera o funil do grupo + composição
   por unidade + análise geral, com revisão antes do PDF.
3. **Listagem** — até 20 `.xlsx` → PDF em paisagem com uma tabela, uma
   linha por conta, na ordem de envio dos anexos. Sem consolidação, sem
   análise e sem ranking; título configurável (default "Relatório de
   Listagem").
4. **Indicador Único** — 2 a 20 `.xlsx` + **uma métrica escolhida** → PDF
   comparando só essa métrica entre as contas: tabela ordenada pela direção
   de "melhor" da métrica (melhor unidade em verde), gráfico de barras e
   total do grupo. Atende o pedido "me manda só os números de X de todas as
   unidades" sem gerar o relatório completo. Aceita ainda um **recorte de
   campanhas** (todas / somente ativas / somente inativas) lido da coluna
   "Veiculação da campanha" do export. Métrica e recorte são reeditáveis na
   revisão, sem reenviar os anexos.

Os quatro modos seguem o mesmo fluxo de duas etapas — **01 Importar dados**
→ **02 Revisar e gerar** — e o nome de cada conta pode ser digitado já no
painel, por anexo (em branco, cai no nome do arquivo).

## Rodando
```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```
Acesse http://127.0.0.1:8000/

### Dependências de sistema (WeasyPrint)
O PDF é renderizado com **WeasyPrint**, que desenha o texto com Pango/HarfBuzz.
No Debian/Ubuntu:
```bash
sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core
```
(Em outras distros/macOS, veja https://doc.courtbouillon.org/weasyprint/stable/first_steps.html.)
As fontes são as do sistema — os templates do PDF pedem Helvetica e caem em
DejaVu Sans, daí o `fonts-dejavu-core`; sem ele o PDF sai com outra fonte.

## Deploy na VPS
`deploy/deploy.sh` publica a aplicação numa VPS Ubuntu 24.04 sem domínio: o
painel responde em `http://<ip-da-vps>`, atrás de nginx com senha, servido por
gunicorn sob systemd (sobe no boot, reinicia sozinho se cair).

Na VPS, como usuário com sudo:
```bash
git clone git@github.com:davioliveiraes/apex-reports.git
sudo apex-reports/deploy/deploy.sh
```
Na primeira execução o script gera uma chave de deploy, mostra a pública e
para — basta cadastrá-la em **Settings → Deploy keys** do repositório (sem
write access) e rodar de novo. Ele também gera o `SECRET_KEY`, a senha do
painel e imprime tudo no fim.

O script é idempotente e é o próprio mecanismo de atualização: rodar de novo
faz `git pull`, reinstala dependências, aplica migrações, recolhe estáticos e
reinicia o serviço.
```bash
sudo /opt/apex-reports/deploy/deploy.sh              # publica versão nova
sudo /opt/apex-reports/deploy/deploy.sh --senha 'x'  # troca a senha do painel
sudo journalctl -u apex-reports -f                   # logs
```
Sem domínio não há HTTPS: o tráfego trafega em texto puro entre o navegador e a
VPS. A senha do nginx impede o uso por terceiros, mas não criptografa.

## Estrutura
- `relatorios/parser_xlsx.py` — leitura do export (colunas em PT ou EN,
  identificadas por palavra-chave; ignora linhas de total)
- `relatorios/benchmarks.py` — faixas de referência das métricas (CTR, CPC,
  CPM, taxa de conversão, frequência), editáveis por vertical/objetivo;
  a classificação alimenta as leituras dos cards e a análise sugerida
- `relatorios/gerador_pdf.py` — gerador do PDF individual/consolidado
  (HTML + CSS → WeasyPrint, layout dark de dashboard em 1 página; donut
  via matplotlib embutido)
- `relatorios/gerador_listagem.py` — gerador do PDF de listagem (paisagem,
  tabela 1 linha por conta, paginação no rodapé)
- `relatorios/metricas.py` — **registro central das métricas** do modo
  Indicador Único (`METRICS_REGISTRY`): rótulo, unidade, estágio do funil,
  regra de agregação (`soma` × `recalculo` + fórmula) e direção do ranking.
  Fonte única do seletor da UI e do motor de agregação — acrescentar uma
  métrica é acrescentar uma entrada ao dicionário
- `relatorios/gerador_indicador.py` — gerador do PDF de indicador único
  (tabela ordenada + barras horizontais via matplotlib)
- `relatorios/templates/relatorios/pdf_relatorio.html` — template do PDF
  individual/consolidado; `pdf_listagem.html` — listagem;
  `pdf_indicador.html` — indicador único
- `relatorios/views.py` — painel de modos → (revisão →) PDF
- `docs/img/logo_apex.png` — logo usado no cabeçalho do PDF
- `docs/exemplo_*.pdf` — PDFs de exemplo (individual, consolidado, 20 unidades)

## Observações
- Alcance total é a soma das linhas do export (pode haver sobreposição
  de audiência entre anúncios; o Meta desduplica, a soma não).
- Métricas de taxa (CTR, CPM, CPA, CPC, frequência, taxa de conversão)
  **nunca** são média das médias: tanto no consolidado quanto no indicador
  único o total é recalculado sobre os brutos somados de todas as contas.
- No indicador único, conta cujo export não traz a coluna necessária entra
  como "—", fica fora do total e é listada no rodapé do PDF.
- O recorte de veiculação filtra as LINHAS do export antes de qualquer soma,
  então todo número do PDF (inclusive os recalculados) sai do recorte. Conta
  sem campanhas no recorte fica fora do total; export sem a coluna entra com
  todas as campanhas e é sinalizado no rodapé.
- A prévia da revisão de listagem/indicador é montada pelas mesmas funções
  que alimentam o PDF (`gerador_listagem.linha_conta`,
  `gerador_indicador.montar_tabela`) — o que se confere na tela é o que sai
  no arquivo.
- `SECRET_KEY`, `DEBUG` e `ALLOWED_HOSTS` vêm do ambiente
  (`DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`). Sem nenhuma
  variável valem os padrões de desenvolvimento (debug ligado, qualquer host);
  na VPS o systemd carrega os valores de produção de `/etc/apex-reports/env`.
- A aplicação não tem modelos próprios, mas a sessão que liga a importação à
  tela de revisão é gravada no banco — `migrate` é obrigatório também em
  produção.
