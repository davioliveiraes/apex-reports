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

### 1. Abrir a conta e travar o período

Gerenciador de Anúncios → seletor de conta no topo → escolher o cliente.
No seletor de datas, usar **Este mês**.

> Não usar "Últimos 30 dias" — atravessa a virada de mês e quebra a conferência contra o contratado.

### 2. Escolher o nível certo da tabela

As abas *Campanhas* / *Conjuntos de anúncios* / *Anúncios* mudam o que sai no export. Exportar apenas o nível de campanha faz todas as linhas `[ABO]` virem com orçamento em branco.

### 3. Abrir o personalizador de colunas

Botão **Colunas: Desempenho** → última opção do dropdown, *Personalizar colunas*.

O painel tem quatro abas no topo: *Principais métricas*, *Métricas de suporte*, **Configurações de anúncios**, *Mais*.

> **Quase todo campo de verba está em "Configurações de anúncios".** *Principais métricas* é a aba de performance — dela sai um único campo. Se estiver rolando listas de Resultados, Alcance, Cliques ou Mensagens procurando orçamento, está na aba errada.

Use a busca do painel em vez de navegar pelas categorias.

### 4. Marcar os campos — seleção fechada

**Aba: Principais métricas** — grupo *Gasto*

- [x] `Valor gasto`

Um campo só. Desmarque todo o resto da aba.

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

### 7. Exportar nos dois níveis

Canto superior direito da tabela → **Exportar e compartilhar** → *Exportar dados da tabela* → formato `.xlsx`.

1. Exportar na aba **Campanhas**
2. Trocar para **Conjuntos de anúncios** e repetir

Resultado: dois arquivos. Fim da coleta.

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

E o inverso vale para `[ABO]` no export de campanha. Não é erro — é a estrutura. Por isso os dois arquivos. A aplicação aceita **um só** quando a conta é 100% `[CBO]`, e avisa nominalmente quando encontra `[ABO]` sem o export de conjunto para resolvê-la.

### O merge é por ID, nunca por nome

Nome de campanha é renomeado durante o mês e o cruzamento perde linhas sem avisar. As colunas de identificação não mudam — por isso entram na predefinição `VERBA`. Sem elas a aplicação cai no nome e **avisa na tela** que caiu.

### Linhas com gasto zerado

Manter no agregado de investimento. Conjunto pausado com R$ 0,00 gasto é informação — some ele e a soma do mês fica errada. A aplicação soma o gasto de todas as linhas e o orçamento só das ativas.

---

## Checklist de coleta por conta

- [ ] Período travado em *Este mês*
- [ ] Predefinição `VERBA` aplicada
- [ ] Export nível **campanha** (`.xlsx`)
- [ ] Export nível **conjunto de anúncios** (`.xlsx`)

---

## Depois da coleta

Abrir a aplicação → **Análise de Verba** → preencher a base interna
(cliente/unidade, orçamento contratado e data de hoje), arrastar os dois
`.xlsx` e ler o resultado. A aplicação devolve os dois blocos do fechamento —
a mensagem do cliente e a análise interna do desvio — mais a tabela de
conferência campanha a campanha.
