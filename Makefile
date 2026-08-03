# Atalhos do Apex Reports. `make` sem alvo lista o que existe.
#
# O deploy roda NA VPS: o script faz o pull, instala o serviço e recarrega o
# nginx. Daqui do desenvolvimento, `make deploy-remoto` faz isso por SSH.
#
# Qualquer variável pode ser sobrescrita na chamada, sem editar este arquivo:
#     make deploy IP=203.0.113.10
#     make deploy-remoto VPS=deploy@outra-vps

IP     ?= 69.62.104.167
REPO   ?= https://github.com/davioliveiraes/apex-reports.git
BRANCH ?= main
VPS    ?= deploy@$(IP)
DIR    ?= ~/apex-reports

PY := venv/bin/python

.DEFAULT_GOAL := ajuda
.PHONY: ajuda deploy deploy-remoto teste rodar

ajuda:  ## Lista os alvos disponíveis
	@grep -hE '^[a-z-]+:.*##' $(MAKEFILE_LIST) \
	  | sed -e 's/:.*## /\t/' -e 's/^/  make /' | expand -t 24

deploy:  ## Publica a versão do branch (rodar NA VPS)
	sudo deploy/deploy.sh --ip $(IP) --repo $(REPO) --branch $(BRANCH)

deploy-remoto:  ## Dispara o deploy na VPS por SSH (rodar no desenvolvimento)
	@echo "→ deploy em $(VPS)"
	ssh -t $(VPS) 'cd $(DIR) && git pull --quiet && \
	  sudo deploy/deploy.sh --ip $(IP) --repo $(REPO) --branch $(BRANCH)'

teste:  ## Roda a suíte de testes
	$(PY) manage.py test relatorios

rodar:  ## Sobe o servidor de desenvolvimento
	$(PY) manage.py runserver
