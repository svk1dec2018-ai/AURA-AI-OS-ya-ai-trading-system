#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_path="${repo_root}/.venv/bin/python"
template="${repo_root}/deploy/systemd/aura-paper.service.in"
unit_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
unit_path="${unit_dir}/aura-paper.service"

if [[ ! -x "${python_path}" ]]; then
  printf 'AURA virtual environment not found: %s\n' "${python_path}" >&2
  printf 'Create it and install AURA before installing the service.\n' >&2
  exit 1
fi

"${python_path}" "${repo_root}/examples/run_production_preflight.py" \
  --mode paper \
  --connector public \
  --runtime-dir "${repo_root}/runtime/free_public_autonomy"

mkdir -p "${unit_dir}" "${repo_root}/runtime/free_public_autonomy"
escaped_root="${repo_root//&/\\&}"
escaped_python="${python_path//&/\\&}"
sed \
  -e "s&@AURA_ROOT@&${escaped_root}&g" \
  -e "s&@AURA_PYTHON@&${escaped_python}&g" \
  "${template}" > "${unit_path}"

systemctl --user daemon-reload
systemctl --user enable --now aura-paper.service
printf 'AURA paper service installed: %s\n' "${unit_path}"
printf 'Status: systemctl --user status aura-paper.service\n'
printf 'Logs:   journalctl --user -u aura-paper.service -f\n'
