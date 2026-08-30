#!/usr/bin/env bash
#
# nomado-workspace-init.sh — разворачивает workspace агента маркетплейсов
# из шаблона examples/nomado-workspace/.
#
# Идемпотентен: существующие файлы не перезаписываются (нужно — передайте --force).
# Ничего не запускает и не трогает systemd — только создаёт каталоги и файлы.
#
# Запуск на сервере:
#   ./scripts/nomado-workspace-init.sh
#   ./scripts/nomado-workspace-init.sh --agent nomado-market --lab-root ~/.claude-lab
#
set -euo pipefail

ROLE="market"
AGENT=""
LAB_ROOT="${HOME}/.claude-lab"
FORCE=0
DRY_RUN=0

usage() {
  cat <<'USAGE'
nomado-workspace-init.sh — развернуть workspace агента Номадо

  --role ROLE        market  — экономика, цены, сводки (по умолчанию)
                     content — визуал, карточки, отзывы и вопросы
  --agent NAME       имя агента (по умолчанию: nomado-<role>)
  --lab-root PATH    корень лаборатории (по умолчанию: ~/.claude-lab)
  --force            перезаписать существующие файлы шаблона
  --dry-run          показать, что было бы сделано, ничего не менять
  -h, --help         эта справка
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --role)     ROLE="${2:?--role требует значение}"; shift 2 ;;
    --agent)    AGENT="${2:?--agent требует значение}"; shift 2 ;;
    --lab-root) LAB_ROOT="${2:?--lab-root требует значение}"; shift 2 ;;
    --force)    FORCE=1; shift ;;
    --dry-run)  DRY_RUN=1; shift ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "неизвестный аргумент: $1" >&2; usage >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

case "$ROLE" in
  market)  TEMPLATE="${SCRIPT_DIR}/../examples/nomado-workspace" ;;
  content) TEMPLATE="${SCRIPT_DIR}/../examples/nomado-content-workspace" ;;
  *) echo "неизвестная роль: $ROLE (ожидается market или content)" >&2; exit 2 ;;
esac

: "${AGENT:=nomado-${ROLE}}"

if [[ ! -d "$TEMPLATE" ]]; then
  echo "шаблон не найден: $TEMPLATE" >&2
  exit 1
fi

WORKSPACE="${LAB_ROOT}/${AGENT}/.claude"
STATE_DIR="${LAB_ROOT}/shared/state/${AGENT}/telegram"
SECRETS_DIR="${LAB_ROOT}/${AGENT}/secrets"

# В dry-run выполнение подавляется; что именно было бы создано, показывают
# маркеры "+" (создать) и "=" (уже есть) ниже.
run() {
  (( DRY_RUN )) && return 0
  "$@"
}

# Копирует файл шаблона, не затирая уже существующий (без --force).
install_file() {
  local src="$1" dst="$2"
  if [[ -e "$dst" && $FORCE -eq 0 ]]; then
    echo "  = пропуск (уже есть): ${dst#"$HOME"/}"
    return
  fi
  run mkdir -p "$(dirname "$dst")"
  run cp "$src" "$dst"
  echo "  + ${dst#"$HOME"/}"
}

echo "Номадо · workspace агента"
echo "  роль:      ${ROLE}"
echo "  агент:     ${AGENT}"
echo "  workspace: ${WORKSPACE}"
(( DRY_RUN )) && echo "  режим:     dry-run, изменений не будет"
echo

echo "Каталоги:"
for dir in "$WORKSPACE" "$WORKSPACE/core/hot" "$WORKSPACE/data" "$STATE_DIR" "$SECRETS_DIR"; do
  if [[ -d "$dir" ]]; then
    echo "  = ${dir#"$HOME"/}"
  else
    run mkdir -p "$dir"
    echo "  + ${dir#"$HOME"/}"
  fi
done
run chmod 700 "$SECRETS_DIR"

echo
echo "Файлы workspace:"
# Обходим шаблон целиком: добавленный в него файл подхватится без правки скрипта.
# channel.env.example исключён — он уезжает в secrets/, не в workspace.
while IFS= read -r rel; do
  install_file "${TEMPLATE}/${rel}" "${WORKSPACE}/${rel}"
done < <(cd "$TEMPLATE" && find . -type f ! -name 'channel.env.example' -printf '%P\n' | sort)

echo
echo "Секреты:"
ENV_DST="${SECRETS_DIR}/channel.env"
install_file "${TEMPLATE}/channel.env.example" "$ENV_DST"
if [[ -e "$ENV_DST" ]] && ! (( DRY_RUN )); then
  chmod 600 "$ENV_DST"
fi

cat <<NEXT

Готово. Дальше:

  1. Впишите токен бота и свой user_id:
       \$EDITOR ${ENV_DST}
  2. Заполните ставки комиссий по своим категориям:
       \$EDITOR ${WORKSPACE}/core/unit-economics.md
  3. Проверьте, что порт TELEGRAM_WEBHOOK_PORT не занят другим агентом:
       ss -ltnp | grep -E ':(8089|8090|8091)'
  4. Запуск вручную (проверка перед systemd):
       cd <путь к плагину>/plugin
       set -a; . ${ENV_DST}; set +a
       claude --dangerously-load-development-channels server:dashi-channel

Автозапуск через systemd — examples/systemd-unit.service.example,
подробности в docs/03-installation-linux.md.
NEXT
