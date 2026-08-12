# Atalhos do Apex Reports. `make` sem alvo lista o que existe.
#
# O deploy publica o que está NO GITHUB, não o que está na sua pasta: o script
# roda na VPS e faz `git reset --hard origin/<branch>`. Por isso `make deploy`
# confere antes se falta commit ou push, em vez de subir a versão anterior sem
# avisar.
#
# Qualquer variável pode ser sobrescrita na chamada, sem editar este arquivo:
#     make deploy IP=203.0.113.10
#     make deploy VPS=deploy@outra-vps BRANCH=teste

IP     ?= 69.62.104.167
REPO   ?= https://github.com/davioliveiraes/apex-reports.git
BRANCH ?= main
VPS    ?= deploy@$(IP)
DIR    ?= ~/apex-reports

# O interpretador do venv muda de lugar conforme o sistema: `Scripts/python.exe`
# no Windows, `bin/python` no Linux e no macOS. Sem venv nenhum, cai no python3
# do PATH — assim `make teste` não morre com "No such file or directory" numa
# máquina recém-clonada, e sim com o erro de dependência, que diz o que fazer.
PY := $(firstword $(wildcard venv/Scripts/python.exe venv/bin/python) python3)
DEPLOY := sudo deploy/deploy.sh --ip $(IP) --repo $(REPO) --branch $(BRANCH)

.DEFAULT_GOAL := ajuda
.PHONY: ajuda deploy deploy-aqui checa-git teste rodar

ajuda:  ## Lista os alvos disponíveis
	@grep -hE '^[a-z-]+:.*##' $(MAKEFILE_LIST) \
	  | sed -e 's/:.*## /\t/' -e 's/^/  make /' | expand -t 22

deploy: checa-git  ## Publica na VPS por SSH — é o comando do dia a dia
	@echo "→ deploy de $(BRANCH) em $(VPS)"
	@# Sem `git pull` aqui: o script já faz fetch + reset --hard e se
	@# re-executa se ele próprio mudou. Um pull antes só acrescentaria uma
	@# forma de falhar (conflito local na VPS aborta o encadeamento).
	ssh -t $(VPS) 'cd $(DIR) && $(DEPLOY)'

deploy-aqui:  ## Roda o script na máquina atual (use SÓ estando na VPS)
	$(DEPLOY)

# O deploy puxa do GitHub. Trabalho não enviado não vai junto, e o script
# reinicia o serviço de qualquer jeito — daria um deploy "bem-sucedido" que
# republica a versão anterior.
checa-git:
	@test -z "$$(git status --porcelain)" || { \
	  echo "há alterações não commitadas:"; git status --short; \
	  echo "commite antes, ou rode: make deploy-aqui (na VPS)"; exit 1; }
	@git fetch --quiet origin $(BRANCH)
	@test -z "$$(git log origin/$(BRANCH)..$(BRANCH) --oneline)" || { \
	  echo "há commits não enviados:"; \
	  git log origin/$(BRANCH)..$(BRANCH) --oneline; \
	  echo "rode: git push origin $(BRANCH)"; exit 1; }

teste:  ## Roda a suíte de testes
	$(PY) manage.py test relatorios

rodar:  ## Sobe o servidor de desenvolvimento
	$(PY) manage.py runserver
