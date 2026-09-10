#!/usr/bin/env bash
# 发布闸门：这个仓是公开的，跑一遍确认没把私有基础设施 / 凭证 / 别人的内容带出来。
# 命中任何一条即 exit 1。CI 和打 tag 前都跑。
set -uo pipefail
cd "$(dirname "$0")/.."

# 二进制（字体）不参与扫描，否则会命中随机字节。
EXCLUDE=(--exclude-dir=.git --exclude=*.ttf --exclude=*.otf --exclude=check-no-secrets.sh)

fail=0
hit() {  # hit <说明> <正则>
  local desc="$1" pat="$2" out
  out=$(grep -rInE "${EXCLUDE[@]}" -- "$pat" . 2>/dev/null || true)
  if [ -n "$out" ]; then
    echo "✗ $desc"
    echo "$out" | sed 's/^/    /'
    fail=1
  fi
}

# 私有 SSH 别名 / 主机
hit "私有主机名"        '\b(tserver|lbot-(pvg[0-9]+|useast))\b'
# 私有域名与云资源
hit "私有域名/桶"       '(kexiaoyu\.com|radar-assets)'
# 本机绝对路径
hit "本机绝对路径"      '(/Volumes/4TB-SD|/Users/[a-z]+/(Projects|repos)/)'
# 凭证形状。BBDown.data 只允许作为路径名出现，不允许出现文件内容里的 cookie 字段。
hit "疑似 API key"      'sk-[0-9a-zA-Z]{8,}'
# 只抓「字段名 = 一串足够长的值」这种真泄漏形态。裸的 `SESSDATA=` 会出现在
# 校验代码和文档里（比如 `if "SESSDATA=" in text`），那不是泄漏，不能算。
hit "B站登录态明文"     '(SESSDATA|bili_jct|DedeUserID)=[A-Za-z0-9%._-]{16,}'
hit "Cloudflare 标识"   '\b[0-9a-f]{32}\b'

if [ "$fail" = 0 ]; then
  echo "✓ 无命中，可以发布"
fi
exit $fail
