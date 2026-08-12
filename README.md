# Gerador de Relatórios PDF — Apex (Meta Ads)

Aplicação Django que lê o export **.xlsx** do Meta Ads Manager e gera o
relatório em PDF no padrão visual da Apex.

## Fluxo
O painel inicial oferece quatro modos:

1. **Anexo único** — 1 `.xlsx` → relatório individual. A aplicação lê KPIs
   (investimento, resultados, custo/resultado, impressões, alcance,
   frequência, CPM), monta o funil e o desempenho por campanha e sugere a
   Análise do Período em linguagem de cliente — leitura, ponto de atenção,
   o que será feito e o objetivo do próximo ciclo (status de veiculação
   nunca aparece no relatório) — tudo editável na etapa de revisão antes de
   gerar o PDF.
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
No Windows nativo (sem WSL), o pip não instala essas libs — `import weasyprint`
falha com `OSError: cannot load library 'libgobject-2.0-0'`. Resolve com
[MSYS2](https://www.msys2.org/):
```powershell
winget install --id MSYS2.MSYS2 -e
C:\msys64\usr\bin\bash.exe -lc "pacman -Sy --noconfirm && pacman -S --noconfirm mingw-w64-x86_64-pango"
```
Depois adicione `C:\msys64\mingw64\bin` ao PATH do usuário (Configurações →
Sistema → Variáveis de ambiente, ou
`[Environment]::SetEnvironmentVariable("Path", "$([Environment]::GetEnvironmentVariable('Path','User'));C:\msys64\mingw64\bin", "User")`
no PowerShell) e abra um terminal novo para o PATH atualizado valer.
(Em outras distros/macOS, veja https://doc.courtbouillon.org/weasyprint/stable/first_steps.html.)
As fontes são as do sistema — os templates do PDF pedem Helvetica e caem em
DejaVu Sans, daí o `fonts-dejavu-core`; sem ele o PDF sai com outra fonte.

## Deploy na VPS
`deploy/deploy.sh` publica a aplicação numa VPS Ubuntu 24.04 sem domínio: o
painel responde em `http://<ip-da-vps>/apex-reports`, atrás de nginx com senha,
servido por gunicorn sob systemd (sobe no boot, reinicia sozinho se cair).

Na VPS, no home do usuário com sudo que vai rodar a aplicação:
```bash
git clone git@github.com:davioliveiraes/apex-reports.git
sudo apex-reports/deploy/deploy.sh
```
A aplicação fica em `~/apex-reports` desse usuário, e é como ele que o serviço
roda — o projeto aparece ao lado dos outros no home, não escondido em `/opt`
(`--dir` e `--usuario` mudam isso). Só os estáticos vão para fora, em
`/var/www/apex-reports/static`, para o nginx não precisar de permissão de
travessia dentro do home.

Para clonar, o script usa a chave SSH que o usuário já tiver. Se ela não
alcançar o repositório, ele gera uma chave de deploy, mostra a pública e para:
basta cadastrá-la em **Settings → Deploy keys** (sem write access) e rodar de
novo. Ele também gera o `SECRET_KEY`, a senha do painel e imprime tudo no fim.

O script é idempotente e é o próprio mecanismo de atualização: rodar de novo
faz `git pull`, reinstala dependências, aplica migrações, recolhe estáticos e
reinicia o serviço.

O `Makefile` guarda o IP e o repositório, então no dia a dia basta:
```bash
make deploy       # da máquina de desenvolvimento: entra na VPS por SSH e publica
make deploy-aqui  # roda o script na máquina atual (use SÓ estando na VPS)
```
`make deploy` recusa se houver alteração não commitada ou commit não enviado:
o script publica o que está no GitHub, então subir com trabalho local pendente
daria um deploy "bem-sucedido" que republica a versão anterior.
Qualquer variável é sobrescrita na chamada — `make deploy IP=203.0.113.10`,
`make deploy BRANCH=teste`. Os comandos por extenso continuam valendo:
```bash
sudo ~/apex-reports/deploy/deploy.sh              # publica versão nova
sudo ~/apex-reports/deploy/deploy.sh --senha 'x'  # troca a senha do painel
sudo journalctl -u apex-reports -f                # logs
```
Sem domínio não há HTTPS: o tráfego trafega em texto puro entre o navegador e a
VPS. A senha do nginx impede o uso por terceiros, mas não criptografa.

O subcaminho `/apex-reports` (mudável com `--caminho`) identifica a aplicação na
URL e deixa a raiz do IP livre para outra. O nginx tira o prefixo antes de
repassar ao gunicorn; quem o recoloca em tudo que o Django gera — `{% url %}`,
redirects, `{% static %}` — é o `FORCE_SCRIPT_NAME`, alimentado pela variável
`DJANGO_SCRIPT_NAME`. Os cookies de sessão e CSRF ficam restritos ao prefixo,
para não colidirem com os de outra aplicação no mesmo IP.

Por ora quem digita só o IP é redirecionado ao painel, e o bloco se declara
`default_server` na porta 80 (removendo o site `default` do nginx). Quando outra
aplicação ocupar a raiz, é esse redirect que sai — o resto continua igual.

## Estrutura
- `relatorios/parser_xlsx.py` — leitura do export (colunas em PT ou EN,
  identificadas por palavra-chave; ignora linhas de total)
- `relatorios/benchmarks.py` — faixas de referência das métricas (CTR, CPC,
  CPM, taxa de conversão, frequência), editáveis por vertical/objetivo;
  a classificação alimenta as leituras dos cards do funil
- `relatorios/analysis/` — **motor de regras da Análise do Período**, da conta
  individual e do consolidado, determinístico e offline: `benchmarks.py`
  (faixas de CPA por perfil, faixas de apoio de CPM/frequência/CTR e a
  precedência das referências), `rules.py` (`avaliar` classifica o período em
  ÓTIMO/BOM/ATENÇÃO, emite os sinais e escolhe o próximo passo; `avaliar_grupo`
  faz o mesmo para o grupo e mede cada unidade contra o CPA do grupo),
  `contexto.py` (vocabulário do que o operador informa na revisão — fonte
  única do formulário e do motor) e `templates.py` (`redigir`/`redigir_grupo`
  escrevem a partir dessa decisão, em 3 a 5 blocos rotulados, com ou sem
  números, para PDF ou WhatsApp). Testes em `relatorios/analysis/tests/`
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
- A coluna de verba muda de rótulo entre exports do Meta ("Valor usado (BRL)",
  "Valor gasto (BRL)"). Todas as variantes conhecidas estão em `_COLUNAS`, e
  há teste: não reconhecê-la zera investimento e custo por resultado sem
  avisar ninguém, porque o zero passa por número legítimo.
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
- A Análise do Período é decidida antes de ser escrita: o **CPA sozinho**
  define ÓTIMO/BOM/ATENÇÃO, e CPM, frequência, CTR e estrutura de campanhas só
  justificam o veredito e escolhem o próximo passo. O que muda de um relatório
  para outro não é a regra, é a **referência** contra a qual o CPA é medido,
  nesta ordem: *meta combinada com o cliente* → *CPA do grupo no mesmo
  período* → *faixa estimada do perfil*.
  O único rebaixamento é por amostra pequena (< 30 resultados), que derruba
  ÓTIMO para BOM. Resultado sem verba lida não é classificado: o motor abre
  dizendo que a leitura está incompleta em vez de elogiar o que não mediu.
- **No consolidado cada unidade é medida contra o CPA do próprio grupo** — a
  única referência do sistema que não é estimativa nossa: as outras unidades
  rodaram o mesmo intervalo, o mesmo tipo de campanha e a mesma gestão. Daí
  saem os sinais de dispersão (praça cara, praça barata, grupo homogêneo) e o
  próximo passo do grupo, que na prática é levar o método das melhores praças
  às demais. O grupo em si continua medido contra a meta ou a faixa do perfil:
  compará-lo consigo mesmo faria todo consolidado sair BOM por construção.
- O bloco 2 da análise do grupo **nomeia a praça mais cara e a mais barata**,
  então o nome que o operador digita no painel vai para o PDF do cliente — em
  branco ele cai no nome do arquivo, que costuma ser feio. A decisão viaja em `dados["avaliacao"]`, serializável, ao
  lado do texto. **As faixas de CPA são estimativas calibráveis**, não
  benchmark verificado — ajuste em `analysis/benchmarks.py` conforme o
  histórico acumular.
- A análise sai em **3 a 5 blocos rotulados**: *Leitura do período*, *O que
  vamos fazer* e *Objetivo do próximo ciclo* são fixos; *Ponto de atenção* e
  *Leitura atual* (ou *O que sustentou o resultado*, quando aparece sozinho)
  entram conforme os sinais. O texto tem teto de caracteres **medido** no PDF
  real por bissecção (`OrcamentoDePaginaTest`); se estourar, o corte é por
  precedência de sinal e os fixos nunca saem. O último bloco é uma escada por
  classificação:
  ATENÇÃO mira voltar à faixa de trabalho, BOM mira baixar o custo com o
  mesmo investimento, ÓTIMO mira sustentar o patamar ganhando volume. Ele
  compromete com **direção** ("o objetivo é", "buscamos") e nunca com número
  ou promessa de resultado — há teste para isso.
- Cada métrica é dita como consequência de negócio, não como métrica: o
  leitor é o dono da loja. "Frequência saturada" vira "o mesmo público já viu
  os anúncios muitas vezes"; sigla crua (CPM, CPA, CTR) não aparece.
- No PDF a análise não repete número que já está nas tabelas logo acima — mas
  **número derivado entra**: a verba das campanhas sem resultado e quantos
  contatos ela deveria ter trazido não estão em tabela nenhuma, e são eles que
  sustentam o argumento. Ficam em `avaliacao["derivados"]`. O mesmo motor
  redige com todos os números (`incluir_numeros=True`) para destinos sem
  tabela.
- Na tela **02 Revisar e gerar** há o bloco **Contexto do período**: o que
  mudou (criativos, público, captação, orçamento), problema operacional e sua
  situação, meta de custo por resultado e próximo passo — tudo opcional. O
  botão *Regerar análise* recalcula o texto sem reenviar o anexo, e o contexto
  fica na sessão. Preencher e ir direto ao *Gerar PDF* **não** perde o que foi
  informado: o relatório é segurado e a tela volta com a análise recalculada,
  para o operador ler antes de mandá-la ao cliente. Se o texto tiver sido
  editado à mão, nada é sobrescrito — a tela pergunta, e *Gerar assim mesmo*
  mantém o que o operador escreveu. As opções vivem em `analysis/contexto.py`,
  fonte única do formulário e do motor; nenhuma delas muda a classificação,
  que continua sendo do CPA. Com tudo vazio a saída é idêntica à de antes de
  os campos existirem.
- A prévia da revisão de listagem/indicador é montada pelas mesmas funções
  que alimentam o PDF (`gerador_listagem.linha_conta`,
  `gerador_indicador.montar_tabela`) — o que se confere na tela é o que sai
  no arquivo.
- Os ajustes de produção vêm do ambiente: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`,
  `DJANGO_ALLOWED_HOSTS`, `DJANGO_STATIC_ROOT` e `DJANGO_SCRIPT_NAME`. Na VPS
  o systemd carrega tudo de `/etc/apex-reports/env`, que o `deploy.sh` escreve.
  O padrão do `settings.py` é **produção**: sem `DJANGO_SECRET_KEY` a
  aplicação se recusa a subir, em vez de cair numa chave que está publicada
  aqui no repositório; `DEBUG` só liga com `1`/`true`/`yes`/`on`, e sem
  `DJANGO_ALLOWED_HOSTS` valem só os endereços locais. Quem liga o modo de
  desenvolvimento é o `manage.py` — produção sobe por `gunicorn
  apex_reports.wsgi`, que não passa por ele —, então `python manage.py
  runserver` continua não precisando de variável nenhuma.
- A aplicação não tem modelos próprios, mas a sessão que liga a importação à
  tela de revisão é gravada no banco — `migrate` é obrigatório também em
  produção.
