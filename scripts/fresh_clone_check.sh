#!/usr/bin/env bash
set -u

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/tickwatch-fresh-clone.XXXXXX")"
clone_dir="$temp_dir/repo"
server_pid=""
passed=0
failed=0
port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
base_url="http://127.0.0.1:$port"

record_pass() {
  printf 'PASS | %s\n' "$1"
  passed=$((passed + 1))
}

record_fail() {
  printf 'FAIL | %s\n' "$1"
  failed=$((failed + 1))
}

stop_tree() {
  local parent="$1"
  local child
  for child in $(pgrep -P "$parent" 2>/dev/null || true); do
    stop_tree "$child"
  done
  kill "$parent" 2>/dev/null || true
}

cleanup() {
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
    stop_tree "$server_pid"
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf "$temp_dir"
}
trap cleanup EXIT INT TERM

run_logged_step() {
  local label="$1"
  shift
  local log_file="$temp_dir/step-$((passed + failed + 1)).log"
  if (cd "$clone_dir" && "$@") >"$log_file" 2>&1; then
    record_pass "$label"
  else
    record_fail "$label"
    tail -n 8 "$log_file"
  fi
}

if git clone --quiet "$repo_root" "$clone_dir" >"$temp_dir/clone.log" 2>&1; then
  record_pass "clone repository from local path"
else
  record_fail "clone repository from local path"
  cat "$temp_dir/clone.log"
  printf 'Summary: %s passed, %s failed\n' "$passed" "$failed"
  exit 1
fi

run_logged_step "uv sync --extra dev" uv sync --extra dev
run_logged_step "make lint" make lint
run_logged_step "make test" make test
run_logged_step "make ingest" make ingest

(
  cd "$clone_dir"
  TICKWATCH_PORT="$port" make run >"$temp_dir/server.log" 2>&1
) &
server_pid=$!
server_ready=0
for _ in $(seq 1 30); do
  status="$(curl -sS --max-time 2 -o /dev/null -w '%{http_code}' "$base_url/health" 2>/dev/null || true)"
  if [[ "$status" == "200" ]]; then
    server_ready=1
    break
  fi
  sleep 1
done
if [[ "$server_ready" == "1" ]]; then
  record_pass "start server with make run"
else
  record_fail "start server with make run"
  tail -n 12 "$temp_dir/server.log"
fi

check_endpoint() {
  local path="$1"
  local status
  status="$(curl -sS --max-time 8 -o /dev/null -w '%{http_code}' "$base_url$path" 2>/dev/null || true)"
  if [[ "$status" == "200" ]]; then
    record_pass "GET $path returns 200"
  else
    record_fail "GET $path returned $status, expected 200"
  fi
}

if [[ "$server_ready" == "1" ]]; then
  check_endpoint "/health"
  check_endpoint "/sightings?region=Manchester&limit=1"
  check_endpoint "/sightings/02WNholuSg6ndCk4c1dA"
  check_endpoint "/analytics/by-region?species=Marsh%20tick"
  check_endpoint "/analytics/by-species"
  check_endpoint "/analytics/trends?granularity=monthly&region=Manchester"
  check_endpoint "/insights/anomalies?region=Manchester"
  check_endpoint "/insights/forecast?region=Manchester"
  check_endpoint "/insights/seasonality?city=Manchester&species=Marsh%20tick"
else
  record_fail "endpoint curls skipped because the server did not start"
fi

stop_tree "$server_pid"
wait "$server_pid" 2>/dev/null || true
server_pid=""
stopped_status="$(curl -sS --max-time 2 -o /dev/null -w '%{http_code}' "$base_url/health" 2>/dev/null || true)"
if [[ "$stopped_status" != "200" ]]; then
  record_pass "stop server"
else
  record_fail "stop server (health endpoint still responds)"
fi

printf 'Summary: %s passed, %s failed\n' "$passed" "$failed"
[[ "$failed" == "0" ]]
