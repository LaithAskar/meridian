#!/usr/bin/env bash
# Job-scoped external-egress boundary for GitHub's disposable Ubuntu runner.
# Run as root after dependency installation. Loopback and established runner
# control connections remain available; new external IPv4/IPv6 traffic is
# rejected for the runner UID until `disable` or VM teardown.
set -Eeuo pipefail

CHAIN=MERIDIAN_EGRESS
TARGET_UID=${MERIDIAN_EGRESS_UID:-${SUDO_UID:-}}

require_target_uid() {
  [[ $TARGET_UID =~ ^[0-9]+$ ]] || {
    echo "set MERIDIAN_EGRESS_UID or invoke through sudo so SUDO_UID identifies the runner user" >&2
    exit 2
  }
  [[ $TARGET_UID -ne 0 ]] || {
    echo "refusing to apply the job egress guard to uid 0" >&2
    exit 2
  }
}

ipt() {
  local family=$1
  shift
  if [[ $family == 4 ]]; then
    iptables -w "$@"
  else
    ip6tables -w "$@"
  fi
}

disable_family() {
  local family=$1
  while ipt "$family" -C OUTPUT -m owner --uid-owner "$TARGET_UID" -j "$CHAIN" 2>/dev/null; do
    ipt "$family" -D OUTPUT -m owner --uid-owner "$TARGET_UID" -j "$CHAIN"
  done
  ipt "$family" -F "$CHAIN" 2>/dev/null || true
  ipt "$family" -X "$CHAIN" 2>/dev/null || true
}

enable_family() {
  local family=$1 reject
  disable_family "$family"
  ipt "$family" -N "$CHAIN"
  ipt "$family" -A "$CHAIN" -o lo -j RETURN
  ipt "$family" -A "$CHAIN" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
  if [[ $family == 4 ]]; then
    reject=icmp-port-unreachable
  else
    reject=icmp6-port-unreachable
  fi
  ipt "$family" -A "$CHAIN" -j REJECT --reject-with "$reject"
  ipt "$family" -I OUTPUT 1 -m owner --uid-owner "$TARGET_UID" -j "$CHAIN"
}

rollback_enable() {
  trap - ERR
  disable_family 4 || true
  disable_family 6 || true
}

case "${1:-}" in
  enable)
    [[ ${EUID} -eq 0 ]] || { echo "egress guard must run as root" >&2; exit 2; }
    require_target_uid
    trap rollback_enable ERR
    enable_family 4
    enable_family 6
    trap - ERR
    ;;
  disable)
    [[ ${EUID} -eq 0 ]] || { echo "egress guard must run as root" >&2; exit 2; }
    require_target_uid
    disable_family 4
    disable_family 6
    ;;
  status)
    require_target_uid
    ipt 4 -C OUTPUT -m owner --uid-owner "$TARGET_UID" -j "$CHAIN"
    ipt 6 -C OUTPUT -m owner --uid-owner "$TARGET_UID" -j "$CHAIN"
    ;;
  *)
    echo "usage: $0 {enable|disable|status}" >&2
    exit 2
    ;;
esac
