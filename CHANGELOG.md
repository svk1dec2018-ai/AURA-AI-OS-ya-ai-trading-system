# Changelog

Notable changes to AURA AI OS are recorded here.

## Unreleased

### Hardening
- add real process-level backend/dashboard/Redis/fleet CI smoke tests
- add Windows MetaTrader5 import and PowerShell syntax/startup smoke checks
- make the Windows production launcher keep diagnostics available when optional fleet dependencies degrade
- make the fleet launcher start/wait for Docker Desktop when possible

### Dashboard
- professional grouped terminal navigation
- chart-first workstation hierarchy with larger readable market data
- explicit core/MT5/engine/fleet health status
- actionable degraded-mode diagnostics
- TradingView Lightweight Charts attribution

### Repository
- contribution, ownership, issue and pull-request standards
- dashboard design research and canonical repository guide

## 2026-09-19

- canonical Windows production setup/configure/start/doctor/stop workflow
- Redis Streams nine-service fleet with supervisor and SSE dashboard feed
- protected MT5 DEMO readiness and no-send execution checks
- hermetic test setup separated from runtime AI configuration
- optional local Ollama balanced-five free/unmetered AI installer
