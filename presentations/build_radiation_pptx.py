#!/usr/bin/env python3
"""Build IGCSE Edexcel Physics presentation: dangers of ionising radiation."""

from copy import deepcopy
from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import nsmap, qn
from pptx.util import Emu, Inches, Pt
from pptx.oxml import parse_xml

NAVY = RGBColor(0x1E, 0x1B, 0x4B)
PURPLE = RGBColor(0x7C, 0x3A, 0xED)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
CREAM = RGBColor(0xF8, 0xF5, 0xFF)
GOLD = RGBColor(0xF5, 0xC5, 0x42)
SOFT = RGBColor(0xE9, 0xE4, 0xF8)
BODY = RGBColor(0x2A, 0x27, 0x4B)
MUTED = RGBColor(0x5B, 0x57, 0x7A)
LILAC = RGBColor(0xC4, 0xB5, 0xFD)

TITLE_FONT = "Alasassy Caps"
BODY_FONT = "Calibri"

SLIDE_W = 12192000
SLIDE_H = 6858000

from pathlib import Path
MEDIA = Path(__file__).resolve().parent / "media"
IMG = {
    "person": str(MEDIA / "image1.png"),
    "trefoil": str(MEDIA / "image2.png"),
    "ion_vs": str(MEDIA / "image3.png"),
    "dna": str(MEDIA / "image4.png"),
}


def emu(x):
    return Emu(int(x))


def set_run(run, text, size=18, bold=False, color=BODY, font=BODY_FONT, italic=False):
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.name = font
    run.font.color.rgb = color
    rPr = run._r.get_or_add_rPr()
    latin = rPr.find(qn("a:latin"))
    if latin is None:
        latin = etree.SubElement(rPr, qn("a:latin"))
    latin.set("typeface", font)


def add_textbox(slide, l, t, w, h, text, size=18, bold=False, color=BODY, font=BODY_FONT,
                align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, italic=False):
    box = slide.shapes.add_textbox(emu(l), emu(t), emu(w), emu(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    try:
        tf._txBody.bodyPr.set("anchor", {MSO_ANCHOR.TOP: "t", MSO_ANCHOR.MIDDLE: "ctr", MSO_ANCHOR.BOTTOM: "b"}[anchor])
    except Exception:
        pass
    p = tf.paragraphs[0]
    p.alignment = align
    set_run(p.add_run(), text, size=size, bold=bold, color=color, font=font, italic=italic)
    return box


def add_paras(slide, l, t, w, h, items, size=16, color=BODY, font=BODY_FONT, spacing=8):
    """items: list of str or (text, kwargs)."""
    box = slide.shapes.add_textbox(emu(l), emu(t), emu(w), emu(h))
    tf = box.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(spacing)
        if isinstance(item, str):
            p.alignment = PP_ALIGN.LEFT
            set_run(p.add_run(), item, size=size, color=color, font=font)
        else:
            text, kw = item
            p.alignment = kw.pop("align", PP_ALIGN.LEFT)
            set_run(p.add_run(), text, size=kw.get("size", size), bold=kw.get("bold", False),
                    color=kw.get("color", color), font=kw.get("font", font), italic=kw.get("italic", False))
    return box


def add_bullets(slide, l, t, w, h, lines, size=16, color=BODY, bullet="•"):
    items = []
    for line in lines:
        if isinstance(line, tuple):
            items.append((f"{bullet}  {line[0]}", line[1]))
        else:
            items.append(f"{bullet}  {line}")
    return add_paras(slide, l, t, w, h, items, size=size, color=color, spacing=6)


def solid_rect(slide, l, t, w, h, color, name="rect"):
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, emu(l), emu(t), emu(w), emu(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    sh.line.fill.background()
    return sh


def triangle(slide, l, t, w, h, color, flip_h=False, flip_v=False):
    sh = slide.shapes.add_shape(MSO_SHAPE.RIGHT_TRIANGLE, emu(l), emu(t), emu(w), emu(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    sh.line.fill.background()
    spPr = sh._element.spPr
    xfrm = spPr.find(qn("a:xfrm"))
    if xfrm is None:
        xfrm = etree.SubElement(spPr, qn("a:xfrm"))
    if flip_h:
        xfrm.set("flipH", "1")
    if flip_v:
        xfrm.set("flipV", "1")
    return sh


def round_rect(slide, l, t, w, h, color):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, emu(l), emu(t), emu(w), emu(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    sh.line.fill.background()
    return sh


def set_slide_bg(slide, color):
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def footer(slide, page, total, light=False):
    col = LILAC if light else MUTED
    add_textbox(slide, 400000, 6500000, 7000000, 300000,
                "IGCSE Edexcel Physics  •  7.15–7.16  •  Made by Malak SII",
                size=11, color=col, font=BODY_FONT)
    add_textbox(slide, 10500000, 6500000, 1400000, 300000,
                f"{page}  /  {total}", size=11, color=col, font=BODY_FONT, align=PP_ALIGN.RIGHT)


def card(slide, l, t, w, h, fill=WHITE):
    sh = round_rect(slide, l, t, w, h, fill)
    # slight purple outline
    sh.line.fill.solid()
    sh.line.color.rgb = RGBColor(0xDD, 0xD6, 0xFE)
    sh.line.width = Pt(1)
    return sh


def title_bar_slide(prs, title, page, total):
    """Content slide: navy left slash + cream body."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, CREAM)
    solid_rect(slide, 0, 0, SLIDE_W, SLIDE_H, CREAM)
    # left navy panel + small corner accents (do not cover body text)
    solid_rect(slide, 0, 0, 160000, SLIDE_H, NAVY)
    triangle(slide, 0, SLIDE_H - 1400000, 1400000, 1400000, NAVY)
    # top navy band
    solid_rect(slide, 0, 0, SLIDE_W, 1100000, NAVY)
    triangle(slide, SLIDE_W - 2200000, 0, 2200000, 1100000, PURPLE, flip_h=True)
    add_textbox(slide, 420000, 220000, 9000000, 700000, title,
                size=28, bold=False, color=WHITE, font=TITLE_FONT, anchor=MSO_ANCHOR.MIDDLE)
    footer(slide, page, total, light=False)
    return slide


def dark_slide(prs, page, total):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, NAVY)
    solid_rect(slide, 0, 0, SLIDE_W, SLIDE_H, NAVY)
    triangle(slide, 0, 0, 5200000, SLIDE_H, RGBColor(0x16, 0x14, 0x3A))
    triangle(slide, SLIDE_W - 4200000, SLIDE_H - 2800000, 4200000, 2800000, PURPLE, flip_h=True, flip_v=True)
    footer(slide, page, total, light=True)
    return slide


def table_slide(slide, l, t, w, h, headers, rows, col_w=None):
    cols = len(headers)
    rcount = 1 + len(rows)
    shape = slide.shapes.add_table(rcount, cols, emu(l), emu(t), emu(w), emu(h))
    table = shape.table
    if col_w:
        for i, cw in enumerate(col_w):
            table.columns[i].width = emu(cw)
    for i, htext in enumerate(headers):
        cell = table.cell(0, i)
        cell.text = ""
        p = cell.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        set_run(p.add_run(), htext, size=13, bold=True, color=WHITE, font=BODY_FONT)
        cell.fill.solid()
        cell.fill.fore_color.rgb = NAVY
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    for r, row in enumerate(rows, 1):
        for c, val in enumerate(row):
            cell = table.cell(r, c)
            cell.text = ""
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER if c > 0 else PP_ALIGN.LEFT
            set_run(p.add_run(), val, size=12, bold=(c == 0), color=BODY, font=BODY_FONT)
            cell.fill.solid()
            cell.fill.fore_color.rgb = WHITE if r % 2 else SOFT
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    return shape


def pill(slide, l, t, w, h, text, fill=PURPLE, tcolor=WHITE, size=14):
    sh = round_rect(slide, l, t, w, h, fill)
    add_textbox(slide, l, t, w, h, text, size=size, bold=True, color=tcolor,
                font=BODY_FONT, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    return sh


def build():
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    TOTAL = 20

    # 1 Title
    s = dark_slide(prs, 1, TOTAL)
    try:
        s.shapes.add_picture(IMG["person"], emu(8800000), emu(800000), emu(3000000), emu(4520000))
    except Exception:
        pass
    add_textbox(s, 500000, 1600000, 8200000, 1600000,
                "The dangers to health\nof ionising radiation",
                size=40, color=WHITE, font=TITLE_FONT)
    pill(s, 500000, 3600000, 4200000, 420000, "IGCSE Edexcel Physics  •  Radioactivity", fill=PURPLE)
    add_textbox(s, 500000, 4200000, 7000000, 800000,
                "Specification 7.15–7.16\nContamination, irradiation, cell damage, mutations and radioactive waste",
                size=16, color=LILAC, font=BODY_FONT)
    add_textbox(s, 500000, 5300000, 5000000, 400000, "Made by Malak SII",
                size=18, color=GOLD, font=TITLE_FONT)

    # 2 Learning objectives
    s = title_bar_slide(prs, "What you need to know", 2, TOTAL)
    add_textbox(s, 420000, 1300000, 11000000, 400000,
                "Pearson Edexcel International GCSE Physics (4PH1) — Radioactivity",
                size=14, italic=True, color=PURPLE)
    cards = [
        ("7.4 / 7.5", "Know that α, β and γ are ionising radiations from unstable nuclei, and compare ionising power and penetrating power."),
        ("7.15", "Describe the difference between contamination and irradiation."),
        ("7.16", "Describe the dangers of ionising radiation: mutations, cell and tissue damage, and problems of radioactive waste — plus how risks are reduced."),
        ("Exam skill", "Use the correct terms, link ionisation to DNA damage, and explain why α is most dangerous inside the body."),
    ]
    for i, (code, text) in enumerate(cards):
        y = 1800000 + i * 1100000
        card(s, 420000, y, 11300000, 1000000)
        pill(s, 520000, y + 280000, 1600000, 440000, code, fill=NAVY, size=13)
        add_textbox(s, 2300000, y + 180000, 9200000, 700000, text, size=16, color=BODY)

    # 3 What is ionising radiation
    s = title_bar_slide(prs, "What is ionising radiation?", 3, TOTAL)
    card(s, 420000, 1400000, 7200000, 4800000)
    add_paras(s, 620000, 1600000, 6800000, 4500000, [
        ("Ionising radiation is radiation with enough energy to remove electrons from atoms, forming ions.", {"size": 18, "bold": True, "color": NAVY}),
        "",
        "That is why it can damage living cells: it changes atoms and molecules inside the body.",
        "",
        ("Examples you must know:", {"bold": True, "color": PURPLE, "size": 16}),
        "•  Alpha particles (α)  — helium nuclei (2 protons + 2 neutrons)",
        "•  Beta particles (β)  — fast electrons from the nucleus",
        "•  Gamma rays (γ)  — high-energy electromagnetic waves",
        "•  X-rays  — also EM waves; produced in X-ray tubes, not by nuclei",
        "",
        "Neutron radiation is also on the specification for nuclear equations, but α, β and γ are the main ionising types discussed for health hazards.",
    ], size=15, spacing=4)
    try:
        s.shapes.add_picture(IMG["ion_vs"], emu(7800000), emu(1600000), emu(4000000), emu(1960000))
    except Exception:
        pass
    card(s, 7800000, 3800000, 4000000, 2400000, fill=NAVY)
    add_paras(s, 8000000, 4000000, 3600000, 2100000, [
        ("Key idea", {"size": 16, "bold": True, "color": GOLD, "font": TITLE_FONT}),
        "Non-ionising radiation (radio, microwaves, visible light) does not have enough energy to knock electrons off atoms.",
        "Only ionising radiation can directly damage DNA this way.",
    ], size=14, color=WHITE, spacing=8)

    # 4 Types table
    s = title_bar_slide(prs, "Comparing α, β and γ", 4, TOTAL)
    add_textbox(s, 420000, 1250000, 11000000, 350000,
                "You distinguish them by nature, charge, ionising power and penetrating power.",
                size=15, italic=True, color=MUTED)
    table_slide(
        s, 420000, 1650000, 11300000, 3800000,
        ["Property", "Alpha (α)", "Beta (β)", "Gamma (γ)"],
        [
            ["Nature", "Helium nucleus\n(2p + 2n)", "Fast electron", "EM wave\n(photon)"],
            ["Charge / mass", "+2  •  heavy", "−1  •  light", "0  •  no mass"],
            ["Ionising power", "Very high", "Medium", "Low"],
            ["Penetrating power", "Very low", "Medium", "Very high"],
            ["Stopped by", "Paper / skin\n/ few cm of air", "A few mm of\naluminium", "Reduced by thick\nlead or concrete"],
            ["Range in air", "A few centimetres", "Up to ~1 metre", "Unlimited (intensity falls)"],
        ],
        col_w=[2500000, 2933333, 2933333, 2933334],
    )

    # 5 Why ionising power matters
    s = title_bar_slide(prs, "Why this matters inside the body", 5, TOTAL)
    facts = [
        ("Alpha — most ionising",
         "α particles dump a lot of energy in a very small volume of tissue. They cannot reach organs from outside (skin stops them), but if a source is swallowed, inhaled or in a wound they are the most damaging."),
        ("Beta — medium",
         "β particles travel further than α, so they can damage cells a short distance into the body. Thin metal or plastic shielding is used to reduce the risk."),
        ("Gamma — most penetrating",
         "γ rays pass through the body easily. They are weakly ionising per millimetre, but they can irradiate deep organs from outside. Thick lead or concrete is needed to absorb them."),
    ]
    for i, (h, t) in enumerate(facts):
        x = 420000 + i * 3850000
        card(s, x, 1450000, 3650000, 4200000)
        solid_rect(s, x, 1450000, 3650000, 160000, PURPLE if i == 0 else NAVY)
        add_textbox(s, x + 180000, 1750000, 3300000, 800000, h, size=18, bold=True, color=NAVY)
        add_textbox(s, x + 180000, 2600000, 3300000, 2800000, t, size=15, color=BODY)
    add_textbox(s, 420000, 5800000, 11300000, 500000,
                "Exam line:  The more strongly ionising the radiation, the more damage it does per millimetre of tissue — but the less far it travels.",
                size=14, italic=True, color=PURPLE)

    # 6 How cells are damaged (original content expanded)
    s = title_bar_slide(prs, "How does ionising radiation damage cells?", 6, TOTAL)
    card(s, 420000, 1400000, 7000000, 4800000)
    add_paras(s, 620000, 1550000, 6600000, 4500000, [
        ("When ionising radiation enters the body, it interacts with atoms and molecules in cells.", {"size": 17, "bold": True, "color": NAVY}),
        "",
        "This can:",
        "•  Remove electrons (ionisation)",
        "•  Break chemical bonds",
        "•  Damage DNA in the nucleus",
        "•  Create highly reactive molecules (free radicals) from water in the cell",
        "•  Damage or kill cells",
        "",
        "If the damage is severe, the cell may die. If damaged DNA is not correctly repaired, the cell may become abnormal and divide out of control.",
    ], size=16, spacing=5)
    try:
        s.shapes.add_picture(IMG["dna"], emu(7600000), emu(1500000), emu(4200000), emu(4200000))
    except Exception:
        pass

    # 7 DNA mutations
    s = title_bar_slide(prs, "Mutations and cancer", 7, TOTAL)
    add_textbox(s, 420000, 1280000, 11000000, 400000,
                "A mutation is a change in the DNA of a cell. This is a core 7.16 point.",
                size=15, italic=True, color=MUTED)
    boxes = [
        ("1. DNA hit", "Ionising radiation breaks strands or changes bases in DNA."),
        ("2. Faulty repair", "The cell may repair the DNA wrongly, or fail to repair it."),
        ("3. Mutation", "The genetic code is permanently changed."),
        ("4. Possible cancer", "If genes that control cell division are mutated, cells can divide uncontrollably — a tumour / cancer."),
    ]
    for i, (h, t) in enumerate(boxes):
        x = 420000 + (i % 4) * 2850000
        card(s, x, 1750000, 2700000, 2500000)
        pill(s, x + 150000, 1900000, 2400000, 450000, h, fill=PURPLE if i == 3 else NAVY, size=13)
        add_textbox(s, x + 150000, 2500000, 2400000, 1550000, t, size=14, color=BODY)
    card(s, 420000, 4450000, 11300000, 1750000, fill=NAVY)
    add_paras(s, 620000, 4600000, 10900000, 1500000, [
        ("Two places mutations matter", {"size": 16, "bold": True, "color": GOLD, "font": TITLE_FONT}),
        "•  Body (somatic) cells  →  may cause cancer in that person later.",
        "•  Reproductive cells (sperm / egg)  →  a mutation can be passed to offspring.",
        "Higher dose, longer exposure, and more strongly ionising radiation all increase the chance of harmful mutations.",
    ], size=15, color=WHITE, spacing=6)

    # 8 Cell and tissue damage
    s = title_bar_slide(prs, "Damage to cells and tissue", 8, TOTAL)
    add_textbox(s, 420000, 1250000, 11000000, 350000,
                "Effects depend on dose, time of exposure, type of radiation, and which organ is hit.",
                size=15, italic=True, color=MUTED)
    table_slide(
        s, 420000, 1650000, 11300000, 3200000,
        ["Type of effect", "What happens", "Typical result"],
        [
            ["Cell death", "So many cells are killed that the tissue cannot work", "Burns, hair loss, organ failure at very high dose"],
            ["Tissue damage", "Organs that divide quickly are most sensitive", "Skin, bone marrow, gut lining"],
            ["Mutation", "DNA changed; cell still lives", "Increased cancer risk"],
            ["Sterility / unborn baby", "Reproductive tissue or a foetus is exposed", "Infertility or harm to a developing baby"],
        ],
        col_w=[2800000, 4500000, 4000000],
    )
    card(s, 420000, 5050000, 11300000, 1150000)
    add_textbox(s, 620000, 5200000, 10900000, 900000,
                "IGCSE focus: you do not need named diseases in detail. You do need: radiation can kill cells / damage tissue, and it can cause mutations that may lead to cancer.",
                size=16, color=NAVY)

    # 9 Contamination vs irradiation
    s = title_bar_slide(prs, "Contamination vs irradiation  (7.15)", 9, TOTAL)
    card(s, 420000, 1400000, 5450000, 4300000)
    pill(s, 620000, 1600000, 2800000, 450000, "IRRADIATION", fill=PURPLE)
    add_bullets(s, 620000, 2200000, 5000000, 3300000, [
        "The object / person is exposed to radiation from an outside source.",
        "No radioactive material is transferred.",
        "The person does not become radioactive.",
        "Exposure stops when the source is removed or shielded.",
        "Example: a hospital X-ray; standing near a sealed gamma source.",
    ], size=15)

    card(s, 6050000, 1400000, 5450000, 4300000)
    pill(s, 6250000, 1600000, 3200000, 450000, "CONTAMINATION", fill=NAVY)
    add_bullets(s, 6250000, 2200000, 5050000, 3300000, [
        "Radioactive material gets onto or into the object / person (dust, liquid, gas).",
        "The person now carries a source and keeps being irradiated.",
        "Especially dangerous if swallowed or inhaled (α inside the body).",
        "Radiation continues until the material is removed or decays.",
        "Example: radioactive powder on skin; radon gas in lungs.",
    ], size=15)

    add_textbox(s, 420000, 5850000, 11300000, 450000,
                "Food and surgical instruments can be irradiated on purpose to kill bacteria — they are not left radioactive.",
                size=14, italic=True, color=PURPLE)

    # 10 comparison table
    s = title_bar_slide(prs, "Side-by-side comparison", 10, TOTAL)
    table_slide(
        s, 420000, 1400000, 11300000, 4200000,
        ["Feature", "Irradiation", "Contamination"],
        [
            ["Radioactive material present?", "No", "Yes"],
            ["Object becomes a source?", "No", "Yes"],
            ["Stops when you walk away?", "Yes (source stays behind)", "No — source is on/in you"],
            ["Can make you radioactive?", "No", "Yes (you emit radiation)"],
            ["Typical prevention", "Time, distance, shielding", "Sealed sources, gloves, suits, no eating/drinking in labs"],
            ["Example", "X-ray of a broken bone", "Spill of radioactive liquid on a bench"],
        ],
        col_w=[3300000, 4000000, 4000000],
    )

    # 11 Reducing risk
    s = title_bar_slide(prs, "Reducing the hazard  —  time, distance, shielding", 11, TOTAL)
    tri = [
        ("TIME", "Keep exposure as short as possible. Plan the task. Do not linger near a source."),
        ("DISTANCE", "Stay as far away as you can. Use tongs or remote handling. Intensity falls quickly with distance."),
        ("SHIELDING", "Put a suitable absorber between you and the source: paper/plastic for β, thick lead or concrete for γ."),
    ]
    for i, (h, t) in enumerate(tri):
        x = 420000 + i * 3850000
        card(s, x, 1400000, 3650000, 2800000)
        pill(s, x + 200000, 1600000, 3250000, 500000, h, size=16)
        add_textbox(s, x + 200000, 2300000, 3250000, 1700000, t, size=15, color=BODY)
    card(s, 420000, 4400000, 11300000, 1800000, fill=NAVY)
    add_paras(s, 620000, 4550000, 10900000, 1550000, [
        ("Other IGCSE precautions", {"size": 16, "bold": True, "color": GOLD, "font": TITLE_FONT}),
        "•  Store sources in lead-lined boxes  •  never point a source at anyone  •  wear gloves / lab coats to avoid contamination",
        "•  Monitor with a Geiger–Müller detector or photographic film badge  •  radioactive symbol on stores and rooms",
        "•  Limit who is allowed near sources  •  do not eat, drink or apply makeup in a radioactivity lab",
    ], size=14, color=WHITE, spacing=6)

    # 12 Why alpha inside is worst
    s = title_bar_slide(prs, "Which radiation is most dangerous?", 12, TOTAL)
    card(s, 420000, 1400000, 11300000, 1500000, fill=NAVY)
    add_textbox(s, 620000, 1550000, 10900000, 1200000,
                "Outside the body:  γ (and X-rays) are the main hazard because they penetrate skin and organs.\n"
                "Inside the body:  α is the worst because it is the most strongly ionising — all its energy is absorbed by nearby cells.",
                size=17, color=WHITE)
    table_slide(
        s, 420000, 3100000, 11300000, 2600000,
        ["Situation", "Biggest risk", "Why"],
        [
            ["Sealed source across the room", "Gamma", "α and β may not even reach you; γ can"],
            ["Source on the skin", "Beta (and γ)", "α stopped by outer dead skin; β can burn living skin"],
            ["Dust inhaled / food swallowed", "Alpha", "No skin barrier; dense ionisation in lungs or gut"],
        ],
        col_w=[3800000, 2500000, 5000000],
    )

    # 13 Radioactive waste
    s = title_bar_slide(prs, "Radioactive waste  (7.16)", 13, TOTAL)
    add_textbox(s, 420000, 1250000, 11000000, 400000,
                "Waste keeps emitting ionising radiation. Some isotopes have half-lives of thousands of years.",
                size=15, italic=True, color=MUTED)
    sources = [
        ("Nuclear power", "Spent fuel rods are very hot and highly radioactive. They must be stored, not dumped."),
        ("Hospitals", "Used in diagnosis and cancer treatment. Sources and contaminated items become waste."),
        ("Industry & research", "Tracers, thickness gauges, labs. Must be collected and stored safely."),
    ]
    for i, (h, t) in enumerate(sources):
        y = 1750000 + i * 1450000
        card(s, 420000, y, 11300000, 1300000)
        pill(s, 620000, y + 400000, 2800000, 500000, h, fill=NAVY, size=14)
        add_textbox(s, 3600000, y + 250000, 7900000, 850000, t, size=16, color=BODY)

    # 14 Reducing waste risk
    s = title_bar_slide(prs, "How the risks from waste are reduced", 14, TOTAL)
    rows = [
        ("Shielded containers", "Lead, steel or concrete absorbs radiation so workers and the public are not irradiated."),
        ("Remote handling", "Robots or long tongs keep people away from high-activity waste."),
        ("Cooling / ponds", "Spent fuel is stored under water at first. Water cools it and acts as a shield."),
        ("Secure storage", "Sealed stores stop leaks into soil, air or drinking water (prevents contamination)."),
        ("Deep geological disposal", "Long-lived waste can be buried deep underground, isolated for a very long time."),
        ("Monitor and restrict access", "Warning signs, GM monitors, and limited access reduce accidental exposure."),
    ]
    for i, (h, t) in enumerate(rows):
        col = i % 2
        row = i // 2
        x = 420000 + col * 5750000
        y = 1350000 + row * 1600000
        card(s, x, y, 5550000, 1450000)
        add_textbox(s, x + 200000, y + 180000, 5150000, 400000, h, size=16, bold=True, color=PURPLE)
        add_textbox(s, x + 200000, y + 600000, 5150000, 700000, t, size=14, color=BODY)

    # 15 Background radiation
    s = title_bar_slide(prs, "Background radiation  (linked idea 7.10)", 15, TOTAL)
    add_textbox(s, 420000, 1250000, 11000000, 450000,
                "We are always exposed to a low level of ionising radiation. It is not usually a large extra risk, but you must know the sources.",
                size=15, italic=True, color=MUTED)
    bg = [
        ("Radon gas", "From rocks and soil; can collect in buildings. An α emitter if inhaled."),
        ("Rocks & building materials", "Natural radioactive isotopes in granite and bricks."),
        ("Cosmic rays", "High-energy radiation from space. Greater in aircraft and at high altitude."),
        ("Food and drink", "Tiny amounts of natural isotopes (e.g. carbon-14, potassium-40)."),
        ("Medical uses", "X-rays, CT scans, nuclear medicine — useful, but they add a dose."),
        ("Nuclear industry / fallout", "A small fraction of average background in most places."),
    ]
    for i, (h, t) in enumerate(bg):
        x = 420000 + (i % 3) * 3850000
        y = 1800000 + (i // 3) * 2100000
        card(s, x, y, 3650000, 1900000)
        add_textbox(s, x + 180000, y + 200000, 3300000, 500000, h, size=16, bold=True, color=NAVY)
        add_textbox(s, x + 180000, y + 750000, 3300000, 950000, t, size=14, color=BODY)

    # 16 Uses vs dangers
    s = title_bar_slide(prs, "Uses still involve a hazard", 16, TOTAL)
    add_textbox(s, 420000, 1250000, 11000000, 400000,
                "7.14 uses of radioactivity — always balanced against 7.16 dangers.",
                size=15, italic=True, color=MUTED)
    uses = [
        ("Cancer radiotherapy", "High dose of γ (or other beams) is aimed at a tumour to kill cancer cells. Nearby healthy tissue must be shielded or the beam shaped."),
        ("Tracers in medicine", "A small amount of a short-half-life gamma emitter is swallowed or injected. The patient is briefly irradiated from inside; contamination of other people is controlled."),
        ("Sterilising equipment / food", "Gamma irradiation kills bacteria. The objects do not become radioactive."),
        ("Smoke alarms", "Americium-241 (α) ionises air in the detector. The source is sealed so you are not contaminated."),
        ("Thickness gauges / industry", "β or γ through paper, foil or metal. Workers stay behind shielding."),
        ("Nuclear power", "Fission produces heat and a large amount of radioactive waste that must be stored for a long time."),
    ]
    for i, (h, t) in enumerate(uses):
        y = 1700000 + i * 750000
        solid_rect(s, 420000, y, 180000, 600000, PURPLE if i % 2 == 0 else GOLD)
        add_textbox(s, 720000, y, 3000000, 600000, h, size=14, bold=True, color=NAVY, anchor=MSO_ANCHOR.MIDDLE)
        add_textbox(s, 3800000, y, 7900000, 600000, t, size=13, color=BODY, anchor=MSO_ANCHOR.MIDDLE)

    # 17 Exam phrases
    s = title_bar_slide(prs, "Phrases that gain marks", 17, TOTAL)
    phrases = [
        "Ionising radiation can remove electrons from atoms in cells.",
        "This can damage or kill cells / damage tissue.",
        "It can cause mutations in DNA, which may lead to cancer.",
        "Mutations in reproductive cells can be inherited.",
        "Irradiation is exposure to radiation; the object does not become radioactive.",
        "Contamination is unwanted radioactive material on or in a person / object.",
        "Alpha is the most ionising, so most dangerous if the source is inside the body.",
        "Gamma is the most penetrating, so most dangerous from outside the body.",
        "Reduce risk by reducing time, increasing distance, and using shielding.",
        "Radioactive waste remains hazardous for a long time because of long half-lives; store it shielded and isolated.",
    ]
    for i, p in enumerate(phrases):
        y = 1220000 + i * 510000
        n = f"{i+1:02d}"
        pill(s, 420000, y, 700000, 400000, n, fill=NAVY, size=12)
        add_textbox(s, 1250000, y, 10400000, 400000, p, size=15, color=BODY, anchor=MSO_ANCHOR.MIDDLE)

    # 18 Practice questions
    s = title_bar_slide(prs, "Practice questions", 18, TOTAL)
    qs = [
        "1.  Define ionising radiation. Name the three types emitted by unstable nuclei.",
        "2.  Explain why alpha radiation is more dangerous than gamma radiation if a source is swallowed, but less dangerous if the source is outside the body.",
        "3.  A technician stands near a sealed cobalt-60 source. Is this contamination or irradiation? Explain.",
        "4.  Radioactive powder is spilled on a glove. Identify the hazard and say how the risk should be reduced.",
        "5.  Describe how ionising radiation can cause cancer.",
        "6.  State two problems of disposing of radioactive waste and two ways of reducing the risk.",
        "7.  Give three precautions taken in a school lab when using sealed radioactive sources.",
        "8.  Food can be irradiated to kill bacteria. Explain why the food is not radioactive afterwards.",
    ]
    add_paras(s, 420000, 1300000, 11300000, 5000000,
              [(q, {"size": 16, "color": BODY}) for q in qs], size=16, spacing=10)

    # 19 Answers
    s = title_bar_slide(prs, "Outline answers", 19, TOTAL)
    ans = [
        "1.  Radiation with enough energy to remove electrons / form ions. α, β, γ.",
        "2.  Inside: α is highly ionising so it damages nearby cells a lot; γ is weakly ionising. Outside: skin / air stop α, so it does not reach organs; γ penetrates the body.",
        "3.  Irradiation — sealed source, no material transferred, technician does not become radioactive.",
        "4.  Contamination. Do not touch with bare skin; remove glove as hazardous waste; wash; monitor with a GM detector; prevent powder spreading.",
        "5.  Radiation damages DNA → mutation → cell may divide uncontrollably → cancer.",
        "6.  Problems: remains radioactive for a long time; can contaminate land/water and harm people. Reduce: shielded containers, remote handling, secure / deep underground storage, restricted access.",
        "7.  Any three: tongs; store in lead box; short time; keep distance; never point at people; film badge / GM check; no eating in lab.",
        "8.  Irradiation does not transfer radioactive nuclei to the food; only energy is delivered, so the food does not become a source.",
    ]
    add_paras(s, 420000, 1250000, 11300000, 5100000,
              [(a, {"size": 14, "color": BODY}) for a in ans], size=14, spacing=8)

    # 20 End
    s = dark_slide(prs, 20, TOTAL)
    try:
        s.shapes.add_picture(IMG["trefoil"], emu(9200000), emu(1800000), emu(2200000), emu(2200000))
    except Exception:
        pass
    add_textbox(s, 500000, 1400000, 8500000, 1200000, "Remember this",
                size=36, color=WHITE, font=TITLE_FONT)
    add_paras(s, 500000, 2700000, 8500000, 2800000, [
        "Ionise  →  damage cells / DNA  →  death or mutation (cancer).",
        "Irradiation ≠ contamination.",
        "Time  •  distance  •  shielding.",
        "Waste: long-lived, must be stored and isolated.",
    ], size=20, color=WHITE, spacing=12)
    add_textbox(s, 500000, 5300000, 8000000, 500000, "Made by Malak SII   •   IGCSE Edexcel Physics",
                size=16, color=GOLD, font=TITLE_FONT)

    out = "/workspace/presentations/Damage_of_Ionizing_Radiation_to_Humans.pptx"
    prs.save(out)
    print("saved", out, "slides", len(prs.slides))
    return out


if __name__ == "__main__":
    build()
