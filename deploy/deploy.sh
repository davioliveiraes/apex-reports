#!/usr/bin/env bash
#
# Deploy do Apex Reports numa VPS Ubuntu 24.04 (Hostinger KVM1), sem domínio:
# o painel passa a responder em http://<ip-da-vps>, atrás do nginx com senha,
# e sobe sozinho no boot — não é mais preciso deixar um `runserver` aberto.
#
# Roda NA VPS, com sudo. Pode ser executado quantas vezes quiser: cada passo
# confere o estado antes de agir, e o segredo do Django, a senha do painel e a
# chave de deploy são gerados uma vez só e preservados nas execuções seguintes.
# Rodar de novo é também como se publica uma versão nova (faz o pull).
#
#   sudo ./deploy.sh                       # detecta o IP público sozinho
#   sudo ./deploy.sh --ip 203.0.113.10     # ou informe o IP na mão
#   sudo ./deploy.sh --senha 'nova-senha'  # troca a senha do painel
#   sudo ./deploy.sh --branch outra        # publica outro branch
#
set -euo pipefail

REPO="git@github.com:davioliveiraes/apex-reports.git"
BRANCH="main"
DESTINO="/opt/apex-reports"
USUARIO_APP="apex"          # dono dos arquivos e do processo, sem shell
USUARIO_PAINEL="apex"       # login da senha do nginx
SERVICO="apex-reports"
PORTA_APP="127.0.0.1:8000"  # só loopback: quem fala com a internet é o nginx
ETC="/etc/apex-reports"
AMBIENTE="$ETC/env"
CHAVE="$ETC/deploy_key"
CONHECIDOS="$ETC/known_hosts"
HTPASSWD="/etc/nginx/${SERVICO}.htpasswd"
IP=""
SENHA=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ip)     IP="$2"; shift 2 ;;
    --senha)  SENHA="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --repo)   REPO="$2"; shift 2 ;;
    -h|--help) sed -n '2,18p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; exit 1 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "rode com sudo: sudo $0 $*" >&2; exit 1; }

passo() { printf '\n\033[1;31m▸\033[0m \033[1m%s\033[0m\n' "$1"; }

# IP de saída da máquina — na KVM1 é o mesmo IP público que a Hostinger mostra
# no painel. Se a VPS estiver atrás de NAT isso devolve um IP interno; nesse
# caso use --ip.
if [[ -z "$IP" ]]; then
  IP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}' || true)
fi
[[ -n "$IP" ]] || { echo "não consegui detectar o IP — passe --ip" >&2; exit 1; }


passo "Pacotes do sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# libpango/libharfbuzz: o WeasyPrint desenha o PDF com eles.
# fonts-dejavu-core: os templates do PDF pedem Helvetica e caem em DejaVu Sans,
# que é o que a sua máquina também usa — sem isso o PDF sai com outra fonte.
apt-get install -y -qq \
  git curl ufw nginx apache2-utils \
  python3-venv python3-dev build-essential \
  libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
  fonts-dejavu-core >/dev/null


passo "Usuário e diretórios"
id -u "$USUARIO_APP" &>/dev/null || useradd \
  --system --create-home --home-dir "/home/$USUARIO_APP" \
  --shell /usr/sbin/nologin "$USUARIO_APP"
install -d -m 750 -o root -g "$USUARIO_APP" "$ETC"


passo "Chave de deploy do GitHub"
if [[ ! -f "$CHAVE" ]]; then
  ssh-keygen -q -t ed25519 -N "" -C "apex-reports deploy" -f "$CHAVE"
  chown "$USUARIO_APP:$USUARIO_APP" "$CHAVE" "$CHAVE.pub"
  chmod 600 "$CHAVE"
fi
if [[ ! -s "$CONHECIDOS" ]]; then
  ssh-keyscan -t ed25519 github.com > "$CONHECIDOS" 2>/dev/null
  chown "$USUARIO_APP:$USUARIO_APP" "$CONHECIDOS"
fi

export GIT_SSH_COMMAND="ssh -i $CHAVE -o IdentitiesOnly=yes -o UserKnownHostsFile=$CONHECIDOS"
como_app() { sudo -u "$USUARIO_APP" env HOME="/home/$USUARIO_APP" \
             GIT_SSH_COMMAND="$GIT_SSH_COMMAND" "$@"; }

if ! como_app git ls-remote "$REPO" &>/dev/null; then
  cat <<AVISO

  A VPS ainda não tem permissão de ler o repositório.

  1. Copie a chave pública abaixo (a linha inteira).
  2. Abra https://github.com/davioliveiraes/apex-reports/settings/keys
  3. "Add deploy key", cole, título "VPS Hostinger", NÃO marque write access.
  4. Rode este script de novo — ele continua de onde parou.

AVISO
  cat "$CHAVE.pub"
  echo
  exit 1
fi


passo "Código ($BRANCH)"
if [[ -d "$DESTINO/.git" ]]; then
  # A VPS é alvo de publicação, não área de trabalho: o que estiver alterado
  # lá dentro é descartado em favor do que está no GitHub.
  como_app git -C "$DESTINO" fetch --quiet origin "$BRANCH"
  como_app git -C "$DESTINO" reset --hard --quiet "origin/$BRANCH"
else
  install -d -m 755 -o "$USUARIO_APP" -g "$USUARIO_APP" "$DESTINO"
  como_app git clone --quiet --branch "$BRANCH" "$REPO" "$DESTINO"
fi
echo "  $(como_app git -C "$DESTINO" log -1 --format='%h %s')"


passo "Dependências Python"
[[ -x "$DESTINO/venv/bin/python" ]] || como_app python3 -m venv "$DESTINO/venv"
como_app "$DESTINO/venv/bin/pip" install --quiet --upgrade pip
como_app "$DESTINO/venv/bin/pip" install --quiet -r "$DESTINO/requirements.txt"


passo "Configuração do Django"
if [[ -f "$AMBIENTE" ]]; then
  SEGREDO=$(sed -n 's/^DJANGO_SECRET_KEY=//p' "$AMBIENTE")
else
  # token_urlsafe em vez do gerador do Django: o EnvironmentFile do systemd não
  # interpreta aspas nem escapes, e o alfabeto do Django tem $ # & ( ).
  SEGREDO=$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')
fi
HOSTS="$IP,localhost,127.0.0.1"
cat > "$AMBIENTE" <<EOF
DJANGO_SECRET_KEY=$SEGREDO
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=$HOSTS
EOF
chown root:"$USUARIO_APP" "$AMBIENTE"
chmod 640 "$AMBIENTE"

manage() { como_app env DJANGO_SECRET_KEY="$SEGREDO" DJANGO_DEBUG=0 \
           DJANGO_ALLOWED_HOSTS="$HOSTS" \
           "$DESTINO/venv/bin/python" "$DESTINO/manage.py" "$@"; }
# O app não tem modelos próprios, mas a sessão que liga a importação à tela de
# revisão é gravada no banco — sem migrate o segundo passo do fluxo quebra.
manage migrate --noinput >/dev/null
manage collectstatic --noinput --clear >/dev/null
echo "  banco e estáticos prontos"


passo "Serviço systemd"
cat > "/etc/systemd/system/${SERVICO}.service" <<EOF
[Unit]
Description=Apex Reports (gunicorn)
After=network.target

[Service]
User=$USUARIO_APP
Group=$USUARIO_APP
WorkingDirectory=$DESTINO
EnvironmentFile=$AMBIENTE
# Cache de fontes do matplotlib; sem isso ele reconstrói o índice a cada start.
CacheDirectory=$SERVICO
Environment=MPLCONFIGDIR=/var/cache/$SERVICO
# workers sync, sem threads: o matplotlib usa estado global no pyplot e dois
# gráficos desenhados ao mesmo tempo no mesmo processo se atrapalham.
# timeout alto porque gerar 20 contas com gráfico passa dos 30s padrão.
# preload: os 3 workers compartilham a memória do matplotlib/weasyprint.
ExecStart=$DESTINO/venv/bin/gunicorn apex_reports.wsgi:application \\
  --bind $PORTA_APP --workers 3 --timeout 180 --preload \\
  --access-logfile - --error-logfile -
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --quiet "$SERVICO"
systemctl restart "$SERVICO"


passo "Senha do painel"
GERADA=""
if [[ -n "$SENHA" ]]; then
  htpasswd -bc "$HTPASSWD" "$USUARIO_PAINEL" "$SENHA" >/dev/null 2>&1
elif [[ ! -f "$HTPASSWD" ]]; then
  SENHA=$(python3 -c 'import secrets; print(secrets.token_urlsafe(9))')
  htpasswd -bc "$HTPASSWD" "$USUARIO_PAINEL" "$SENHA" >/dev/null 2>&1
  GERADA=1
fi
chown root:www-data "$HTPASSWD"
chmod 640 "$HTPASSWD"


passo "nginx"
cat > "/etc/nginx/sites-available/$SERVICO" <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    # 20 planilhas de uma vez cabem folgado aqui.
    client_max_body_size 64M;

    auth_basic "Apex Reports";
    auth_basic_user_file $HTPASSWD;

    location /static/ {
        alias $DESTINO/staticfiles/;
        access_log off;
        expires 7d;
    }

    location / {
        proxy_pass http://$PORTA_APP;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        # a geração do PDF é síncrona e pode demorar; o nginx precisa esperar
        # tanto quanto o gunicorn antes de desistir.
        proxy_read_timeout 180s;
        proxy_send_timeout 180s;
        # sem buffer o download do PDF começa assim que o Django despacha.
        proxy_buffering off;
    }
}
EOF
ln -sf "/etc/nginx/sites-available/$SERVICO" "/etc/nginx/sites-enabled/$SERVICO"
rm -f /etc/nginx/sites-enabled/default   # senão dois default_server conflitam
nginx -t || { echo "configuração do nginx recusada — nada foi recarregado" >&2; exit 1; }
systemctl reload nginx


passo "Firewall"
# Lê a porta real do sshd antes de ligar o ufw — se você tiver mudado o SSH de
# porta, liberar só o perfil OpenSSH te trancaria para fora.
PORTA_SSH=$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}' || true)
ufw allow "${PORTA_SSH:-22}/tcp" >/dev/null
ufw allow 80/tcp >/dev/null
ufw --force enable >/dev/null


passo "Conferência"
sleep 2
codigo() { curl -s -o /dev/null -m 10 -w '%{http_code}' "$1" || echo 000; }
# Direto no gunicorn: 200 prova que o Django subiu. Pelo nginx sem senha: 401
# prova que a porta 80 está no ar E que a proteção está valendo.
APP=$(codigo "http://$PORTA_APP/")
WEB=$(codigo "http://127.0.0.1/")
ok() { [[ "$1" == "$2" ]] && echo "✓" || echo "✗ (esperado $2)"; }
echo "  Django no gunicorn ... HTTP $APP $(ok "$APP" 200)"
echo "  nginx com senha ..... HTTP $WEB $(ok "$WEB" 401)"

cat <<FIM

────────────────────────────────────────────────────────────
  Apex Reports no ar:  http://$IP
  Usuário: $USUARIO_PAINEL
FIM
if [[ -n "$GERADA" ]]; then
  echo "  Senha:   $SENHA      ← anote agora, não aparece de novo"
elif [[ -n "$SENHA" ]]; then
  echo "  Senha:   (a que você passou em --senha)"
else
  echo "  Senha:   (a mesma de antes; troque com --senha 'nova')"
fi
cat <<FIM

  Publicar uma versão nova:  sudo $DESTINO/deploy/deploy.sh
  Ver os logs:               sudo journalctl -u $SERVICO -f
  Reiniciar:                 sudo systemctl restart $SERVICO

  Sem domínio não há HTTPS: o tráfego entre o navegador e a VPS vai em
  texto puro. A senha impede o uso por terceiros, mas não criptografa.
────────────────────────────────────────────────────────────
FIM
