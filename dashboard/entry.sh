#!/usr/bin/env bash
#
# entry.sh - Arranca el stack completo del dashboard "Air Majoro":
#
#   1. Evidence   (evidence dev --port 4001)     -> backend del informe
#   2. Proxy      (node proxy/proxy.mjs :4000)   -> delante de Evidence
#   3. Túnel inverso (autossh -R 8081:localhost:4000 server@51.38.243.200 -N)
#
# El proxy escucha en :4000 y reenvía a Evidence (:4001). El túnel inverso
# publica el proxy en el servidor remoto (puerto 8081 -> localhost:4000).
#
# Uso:
#   ./entry.sh
#
# Variables de entorno opcionales (con sus valores por defecto):
#   EVIDENCE_PORT=4001   PROXY_PORT=4000   REMOTE_PORT=8081
#   REMOTE_HOST=server@51.38.243.200
#   EVIDENCE_LOG=/tmp/aim-evidence.log  PROXY_LOG=/tmp/aim-proxy.log
#   AUTOSSH_LOG=$HOME/autossh.log
#
set -euo pipefail

# --- Rutas y parámetros ---------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

EVIDENCE_PORT="${EVIDENCE_PORT:-4001}"
PROXY_PORT="${PROXY_PORT:-4000}"
REMOTE_PORT="${REMOTE_PORT:-8081}"
REMOTE_HOST="${REMOTE_HOST:-server@51.38.243.200}"

EVIDENCE_LOG="${EVIDENCE_LOG:-/tmp/aim-evidence.log}"
PROXY_LOG="${PROXY_LOG:-/tmp/aim-proxy.log}"
AUTOSSH_LOG="${AUTOSSH_LOG:-$HOME/autossh.log}"

PROXY_ENTRY="$SCRIPT_DIR/proxy/proxy.mjs"
READY_TIMEOUT="${READY_TIMEOUT:-60}" # segundos de espera máxima por cada puerto

# --- Utilidades -----------------------------------------------------------
log()  { printf '[entry] %s\n' "$*"; }
die()  { printf '[entry] ERROR: %s\n' "$*" >&2; exit 1; }

# Espera activa hasta que el puerto responda con cualquier respuesta HTTP.
wait_for_port() {
	local port="$1" timeout="$2" waited=0
	while (( waited < timeout )); do
		if curl -s -o /dev/null --max-time 2 "http://localhost:${port}/"; then
			return 0
		fi
		sleep 1
		waited=$((waited + 1))
	done
	return 1
}

# --- 0. Comprobaciones previas -------------------------------------------
command -v evidence >/dev/null 2>&1 || die "no se encontró el CLI 'evidence' en el PATH"
command -v node     >/dev/null 2>&1 || die "no se encontró 'node' en el PATH"
command -v autossh  >/dev/null 2>&1 || die "no se encontró 'autossh' en el PATH (sudo apt install autossh)"
command -v curl     >/dev/null 2>&1 || die "no se encontró 'curl' en el PATH"
[[ -f "$PROXY_ENTRY" ]] || die "no existe $PROXY_ENTRY"

# --- 1. Parar instancias previas -----------------------------------------
log "Deteniendo procesos previos (evidence, proxy, autossh)..."
pkill -f "evidence dev"          2>/dev/null || true
pkill -f "proxy/proxy.mjs"       2>/dev/null || true
pkill -f "autossh"               2>/dev/null || true
pkill -f "ssh -R ${REMOTE_PORT}" 2>/dev/null || true
sleep 2

# --- 2. Arrancar Evidence -------------------------------------------------
log "Arrancando Evidence en :${EVIDENCE_PORT} (log: ${EVIDENCE_LOG})..."
setsid nohup evidence dev --port "$EVIDENCE_PORT" \
	> "$EVIDENCE_LOG" 2>&1 < /dev/null &

if wait_for_port "$EVIDENCE_PORT" "$READY_TIMEOUT"; then
	log "Evidence listo en http://localhost:${EVIDENCE_PORT}"
else
	log "AVISO: Evidence no respondió en ${READY_TIMEOUT}s; revisa ${EVIDENCE_LOG}"
fi

# --- 3. Arrancar el proxy -------------------------------------------------
log "Arrancando el proxy en :${PROXY_PORT} -> Evidence :${EVIDENCE_PORT} (log: ${PROXY_LOG})..."
PORT="$PROXY_PORT" UPSTREAM_PORT="$EVIDENCE_PORT" \
	setsid nohup node "$PROXY_ENTRY" \
	> "$PROXY_LOG" 2>&1 < /dev/null &

if wait_for_port "$PROXY_PORT" "$READY_TIMEOUT"; then
	log "Proxy listo en http://localhost:${PROXY_PORT}"
else
	log "AVISO: el proxy no respondió en ${READY_TIMEOUT}s; revisa ${PROXY_LOG}"
fi

# --- 4. Túnel inverso con autossh ----------------------------------------
log "Estableciendo túnel inverso: remoto :${REMOTE_PORT} -> localhost:${PROXY_PORT} (log: ${AUTOSSH_LOG})..."
nohup autossh -M 0 \
	-o "ServerAliveInterval 30" \
	-o "ServerAliveCountMax 3" \
	-o "ExitOnForwardFailure yes" \
	-R "${REMOTE_PORT}:localhost:${PROXY_PORT}" \
	"$REMOTE_HOST" -N \
	> "$AUTOSSH_LOG" 2>&1 &

sleep 3
if pgrep -f "autossh" >/dev/null 2>&1; then
	log "Túnel autossh activo."
else
	log "AVISO: autossh no parece estar corriendo; revisa ${AUTOSSH_LOG}"
fi

# --- 5. Resumen -----------------------------------------------------------
log "Stack arrancado:"
log "  Evidence local : http://localhost:${EVIDENCE_PORT}"
log "  Proxy local    : http://localhost:${PROXY_PORT}"
log "  Proxy remoto   : ${REMOTE_HOST} :${REMOTE_PORT}"
