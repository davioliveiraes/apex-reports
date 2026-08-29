# GUIA — Extração de Dados de Verba no Gerenciador de Anúncios

**Versão:** 1.1
**Objetivo:** montar a visualização de colunas `VERBA` e exportar os dois `.xlsx` que alimentam a frente de *Análise de Verba* da aplicação.
**Escopo:** coleta de dados de **verba**. Não coleta métrica de performance.

> Este é o documento de coleta. Quem consome os arquivos é
> `relatorios/parser_verba.py`; as fórmulas do fechamento estão em
> `relatorios/fechamento_verba.py`.

---

## Princípio

**Orçamento não é métrica, é configuração.** Ele só existe na tabela do Gerenciador de Anúncios, no nível em que foi definido:

| Estrutura | Onde o orçamento vive |
| --- | --- |
| `[CBO]` | Nível de **campanha** |
| `[ABO]` | Nível de **conjunto de anúncios** |

Como a estrutura varia de conta para conta, a exportação é sempre feita **duas vezes**, uma em cada nível. Não vale checar antes qual é — exporte os dois.

---

## Passo a passo

### 1. Abrir a conta e escolher o período do ciclo

Gerenciador de Anúncios → seletor de conta no topo → escolher o cliente.

No seletor de datas, escolher **o intervalo do ciclo deste cliente**: do dia em
que o ciclo começou até **ontem**.

| O cliente | Seletor de datas |
|---|---|
| fecha do dia 1º | **Este mês** |
| fecha de segunda a domingo | **Esta semana** |
| fecha por quinzena | intervalo **personalizado**, do dia em que a quinzena começou |
| entrou no meio do mês (dia 17, dia 30…) | intervalo **personalizado**, do dia do contrato até ontem |
| fecha numa semana que não começa na segunda | intervalo **personalizado**, de sete dias |

> Não usar "Últimos 30 dias" nem "Últimos 7 dias" quando o ciclo do cliente não
> for esse: são janelas móveis, e a aplicação vai tomá-las como o ciclo.

**Este passo define o fechamento inteiro.** A predefinição inclui `Início dos
relatórios` e `Encerramento dos relatórios` (passo 4), e a aplicação lê o ciclo
dali: o ciclo COMEÇA onde o relatório começa, e tem o tamanho da periodicidade
escolhida na tela — 7 dias, 15 dias, ou até a véspera do mesmo dia no mês
seguinte.

Não há campo de data na tela por causa disso. Em troca, a aplicação confia no
intervalo escolhido aqui: exportar "Últimos 7 dias" para um cliente mensal cria
um ciclo que começa sete dias atrás, e nenhuma conta acusa isso. **A tela 02
escreve o ciclo deduzido** — confira essa linha antes de copiar a mensagem.

O que ela recusa em vermelho é o export que cobre MAIS de um ciclo: trinta dias
num cliente semanal soma quatro fechamentos num número só.

> Não confundir com as colunas `Início` e `Término` da aba *Configurações de
> anúncios*: aquelas são as datas em que a CAMPANHA foi configurada para
> começar e terminar. As quatro convivem no export e a aplicação usa cada par
> para uma coisa — o de configuração decide desde quando a campanha veicula, o
> de relatório decide o ciclo e a que período o gasto se refere.

### 2. Escolher a aba do nível em que a conta está montada

As abas *Campanhas* / *Conjuntos de anúncios* / *Anúncios* mudam o que sai no
export. **Um arquivo só**, e a aba depende da estrutura da conta:

| Estrutura | Aba a exportar |
|---|---|
| `[CBO]` — orçamento na campanha | **Campanhas** |
| `[ABO]` — orçamento no conjunto | **Conjuntos de anúncios** |

É a mesma escolha que se marca na tela 01, e a aplicação confere: marcar CBO e
enviar o export de conjunto soma o gasto no nível errado sem reclamar de nada,
então ela recusa.

Eram dois arquivos até 29/08/2026, e a razão era o orçamento — `[CBO]` guarda o
valor na campanha, `[ABO]` no conjunto. O diário do fechamento passou a vir do
contratado dividido pelos dias do ciclo (R$ 300/semana = R$ 43/dia), o orçamento
da planilha virou informação de conferência, e o segundo arquivo perdeu a
função.

### 3. Abrir o personalizador de colunas

Botão **Colunas: Desempenho** → última opção do dropdown, *Personalizar colunas*.

O painel tem quatro abas no topo: *Principais métricas*, *Métricas de suporte*, **Configurações de anúncios**, *Mais*.

> **Quase todo campo de verba está em "Configurações de anúncios".** *Principais métricas* é a aba de performance — dela sai um único campo. Se estiver rolando listas de Resultados, Alcance, Cliques ou Mensagens procurando orçamento, está na aba errada.

Use a busca do painel em vez de navegar pelas categorias.

### 4. Marcar os campos — seleção fechada

**Aba: Principais métricas** — grupo *Gasto*

- [x] `Valor gasto`

Um campo só. Desmarque todo o resto da aba.

**Aba: Mais** — grupo *Configurações de relatório*

- [x] `Início dos relatórios`
- [x] `Encerramento dos relatórios`

São as duas que dizem de que período é o gasto. **Sem elas o app recusa o
arquivo**, porque projetar um gasto de intervalo desconhecido é como o
fechamento sai errado sem ninguém perceber. Se não aparecerem nessa aba, buscar
por `relatórios` no campo de busca do painel.

**Aba: Configurações de anúncios**

- [x] `Orçamento`
- [x] `Tipo de orçamento`
- [x] `Estratégia de lances`
- [x] `Início`
- [x] `Término`
- [x] `Objetivo`
- [x] `Veiculação`
- [x] `Identificação da campanha`
- [x] `Identificação do conjunto de anúncios`

Se algum rótulo não bater exatamente, buscar por `orçamento`, `lance` e `identificação`. Os nomes da interface mudam de tempos em tempos.

### 5. O que NÃO entra

Deixar desmarcado, sem exceção:

| Bloco | Campos |
| --- | --- |
| Resultados | Resultados · Custo por resultado · Índice de resultados · ROAS |
| Impressões | Alcance · Frequência · Impressões · CPM |
| Cliques | Cliques (todos) · Cliques no link · CTR · CPC |
| Mídia | Reproduções de vídeo · ThruPlays · Custo por ThruPlay |
| Tráfego | Visualizações da página de destino · Visitas ao perfil |
| Engajamento | Interações · Reações · Comentários · Compartilhamentos |
| Mensagens | Conversas por mensagem iniciadas · Custo por conversa · Conversas respondidas |
| Conversões | ROAS de compras · Retorno sobre investimento |

**O caso que mais tenta é `Conversas por mensagem iniciadas`.** É a métrica principal das contas com destino WhatsApp, e por isso a mão vai nela por reflexo. Deixe fora: ela pertence ao *Review de Conta*, não ao fechamento de verba. A mensagem de verba proíbe métrica de performance — se o campo estiver no export, o número aparece na tela na hora de escrever e contamina a conversa.

### 6. Salvar como predefinição

Ainda no painel, marcar **Salvar como predefinição** no rodapé e nomear `VERBA`. Só depois clicar em *Aplicar*.

A predefinição fica disponível no dropdown de colunas para todas as contas — a seleção não precisa ser refeita cliente a cliente.

### 7. Exportar

Canto superior direito da tabela → **Exportar e compartilhar** → *Exportar dados
da tabela* → formato `.xlsx`.

Exportar na aba escolhida no passo 2 — **Campanhas** para conta CBO,
**Conjuntos de anúncios** para conta ABO.

Resultado: um arquivo. Fim da coleta.

---

## Por que cada campo de configuração está na lista

| Campo | Para que serve no cálculo |
| --- | --- |
| `Orçamento` | o número conferido contra o contratado |
| `Tipo de orçamento` | separa diário de vitalício — muda a fórmula de projeção |
| `Estratégia de lances` | contexto de escoamento; lance manual limita gasto |
| `Início` | define quantos dias **realmente veicularam** |
| `Término` | separa campanha contínua de campanha com data-limite |
| `Objetivo` | expõe divergência entre nomenclatura e configuração real |
| `Veiculação` | ativa/pausada explica gasto abaixo do previsto |
| `Identificação da campanha` | chave do merge |
| `Identificação do conjunto de anúncios` | chave do merge |

### Nota sobre `Início`

Este campo é o que separa subentrega real de artefato de cálculo.

A fórmula do fechamento divide o gasto por `dias_veiculados`. Se a campanha subiu no meio do mês, usar `dias_encerrados` (dia de hoje − 1) contaria dias em que não havia nada no ar.

Caso real — Rei do Celular, agosto/2026: campanha iniciada em 17/08, conferência em 25/08.

- Dividindo pelos dias encerrados → subentrega crítica; manda investigar limite de conta e leilão.
- Dividindo pelos dias de veiculação → subentrega leve, compatível com aprendizado; manda esperar.

Sem a coluna `Início`, você lê o primeiro. É por isso que a aplicação recusa
qualquer denominador que não sejam os dias de veiculação — e por isso a coluna
é obrigatória na predefinição.

---

## Armadilhas

### Relatórios de Anúncios não serve aqui

A ferramenta de Relatórios (a que agenda envio por e-mail) trabalha só com métricas de desempenho. Orçamento não está na lista de campos disponíveis. Verba sai da tabela do Gerenciador, e é manual até a integração via API.

### A coluna `Orçamento` vem como texto

O export traz valor e periodicidade na mesma célula — `R$ 33,00 Diário`, `R$ 1.000,00 Vitalício`. O parser separa os dois em `partir_orcamento`.

### Conta `[CBO]` traz orçamento em branco no export de conjunto

E o inverso vale para `[ABO]` no export de campanha. Não é erro — é a estrutura, e é por isso que a aba a exportar depende dela. Exportar a aba errada não faz a aplicação reclamar de orçamento: faz ela somar o gasto no nível errado. Por isso a estrutura é declarada na tela 01 e **conferida contra as colunas** do arquivo.

### O orçamento do export não decide número nenhum

Desde 29/08/2026 o diário do fechamento é o **contratado dividido pelos dias do ciclo** — R$ 300/semana são R$ 43/dia, R$ 990/mês são R$ 32/dia num mês de 31. A coluna `Orçamento` continua sendo lida e continua na tabela de conferência, porque é ela que denuncia o Meta setado em R$ 20/dia sob um contrato que pede R$ 43. Mas denuncia para você ler, não para a conta usar.

Antes o diário saía da soma dos orçamentos configurados, e bastava a conta ser `[ABO]` sem o export de conjunto para ele virar R$ 0/dia num fechamento com R$ 1.304 gastos.

### Linhas com gasto zerado

Manter no agregado de investimento. Estrutura pausada com R$ 0,00 gasto é informação — some ela e a soma do ciclo fica errada. A aplicação soma o gasto de todas as linhas.

---

## Checklist de coleta por conta

- [ ] Período do seletor = o ciclo do cliente, do começo dele até ontem
- [ ] Predefinição `VERBA` aplicada (com as duas colunas de período do relatório)
- [ ] Export da aba do nível da conta — **Campanhas** (CBO) ou **Conjuntos de anúncios** (ABO)
- [ ] Na tela 02, o ciclo deduzido bate com o do contrato

---

## Depois da coleta

Abrir a aplicação → **Análise de Verba** → preencher a base interna
(cliente/unidade, orçamento contratado, por mês ou por semana, e a estrutura da
conta), arrastar o `.xlsx` e ler o resultado.

Não há data a digitar: o ciclo vem do intervalo do próprio export. **Confira a
linha do ciclo deduzido** na tela 02 antes de copiar — é ela que diz se o
intervalo escolhido no Gerenciador foi o certo.

A aplicação devolve os dois blocos do fechamento — a mensagem do cliente e a
análise interna do desvio — mais a tabela de conferência estrutura a estrutura.
