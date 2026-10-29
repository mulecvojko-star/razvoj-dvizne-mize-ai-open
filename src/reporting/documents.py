"""A4 PDFs and a formula-based Excel workbook. Values come only from the handoff."""

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.graphics.shapes import Drawing, Line, String, PolyLine
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.workbook.properties import CalcProperties

NAVY = colors.HexColor("#17344C")
TEAL = colors.HexColor("#187A83")
WIDTH = A4[0] - 36*mm
MISSING = "Ni določeno – manjkajo vhodni podatki."
LABELS = {"konstruktor": "Konstruktor", "hidravlik": "Hidravlik", "ekonomist": "Ekonomist", "recenzent": "Recenzent"}


def fonts():
    if "DV" not in pdfmetrics.getRegisteredFontNames():
        root = Path(__file__).with_name("fonts")
        pdfmetrics.registerFont(TTFont("DV", str(root/"DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DV-Bold", str(root/"DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-Bold", italic="DV", boldItalic="DV-Bold")


def fmt(value, digits=2):
    if value is None:
        return MISSING
    if isinstance(value, bool):
        return "da" if value else "ne"
    if isinstance(value, (float, int)):
        return f"{value:,.{digits}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return str(value)


def paragraph(text, *, small=False, heading=False):
    style = ParagraphStyle("DV", fontName="DV-Bold" if heading else "DV", fontSize=12 if heading else 7.5 if small else 9,
                           leading=17 if heading else 11 if small else 14, textColor=NAVY if heading else colors.HexColor("#233342"),
                           spaceBefore=12 if heading else 0, spaceAfter=7, splitLongWords=1, keepWithNext=heading)
    return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)


def table(headers, rows, widths=None):
    widths = widths or [WIDTH/len(headers)]*len(headers)
    data = [[paragraph(value, small=True) for value in row] for row in [headers, *rows]]
    result = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    result.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#E1EBF1")),
                               ("VALIGN", (0,0), (-1,-1), "TOP"), ("GRID", (0,0), (-1,-1), .3, colors.HexColor("#CAD6DE")),
                               ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6),
                               ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 2),
                               ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F5F8FA")])]))
    return result


def section(story, title, texts):
    story.append(paragraph(title, heading=True))
    for text in texts:
        story.append(paragraph(text))


def agent_text(story, data):
    section(story, "Povzetek agenta", [data.get("summary", "Deterministični simulirani rezultat.")])
    if data.get("outputs"):
        story.append(table(["Rezultat", "Vrednost / enota", "Podlaga"],
                           [[r["name"], (f"{r['value']} [{r['unit']}]" if len(str(r["value"])) <= 300 else "Dolga izvirna vrednost je v 05_Izvorni_podatki.json; numerični pregled je v tabelah tega poročila."), r["basis"]] for r in data["outputs"]],
                           [WIDTH*.23, WIDTH*.42, WIDTH*.35]))
    section(story, "Odprta vprašanja agenta", data.get("open_questions") or ["Agent ni navedel dodatnih vprašanj; nepreverjeni tehnični detajli ostajajo odprti."])


def graph(xs, ys, xlabel, ylabel):
    width, height = WIDTH, 205
    left, bottom, right, top = 62, 40, width-18, height-25
    drawing = Drawing(width, height)
    xmin, xmax = min(xs), max(xs)
    ymax = max(ys)*1.1 or 1
    for i in range(5):
        y = bottom+(top-bottom)*i/4
        drawing.add(Line(left,y,right,y,strokeColor=colors.HexColor("#D9E2E8"),strokeWidth=.5))
        drawing.add(String(left-8,y-3,fmt(ymax*i/4,1),fontName="DV",fontSize=7,textAnchor="end"))
    drawing.add(Line(left,bottom,right,bottom,strokeColor=NAVY))
    drawing.add(Line(left,bottom,left,top,strokeColor=NAVY))
    for i in range(6):
        x=left+(right-left)*i/5
        drawing.add(String(x,bottom-15,fmt(xmin+(xmax-xmin)*i/5,0),fontName="DV",fontSize=7,textAnchor="middle"))
    points=[]
    for x,y in zip(xs,ys):
        points.extend([left+(right-left)*(x-xmin)/(xmax-xmin or 1),bottom+(top-bottom)*y/ymax])
    drawing.add(PolyLine(points,strokeColor=TEAL,strokeWidth=2))
    drawing.add(String((left+right)/2,5,xlabel,fontName="DV",fontSize=8,textAnchor="middle"))
    drawing.add(String(left, height-10,ylabel,fontName="DV-Bold",fontSize=8))
    return drawing


def pdf(path, title, handoff, story, provenance):
    fonts()
    label=handoff.label
    def page(canvas, doc):
        canvas.setFont("DV",7)
        canvas.setFillColor(NAVY)
        canvas.drawString(18*mm,A4[1]-13*mm,f"{label}  |  RAZVOJNI PAKET  |  SINTETIČNI PODATKI")
        canvas.setStrokeColor(colors.HexColor("#CCD8E0"))
        canvas.line(18*mm,16*mm,A4[0]-18*mm,16*mm)
        canvas.drawString(18*mm,11*mm,"Preliminarno – ni tehnično potrjeno – engineering_verified=false")
        canvas.drawRightString(A4[0]-18*mm,11*mm,f"Stran {doc.page}")
    opening=[paragraph(f"{label} · {title}",heading=True),
             paragraph("IZOBRAŽEVALNI PREIZKUS · Sintetični podatki. Uspešno izveden programski cikel ne pomeni tehnično potrjene konstrukcije. Status: changes_required; engineering_verified=false.")]
    ending=[paragraph("Sledljivost",heading=True),paragraph(f"Izvor: {provenance.get('input_file','zaključena predaja cikla')}; SHA-256: {provenance.get('input_file_sha256','vključen v 05_Izvorni_podatki.json')}",small=True)]
    manifest=provenance.get("manifest",{})
    if manifest:
        ending.append(paragraph(f"GitHub run: {manifest.get('run_id','ni podan')}; commit: {manifest.get('commit','ni podan')}; model: {manifest.get('configuration',{}).get('model','ni podan')}",small=True))
    SimpleDocTemplate(str(path),pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=22*mm,bottomMargin=23*mm,
                      title=f"{label} – {title}",author="Razvoj dvižne mize – štirje agenti").build(opening+ending+story,onFirstPage=page,onLaterPages=page)


def requirements(handoff):
    names={"payload_kg":("Nosilnost","kg"),"platform_length_mm":("Dolžina ploščadi","mm"),
           "platform_width_mm":("Širina ploščadi","mm"),"min_height_mm":("Najnižja višina","mm"),
           "max_height_mm":("Najvišja višina","mm")}
    return [[name,fmt(handoff.inputs[key]),unit] for key,(name,unit) in names.items()]


def make_pdfs(root, handoff, provenance):
    fonts()
    c,h,e,r=[handoff.results[n]["engineering"] for n in LABELS]
    summary=[paragraph("Vhodne tehnične zahteve",heading=True),table(["Zahteva","Vrednost","Enota"],requirements(handoff))]
    section(summary,"Glavni rezultati",[f"Ploščad {fmt(handoff.inputs['platform_length_mm'],0)} × {fmt(handoff.inputs['platform_width_mm'],0)} mm. Potreben dvig: {fmt(c['lift_mm'])} mm.",
        f"Največja sila enega cilindra: {fmt(c['peak_cylinder_force_N']/1000)} kN ({fmt(c['peak_cylinder_force_N'])} N). Zahtevani hod: {fmt(c['stroke_mm'])} mm.",
        f"Nepopoln sintetični vmesni seštevek: {fmt(e['synthetic_subtotal_EUR'])} EUR. Potrjena skupna cena naprave NI DOLOČENA; neznani stroški niso nič EUR.",
        "Končna tehnična odločitev: changes_required. Numerične kontrole so opravljene; nadaljnje strokovne preverbe so obvezne."])
    for name in LABELS:
        section(summary,LABELS[name],[handoff.results[name].get("summary",handoff.results[name].get("concept",handoff.results[name].get("analysis",handoff.results[name].get("basis","Lokalno izračunana preliminarna predaja."))))])
    section(summary,"Glavne nadaljnje preveritve",[f"{LABELS.get(f['target_agent'],'Ročni pregled')}: {f['required_correction']}" for f in r["findings"]])
    section(summary,"Zbrana odprta vprašanja",handoff.open_questions or ["Glej odprte ugotovitve recenzenta."])
    pdf(root/"00_Povzetek.pdf","Povzetek razvojne variante",handoff,summary,provenance)

    story=[]
    section(story,"Konstrukcijski koncept",["Enostopenjska škarjasta miza: dve vzporedni ravnini s štirimi rokami in en osrednji iztezni cilinder prek prečne povezave.",c["coordinate_system"],
        "A=(0,0), B=(s,0), C=(s,h), D=(0,h); roki AC in BD. A je spodnji fiksni sklep, B spodnji drsnik, D sklep na ploščadi in C zgornji drsnik."])
    story.append(table(["Zahteva","Vrednost","Enota"],requirements(handoff)))
    section(story,"Prečna razporeditev",[f"Ravnini škarij y: {'; '.join(fmt(v) for v in c['scissor_plane_y_mm'])} mm; os cilindra y={fmt(c['cylinder_y_mm'])} mm."])
    section(story,"Predpostavke in uporabljeni parametri",c["assumptions"])
    parameter_names={"arm_length_mm":"Dolžina roke [mm]", "structure_offset_mm":"Skupni višinski odmik [mm]",
                     "cylinder_base_x_mm":"Vpetje cilindra a [mm]", "rod_pin_fraction":"Delež vpetja f [1]",
                     "moving_mass_kg":"Premična masa [kg]", "load_factor":"Faktor obremenitve [1]",
                     "mechanical_efficiency":"Mehanski izkoristek [1]", "gravity_m_s2":"Težni pospešek [m/s²]"}
    story.append(table(["Parameter","Podana vrednost"],[[parameter_names.get(k,k),fmt(v)] for k,v in c["parameters"].items()],[WIDTH*.55,WIDTH*.45]))
    section(story,"Uporabljene formule",["h = H − odmik; s = sqrt(L² − h²); kot = asin(h/L).",
        "E=(a,0); P=(f·s,f·h); l = sqrt((f·s−a)² + (f·h)²).",
        "dl/dH = a·f·h/(l·s); W = (nosilnost + premična masa)·g·faktor; F = W/(eta·dl/dH).",
        "Hod = l(zgornja lega) − l(spodnja lega). Vrednosti spodaj so prenesene iz izvorne predaje, ne ponovno optimizirane."])
    section(story,"Tabela vseh 11 računskih položajev",[])
    rows=c["positions"]
    story.append(table(["H [mm]","h [mm]","s [mm]","Kot [°]","l [mm]","F [N]"],
                       [[fmt(x[k]) for k in ("platform_height_mm","scissor_height_mm","span_mm","angle_deg","cylinder_length_mm","cylinder_force_N")] for x in rows]))
    section(story,"Koordinate vpetij in sredinskega sklepa [mm]",[])
    story.append(table(["H [mm]","E (x,z)","P (x,z)","Sklep (x,z)"],[[fmt(x["platform_height_mm"],0),*[
        "; ".join(fmt(v) for v in x[k]) for k in ("cylinder_base_mm","cylinder_rod_pin_mm","cross_pin_mm")]] for x in rows],
        [WIDTH*.16,WIDTH*.25,WIDTH*.30,WIDTH*.29]))
    section(story,"Sila cilindra skozi dvig",[])
    story.append(graph([x["platform_height_mm"] for x in rows],[x["cylinder_force_N"]/1000 for x in rows],"Višina ploščadi H [mm]","Sila cilindra [kN]"))
    section(story,"Hod in največje obremenitve",[f"Razdalja med sornikoma spodaj: {fmt(c['cylinder_closed_pin_mm'])} mm; zgoraj: {fmt(c['cylinder_open_pin_mm'])} mm; hod: {fmt(c['stroke_mm'])} mm.",
        f"Projektna navpična sila: {fmt(c['design_vertical_load_N'])} N; največja sila cilindra: {fmt(c['peak_cylinder_force_N'])} N. {c['peak_basis']}",
        "To niso izračuni napetosti, uklona, zvarov, sornikov ali stabilnosti. Dejanska vgradna dolžina standardnega cilindra in kolizije še niso preverjene."])
    agent_text(story,handoff.results["konstruktor"])
    pdf(root/"01_Konstruktor.pdf","Konstruktor",handoff,story,provenance)

    story=[]
    section(story,"Prevzeti podatki Konstruktorja",[f"Izvorni SHA-256: {h['source_constructor_sha256']}",f"Potreben hod: {fmt(c['stroke_mm'])} mm; največja zahtevana sila: {fmt(h['max_force_N'])} N."])
    story.append(table(["H [mm]","Dolžina cilindra [mm]","Zahtevana sila [N]"],[[fmt(x[k]) for k in ("platform_height_mm","cylinder_length_mm","force_N")] for x in h["force_curve"]]))
    section(story,"Primerjava tlakov in teoretičnih premerov",["1 bar = 0,1 N/mm²; A=Fmax/p; D=sqrt(4A/pi). Teoretični premer ni izbira standardnega dobavnega cilindra."])
    story.append(table(["Tlak [bar]","Teoretični premer [mm]","Površina bata [mm²]"],[[fmt(p[k]) for k in ("pressure_bar","theoretical_bore_mm","piston_area_mm2")] for p in h["pressure_options"]]))
    story.append(graph([x["pressure_bar"] for x in h["pressure_options"]],[x["theoretical_bore_mm"] for x in h["pressure_options"]],"Tlak [bar]","Teoretični premer [mm]"))
    section(story,"Pretok, hitrost in moč",[f"Čas dviga [s]: {fmt(h['lift_time_s'])}", h["flow_basis"]])
    if h["flow_L_min"] is None:
        section(story,"Manjkajoči podatki",["Pretok [L/min], hitrost ploščadi in cilindra [mm/s] ter hidravlična moč [kW] niso določeni, ker ni podan čas dviga. Moč na gredi ni določena brez podatkov o pogonu/izkoristku. Vrednosti niso ocenjene ali nadomeščene z nič."])
    else:
        story.append(table(["H [mm]","Pretok [L/min]","Hidravlična moč [kW]"],[[fmt(row["platform_height_mm"]),fmt(q),fmt(p)] for row,q,p in zip(rows,h["flow_L_min"],h["hydraulic_power_kW"])]))
        section(story,"Hitrost",["Izvorna predaja ne vsebuje ločene tabele hitrosti; tu je ne izmišljamo. Pri podanem času glej izvorne predpostavke o konstantni hitrosti ploščadi.",f"Moč na gredi [kW]: {fmt(h['shaft_power_kW'])}"])
    section(story,"Varnostne funkcije",h["safety_functions"])
    section(story,"Omejitve",h["limitations"])
    agent_text(story,handoff.results["hidravlik"])
    pdf(root/"02_Hidravlik.pdf","Hidravlik",handoff,story,provenance)

    story=[]
    section(story,"Opravljene lokalne kontrole",["Numerična kontrola: uspešna. To ni potrditev konstrukcije ali pravilnosti vseh fizikalnih predpostavk."])
    story.append(table(["Kontrola","Rezultat","Odgovorni agent"],[[x["check"],"uspešno" if x["status"]=="pass" else "neuspešno",LABELS[x["target_agent"]]] for x in r["checks"]],[WIDTH*.60,WIDTH*.16,WIDTH*.24]))
    section(story,"Pomen oznak ugotovitev",["critical: kritična; major: glavna; minor: manjša; info: obvestilo. open: odprto; resolved: odpravljeno. Izvirne kode so ohranjene zaradi sledljivosti."])
    for heading,findings in (("Lokalne ugotovitve",r["findings"]),("Ugotovitve AI-recenzenta",handoff.results["recenzent"].get("findings",[]))):
        section(story,heading,[])
        for f in findings:
            section(story,f"{f['id']} · {f['severity']} · {f['status']} · {LABELS.get(f['target_agent'],'Ročni pregled')}",[f["description"],"Zahtevani popravek: "+f["required_correction"]])
    section(story,"Končni status",[f"Odločitev: {handoff.results['recenzent']['decision']}. engineering_verified=false. Sledi uporabnikov pregled in izrecna odobritev naslednjega razvojnega cikla."])
    agent_text(story,handoff.results["recenzent"])
    pdf(root/"04_Recenzent.pdf","Recenzent",handoff,story,provenance)


def literal(cell, value):
    cell.value = str(value)
    cell.data_type = "s"  # Model text beginning with =,+,-,@ is never an Excel formula.


def make_excel(path, handoff):
    wb=Workbook(); ws=wb.active;ws.title="Stroški"
    wb.calculation=CalcProperties(calcId=191029,fullCalcOnLoad=True)
    ws.append([handoff.label+" – NEPOPOLNA SINTETIČNA STROŠKOVNA OCENA"])
    ws.merge_cells("A1:I1")
    ws.append(["changes_required; engineering_verified=false. Neznani stroški niso nič. Ni potrjene skupne cene naprave."])
    ws.merge_cells("A2:I2")
    headers=["Kategorija","Postavka / opis","Količina","Enota količine","Cena enote [EUR]","Znesek vira [EUR]","Delni seštevek [EUR]","Status cene","Vir / podlaga"]
    ws.append(headers)
    names={"arms":"Štiri škarjaste roke","base_and_deck":"Podnožje in ploščad","cylinder":"Hidravlični cilinder",
           "hydraulic_unit":"Hidravlični agregat","assembly":"Sestava","safety_and_verification":"Varnost in preverjanje"}
    e=handoff.results["ekonomist"]["engineering"]
    for index,item in enumerate(e["cost_items"],4):
        for col,value in ((1,item["category"]),(2,names.get(item["category"],item["category"])),(8,"SINTETIČNO" if item["price_kind"]=="synthetic" else "NEZNANO"),(9,item["source"])):
            literal(ws.cell(index,col),value)
        ws.cell(index,6,item["amount_EUR"])
        if item["category"]=="arms":
            ws.cell(index,3,4*handoff.results["konstruktor"]["engineering"]["parameters"]["arm_length_mm"]/1000)
            literal(ws.cell(index,4),"m skupaj")
            ws.cell(index,5,50)  # Explicitly supplied synthetic 50 EUR/m in source catalogue.
        ws.cell(index,7,f'=IF(ISNUMBER(F{index}),ROUND(F{index},2),"")')
        if item["category"]=="arms":
            ws.cell(index,7,f'=IF(AND(ISNUMBER(C{index}),ISNUMBER(E{index})),ROUND(C{index}*E{index},2),"")')
    end=3+len(e["cost_items"])
    row=end+2
    for offset,(title,status) in enumerate((("Nepopoln sintetični vmesni seštevek","SINTETIČNO"),("Preverjene cene – ni predloženih ponudb","PREVERJENO"))):
        literal(ws.cell(row+offset,2),title)
        ws.cell(row+offset,7,f'=IF(COUNTIF(H4:H{end},"{status}")=0,"",SUMIF(H4:H{end},"{status}",G4:G{end}))')
    literal(ws.cell(row+2,2),"Število neznanih postavk")
    ws.cell(row+2,7,f'=COUNTIF(H4:H{end},"NEZNANO")')
    literal(ws.cell(row+3,2),"Potrjena skupna cena naprave")
    literal(ws.cell(row+3,7),"NI DOLOČENA")
    literal(ws.cell(row+4,2),f"Izvorni nepopolni seštevek: {fmt(e['synthetic_subtotal_EUR'])} EUR; brez DDV in dobaviteljskih ponudb.")
    ws.merge_cells(start_row=row+4,start_column=2,end_row=row+4,end_column=9)
    widths=[17,25,10,13,14,16,17,16,40]
    for column,width in zip("ABCDEFGHI",widths): ws.column_dimensions[column].width=width
    for cells in ws:
        for cell in cells:
            cell.alignment=Alignment(vertical="top",wrap_text=True)
            cell.font=Font(name="DejaVu Sans",size=10,color="233342")
            if cell.column in (5,6,7) and cell.row>=4: cell.number_format='#,##0.00 "EUR"'
    ws.cell(row+2,7).number_format="0"
    for cell in ws[3]: cell.fill=PatternFill("solid",fgColor="E1EBF1");cell.font=Font(bold=True,color="17344C")
    ws.row_dimensions[1].height=28;ws.row_dimensions[2].height=34;ws.row_dimensions[3].height=36
    for i in range(4,end+1): ws.row_dimensions[i].height=46
    for i in range(row,row+5): ws.row_dimensions[i].height=28
    ws.freeze_panes="C4";ws.auto_filter.ref=f"A3:I{end}"
    ws.sheet_properties.pageSetUpPr.fitToPage=True
    ws.page_setup.orientation="landscape";ws.page_setup.paperSize=ws.PAPERSIZE_A4;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=1
    ws.print_title_rows="1:3";ws.print_area=f"A1:I{row+4}"
    ws.oddFooter.center.text=handoff.label+" | Sintetično – ni potrjena cena | Stran &P"
    info=wb.create_sheet("Sledljivost")
    for values in (["Varianta",handoff.variant],["Revizija",handoff.revision],["Status","changes_required"],["engineering_verified","false"],
                   ["Pojasnilo","Prazne celice pomenijo neznano/nepodano, ne nič. Formule preračuna Excel ali LibreOffice ob odprtju."],
                   ["Izvor konstruktorja",e["source_constructor_sha256"]],["Izvor hidravlike",e["source_hydraulics_sha256"]]):
        info.append(values)
        for cell in info[info.max_row]: literal(cell,cell.value)
    info.column_dimensions["A"].width=27;info.column_dimensions["B"].width=92
    for cells in info:
        for cell in cells: cell.alignment=Alignment(wrap_text=True,vertical="top")
        info.row_dimensions[cells[0].row].height=44
    info.sheet_properties.pageSetUpPr.fitToPage=True;info.page_setup.paperSize=info.PAPERSIZE_A4;info.page_setup.fitToWidth=1
    wb.save(path)
