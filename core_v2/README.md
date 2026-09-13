# Hermes Core v2

Primeira camada do Hermes local-first para a VPS.

Objetivos desta fase:
- manter inferencia local em llama.cpp;
- separar trabalho deterministico de raciocinio do LLM;
- consultar saude real da VPS via Python;
- preparar a base para tools, memoria, collectors e automacoes;
- continuar usando o Hermes/gateway atual enquanto o Core v2 evolui.

## Instalar/atualizar

Na VPS, dentro do repositorio:

```bash
git pull
chmod +x install-core-v2.sh
./install-core-v2.sh
```

## Testar

```bash
~/.hermes/core-v2/venv/bin/python ~/.hermes/core-v2/hermes_core.py "status da vps"
```

Modo interativo:

```bash
~/.hermes/core-v2/venv/bin/python ~/.hermes/core-v2/hermes_core.py
```

O arquivo `~/.hermes/core-v2/config.yaml` e preservado entre atualizacoes.
