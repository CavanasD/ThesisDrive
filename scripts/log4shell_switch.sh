#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# ThesisDrive · Log4Shell 插拔开关
#
# 用法：
#   ./log4shell_switch.sh status          # 查看当前开关与 JVM 参数
#   ./log4shell_switch.sh on              # 开启 → 真实 RCE
#   ./log4shell_switch.sh off             # 关闭 → JDK 21 默认（安全）
#   ./log4shell_switch.sh on --recreate   # 开启并重建 security-gateway
#
# 原理：
#   compose.yaml 读取的是 LOG4SHELL_TRUST_CODEBASE_ARMED，该变量
#   只在 LOG4SHELL_TRUST_CODEBASE 的字面值恰为 true 时才非空。
#   这样 .env 里写 false / 空 / 未定义都不会误开。
#
#   ARMED 非空 → JVM 注入 -Dcom.sun.jndi.ldap.object.trustURLCodebase=true
#
# ⚠️ 开启后，任何能访问 POST /api/log4shell 的人都可以在
#    security-gateway 容器内执行任意命令（该端点在 SecurityConfig
#    中为 permitAll，公网可达且无 WAF 覆盖）。
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="/root/Yulin2026/thesis"
ENV_FILE="${PROJECT_DIR}/.env"
SERVICE="security-gateway"
CONTAINER="thesis-drive-security-gateway-1"

cd "${PROJECT_DIR}"

red()  { printf '\033[31m%s\033[0m\n' "$*"; }
grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
yel()  { printf '\033[33m%s\033[0m\n' "$*"; }
cyn()  { printf '\033[36m%s\033[0m\n' "$*"; }
dim()  { printf '\033[2m%s\033[0m\n' "$*"; }

# ── 读取 .env 中 LOG4SHELL_TRUST_CODEBASE 的字面值 ──────────────────
current_value() {
  grep -E '^LOG4SHELL_TRUST_CODEBASE=' "${ENV_FILE}" \
    | tail -1 | cut -d= -f2- | tr -d ' \r'
}

# ── 归一化：只有字面 true 才算 armed ────────────────────────────────
armed_from() {
  local v
  v="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  if [ "${v}" = "true" ]; then printf 'yes'; else printf ''; fi
}

# ── 写入 .env（保留注释块，只改值行）────────────────────────────────
write_value() {
  local newval="$1"
  if grep -qE '^LOG4SHELL_TRUST_CODEBASE=' "${ENV_FILE}"; then
    sed -i "s|^LOG4SHELL_TRUST_CODEBASE=.*|LOG4SHELL_TRUST_CODEBASE=${newval}|" "${ENV_FILE}"
  else
    printf '\nLOG4SHELL_TRUST_CODEBASE=%s\n' "${newval}" >> "${ENV_FILE}"
  fi
}

# ── 导出的 ARMED 值 ────────────────────────────────────────────────
armed_env_export() {
  local v armed
  v="$(current_value)"
  armed="$(armed_from "${v}")"
  export LOG4SHELL_TRUST_CODEBASE_ARMED="${armed}"
}

cmd_status() {
  local v armed
  v="$(current_value || true)"
  armed="$(armed_from "${v:-}")"

  echo
  cyn "── Log4Shell 插拔开关状态 ──────────────────────────────"
  printf '  .env  LOG4SHELL_TRUST_CODEBASE = %s\n' "${v:-<未定义>}"
  if [ -n "${armed}" ]; then
    red "  归一化 ARMED                   = yes"
    red "  关卡状态                       = 真实 RCE（危险）"
  else
    grn "  归一化 ARMED                   = (空)"
    grn "  关卡状态                       = 仅验证注入点（安全）"
  fi

  echo
  dim "  ── 容器内实际 JVM 参数 ──"
  if docker inspect "${CONTAINER}" >/dev/null 2>&1; then
    local jto
    jto="$(docker exec "${CONTAINER}" sh -c 'printf "%s" "${JAVA_TOOL_OPTIONS:-}"' 2>/dev/null || true)"
    printf '  JAVA_TOOL_OPTIONS = %s\n' "${jto:-<未设置>}"
    if printf '%s' "${jto}" | grep -q 'trustURLCodebase=true'; then
      red "  → JVM 已信任远程 codebase：远程类可被加载执行"
    else
      grn "  → JVM 保持 JDK 21 默认：远程类不会被加载"
    fi
  else
    yel "  容器 ${CONTAINER} 不存在"
  fi

  echo
  dim "  ── 相关 env ──"
  printf '  VULN_LOG4SHELL_ENABLED = %s  (决定端点是否走真 JNDI 分支)\n' \
    "$(grep -E '^VULN_LOG4SHELL_ENABLED=' "${ENV_FILE}" | tail -1 | cut -d= -f2- || echo '<未定义>')"
  echo
}

cmd_set() {
  local want="$1"; shift
  local rebuild="${1:-}"

  write_value "${want}"

  echo
  if [ "${want}" = "true" ]; then
    red "  ⚠ 已开启 LOG4SHELL_TRUST_CODEBASE=true"
    red "    /api/log4shell 将成为真实 RCE 端点（permitAll + 公网可达 + 无 WAF）"
    red "    仅限隔离教学靶场。"
  else
    grn "  已关闭 LOG4SHELL_TRUST_CODEBASE=${want}"
    grn "    网关只完成 JNDI 查询与 LDAP 回连，不加载远程类。"
  fi

  if [ "${rebuild}" = "--recreate" ]; then
    armed_env_export
    echo
    cyn "  重建 ${SERVICE} …"
    docker compose --env-file "${ENV_FILE}" up -d --no-deps --force-recreate "${SERVICE}"
    echo
    cyn "  等待健康检查 …"
    for _ in $(seq 1 40); do
      st="$(docker inspect -f '{{.State.Health.Status}}' "${CONTAINER}" 2>/dev/null || echo unknown)"
      [ "${st}" = "healthy" ] && break
      sleep 3
    done
    echo
    cmd_status
  else
    echo
    yel "  配置已写入，但需重建容器才生效："
    dim "    $(basename "$0") ${want} --recreate"
    echo
  fi
}

case "${1:-status}" in
  on|true|enable)   cmd_set true "${2:-}" ;;
  off|false|disable) cmd_set false "${2:-}" ;;
  status|"")        cmd_status ;;
  *)
    echo "用法: $0 {status|on|off} [--recreate]" >&2
    exit 2
    ;;
esac
