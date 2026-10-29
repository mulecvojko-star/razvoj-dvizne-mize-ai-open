"""Direct DOCX XML ingestion: all body text/tables, stable row/cell sources, no model."""
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from xml.etree import ElementTree as ET
import hashlib
import math
import re

from src.orchestrator.revision_policy import fixed_requirements
from src.engineering.costs import allowed_cost_items
from src.engineering.calculations import construction

NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
REQUIRED={f'{prefix}-{i:02d}' for prefix,count in [('REQ',11),('GEO',4),('CON',3),('HYD',8),('COST',12),('REV',8),('TEST',5)] for i in range(1,count+1)}


def text(node):
    return '\n'.join(''.join(p.itertext()) for p in node.findall('.//w:p',NS)) if node.tag.endswith('}tc') else ''.join(node.itertext())


def numeric(value, pattern):
    match=re.fullmatch(pattern,value.strip())
    if not match: raise ValueError('Neveljaven format podatka DOCX: '+value)
    values=[float(v.replace(',','.')) for v in match.groups()]
    if any(not math.isfinite(v) or v<0 for v in values):raise ValueError('Neveljavna numerična vrednost DOCX.')
    return values


def load_knowledge(path, inputs):
    path=Path(path)
    if not path.is_file(): raise ValueError('Manjka Wordova baza: '+str(path))
    try:
        raw=path.read_bytes()
        with ZipFile(path) as archive:
            if sum(i.file_size for i in archive.infolist())>10_000_000: raise ValueError('Prevelik DOCX.')
            body=ET.fromstring(archive.read('word/document.xml')).find('w:body',NS)
    except (BadZipFile,ET.ParseError,KeyError): raise ValueError('Wordova baza ni berljiv DOCX.') from None
    if body is None:raise ValueError('DOCX nima telesa dokumenta.')
    blocks=[];records={};section='Uvod';table_index=0
    def add(identifier, cells, source):
        if identifier in records: raise ValueError('Podvojen ID baze: '+identifier)
        required_columns={'REQ':4,'GEO':3,'CON':4,'HYD':4,'COST':4,'REV':3,'TEST':1}[identifier.split('-')[0]]
        if len(cells)!=required_columns:raise ValueError('Napačno število celic: '+identifier)
        joined=' | '.join(cells)
        category=('incomplete' if any(w in joined for w in ('NI PODATKA','NI DOLOČENA','NEZNANO')) else
                  'fixed_requirement' if identifier.startswith('REQ') and 'FIKSNO' in joined else
                  'calculated_result' if 'IZPELJANO' in joined else
                  'variable_parameter' if identifier.startswith(('GEO','HYD','CON')) or 'SPREMENLJIVO' in joined else
                  'synthetic_price' if identifier.startswith('COST') else 'decision_rule')
        records[identifier]={'id':identifier,'cells':cells,'classification':category,'source':source}
    for index,node in enumerate(body):
        source={'document':path.name,'document_sha256':hashlib.sha256(raw).hexdigest(),'section':section,'body_index':index}
        if node.tag.endswith('}p'):
            value=text(node)
            if re.match(r'^\d+\. ',value): section=value;source['section']=section
            blocks.append({'type':'paragraph','text':value,'source':source})
            match=re.match(r'^(TEST-\d+):',value)
            if match:add(match[1],[value],source)
        elif node.tag.endswith('}tbl'):
            table_index+=1;rows=[]
            for row_index,row in enumerate(node.findall('w:tr',NS),1):
                cells=[text(c) for c in row.findall('w:tc',NS)]
                row_source={**source,'table':table_index,'row':row_index}
                rows.append({'cells':cells,'source':row_source,'cell_sources':[{**row_source,'column':i+1} for i in range(len(cells))]})
                if cells and re.fullmatch(r'(REQ|GEO|CON|HYD|COST|REV)-\d+',cells[0]):add(cells[0],cells,row_source)
            blocks.append({'type':'table','rows':rows,'source':{**source,'table':table_index}})
        else:
            # Preserve other body elements as readable text too; no silent text loss.
            if text(node).strip():blocks.append({'type':'other','text':text(node),'source':source})
    if REQUIRED-set(records):raise ValueError('V bazi manjkajo ID: '+','.join(sorted(REQUIRED-set(records))))
    if not any('NAMERNO IZMIŠLJENI' in b.get('text','') for b in blocks):raise ValueError('Dokument ne potrjuje sintetičnega izvora podatkov.')
    def cell(identifier):return records[identifier]['cells'][2]
    actual={'payload_kg':numeric(cell('REQ-01'),r'([\d.,]+) kg')[0],
            'min_height_mm':numeric(cell('REQ-02'),r'([\d.,]+) mm')[0],
            'max_height_mm':numeric(cell('REQ-03'),r'([\d.,]+) mm')[0]}
    actual['platform_length_mm'],actual['platform_width_mm']=numeric(cell('REQ-05'),r'([\d.,]+) × ([\d.,]+) mm')
    conflicts=[{'severity':'blocking','field':k,'program':inputs.get(k),'document':v,'source':records[{'payload_kg':'REQ-01','min_height_mm':'REQ-02','max_height_mm':'REQ-03','platform_length_mm':'REQ-05','platform_width_mm':'REQ-05'}[k]]['source']} for k,v in actual.items() if inputs.get(k)!=v]
    lift=numeric(cell('REQ-04'),r'([\d.,]+) mm')[0]
    if lift!=actual['max_height_mm']-actual['min_height_mm']:conflicts.append({'severity':'blocking','field':'required_lift_mm','reason':'REQ-04 nasprotuje REQ-02/03'})
    if cell('REQ-07')!='R01 in največ R02':raise ValueError('Nepodprta programska omejitev REQ-07; potreben pregled.')
    if records['REQ-06']['cells'][2]!='Hidravlična škarjasta miza':conflicts.append({'severity':'blocking','field':'concept','reason':'REQ-06 ni podprt koncept V01'})
    if cell('REQ-08')!='Kandidati 160/200/250/315 bar':conflicts.append({'severity':'blocking','field':'pressure_candidates','reason':'REQ-08 odstopa od podprte tlačne primerjave.'})
    for identifier,expected in [('GEO-02','Dve vzporedni škarjasti ravnini'),('GEO-03','En osrednji cilinder')]:
        if records[identifier]['cells'][1]!=expected:conflicts.append({'severity':'blocking','field':identifier,'reason':'Koncept ni podprt z obstoječim računskim modelom.'})
    components={}
    for i in range(1,9):
        identifier=f'HYD-{i:02d}';row=records[identifier];value=row['cells'][2]
        item={'id':identifier,'name':row['cells'][1],'description':value,'limitations':row['cells'][3],'source':row['source']}
        if i<=4:item['bore_mm'],item['max_pressure_bar']=numeric(value,r'Premer bata ([\d.,]+) mm; tlak največ ([\d.,]+) bar')
        elif i<=6:item['flow_L_min'],item['max_pressure_bar']=numeric(value,r'Nazivni pretok ([\d.,]+) l/min; tlak največ ([\d.,]+) bar')
        if any(item.get(k,1)<=0 for k in ('bore_mm','max_pressure_bar','flow_L_min')):raise ValueError('Neveljavni kataloški parametri: '+identifier)
        components[identifier]=item
    prices={}
    for i in range(1,13):
        identifier=f'COST-{i:02d}';row=records[identifier];v=row['cells'][2]
        if row['cells'][3] not in ('IZMIŠLJENO','NEZNANO'):raise ValueError('Nepodprt izvor cene: '+identifier)
        prices[identifier]={'id':identifier,'name':row['cells'][1],'amount_EUR':None if v=='NI PODATKA' else numeric(v,r'([\d.,]+)')[0],'price_kind':'unknown' if v=='NI PODATKA' else 'synthetic','source':row['source']}
        if (prices[identifier]['amount_EUR'] is None)!=(row['cells'][3]=='NEZNANO'):raise ValueError('Neskladje statusa cene: '+identifier)
    for hyd_id,cost_id in [('HYD-01','COST-03'),('HYD-02','COST-04'),('HYD-03','COST-05'),('HYD-04','COST-06'),('HYD-05','COST-07'),('HYD-06','COST-08')]:
        if components[hyd_id]['name']!=prices[cost_id]['name']:raise ValueError('Neskladna povezava kataloga in cene: '+hyd_id+'/'+cost_id)
    arm=numeric(records['GEO-01']['cells'][1],r'Dolžina škarjaste roke ([\d.,]+) mm')[0]
    local=construction(inputs)
    if arm!=local['parameters']['arm_length_mm']:conflicts.append({'severity':'documented_difference','field':'arm_length_mm','document':arm,'program':local['parameters']['arm_length_mm'],'reason':'Geometrijska referenca Worda se razlikuje; samodejna sprememba ni dovoljena.'})
    geo=next((b for b in blocks if b['type']=='paragraph' and b['text'].startswith('SINTETIČNA REFERENCA GEO-01:')),None)
    if geo is None:raise ValueError('Manjka referenčni odstavek GEO-01.')
    match=re.search(r'hod cilindra ([\d,]+) mm in največja idealizirana sila ([\d,]+) kN',geo['text'])
    if not match:raise ValueError('Neberljiva referenčna izračunana rezultata GEO-01.')
    stroke,force=[float(v.replace(',','.')) for v in match.groups()]
    references={'stroke_mm':stroke,'peak_cylinder_force_N':force*1000,'source':geo['source'],'classification':'calculated_result','basis':'Zaokrožena zgodovinska referenca R01.'}
    if abs(stroke-local['stroke_mm'])>.01 or abs(force*1000-local['peak_cylinder_force_N'])>10:
        conflicts.append({'severity':'documented_difference','field':'reference_results','reason':'Zaokrožena referenca Worda odstopa od sedanjega izračuna; nobena vrednost ni prepisana.','document':references})
    conflicts += [{'severity':'documented_difference','field':'synthetic_price_catalogue','reason':'Zgodovinski pavšali programa niso COST cenik KB-01; novi zaključni preizkus uporablja izključno COST. Zgodovina ostane nespremenjena.','legacy':allowed_cost_items(1100)},
                  {'severity':'stricter_limit','field':'max_revisions','reason':'REQ-07 dovoljuje največ R02; zato največ 2 reviziji, tudi če proračun 16 klicev dopušča več.'}]
    return {'format':'V01-KB-01','document':path.name,'sha256':hashlib.sha256(raw).hexdigest(),'blocks':blocks,'records':records,
            'fixed_snapshot':fixed_requirements(inputs),'reference_results':references,'components':components,'prices':prices,'conflicts':conflicts,
            'compatible':not any(c['severity']=='blocking' for c in conflicts),'max_revisions':2,'synthetic':True}
