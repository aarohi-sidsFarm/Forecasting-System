from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "Sids_Farm_Forecasting_Project_Handover_2026-08-27.docx"
LOGO = ROOT / "frontend" / "public" / "sids-farm-logo.png"

YELLOW = "FCE099"
YELLOW_STRONG = "F4C84A"
CHARCOAL = "2E3440"
MUTED = "667085"
LIGHT = "F7F7F5"
LINE = "D9DCE1"
WHITE = "FFFFFF"
RED = "B42318"
GREEN = "027A48"
BLUE = "175CD3"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=80, start=110, bottom=80, end=110) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_geometry(table, widths: list[int]) -> None:
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl_pr = table._tbl.tblPr
    width = tbl_pr.find(qn("w:tblW"))
    if width is None:
        width = OxmlElement("w:tblW")
        tbl_pr.append(width)
    width.set(qn("w:w"), "9360")
    width.set(qn("w:type"), "dxa")
    indent = tbl_pr.find(qn("w:tblInd"))
    if indent is None:
        indent = OxmlElement("w:tblInd")
        tbl_pr.append(indent)
    indent.set(qn("w:w"), "120")
    indent.set(qn("w:type"), "dxa")
    for row in table.rows:
        for idx, cell in enumerate(row.cells):
            cell.width = Inches(widths[idx] / 1440)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_margins(cell)


def set_cell_border(cell, color=LINE, size="6") -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = qn(f"w:{edge}")
        node = borders.find(tag)
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), size)
        node.set(qn("w:color"), color)


def prevent_row_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    cant_split = OxmlElement("w:cantSplit")
    tr_pr.append(cant_split)


def repeat_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def add_page_number(paragraph) -> None:
    run = paragraph.add_run()
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr_text = OxmlElement("w:instrText")
    instr_text.set(qn("xml:space"), "preserve")
    instr_text.text = " PAGE "
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "end")
    run._r.extend([fld_char1, instr_text, fld_char2])


def configure_document(doc: Document) -> None:
    section = doc.sections[0]
    section.top_margin = Inches(0.62)
    section.bottom_margin = Inches(0.58)
    section.left_margin = Inches(0.68)
    section.right_margin = Inches(0.68)
    section.header_distance = Inches(0.25)
    section.footer_distance = Inches(0.25)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(9.2)
    normal.font.color.rgb = RGBColor.from_string(CHARCOAL)
    normal.paragraph_format.space_after = Pt(4)
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE

    for name, size, color, before, after in (
        ("Title", 29, CHARCOAL, 0, 10),
        ("Subtitle", 13, MUTED, 0, 8),
        ("Heading 1", 18, CHARCOAL, 16, 6),
        ("Heading 2", 12.5, CHARCOAL, 10, 4),
        ("Heading 3", 10.5, MUTED, 7, 2),
    ):
        style = styles[name]
        style.font.name = "Aptos Display" if name != "Subtitle" else "Aptos"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string(color)
        style.font.bold = name != "Subtitle"
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    for list_name in ("List Bullet", "List Number"):
        style = styles[list_name]
        style.font.name = "Aptos"
        style.font.size = Pt(9.2)
        style.paragraph_format.left_indent = Inches(0.22)
        style.paragraph_format.first_line_indent = Inches(-0.16)
        style.paragraph_format.space_after = Pt(2)

    header = section.header
    hp = header.paragraphs[0]
    hp.text = "SID’S FARM  /  DEMAND FORECASTING HANDOVER"
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hp.runs[0].font.name = "Aptos"
    hp.runs[0].font.size = Pt(7.5)
    hp.runs[0].font.bold = True
    hp.runs[0].font.color.rgb = RGBColor.from_string(MUTED)

    footer = section.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = fp.add_run("INTERNAL HANDOVER  •  27 AUG 2026  •  ")
    run.font.name = "Aptos"
    run.font.size = Pt(7)
    run.font.color.rgb = RGBColor.from_string(MUTED)
    add_page_number(fp)


def add_para(doc, text="", style=None, bold_prefix=None, color=None, keep=False):
    p = doc.add_paragraph(style=style)
    if bold_prefix and text.startswith(bold_prefix):
        p.add_run(bold_prefix).bold = True
        p.add_run(text[len(bold_prefix):])
    else:
        run = p.add_run(text)
        if color:
            run.font.color.rgb = RGBColor.from_string(color)
    if keep:
        p.paragraph_format.keep_with_next = True
    return p


def _new_list_num_id(doc, kind: str) -> int:
    numbering = doc.part.numbering_part.element
    abstract_ids = [int(node.get(qn("w:abstractNumId"))) for node in numbering.findall(qn("w:abstractNum"))]
    num_ids = [int(node.get(qn("w:numId"))) for node in numbering.findall(qn("w:num"))]
    abstract_id = max(abstract_ids, default=0) + 1
    num_id = max(num_ids, default=0) + 1

    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    nsid = OxmlElement("w:nsid")
    nsid.set(qn("w:val"), f"{0xA0000000 + abstract_id:08X}")
    template = OxmlElement("w:tmpl")
    template.set(qn("w:val"), f"{0xB0000000 + abstract_id:08X}")
    abstract.extend([nsid, template])
    multi = OxmlElement("w:multiLevelType")
    multi.set(qn("w:val"), "singleLevel")
    abstract.append(multi)
    level = OxmlElement("w:lvl")
    level.set(qn("w:ilvl"), "0")
    start = OxmlElement("w:start")
    start.set(qn("w:val"), "1")
    num_fmt = OxmlElement("w:numFmt")
    num_fmt.set(qn("w:val"), "bullet" if kind == "bullet" else "decimal")
    lvl_text = OxmlElement("w:lvlText")
    lvl_text.set(qn("w:val"), "•" if kind == "bullet" else "%1.")
    suffix = OxmlElement("w:suff")
    suffix.set(qn("w:val"), "space")
    lvl_jc = OxmlElement("w:lvlJc")
    lvl_jc.set(qn("w:val"), "left")
    p_pr = OxmlElement("w:pPr")
    tabs = OxmlElement("w:tabs")
    tab = OxmlElement("w:tab")
    tab.set(qn("w:val"), "num")
    tab.set(qn("w:pos"), "360")
    tabs.append(tab)
    ind = OxmlElement("w:ind")
    ind.set(qn("w:left"), "360")
    ind.set(qn("w:hanging"), "180")
    p_pr.extend([tabs, ind])
    level.extend([start, num_fmt, lvl_text, suffix, lvl_jc, p_pr])
    abstract.append(level)
    numbering.append(abstract)

    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    abstract_ref = OxmlElement("w:abstractNumId")
    abstract_ref.set(qn("w:val"), str(abstract_id))
    num.append(abstract_ref)
    level_override = OxmlElement("w:lvlOverride")
    level_override.set(qn("w:ilvl"), "0")
    start_override = OxmlElement("w:startOverride")
    start_override.set(qn("w:val"), "1")
    level_override.append(start_override)
    num.append(level_override)
    numbering.append(num)
    return num_id


def _apply_list_num(paragraph, num_id: int) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    num_pr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    num_id_node = OxmlElement("w:numId")
    num_id_node.set(qn("w:val"), str(num_id))
    num_pr.extend([ilvl, num_id_node])
    p_pr.append(num_pr)


def add_bullets(doc, items):
    num_id = _new_list_num_id(doc, "bullet")
    for item in items:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        _apply_list_num(p, num_id)
        if isinstance(item, tuple):
            lead, rest = item
            p.add_run(lead).bold = True
            p.add_run(rest)
        else:
            p.add_run(item)


def add_numbered(doc, items):
    for index, item in enumerate(items, start=1):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.22)
        p.paragraph_format.first_line_indent = Inches(-0.16)
        p.paragraph_format.space_after = Pt(2)
        p.add_run(f"{index}. ")
        if isinstance(item, tuple):
            lead, rest = item
            p.add_run(lead).bold = True
            p.add_run(rest)
        else:
            p.add_run(item)


def add_callout(doc, title, body, fill=YELLOW, accent=CHARCOAL):
    table = doc.add_table(rows=1, cols=1)
    set_table_geometry(table, [9360])
    cell = table.cell(0, 0)
    set_cell_shading(cell, fill)
    set_cell_border(cell, fill, "2")
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(title.upper())
    run.bold = True
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor.from_string(accent)
    p2 = cell.add_paragraph(body)
    p2.paragraph_format.space_after = Pt(0)
    prevent_row_split(table.rows[0])
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_table(doc, headers, rows, widths, header_fill=CHARCOAL, zebra=True, font_size=8):
    table = doc.add_table(rows=1, cols=len(headers))
    set_table_geometry(table, widths)
    header = table.rows[0]
    repeat_header(header)
    prevent_row_split(header)
    for i, value in enumerate(headers):
        cell = header.cells[i]
        set_cell_shading(cell, header_fill)
        set_cell_border(cell)
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(str(value))
        r.bold = True
        r.font.size = Pt(font_size)
        r.font.color.rgb = RGBColor.from_string(WHITE if header_fill == CHARCOAL else CHARCOAL)
    for row_idx, values in enumerate(rows):
        row = table.add_row()
        prevent_row_split(row)
        for i, value in enumerate(values):
            cell = row.cells[i]
            if zebra and row_idx % 2:
                set_cell_shading(cell, LIGHT)
            set_cell_border(cell)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.keep_together = True
            r = p.add_run(str(value))
            r.font.size = Pt(font_size)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return table


def add_code_block(doc, text):
    table = doc.add_table(rows=1, cols=1)
    set_table_geometry(table, [9360])
    cell = table.cell(0, 0)
    set_cell_shading(cell, "F2F4F7")
    set_cell_border(cell, LINE, "4")
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.keep_together = True
    r = p.add_run(text)
    r.font.name = "Consolas"
    r.font.size = Pt(7.8)
    return table


def page_break(doc):
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def add_cover(doc):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(28)
    if LOGO.exists():
        p.add_run().add_picture(str(LOGO), width=Inches(1.35))
    p = doc.add_paragraph("DEMAND FORECASTING SYSTEM", style="Title")
    p.paragraph_format.space_before = Pt(18)
    p = doc.add_paragraph("Complete Project & Production Handover", style="Subtitle")
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(16)
    r = p.add_run("Business logic  •  Data contracts  •  ML  •  Backend  •  Dashboard  •  Operations")
    r.bold = True
    r.font.color.rgb = RGBColor.from_string(CHARCOAL)
    add_callout(
        doc,
        "Current position",
        "The workflow is production-oriented and operationally safer than the original D-1 total-demand prototype. "
        "It now issues immutable D-2/D-3 forecasts, uses live known demand as a floor, trains direct-horizon models, "
        "and reconciles against Query 1968. The requested below-1% error is still not achieved consistently and must not be represented as complete.",
        fill=YELLOW,
    )
    add_table(
        doc,
        ["Document", "Value"],
        [
            ("Prepared for", "Senior engineering, ML, analytics and operations handover"),
            ("Repository", r"D:\ML_Forecasting_Model"),
            ("Status date", "27 August 2026 (IST)"),
            ("System scope", "4 cities × 7 milk/curd SKUs = 28 daily series"),
            ("Operational policy", "HYD/VGA D-2; BLR/PNQ D-3; issue time 22:05 IST"),
            ("Source of truth", "Redash Query 1968 for completed actual sales"),
            ("Confidentiality", "Internal handover; credentials and secrets intentionally excluded"),
        ],
        [2450, 6910],
        header_fill=CHARCOAL,
        font_size=8.5,
    )
    add_para(doc, "Owner note", style="Heading 2")
    add_para(
        doc,
        "This document explains what was built, why each part exists, what changed after 1 August, what is verified, "
        "what remains risky, and how another developer can operate and improve the system without reconstructing decisions from chat history.",
    )
    page_break(doc)


def build_document():
    doc = Document()
    configure_document(doc)
    add_cover(doc)

    doc.add_heading("Contents", level=1)
    add_table(
        doc,
        ["Part", "Coverage"],
        [
            ("1–3", "Executive summary, business problem, scope and success measures"),
            ("4–7", "Business rules, architecture, Redash contracts and data pipeline"),
            ("8–11", "Features, models, forecast composition and festival handling"),
            ("12–15", "Backend, history, dashboard, scheduling and daily operations"),
            ("16–19", "Evolution, issues, achievements, current accuracy and limitations"),
            ("20–23", "Prioritized roadmap, troubleshooting, handover and glossary"),
        ],
        [1500, 7860],
        header_fill=YELLOW_STRONG,
    )
    add_callout(
        doc,
        "How to read this",
        "Sections 4, 6, 10, 13 and 15 define the production contract. Section 19 is the honest accuracy position. "
        "Section 20 is the next implementation plan for improving accuracy without corrupting the official forecast history.",
        fill="FFF8E1",
    )

    doc.add_heading("1. Executive summary", level=1)
    add_para(
        doc,
        "Sid’s Farm needs packet-level demand forecasts early enough for procurement and production decisions. The system forecasts seven milk/curd SKUs for Hyderabad, Vijayawada, Bengaluru and Pune. Because dairy is perishable, the cost is two-sided: under-forecasting causes shortages and failed customer demand; over-forecasting creates wastage.",
    )
    add_para(
        doc,
        "The original implementation mainly treated forecasting as a pure time-series/LightGBM total-demand problem. The current implementation is an operational hybrid: demand already visible in Redash is deterministic, while the model predicts the remaining uncertainty. Forecasts are frozen on the real issue date and later compared with completed actuals from Query 1968.",
    )
    add_bullets(doc, [
        ("Known demand floor: ", "wallet-confirmed scheduled subscriptions plus buy-once orders already placed by the issue cutoff."),
        ("Modelled uncertainty: ", "the remaining gap up to the model’s predicted final city–SKU total."),
        ("Operational horizons: ", "HYD/VGA are issued two days before delivery; BLR/PNQ three days before delivery."),
        ("Official record: ", "a successful daily issuance is immutable and stores issue date, target date, components, model output and run ID."),
        ("Accuracy truth: ", "forecast rows are joined by target date + city + SKU to Query 1968 actuals; row-order comparisons are rejected."),
    ])
    add_callout(
        doc,
        "Bottom line",
        "The project has achieved a safer and explainable production workflow, but it has not achieved guaranteed below-1% WAPE by city or SKU. "
        "The main remaining modelling problem is uncertainty between D-2/D-3 issuance and final delivery, especially subscription pauses, wallet recovery, cancellations and post-issue buy-once arrivals.",
        fill="FDECEC",
        accent=RED,
    )

    doc.add_heading("2. Business problem and objective", level=1)
    doc.add_heading("2.1 Decision being supported", level=2)
    add_para(doc, "The output is a procurement forecast: the number of packets that operations should plan for each target delivery date, city and SKU. The dashboard is not merely a sales chart; it is the decision surface used before procurement cutoffs.")
    doc.add_heading("2.2 Forecasting unit", level=2)
    add_table(
        doc,
        ["Dimension", "Definition"],
        [
            ("Target date", "The delivery/sales date being forecast."),
            ("Issue date", "The date on which procurement receives the forecast."),
            ("City", "HYD, VGA, BLR or PNQ after canonical normalization."),
            ("SKU", "One of seven approved milk/curd names."),
            ("Quantity", "Final packet quantity using the same gross all-status business definition as Query 1968."),
            ("Lead", "target_date − issue_date: 2 days for HYD/VGA, 3 days for BLR/PNQ."),
        ],
        [2200, 7160],
    )
    doc.add_heading("2.3 Success criteria", level=2)
    add_bullets(doc, [
        "Correct date/city/SKU quantities are available before procurement acts.",
        "No data arriving after the issue cutoff leaks into an official forecast.",
        "A failed Redash input never publishes a partial or mixed forecast as official.",
        "Forecasts and actuals can be reproduced by run ID and compared on matching keys.",
        "Accuracy is reported separately by city, SKU, horizon and normal/festival regime.",
        "The business aspiration is below 1% error; current evidence does not support guaranteeing it.",
    ])

    doc.add_heading("3. Scope", level=1)
    add_table(
        doc,
        ["City code", "Business name", "Lead", "Issue-date rule"],
        [
            ("HYD", "Hyderabad", "D-2", "For target T, use issuance from T−2"),
            ("VGA", "Vijayawada", "D-2", "For target T, use issuance from T−2"),
            ("BLR", "Bengaluru", "D-3", "For target T, use issuance from T−3"),
            ("PNQ", "Pune", "D-3", "For target T, use issuance from T−3"),
        ],
        [1200, 2200, 1000, 4960],
        header_fill=YELLOW_STRONG,
    )
    add_table(
        doc,
        ["Supported SKUs", "Operational note"],
        [
            ("A2 Buffalo Milk", "Major-volume SKU; separately monitored."),
            ("A2 Desi Cow Milk", "Product aliases normalized in SQL/backend."),
            ("Cow Milk", "Major source of recent HYD error investigation."),
            ("Curd", "Lower volume; percentage error is naturally more volatile."),
            ("Double Toned A2 Buffalo Milk", "Alias order matters to prevent accidental A2 Buffalo mapping."),
            ("Skim Milk", "Supported in all four cities."),
            ("Toned Milk", "Mapping added consistently to live queries."),
        ],
        [3700, 5660],
    )
    add_para(doc, "Out of scope today: hub/dark-store-level forecasts, automated procurement ordering, production authentication/SSO, a cloud deployment, and a contractual guarantee of 99% accuracy.")

    doc.add_heading("4. Core business logic", level=1)
    doc.add_heading("4.1 Target-date-first user experience", level=2)
    add_para(doc, "The user selects the date they need to procure for. The system calculates the required issue date automatically; the user does not manually go backward to D-2 or D-3.")
    add_code_block(doc, "selected target T\nHYD/VGA rows  <- frozen run issued on T - 2 days\nBLR/PNQ rows  <- frozen run issued on T - 3 days")
    doc.add_heading("4.2 Demand decomposition", level=2)
    add_code_block(doc, "visible_known_qty = confirmed_subscription_qty + known_buy_once_qty\nremaining_model_gap_qty = max(0, predicted_final_total_qty - visible_known_qty)\nfinal_forecast_qty = visible_known_qty + remaining_model_gap_qty\n                   = max(visible_known_qty, predicted_final_total_qty)")
    add_para(doc, "The legacy API name ml_unknown_adhoc_qty is retained for compatibility. In the current total-target architecture it means remaining model gap; it is not yet a separately trained ad-hoc model.")
    doc.add_heading("4.3 Subscription floor", level=2)
    add_bullets(doc, [
        "confirmed_qty is the operational floor.",
        "expected_qty is scheduled quantity before wallet certainty is applied.",
        "at_risk_qty represents scheduled subscriptions whose prepaid balance is insufficient.",
        "wallet_unknown_qty represents cases where the wallet state is unavailable/uncertain.",
        "Unconfirmed subscriptions = expected_qty − confirmed_qty. This is diagnostic, not an additional quantity to sum into the final forecast.",
        "Required invariant: expected_qty = confirmed_qty + at_risk_qty + wallet_unknown_qty.",
    ])
    doc.add_heading("4.4 Why the dashboard freeze and SQL cutoff are both needed", level=2)
    add_para(doc, "Freezing protects the output after it is produced. A cutoff-aware SQL query protects the input before it is produced. Without the query cutoff, a historical refresh could include orders placed after procurement decided, creating future leakage even though the resulting row is frozen.")
    doc.add_heading("4.5 Official versus preview", level=2)
    add_table(
        doc,
        ["Status", "Meaning", "Eligible for official accuracy?"],
        [
            ("official_issued", "Created at the real issue date with all required inputs; immutable.", "Yes"),
            ("partial_issued", "Only some city groups have frozen rows for the selected target.", "No"),
            ("live_preview", "Computed now; may be late and may use information unavailable at the official cutoff.", "No"),
            ("legacy_issued", "Historical/imported row without the full modern issuance contract.", "No, unless explicitly audited"),
        ],
        [1600, 5360, 2400],
    )

    doc.add_heading("5. End-to-end architecture", level=1)
    add_table(
        doc,
        ["Stage", "Responsibility", "Main implementation"],
        [
            ("1. Source", "Business state and completed sales", "Redash queries 3085, 3086, 3101, 1968, 3269"),
            ("2. Validation", "Schema checks, normalization, required-input and freshness checks", "backend/main.py; fetch scripts"),
            ("3. Features", "Calendar, lags, rolling demand, trend, event flags", "ml_pipeline/build_features.py + serving parity code"),
            ("4. Models", "General, HYD-specific and direct-horizon forecasts", "LightGBM artifacts under backend/ml_models"),
            ("5. Composition", "Known floor + remaining model gap", "backend/main.py"),
            ("6. History", "Atomic immutable runs and actual reconciliation", "backend/forecast_history.py"),
            ("7. Delivery", "API, CSV export and filtered dashboard", "FastAPI + React/Vite"),
        ],
        [1300, 3800, 4260],
    )
    add_callout(doc, "Architectural principle", "Known operational facts must be deterministic; ML predicts only what is not yet known. Every metric must be evaluated at the information cutoff that existed when the decision was made.", fill="EAF2FF", accent=BLUE)

    doc.add_heading("6. Redash data contracts", level=1)
    add_table(
        doc,
        ["ID", "Contract", "Used for", "When called"],
        [
            ("3085", "Subscription forecast", "Confirmed floor, expected/at-risk/unknown diagnostics", "Live issue/preview per target"),
            ("3086", "Known buy-once", "Orders already placed by city issue cutoff", "Live issue/preview per target"),
            ("3101", "Recent final actuals", "Completed demand lags for inference", "Live issue/preview per target"),
            ("1968", "Official actual sales", "Comparison, reconciliation and accuracy", "After target day completes"),
            ("3269", "Procurement training export", "Historical final total and components", "Incremental daily/weekly refresh"),
        ],
        [800, 2100, 3760, 2700],
        header_fill=YELLOW_STRONG,
        font_size=7.7,
    )
    doc.add_heading("6.1 Query 3085 — subscription forecast", level=2)
    add_para(doc, "Calculates scheduled quantities for daily, alternate-day and custom subscriptions on the target date. It excludes deleted customer holidays, paused subscriptions and subscriptions outside validity dates; maps variant/product and shipping city; and assesses prepaid wallet coverage at customer-order level.")
    add_bullets(doc, [
        "Shipping address city is preferred; latest active customer city is a fallback.",
        "Product names are canonicalized with Double Toned rules evaluated before generic A2 Buffalo rules.",
        "Wallet balance is compared with the customer’s scheduled order value, not one row in isolation.",
        "The API consumes confirmed_qty as the floor and retains expected/at-risk/unknown for explanation.",
    ])
    doc.add_heading("6.2 Query 3086 — known buy-once", level=2)
    add_para(doc, "Aggregates non-free buy-once-like temp order items for the target delivery date that existed by the correct city issue cutoff. Accepted operational statuses include DRAFT and PROCESSED_TO_ORDER; status choices must remain aligned with the all-status final target.")
    doc.add_heading("6.3 Query 3101 — recent completed actuals", level=2)
    add_para(doc, "Provides completed final total demand for lag construction. It must use the same quantity definition, city mapping and SKU mapping as training and Query 1968. A successful /api/status call does not prove this query is fresh; the status payload carries training freshness and Redash state separately.")
    doc.add_heading("6.4 Query 1968 — source of truth", level=2)
    add_para(doc, "This is the team’s approved comparison query. The backend may receive a wide/month-level result and then filters to the requested target date before aggregating. Every comparison joins on target date, canonical city and product name.")
    doc.add_heading("6.5 Query 3269 — training export", level=2)
    add_para(doc, "Provides historical final_subscription_qty, final_buy_once_qty, final_total_qty and order counts. The refresh process fetches only a recent overlap window, audits changed historical values, appends/deduplicates and atomically replaces the local export.")
    add_callout(doc, "Why multiple queries?", "They answer different questions at different times: what is known at issue time, what happened recently for lags, what finally happened, and what history is required for training. Combining them into one live query would increase latency, blur cutoffs and make leakage harder to detect.", fill="FFF8E1")

    page_break(doc)
    doc.add_heading("7. Data pipeline and quality controls", level=1)
    add_numbered(doc, [
        ("Incremental extraction. ", "Fetch Query 3269 from the latest stored date with a seven-day overlap; do not download the entire 2025+ history every day."),
        ("Overlap audit. ", "Compare overlapping keys and block/flag unexpectedly large historical changes. The threshold was relaxed from 5% to 30% after a valid 21.46% backfill correction was observed; changes remain visible."),
        ("Canonical cleaning. ", "Normalize city/SKU values and aggregate to one target_date × city × SKU row."),
        ("Gap filling. ", "Create a complete daily grid for all 28 series; distinguish true zeros from missing source data through upstream validation."),
        ("Feature building. ", "Generate lag, rolling, calendar, trend, quantity/order and event features."),
        ("Training. ", "Train general, HYD-specific, HYD D-2 direct and BLR D-3 direct artifacts."),
        ("Reconciliation. ", "Load Query 1968 completed actuals into forecast history before accuracy evaluation."),
        ("Atomic publication. ", "Publish all required issued rows or none; never mix partial live inputs into an official run."),
    ])
    add_table(
        doc,
        ["Current training snapshot", "Value"],
        [
            ("Rows", "13,524"),
            ("Date range", "1 May 2025 through 26 August 2026"),
            ("Series", "28 city–SKU combinations"),
            ("Cities", "BLR, HYD, PNQ, VGA"),
            ("Serving copy", "backend/ml_models/training_filled.csv"),
        ],
        [3200, 6160],
    )
    doc.add_heading("7.1 Data quality gates", level=2)
    add_bullets(doc, [
        "Required Redash query IDs must be configured.",
        "Missing required live components raise an error; they must not silently become zero.",
        "City/SKU aliases are normalized before aggregation and joining.",
        "Duplicate comparison keys and unmatched forecast/actual keys are rejected.",
        "Training freshness is exposed in /api/status.",
        "Festival calendar schema, duplicate city/date entries and upcoming dates are audited before issuance.",
        "Model artifacts and feature ordering are loaded at backend startup.",
    ])

    doc.add_heading("8. Feature engineering", level=1)
    add_table(
        doc,
        ["Feature group", "Examples", "Purpose / leakage rule"],
        [
            ("Identity", "city, product, city-product encodings", "Let one model learn series-specific behavior."),
            ("Calendar", "day of week, month, weekend, cyclical sin/cos", "Represent recurring seasonality known in advance."),
            ("Lags", "lag 7, 14, 21, 28; selected shorter lags", "Use only values completed by the issue cutoff."),
            ("Rolling", "7/14/28-day means, dispersion, trend slope", "Describe level and movement without looking ahead."),
            ("Operations", "visible subscription/buy-once, quantity per order", "Tie the model to demand already visible at issuance."),
            ("Events", "festival, city festival, pre/post, impact direction", "Static date lookup; event state must not come from recursive predictions."),
            ("Trend", "time index / recent slope", "Allow gradual change, while recognizing tree models extrapolate weakly."),
        ],
        [1700, 3200, 4460],
        font_size=7.7,
    )
    add_para(doc, "Direct-horizon artifacts are designed to remove recursive contamination. For HYD D-2, completed actual lags stop at T−3. For BLR D-3, they stop at T−4. Intermediate model predictions are not inserted as if they were actual sales.")

    doc.add_heading("9. Models", level=1)
    add_table(
        doc,
        ["Artifact", "Role", "Target / horizon", "Current state"],
        [
            ("lgbm_model.pkl", "General four-city model", "Final procurement total", "Loaded by backend"),
            ("lgbm_model_hyd.pkl", "HYD-specialized model", "Final procurement total", "Loaded by backend"),
            ("hyd_d2_direct.pkl", "Cutoff-safe direct HYD selector", "T at D-2", "Available and enabled by default"),
            ("blr_d3_direct.pkl", "Cutoff-safe direct BLR selector", "T at D-3", "Available and enabled by default"),
            ("challenger_*_d1_d7.pkl", "Multi-horizon shadow artifacts", "D+1 through D+7", "Evaluation/supporting artifacts"),
        ],
        [2200, 2600, 2200, 2360],
        font_size=7.7,
    )
    doc.add_heading("9.1 Why LightGBM", level=2)
    add_para(doc, "LightGBM is appropriate for the current dataset because the problem is tabular time series with nonlinear interactions among city, SKU, calendar, lag and operational features. It trains quickly on a local Windows machine and is easier to operate than a deep-learning stack at this data scale.")
    doc.add_heading("9.2 What tuning alone cannot fix", level=2)
    add_para(doc, "Optuna, feature selection, SHAP, log targets, stricter leaves and early stopping are useful experiments, but none can reconstruct information that was not captured at D-2/D-3. The dominant remaining problem is cutoff-state data: subscription pauses, wallet changes, cancellations and post-issue buy-once arrivals.")
    doc.add_heading("9.3 Model selection inside direct artifacts", level=2)
    add_para(doc, "Each city–SKU may select the best validated method among LightGBM and stable time-series baselines such as seasonal-7 or recent mean. This prevents forcing a high-variance model on a series where a simple same-weekday baseline is stronger.")

    doc.add_heading("10. Forecast generation sequence", level=1)
    add_numbered(doc, [
        "Resolve the issue date and target dates from the city horizon policy.",
        "Fetch subscription, known buy-once and recent completed actuals from Redash.",
        "Validate responses and normalize city/SKU names.",
        "Build cutoff-safe feature rows for each city–SKU.",
        "Run general/HYD models and direct-horizon selectors where enabled.",
        "Apply narrow validation-derived calibration/guardrails where configured.",
        "Calculate the confirmed floor, remaining model gap and final forecast.",
        "Validate the full 28-row issuance and write it atomically to forecast history.",
        "Expose frozen rows through the target-date dashboard and exports.",
        "After sales complete, reconcile Query 1968 actuals and compute eligible accuracy.",
    ])
    add_callout(doc, "No partial publication", "If any required Redash input fails, the issuance is rejected and the previous frozen rows remain unchanged. A partial dashboard view is labelled PARTIAL and is not eligible for official accuracy.", fill="EAF2FF", accent=BLUE)

    doc.add_heading("11. Festival and regional-event handling", level=1)
    add_para(doc, "The static calendar contains 197 rows from 1 January 2024 through 25 December 2026: 105 national rows and 92 regional rows. It supports national and city-specific events and is reviewed for the next 45 days before daily issuance.")
    add_table(
        doc,
        ["Capability", "Implementation rule"],
        [
            ("Static lookup", "Join event flags by the exact target date and applicable city."),
            ("Regional events", "Examples include Bonalu/Bathukamma for HYD, Varamahalakshmi/Gowri Habba for BLR and Dahi Handi/Gauri events for PNQ."),
            ("Pre/post effects", "Separate event-day, pre-event and post-event indicators; do not keep a generic festival flag switched on."),
            ("Impact direction", "Calendar can represent uplift, dip or neutral/unknown direction."),
            ("Guardrail cap", "Festival-specific adjustments are narrow and capped; current configured cap is 5% except documented manual event exceptions."),
            ("Moon-sighting warning", "Dates dependent on observation must be reconfirmed before operational issuance."),
        ],
        [2300, 7060],
    )
    add_para(doc, "A festival near the target date must not automatically affect a normal day. If a non-festival target receives a festival feature, the defect is in the calendar join or future feature matrix, not in LightGBM. Debug endpoints expose target-date event flags for inspection.")

    doc.add_heading("12. Backend service", level=1)
    add_para(doc, "The backend is FastAPI in backend/main.py. It loads models and training history at startup, calls Redash asynchronously through httpx, constructs features, generates forecasts, stores immutable history and returns dashboard/export responses.")
    add_table(
        doc,
        ["Endpoint", "Purpose"],
        [
            ("GET /health", "Basic model/query metadata and liveness."),
            ("GET /api/status", "Redash state, model/direct-model status, training freshness, calendar and issuance/cache status."),
            ("GET /api/operational_forecast", "Target-date-first frozen/live operational forecast and comparison metadata."),
            ("GET /api/forecast_day", "Day-level forecast generation."),
            ("GET /api/debug/components", "Raw component counts and forecast decomposition diagnostics."),
            ("GET /api/debug/model_features", "Lag sources, recursive days, event flags and champion/direct challenger outputs."),
            ("GET /api/export/operational_forecast.csv", "Operational rows for sharing/processing."),
            ("GET /api/export/accuracy_report.csv", "Eligible forecast-versus-actual report."),
            ("GET /api/forecast_trend", "Cached trend aggregation."),
        ],
        [3700, 5660],
        font_size=7.8,
    )
    doc.add_heading("12.1 Runtime behavior", level=2)
    add_bullets(doc, [
        "Backend: http://127.0.0.1:8000; frontend development server: http://localhost:5173.",
        "Do not start Uvicorn twice on port 8000. WinError 10048 means another backend process already owns the port.",
        "A 200 response from /api/status means FastAPI is reachable; status=degraded means Redash or freshness is unhealthy.",
        "Identical Redash calls are deduplicated, successful results are cached, failed calls enter a retry cooldown, and async Redash jobs may poll for up to 15 minutes.",
        "If models are retrained while the backend is running, restart the backend so it loads the new artifacts.",
    ])
    doc.add_heading("12.2 Security and technical debt", level=2)
    add_bullets(doc, [
        "Redash credentials are environment variables and must never be added to the repository or documentation.",
        "Debug endpoints can use ADMIN_TOKEN, but application-wide authentication/SSO is not implemented.",
        "backend/main.py remains monolithic and should eventually be split into routers, Redash client, forecast service, model service and history repository.",
        "The frontend API URL should be environment-based for deployment.",
    ])

    doc.add_heading("13. Immutable forecast history and accuracy contract", level=1)
    add_para(doc, "backend/forecast_history.py stores forecast runs and rows in a local SQLite history. An official issuance requires an issue date and is unique at the issue-date/target/city/SKU grain. Re-running a completed issue date returns already_issued rather than overwriting it.")
    add_table(
        doc,
        ["Stored field group", "Examples"],
        [
            ("Identity", "run_id, run_kind, generated_at, issue_date, forecast_date"),
            ("Decision grain", "city_cd, product_name, lead_time_days"),
            ("Components", "confirmed subscription, at-risk subscription, visible buy-once, model gap"),
            ("Output", "forecast quantity and method/model provenance"),
            ("Outcome", "actual quantity from Query 1968 after reconciliation"),
        ],
        [2800, 6560],
    )
    add_callout(doc, "Accuracy eligibility", "Only complete official_issued forecasts at the required D-2/D-3 horizon may be presented as production accuracy. Retrospective reconstruction, live previews and mixed issue dates are diagnostics only.", fill="FFF8E1")

    doc.add_heading("14. Dashboard", level=1)
    add_para(doc, "The React/Vite dashboard is intentionally minimal and uses Sid’s Farm white, muted yellow and soft-charcoal styling. Users select a target date, search/filter city or SKU, show components, download visible rows or copy a share-ready forecast.")
    add_bullets(doc, [
        "Target date is the primary date control; lead dates are calculated automatically.",
        "City colors distinguish rows/cards without flooding the interface with yellow.",
        "Component columns expose confirmed subscriptions, at-risk/unconfirmed subscriptions, placed buy-once, remaining forecast and final forecast.",
        "Query 1968 actual and deviation columns appear only when the target date is complete and an eligible frozen forecast exists.",
        "PARTIAL means the selected target requires multiple issue dates and one city group is missing/not yet due/failed.",
        "LIVE PREVIEW must not be copied into the official accuracy history as if it were an on-time forecast.",
    ])
    add_para(doc, "Known UX improvement: when a city group is not yet due, the banner should say ‘not issued yet’ instead of telling the user to refresh Redash. Refresh only helps when the required issue date has passed and the live inputs can be retried.")

    doc.add_heading("15. Scheduling and operating runbook", level=1)
    doc.add_heading("15.1 Automated issue task", level=2)
    add_para(doc, "Windows Task Scheduler task: SidsFarm-Daily-Forecast-Issuance. Normal schedule: 22:05 IST every day, StartWhenAvailable enabled, 90-minute execution limit. It validates festivals, fetches inputs and issues the forecast for the current issue date.")
    add_code_block(doc, "Get-ScheduledTask -TaskName \"SidsFarm-Daily-Forecast-Issuance\"\nGet-ScheduledTaskInfo -TaskName \"SidsFarm-Daily-Forecast-Issuance\"\nStart-ScheduledTask -TaskName \"SidsFarm-Daily-Forecast-Issuance\"")
    add_para(doc, "LastTaskResult 0 means success. 3221225786 (0xC000013A) means the process was interrupted/terminated, commonly by Ctrl+C, closing the host window or an execution boundary. Logs are written under reports/logs/daily_issuance_YYYY-MM-DD.log.")
    doc.add_heading("15.2 Daily operator sequence", level=2)
    add_numbered(doc, [
        "Confirm the machine, network/VPN and scheduled task are available before 22:05.",
        "After the task runs, check LastTaskResult and the daily log.",
        "Start/restart the backend only when needed; verify /api/status reports models loaded and inspect Redash/training freshness separately.",
        "Open the dashboard and select the target date. Verify all 28 rows, issue dates, leads and forecast status.",
        "Check festival flags and component diagnostics for major SKUs and any unusual jump.",
        "Download/copy only the immutable issued rows for the team.",
        "After the target completes, reconcile Query 1968 and inspect city/SKU WAPE, bias and large absolute errors.",
    ])
    doc.add_heading("15.3 Refresh and retraining", level=2)
    add_code_block(doc, "cd D:\\ML_Forecasting_Model\n.\\scripts\\daily_refresh.ps1 -TrainingQueryId 3269 -TrainChallengers")
    add_para(doc, "The refresh now starts from the latest stored date with a seven-day overlap, rebuilds processed data/features, retrains general and HYD models, retrains cutoff-safe HYD D-2 and BLR D-3 models, reconciles Query 1968 actuals and refreshes accuracy diagnostics. It should not fetch the whole history from 2025 every day.")
    doc.add_heading("15.4 Local services", level=2)
    add_code_block(doc, "# Backend\ncd D:\\ML_Forecasting_Model\\backend\n..\\venv\\Scripts\\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000\n\n# Frontend (separate terminal)\ncd D:\\ML_Forecasting_Model\\frontend\nnpm run dev")

    doc.add_heading("16. What changed: before and after 1 August", level=1)
    add_table(
        doc,
        ["Area", "Before 1 Aug", "Current approach"],
        [
            ("Forecast horizon", "Mostly D-1 thinking/manual date interpretation", "Target-date-first HYD/VGA D-2 and BLR/PNQ D-3"),
            ("Model target", "Raw/total time-series focus", "Final total forecast with deterministic visible-demand floor"),
            ("Multi-step logic", "Recursive predictions could enter future lags", "Direct cutoff-safe HYD D-2 and BLR D-3 models enabled"),
            ("Components", "Limited separation/explainability", "Confirmed subs, unconfirmed subs, known buy-once and remaining gap"),
            ("History", "Manual CSV comparisons and mutable previews", "Immutable issue runs with run IDs and actual reconciliation"),
            ("Actuals", "Comparison sheets could be misordered/misaligned", "Query 1968 joined by date/city/SKU with eligibility gates"),
            ("Festivals", "Incomplete/general event coverage", "197-row national/regional calendar with audits and city features"),
            ("Publication", "Failures could surface as blank/partial requests", "Atomic all-or-none issue and last-frozen fallback"),
            ("Refresh", "Large/full fetch and strict 5% overlap block", "Incremental seven-day overlap, audited append, 30% safety limit"),
            ("Dashboard", "Lead/date handling and dense UI", "Minimal target-date view, filters, exports, status and components"),
        ],
        [1450, 3650, 4260],
        font_size=7.2,
    )
    add_para(doc, "The change in forecast behavior after 31 July was not caused by one proven code line alone. Multiple factors changed together: data freshness/backfills, component queries, horizon policy, festival adjustments, model artifacts and the distinction between live preview versus true issue-time snapshots. The current system adds provenance so these factors can be separated instead of guessed.")

    doc.add_heading("17. Issues encountered and resolutions", level=1)
    add_table(
        doc,
        ["Issue", "Root cause", "Resolution / present behavior"],
        [
            ("Script not found from backend", "Relative path assumed repository root", "Run .\\scripts commands from project root or use ..\\venv from backend."),
            ("Overlap WAPE 21.46%", "Historical rows changed after a query/backfill update", "Audit overlap, preserve old export on failure; current controlled limit 30%."),
            ("Accuracy refresh exit −1", "Long/failed Redash sequence", "Longer async polling, deduplication, retry cooldown and atomic retention."),
            ("No completed shadow forecasts", "Future shadow targets had no settled actuals / insufficient 14 days", "Wait for completed days and reconcile actuals; do not bypass the gate."),
            ("Forecast unchanged after component display change", "Column decomposition changed, total model output did not", "Separate presentation changes from model retraining/serving changes."),
            ("Festival bleed concern", "Potential recursive/event-window contamination", "Static exact-date calendar flags plus direct operational-horizon models and debug features."),
            ("503 subscription failure", "Redash query timeout/connection failure", "No partial official publish; reuse last frozen rows/cache where valid and report degraded state."),
            ("Port 8000 WinError 10048", "Backend already running", "Use the existing server or stop that PID; do not launch a second Uvicorn."),
            ("Dashboard shows only some cities", "Target date requires separate T−2 and T−3 issue runs", "Return PARTIAL frozen view and identify unavailable city group."),
            ("Misleading backtest accuracy", "Historical component queries were rerun today, leaking post-issue state", "Use immutable official_issued rows joined with Query 1968."),
            ("Cow Milk large deviation", "Event/regime shift plus post-issue demand uncertainty; not simply a product swap", "Inspect issue-time components, post-issue arrivals, event flags and direct model output."),
        ],
        [2250, 3300, 3810],
        font_size=6.9,
    )

    doc.add_heading("18. What has been achieved", level=1)
    add_bullets(doc, [
        "One coherent four-city, seven-SKU procurement workflow with explicit D-2/D-3 policy.",
        "Target-date-first dashboard with minimal branded UI, filters, component visibility, CSV download and copy-to-share.",
        "Production Redash contracts documented and unused query files removed from the active folder.",
        "Subscription calculation covers daily, alternate and custom schedules, validity, pauses, customer holidays, city attribution and wallet risk.",
        "Known buy-once demand is measured at the applicable issue cutoff.",
        "Recent actual lags and official final actuals are separated by purpose.",
        "Immutable atomic issuance and historical run IDs prevent silent overwrite of procurement decisions.",
        "Direct cutoff-safe models remove recursive lag contamination for the actual HYD D-2 and BLR D-3 horizons.",
        "Regional festival calendar and historical event analysis now cover previously missed events such as Bonalu and Varamahalakshmi-related dates.",
        "Query 1968 is integrated as the sole comparison truth, with key-based joins and accuracy eligibility checks.",
        "Incremental training refresh avoids re-exporting the full history each day.",
        "Redash reliability protections include asynchronous polling, caching, deduplication, retry cooldown, degraded status and last-good retention.",
        "52 automated tests passed during the latest implementation verification covering query contracts, festival logic, history and operational policy.",
    ])
    add_callout(doc, "Important distinction", "Operational safety, reproducibility and explainability are real achievements. Consistent below-1% forecast error is not yet an achievement and should not be promised to stakeholders.", fill="FFF8E1")

    doc.add_heading("19. Current model evidence and limitation", level=1)
    doc.add_heading("19.1 Latest cutoff-safe direct-horizon validation", level=2)
    add_table(
        doc,
        ["City model", "Period end", "Selected WAPE", "Bias", "Conclusion"],
        [
            ("HYD D-2 direct", "26 Aug 2026", "2.22%", "−1.13%", "Improved, but above 1%"),
            ("BLR D-3 direct", "26 Aug 2026", "3.43%", "−0.45%", "Above city target and 1% aspiration"),
        ],
        [2200, 1700, 1700, 1400, 2360],
        header_fill=YELLOW_STRONG,
    )
    doc.add_heading("19.2 Product WAPE — HYD D-2", level=2)
    add_table(
        doc,
        ["SKU", "Selected method", "WAPE"],
        [
            ("A2 Buffalo Milk", "seasonal-7", "2.20%"),
            ("A2 Desi Cow Milk", "LightGBM", "2.23%"),
            ("Cow Milk", "LightGBM", "2.36%"),
            ("Curd", "LightGBM", "3.62%"),
            ("Double Toned A2 Buffalo Milk", "LightGBM", "1.71%"),
            ("Skim Milk", "LightGBM", "2.23%"),
            ("Toned Milk", "LightGBM", "2.19%"),
        ],
        [5000, 2500, 1860],
    )
    doc.add_heading("19.3 Product WAPE — BLR D-3", level=2)
    add_table(
        doc,
        ["SKU", "Selected method", "WAPE"],
        [
            ("A2 Buffalo Milk", "seasonal-7", "3.42%"),
            ("A2 Desi Cow Milk", "seasonal-7", "3.62%"),
            ("Cow Milk", "LightGBM", "2.51%"),
            ("Curd", "LightGBM", "6.42%"),
            ("Double Toned A2 Buffalo Milk", "LightGBM", "3.63%"),
            ("Skim Milk", "recent mean", "4.69%"),
            ("Toned Milk", "recent mean", "3.77%"),
        ],
        [5000, 2500, 1860],
    )
    doc.add_heading("19.4 Why below 1% is not reached", level=2)
    add_bullets(doc, [
        "At D-2/D-3, the final delivered subscription state is not yet known. Customers can pause/resume, change wallets or cancel after issuance.",
        "Buy-once orders continue to arrive after the forecast is issued. Query 3086 can only include orders already visible at cutoff.",
        "Festival and travel effects vary by city, SKU and year; a single uplift is not stable enough.",
        "Twenty-eight series have different volumes. Low-volume SKUs can show large percentage errors from small packet differences.",
        "Historical issue-time component snapshots are still limited; retrospectively querying a target date does not recreate the original cutoff state.",
        "A tree model cannot compensate for missing operational information through hyperparameter tuning alone.",
    ])
    add_para(doc, "A prototype that assumes final subscription quantities are already known produced approximately 0.71% HYD city-total WAPE and 1.14% BLR city-total WAPE. This demonstrates that the remaining error is strongly tied to subscription-state uncertainty. It is diagnostic evidence only, not a deployable result, because those final subscription values are unavailable at D-2/D-3.")
    add_callout(doc, "Metric discipline", "Do not mix daily absolute percentage error, rolling city WAPE and per-SKU WAPE. Report each separately with date window, horizon, run status and actual source.", fill="EAF2FF", accent=BLUE)

    doc.add_heading("20. Recommended next work — priority order", level=1)
    add_numbered(doc, [
        ("Capture exact cutoff history for at least 60 days. ", "Persist customer/SKU subscription state, wallet state, known buy-once, issue timestamp and eventual final actual for every official run. The existing unknown-demand trainer intentionally blocks before 60 exact days."),
        ("Model post-issue deltas directly. ", "Train separate targets for subscription attrition/recovery and buy-once arrivals between issue time and delivery, by city, SKU, day-of-week and event regime."),
        ("Use official walk-forward evaluation only. ", "Evaluate immutable official_issued rows joined to Query 1968. Maintain separate normal-day and festival scorecards."),
        ("Add calibrated uncertainty. ", "Return P50/P80 or a procurement band so operations can distinguish expected demand from safety stock instead of forcing one false-precision number."),
        ("Run model experiments as challengers. ", "Test log1p targets, residual Holt-Winters + LightGBM, Optuna, SHAP/error segmentation and feature selection without overwriting the serving champion."),
        ("Strengthen event features. ", "Use actual multi-year city/SKU evidence, distance-to-event and event type; never use a broad rolling festival switch."),
        ("Improve service architecture. ", "Move Redash fetching out of the user request path through a scheduled persisted feature snapshot/cache; add structured logs, monitoring, auth and CI/CD."),
        ("Define an achievable business SLA. ", "Use rolling city WAPE, major-SKU WAPE, bias, service level and waste together. A guaranteed <1% for every SKU/day is not statistically supportable with current information."),
    ])
    add_table(
        doc,
        ["Priority", "Deliverable", "Evidence of completion"],
        [
            ("P0", "60+ exact cutoff snapshots", "No reconstructed/current-state rows; complete D-2/D-3 provenance"),
            ("P0", "Official accuracy mart", "Immutable forecast × Query 1968; city/SKU/horizon metrics"),
            ("P1", "Post-issue delta models", "Backtest beats direct-total model across rolling windows"),
            ("P1", "Prediction intervals", "Validated P80 coverage and documented procurement policy"),
            ("P2", "Service modularization/monitoring", "CI tests, structured logs, alerting and deployable config"),
        ],
        [900, 3600, 4860],
    )

    page_break(doc)
    doc.add_heading("21. Troubleshooting guide", level=1)
    add_table(
        doc,
        ["Symptom", "Meaning", "Action"],
        [
            ("status=degraded", "Backend is alive but Redash/freshness failed", "Read last_error and training_data_freshness; check VPN/network and Redash job."),
            ("503 operational forecast", "No valid frozen forecast and live required input failed", "Do not publish partial data; retry Redash after cooldown or restore connectivity."),
            ("PARTIAL frozen rows", "One required issue-date group is absent", "Check T−2 HYD/VGA and T−3 BLR/PNQ issuance separately."),
            ("No completed shadow", "Targets are not settled or minimum evidence not met", "Reconcile actuals and wait for required completed days."),
            ("WinError 10048", "Port 8000 already in use", "Use existing backend or stop the owning PID before restart."),
            ("Training stale", "Latest local training date is too old", "Run incremental refresh through latest completed date, then restart backend."),
            ("Overlap audit fails", "Recent historical values changed beyond threshold", "Investigate Redash definition/backfill; never overwrite blindly."),
            ("Normal day has festival signal", "Calendar/feature join error", "Inspect /api/debug/model_features for exact target event flags."),
            ("Forecast total unchanged", "Only component labels/data changed", "Verify the active model artifact and direct-model flags; restart backend after retraining."),
        ],
        [2300, 3050, 4010],
        font_size=7.2,
    )
    doc.add_heading("21.1 Useful checks", level=2)
    add_code_block(doc, "$s = Invoke-RestMethod http://127.0.0.1:8000/api/status\n$s.status\n$s.redash\n$s.training_data_freshness\n$s.models.hyd_d2_direct_enabled\n$s.models.blr_d3_direct_enabled\n$s.official_issuance")
    add_code_block(doc, "Invoke-RestMethod \"http://127.0.0.1:8000/api/debug/components?date=YYYY-MM-DD\"\nInvoke-RestMethod \"http://127.0.0.1:8000/api/debug/model_features?date=YYYY-MM-DD&city=HYD\"")

    doc.add_heading("22. Repository map", level=1)
    add_table(
        doc,
        ["Path", "Ownership / purpose"],
        [
            ("backend/main.py", "FastAPI, Redash client, serving features, model inference and operational endpoints."),
            ("backend/forecast_history.py", "SQLite run/row persistence, immutable issuance and actual history."),
            ("backend/ml_models/", "Serving artifacts, metrics, features, calendar and procurement plan."),
            ("frontend/src/App.jsx", "Operational dashboard behavior and view state."),
            ("frontend/src/App.css", "Minimal Sid’s Farm UI theme and layout."),
            ("ml_pipeline/", "Cleaning, gap filling, features and model training."),
            ("redash_queries/", "Active production contracts and offline festival/arrival diagnostics."),
            ("scripts/daily_refresh.ps1", "Incremental source refresh, rebuild, retrain, reconcile and backtest orchestration."),
            ("scripts/issue_daily_forecasts.ps1", "Festival validation and daily atomic issuance wrapper."),
            ("scripts/register_daily_forecast_task.ps1", "Windows scheduled-task registration."),
            ("scripts/reconcile_forecast_actuals.py", "Loads Query 1968 actuals into history."),
            ("scripts/build_accuracy_report.py", "Strict key-based external forecast/actual comparison."),
            ("tests/", "Query-contract, festival, history and operational-policy tests."),
            ("docs/", "Data contract, operations and historical analysis notes."),
            ("reports/", "Accuracy, festival, shadow and diagnostic outputs."),
        ],
        [3500, 5860],
        font_size=7.4,
    )

    doc.add_heading("23. Senior developer handover checklist", level=1)
    add_bullets(doc, [
        "Read docs/production_forecast_data_contract.md and docs/production_forecast_operations.md before changing serving logic.",
        "Confirm local .env query IDs match Redash: 3085, 3086, 3101, 1968 and 3269.",
        "Review Query 1968 and Query 3269 definitions together before changing the target.",
        "Never reconstruct official D-2/D-3 performance from today’s live component state.",
        "Preserve immutable issued rows and run IDs during migrations.",
        "Run backend tests plus frontend lint/build before committing.",
        "Inspect git status: the documentation-date worktree contains refreshed data/model artifacts and source changes; review generated versus intentional files before staging.",
        "Restart the backend after model/artifact changes and verify direct-model flags in /api/status.",
        "Do not promote experimental models based on one day. Use multiple rolling windows and minimum completed-day gates.",
        "Communicate current accuracy honestly: production workflow ready for controlled use; below-1% target still under development.",
    ])
    add_callout(doc, "Handover decision", "The next developer should focus first on exact cutoff-state data and official accuracy measurement. More LightGBM tuning is secondary until that data foundation exists.", fill=YELLOW)

    doc.add_heading("Glossary", level=1)
    add_table(
        doc,
        ["Term", "Definition"],
        [
            ("D-2 / D-3", "Forecast issued two or three calendar days before the target delivery date."),
            ("WAPE", "sum(|actual − forecast|) / sum(actual) × 100."),
            ("Bias", "sum(forecast − actual) / sum(actual) × 100; negative means under-forecast."),
            ("Known floor", "Demand visible and considered dependable at issue time."),
            ("Remaining gap", "Model quantity above the known floor required to reach predicted final total."),
            ("Cutoff leakage", "Using information that arrived after the historical decision time."),
            ("Direct horizon", "A model trained specifically for a lead, without recursively feeding intermediate predictions."),
            ("Champion / challenger", "Serving model versus an experimental candidate evaluated in parallel."),
            ("Atomic issuance", "All required forecast rows are published together or none are published."),
            ("Frozen row", "Immutable official forecast stored with its original issue timestamp and run ID."),
        ],
        [2200, 7160],
    )
    add_para(doc, "End of handover", style="Heading 2")
    add_para(doc, "Prepared from the repository state and operational decisions available on 27 August 2026. Secrets, API keys and customer-level data are intentionally excluded.", color=MUTED)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    build_document()
