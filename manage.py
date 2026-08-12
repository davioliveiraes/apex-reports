#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'apex_reports.settings')
    # Este arquivo é a porta de entrada do DESENVOLVIMENTO — produção sobe por
    # `gunicorn apex_reports.wsgi`, que nunca passa por aqui. Por isso é aqui
    # que o modo de desenvolvimento é ligado, e não no settings: lá o padrão é
    # produção, para que um env faltando derrube a aplicação em vez de a
    # publicar com DEBUG e a chave de exemplo. `setdefault` e não atribuição —
    # o deploy chama `manage.py migrate` com as variáveis de produção
    # explícitas, e são elas que valem.
    os.environ.setdefault('DJANGO_DEBUG', '1')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
