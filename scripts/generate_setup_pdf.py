from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "AURA_SETUP_AND_OPERATIONS.pdf"

NAVY = colors.HexColor("#0B132B")
BLUE = colors.HexColor("#1C5D99")
CYAN = colors.HexColor("#2EC4B6")
PALE = colors.HexColor("#EAF4F4")
LIGHT = colors.HexColor("#F5F7FA")
AMBER = colors.HexColor("#F4A261")
GREEN = colors.HexColor("#2A9D5B")
INK = colors.HexColor("#17202A")
MUTED = colors.HexColor("#5D6D7E")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=27,
            leading=31,
            textColor=colors.white,
            alignment=TA_LEFT,
            spaceAfter=10,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=12,
            leading=17,
            textColor=colors.HexColor("#D9EAF7"),
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=NAVY,
            spaceBefore=5,
            spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=16,
            textColor=BLUE,
            spaceBefore=8,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.3,
            leading=13.2,
            textColor=INK,
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.8,
            leading=10.5,
            textColor=INK,
        ),
        "small_white": ParagraphStyle(
            "SmallWhite",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.8,
            leading=10.5,
            textColor=colors.white,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.1,
            leading=13,
            leftIndent=12,
            firstLineIndent=-7,
            bulletIndent=2,
            textColor=INK,
            spaceAfter=4,
        ),
        "code": ParagraphStyle(
            "Code",
            parent=base["Code"],
            fontName="Courier",
            fontSize=7.4,
            leading=10.3,
            leftIndent=7,
            rightIndent=7,
            borderColor=colors.HexColor("#D5DBDB"),
            borderWidth=0.6,
            borderPadding=7,
            backColor=colors.HexColor("#F7F9F9"),
            textColor=colors.HexColor("#17202A"),
            spaceBefore=4,
            spaceAfter=8,
        ),
        "callout": ParagraphStyle(
            "Callout",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=13,
            leftIndent=8,
            rightIndent=8,
            borderColor=AMBER,
            borderWidth=1,
            borderPadding=8,
            backColor=colors.HexColor("#FFF6E9"),
            textColor=NAVY,
            spaceBefore=5,
            spaceAfter=9,
        ),
        "center": ParagraphStyle(
            "Center",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=INK,
            alignment=TA_CENTER,
        ),
    }


S = _styles()


class AuraDocument(BaseDocTemplate):
    def __init__(self, path: Path) -> None:
        super().__init__(
            str(path),
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=22 * mm,
            title="AURA AI OS Setup and Operations Guide",
            author="AURA AI OS Engineering",
            subject="Validated paper and demo research release setup",
        )
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="content",
        )
        self.addPageTemplates(PageTemplate(id="main", frames=[frame], onPage=_page_chrome))


def _page_chrome(canvas, doc) -> None:
    canvas.saveState()
    width, height = A4
    if doc.page == 1:
        canvas.setFillColor(NAVY)
        canvas.rect(0, 0, width, height, fill=1, stroke=0)
        canvas.setFillColor(CYAN)
        canvas.rect(0, height - 9 * mm, width, 9 * mm, fill=1, stroke=0)
    else:
        canvas.setStrokeColor(colors.HexColor("#D5DBDB"))
        canvas.line(18 * mm, height - 13 * mm, width - 18 * mm, height - 13 * mm)
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(BLUE)
        canvas.drawString(18 * mm, height - 10 * mm, "AURA AI OS - SETUP AND OPERATIONS")
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(width - 18 * mm, 9 * mm, f"Page {doc.page}")
        canvas.drawString(18 * mm, 9 * mm, "Paper/demo research release candidate - live money disabled")
    canvas.restoreState()


def p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def bullet(text: str) -> Paragraph:
    return Paragraph(f"- {text}", S["bullet"])


def code(text: str) -> Paragraph:
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
        .replace(" ", "&nbsp;")
    )
    return Paragraph(escaped, S["code"])


def status_table(rows: list[tuple[str, str, str]]) -> Table:
    data = [
        [
            p("Capability", "small_white"),
            p("Status", "small_white"),
            p("Evidence / note", "small_white"),
        ]
    ]
    for capability, status, note in rows:
        color = GREEN if status.startswith("READY") or status == "IMPLEMENTED" else AMBER
        data.append(
            [
                p(capability, "small"),
                Paragraph(f"<b><font color='{color.hexval()}'>{status}</font></b>", S["small"]),
                p(note, "small"),
            ]
        )
    table = Table(data, colWidths=[45 * mm, 32 * mm, 88 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D5DBDB")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def architecture_flow() -> Table:
    labels = [
        "Trusted data\n+ news / RAG",
        "10 specialists\n+ local AI council",
        "Bull / bear /\n+ counterfactual",
        "CEO evidence\n+ synthesis",
        "Independent\n+ Risk Engine",
        "Paper broker\n+ WAL / learning",
    ]
    cells = []
    for index, label in enumerate(labels):
        cells.append(p(label.replace("\n", "<br/>"), "center"))
        if index != len(labels) - 1:
            cells.append(p("-&gt;", "center"))
    widths = [25 * mm if index % 2 == 0 else 5 * mm for index in range(len(cells))]
    table = Table([cells], colWidths=widths, rowHeights=[24 * mm])
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]
    for index in range(0, len(cells), 2):
        style.extend(
            [
                ("BACKGROUND", (index, 0), (index, 0), PALE),
                ("BOX", (index, 0), (index, 0), 0.8, BLUE),
            ]
        )
    table.setStyle(TableStyle(style))
    return table


def build_story() -> list:
    return [
        Spacer(1, 45 * mm),
        p("AURA AI OS", "title"),
        p("Complete Setup, 24x7 Paper Service and Operations Guide", "title"),
        Spacer(1, 4 * mm),
        p(
            "Validated integrated release candidate for multi-agent intelligence, local AI, "
            "trusted knowledge, autonomous research, forward shadow learning and risk-first "
            "paper/demo operation.",
            "subtitle",
        ),
        Spacer(1, 15 * mm),
        Table(
            [
                [p("RELEASE CLASS", "small"), p("PAPER / DEMO RESEARCH CANDIDATE", "small_white")],
                [p("VALIDATION", "small"), p("407 LOCAL TESTS PASS; CI GATED", "small_white")],
                [p("LIVE MONEY", "small"), p("DISABLED BY DEFAULT", "small_white")],
                [p("PRIMARY START", "small"), p("START_AURA_OLLAMA.cmd", "small_white")],
            ],
            colWidths=[42 * mm, 105 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), CYAN),
                    ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#14213D")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#4B6584")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            ),
        ),
        Spacer(1, 18 * mm),
        p("Operator guide - generated from the validated AURA repository", "subtitle"),
        PageBreak(),
        p("1. What is included", "h1"),
        p(
            "AURA is not a single indicator bot. The integrated codebase separates intelligence "
            "from authority and uses a deterministic, auditable path for every decision."
        ),
        Spacer(1, 4 * mm),
        architecture_flow(),
        Spacer(1, 7 * mm),
        status_table(
            [
                ("Multi-market scanner", "IMPLEMENTED", "Closed-candle, multi-timeframe runtime foundations."),
                ("10 specialist roles", "IMPLEMENTED", "HTF, SMC/ICT, technical, volume, forecast, options, macro, cross-market, regime, execution."),
                ("Multi-model AI", "IMPLEMENTED", "Ollama council with bounded concurrency and structured evidence."),
                ("CEO + debate", "IMPLEMENTED", "Bull, bear and counterfactual review before deterministic synthesis."),
                ("Knowledge and news", "IMPLEMENTED", "Knowledge firewall, local authorized corpus, official feeds and GDELT."),
                ("Self-learning research", "IMPLEMENTED", "Shadow outcomes, missed opportunities, evolution and governed promotion."),
                ("Risk and accounting", "IMPLEMENTED", "Independent risk veto, paper broker, portfolio ledger, WAL and recovery."),
                ("Local voice", "IMPLEMENTED", "OS-native spoken alerts; no cloud key required."),
                ("Graphical dashboard", "PARTIAL", "Typed command center and status JSON exist; full GUI remains."),
                ("Telegram alerts", "DESTINATION GATE", "Outbound adapter and durable receipts exist; operator bot/chat validation required."),
                ("WhatsApp", "PENDING", "Supported provider, credentials and verified recipient are required."),
            ]
        ),
        p(
            "Safety boundary: AI may advise, explain and propose research. It cannot calculate "
            "financial quantities by guessing, bypass RiskEngine, approve itself, or enable live money.",
            "callout",
        ),
        PageBreak(),
        p("2. Choose the correct deployment", "h1"),
        status_table(
            [
                ("Windows one-click", "READY", "Best for local voice, Ollama and future MT5 demo use."),
                ("Windows background task", "READY", "Starts at user logon and restarts after failures."),
                ("Docker Compose", "READY", "Cross-platform 24x7 public-data service; voice is off inside container."),
                ("Linux systemd user service", "READY", "24x7 VPS/laptop paper research with persistent runtime state."),
                ("Dhan paper", "ACCOUNT GATE", "Requires user-owned Dhan credentials and eligible data access."),
                ("MT5 demo", "ACCOUNT GATE", "Requires Windows MT5 terminal and verified DEMO account."),
                ("Angel One", "READ-ONLY READY", "Account/quote/reconciliation adapter; order submit/cancel locked."),
                ("Live money", "BLOCKED", "Requires Phase 15, broker-origin forward evidence and human approval."),
            ]
        ),
        p("Recommended demonstration path", "h2"),
        bullet("Use Windows one-click when showing local Multi-AI plus voice."),
        bullet("Use Docker Compose or Linux systemd for unattended public-data shadow training."),
        bullet("Use Dhan, Angel One or MT5 only after the public stack is healthy and credentials stay outside Git."),
        p(
            "No setup mode in this guide sends live-money orders. Public autonomy sends no broker "
            "orders. Dhan self-evolution uses internal paper execution. Angel One execution is locked. "
            "MT5 must remain DEMO.",
            "callout",
        ),
        PageBreak(),
        p("3. Windows one-click setup", "h1"),
        p("Prerequisites", "h2"),
        bullet("Windows 10 or 11, 64-bit."),
        bullet("Python 3.11 or 3.12 with Add Python to PATH enabled."),
        bullet("Git, at least 30 GB free disk space, and stable internet."),
        bullet("Ollama installed and running. A 16 GB RAM system should start with one smaller model."),
        p("Install local AI models", "h2"),
        code(
            "ollama pull qwen3.5:4b\n"
            "ollama pull deepseek-r1:8b\n"
            "ollama pull llama3.1:8b\n"
            "ollama pull gemma3:4b\n"
            "ollama pull phi4-mini:3.8b"
        ),
        p(
            "The balanced preset is approximately 20 GB. If hardware is limited, pass an "
            "explicit smaller `-Models` list. Model names must exactly match `ollama list`."
        ),
        p("Clone and launch", "h2"),
        code(
            "git clone https://github.com/svk1dec2018-ai/AURA-AI-OS-ya-ai-trading-system.git\n"
            "cd AURA-AI-OS-ya-ai-trading-system\n"
            "git switch agent/client-paper-release-candidate\n"
            "START_AURA_OLLAMA.cmd"
        ),
        bullet("The first run creates `.venv`, installs dependencies and runs paper preflight."),
        bullet("It starts public data, history, news, the Multi-AI council and shadow strategy lab."),
        bullet("Voice announces shadow signals and states that no order was sent."),
        p("Custom PowerShell launch", "h2"),
        code(
            "powershell -ExecutionPolicy Bypass -File scripts/start_aura_ollama.ps1 `\n"
            "  -Models qwen3.5:4b,gemma3:4b -Provider coinbase -Timeframe 5s"
        ),
        PageBreak(),
        p("4. Windows background service-like mode", "h1"),
        p(
            "Windows Task Scheduler starts at logon, restarts after failure and avoids turning "
            "AURA into an unsafe privileged Windows service."
        ),
        p("Step 1 - complete one foreground run", "h2"),
        code("START_AURA_OLLAMA.cmd"),
        p("Step 2 - install and start the task", "h2"),
        code(
            "powershell -ExecutionPolicy Bypass -File `\n"
            "  scripts/install_aura_windows_task.ps1 -StartNow"
        ),
        p("Operations", "h2"),
        code(
            "Get-ScheduledTask -TaskName 'AURA AI OS Paper Research'\n"
            "Start-ScheduledTask -TaskName 'AURA AI OS Paper Research'\n"
            "Stop-ScheduledTask -TaskName 'AURA AI OS Paper Research'\n"
            "Unregister-ScheduledTask -TaskName 'AURA AI OS Paper Research'"
        ),
        bullet("Keep Ollama configured to start with Windows."),
        bullet("The background task disables voice to avoid speech from a hidden session."),
        bullet("Research state persists in `runtime/free_public_autonomy`. Back up this folder."),
        p(
            "The task runs with the current user at limited privilege. It receives no live "
            "approval variable or broker credential from the installer.",
            "callout",
        ),
        PageBreak(),
        p("5. Docker Compose 24x7 setup", "h1"),
        p("Start Ollama on the host, then build AURA", "h2"),
        code(
            "docker compose -f compose.paper.yml up -d --build\n"
            "docker compose -f compose.paper.yml ps\n"
            "docker compose -f compose.paper.yml logs -f"
        ),
        p("Optional `.env` values", "h2"),
        code(
            "AURA_PUBLIC_PROVIDER=coinbase\n"
            "AURA_DECISION_TIMEFRAME=5s\n"
            "AURA_OLLAMA_URL=http://host.docker.internal:11434\n"
            "AURA_FREE_AI_PRESET=balanced5\n"
            "AURA_OLLAMA_KEEP_ALIVE=0"
        ),
        bullet("Runtime state is stored in the named volume `aura-paper-state`."),
        bullet("The container filesystem is read-only except `/tmp` and the runtime volume."),
        bullet("Linux capabilities are dropped and `no-new-privileges` is enabled."),
        bullet("Live approval variables are explicitly empty inside the service."),
        p("Stop, restart and back up", "h2"),
        code(
            "docker compose -f compose.paper.yml restart\n"
            "docker compose -f compose.paper.yml down\n"
            "docker run --rm -v aura-paper_aura-paper-state:/state `\n"
            "  -v ${PWD}:/backup alpine tar czf /backup/aura-state.tgz -C /state ."
        ),
        p("Do not use `down -v` unless you intentionally want to delete paper learning state.", "callout"),
        PageBreak(),
        p("6. Linux or VPS systemd user service", "h1"),
        p("Prepare AURA", "h2"),
        code(
            "python3.12 -m venv .venv\n"
            ". .venv/bin/activate\n"
            "python -m pip install --upgrade pip\n"
            "pip install -e '.[dev]'\n"
            "python examples/run_production_preflight.py --mode paper --connector public"
        ),
        p("Install the user service", "h2"),
        code(
            "chmod +x scripts/install_aura_user_service.sh\n"
            "./scripts/install_aura_user_service.sh\n"
            "systemctl --user status aura-paper.service\n"
            "journalctl --user -u aura-paper.service -f"
        ),
        p("Keep it running after logout", "h2"),
        code("sudo loginctl enable-linger $USER"),
        bullet("The installer runs paper preflight before creating the service."),
        bullet("The unit restricts writes to AURA's runtime directory."),
        bullet("Ollama may run as a separate host service at `127.0.0.1:11434`."),
        p("Service operations", "h2"),
        code(
            "systemctl --user restart aura-paper.service\n"
            "systemctl --user stop aura-paper.service\n"
            "systemctl --user disable aura-paper.service"
        ),
        PageBreak(),
        p("7. Dhan Indian-market paper setup", "h1"),
        p(
            "Dhan provides Indian-market live data for internal paper learning. Credentials must "
            "belong to the operator and must never be pasted into source code or GitHub."
        ),
        p("Set credentials for the current PowerShell session", "h2"),
        code(
            "$env:AURA_DHAN_CLIENT_ID='YOUR_CLIENT_ID'\n"
            "$env:AURA_DHAN_ACCESS_TOKEN='YOUR_ACCESS_TOKEN'\n"
            "python examples/run_production_preflight.py --mode paper --connector dhan\n"
            "python examples/check_dhan_universe.py\n"
            "python examples/run_dhan_self_evolving_paper.py"
        ),
        bullet("Confirm the instrument master, data subscription and option access."),
        bullet("The runtime uses broad radar selection before expensive deep analysis."),
        bullet("Orders remain internal paper orders; do not reinterpret them as broker fills."),
        PageBreak(),
        p("8. Angel One SmartAPI account and reconciliation", "h1"),
        p(
            "AURA includes an official-SDK adapter for profile verification, LTP, order/trade "
            "books, positions, symbol routing and restart reconciliation. It does not store a "
            "PIN/TOTP seed and cannot submit or cancel orders in this release."
        ),
        p("Create a short-lived official session", "h2"),
        bullet("Use the Angel One developer portal and official SmartAPI authentication flow."),
        bullet("Keep the registered static IP and current account/API eligibility requirements in scope."),
        bullet("Inject only session tokens into the process; never commit them to `.env` or GitHub."),
        p("Run the read-only account preflight", "h2"),
        code(
            ".venv\\Scripts\\python.exe -m pip install smartapi-python\n"
            "$env:AURA_ANGEL_ONE_API_KEY='YOUR_API_KEY'\n"
            "$env:AURA_ANGEL_ONE_CLIENT_CODE='YOUR_CLIENT_CODE'\n"
            "$env:AURA_ANGEL_ONE_JWT_TOKEN='YOUR_SHORT_LIVED_JWT'\n"
            "$env:AURA_ANGEL_ONE_REFRESH_TOKEN='YOUR_REFRESH_TOKEN'\n"
            "$env:AURA_ANGEL_ONE_FEED_TOKEN='YOUR_FEED_TOKEN'\n"
            "python examples/check_angel_one_account.py"
        ),
        bullet("The preflight prints profile readiness plus open-order/position counts only."),
        bullet("Unknown broker-side orders/positions remain visible for reconciliation and risk freeze."),
        p(
            "Order payload translation is unit-tested, but submit/cancel are unconditionally locked "
            "until static-IP, acknowledgement, fill, restart and risk-gate evidence is approved.",
            "callout",
        ),
        PageBreak(),
        p("9. MT5 forex and metals demo setup", "h1"),
        p("Prerequisites", "h2"),
        bullet("Windows MetaTrader 5 installed and logged into a DEMO account."),
        bullet("Python package `MetaTrader5` installed in AURA's `.venv`."),
        bullet("Market Watch symbols enabled for XAUUSD and required instruments."),
        p("Configure only a DEMO account", "h2"),
        code(
            ".venv\\Scripts\\python.exe -m pip install MetaTrader5\n"
            "$env:AURA_MT5_DEMO_LOGIN='YOUR_DEMO_LOGIN'\n"
            "$env:AURA_MT5_DEMO_PASSWORD='YOUR_DEMO_PASSWORD'\n"
            "$env:AURA_MT5_DEMO_SERVER='YOUR_DEMO_SERVER'\n"
            "python examples/run_production_preflight.py --mode demo --connector mt5_demo\n"
            "python examples/run_mt5_self_evolving_paper.py"
        ),
        bullet("AURA checks account mode before guarded MT5 demo broker calls."),
        bullet("Symbol suffixes and contract sizes are broker-specific and must be verified."),
        p(
            "Never place a live login in variables named `AURA_MT5_DEMO_*`. Account-mode mismatch "
            "must stop the runtime rather than bypass the demo guard.",
            "callout",
        ),
        PageBreak(),
        p("10. Knowledge, news and authorized content", "h1"),
        p("Included sources", "h2"),
        bullet("Official RBI and SEBI feeds where available."),
        bullet("GDELT news context."),
        bullet("Optional FRED and Alpha Vantage using user-owned free keys."),
        bullet("Local authorized/public corpus with source, date, trust and hash metadata."),
        p("Optional environment variables", "h2"),
        code(
            "$env:AURA_FRED_API_KEY='YOUR_KEY'\n"
            "$env:AURA_ALPHA_VANTAGE_API_KEY='YOUR_KEY'\n"
            "$env:AURA_SEC_USER_AGENT='Your Name your@email.example'"
        ),
        p("Authorized document ingestion", "h2"),
        bullet("Use only owned, public-domain or properly licensed material."),
        bullet("Record original source, publication date, trust score and content hash."),
        bullet("Do not scrape copyrighted books, paid courses or unauthorized transcripts."),
        bullet("Knowledge is evidence only; it does not calculate quantity or place trades."),
        p(
            "Point-in-time policy: information observed after a decision timestamp is rejected from "
            "that historical decision, even if its publication date appears earlier.",
            "callout",
        ),
        PageBreak(),
        p("11. Telegram outbound alert setup", "h1"),
        p(
            "AURA includes a fail-closed outbound Telegram adapter for system, risk and trade-status "
            "alerts. It uses Telegram's official HTTPS Bot API, deduplicates delivered alert IDs after "
            "restart, honors retry guidance, and writes checksummed delivery receipts. It does not "
            "accept inbound commands and cannot submit orders."
        ),
        p("Prepare the destination", "h2"),
        bullet("Create a bot through Telegram's official BotFather workflow."),
        bullet("Start the bot chat or add the bot to the intended group, then obtain the chat ID."),
        bullet("Store the token and chat ID in the service environment or secret manager, never Git."),
        code(
            'export AURA_TELEGRAM_BOT_TOKEN="..."\n'
            'export AURA_TELEGRAM_CHAT_ID="..."\n'
            "python examples/send_telegram_test_alert.py"
        ),
        p("Verify the receipt", "h2"),
        bullet("The command exits zero only when Telegram returns a sent message ID."),
        bullet("Inspect runtime/alerts/telegram_receipts.jsonl for the checksummed receipt."),
        bullet("The receipt stores a destination hash; it never stores the token or raw chat ID."),
        p(
            "Until the operator performs this real destination test, Telegram remains an external "
            "destination gate even though its adapter and automated tests are implemented.",
            "callout",
        ),
        PageBreak(),
        p("12. Daily operations and health checks", "h1"),
        p("Before startup", "h2"),
        bullet("Run production preflight for the selected paper/demo connector."),
        bullet("Confirm live approval variables are empty."),
        bullet("Confirm system clock, disk space, network and runtime permissions."),
        bullet("Confirm Ollama responds and selected models appear in `ollama list`."),
        p("During operation", "h2"),
        bullet("Watch status JSON, structured logs, AI timeouts and data-quality counters."),
        bullet("Treat NO-TRADE as a valid decision, not a runtime failure."),
        bullet("Investigate reconciliation, stale-feed, future-data and operational incidents."),
        p("Validated maintenance commands", "h2"),
        code(
            "ruff check .\n"
            "pytest -q\n"
            "python -m compileall -q aura\n"
            "python -m aura.ops.repository_audit --check\n"
            "python -m build"
        ),
        p("Important runtime paths", "h2"),
        status_table(
            [
                ("Public autonomy", "STATE", "runtime/free_public_autonomy"),
                ("Dhan paper", "STATE", "runtime/dhan_self_evolving_paper"),
                ("MT5 paper", "STATE", "runtime/mt5_self_evolving_paper"),
                ("Governance evidence", "AUDIT", "artifacts/governance"),
                ("Client guide", "DOC", "output/pdf/AURA_SETUP_AND_OPERATIONS.pdf"),
            ]
        ),
        PageBreak(),
        p("13. Troubleshooting", "h1"),
        status_table(
            [
                ("Ollama unreachable", "CHECK", "Open Ollama, run `ollama serve`, verify `/api/tags` and firewall."),
                ("Model not found", "CHECK", "Use exact name from `ollama list`; pull it once before service start."),
                ("Python import error", "CHECK", "Activate `.venv` and install from repo root."),
                ("No AI decisions", "CHECK", "Wait for minimum history and inspect data and timeout counters."),
                ("No signals", "NORMAL", "NO-TRADE can be correct; inspect evidence before changing thresholds."),
                ("Windows task stops", "CHECK", "Run launcher in foreground for the exact error."),
                ("systemd restart loop", "CHECK", "Use `journalctl --user -u aura-paper.service -n 200`."),
                ("Docker cannot reach Ollama", "CHECK", "Verify host address, Ollama bind policy and firewall."),
                ("Dhan unauthorized", "STOP", "Use official refresh flow; never copy another person's token."),
                ("Angel One mismatch", "STOP", "Refresh the official session; never bypass client/static-IP checks."),
                ("MT5 mismatch", "STOP", "Use a verified DEMO account; do not bypass the demo guard."),
            ]
        ),
        p("Recovery rule", "h2"),
        bullet("Stop the service cleanly and back up runtime state and logs."),
        bullet("Run audit, tests and preflight."),
        bullet("Restart in public paper mode and confirm recovery/reconciliation state."),
        bullet("Never fix a failure by enabling live authority or disabling RiskEngine."),
        PageBreak(),
        p("14. Security and final acceptance", "h1"),
        p("Never commit", "h2"),
        bullet("Broker usernames, passwords, tokens, TOTP seeds or sessions."),
        bullet("`.env` files containing real values."),
        bullet("Live approval identifiers or risk acknowledgements."),
        bullet("Licensed data or copyrighted material without redistribution rights."),
        p("Client acceptance checklist", "h2"),
        bullet("GitHub checks and CodeQL are green."),
        bullet("Paper preflight is READY and live-money-disabled passes."),
        bullet("The deployment survives restart and retains state."),
        bullet("Data-quality and AI failures are visible, not silently ignored."),
        bullet("Every decision has structured evidence and an audit identity."),
        bullet("No strategy can move to live without evidence and human approval."),
        p("Before unrestricted live production", "h2"),
        bullet("Credential-backed broker conformance and reconciliation validation."),
        bullet("Venue-specific lot, tick, margin, expiry and settlement checks."),
        bullet("Long-duration broker-origin forward evidence across regimes."),
        bullet("All mandatory Phase 1-15 evidence gates."),
        bullet("Human strategy approval and smallest-size controlled canary."),
        p(
            "Final truth: this release is ready for client review, public-data autonomy, local "
            "Multi-AI demonstrations and governed paper/demo research. It is not a guaranteed-profit "
            "product and is not certified for unrestricted real-money execution.",
            "callout",
        ),
        Spacer(1, 8 * mm),
        p("Repository", "h2"),
        p("github.com/svk1dec2018-ai/AURA-AI-OS-ya-ai-trading-system"),
        p("Primary integrated review: pull request 25"),
    ]


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    AuraDocument(OUTPUT).build(build_story())
    print(OUTPUT)


if __name__ == "__main__":
    main()
