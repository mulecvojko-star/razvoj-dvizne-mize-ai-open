# Tehnični razvojni paket – Naloga 05

Paket je predstavitev obstoječega zaključenega štiriagentnega cikla. Ne izdela
nove konstrukcijske variante, ne optimizira številskih rezultatov in ne kliče
OpenAI. Preizkusni podatki so sintetični; `changes_required` in
`engineering_verified=false` sta ohranjena v dokumentih in JSON.

## Prenos prek Androida

1. Po združitvi sprememb odpri GitHub → Actions → **Razvojni paket iz obstojecih rezultatov**.
2. Pritisni **Run workflow**, izberi **main**, `source_run_id=40794650126` in
   `source_kind=openai`. To izbere že obstoječi artifact, ne sproži AI-agentov.
3. Po koncu odpri Summary → Artifacts in prenesi `razvojni-paket-...`.
4. Odpri preneseni artifact ZIP; v njem je **V01-R01_Razvojni_paket.zip** s
   spodnjimi dokumenti. Po potrebi v Chromu izberi »Spletno mesto za namizne
   računalnike«. PDF odpre pregledovalnik, XLSX pa Excel ali druga združljiva aplikacija.

GitHub artifacti so shranjeni 7 dni. V javnem repozitoriju niso zaupna shramba.
Izvorni artifact mora še obstajati in izvirati iz uspešnega ročnega ai-trial
zagona na main. Če je potekel, uporabi prej preneseni lokalni JSON/ZIP. Novi
workflow ima samo `contents: read` in `actions: read`, ne dobi OPENAI_API_KEY.

Po prihodnjem uspešnem AI- ali simulacijskem ciklu je isti ZIP že samodejno
v običajnem artifactu pod `runs/packages/`. Noben dodaten modelski klic ni potreben.

## Vsebina ZIP

| Datoteka | Vsebina |
| --- | --- |
| 00_Povzetek.pdf | Vhodi, dimenzije, sila, hod, nepopolni stroški, povzetki agentov in odprta vprašanja |
| 01_Konstruktor.pdf | Predpostavke, geometrija, formule, parametri z enotami, vseh 11 položajev, vpetja in graf sile |
| 02_Hidravlik.pdf | Prenesene sile, tlaki 160/200/250/315 bar, teoretični premeri, hod, pretok/moč ali jasne neznanke, varnostne funkcije |
| 03_Ekonomist.xlsx | Sintetične in neznane postavke, izvorni zneski, količine/cene kjer podane, formule, ločeni seštevki in sledljivost |
| 04_Recenzent.pdf | Izvedene kontrole, lokalne in AI-ugotovitve, resnost, odgovorni agenti, potrebni popravki in dejanski status |
| 05_Izvorni_podatki.json | Nespremenjene številčne predaje, zahteve, validacija, identiteta in razpoložljiva sledljivost/manifest/report |

PDF so A4, imajo vgrajeni pisavi DejaVu Sans, slovenske č/š/ž in vektorske grafe.
Tabele se prelamljajo z glavo na naslednji strani. Dolga nestrukturirana AI-vrednost
je v PDF lahko nadomeščena z izrecnim napotilom na celoten JSON, kadar je numerični
pregled že prikazan v tabeli; izvirna vsebina v JSON se ne krajša.

Excelov glavni list je pripravljen za A4 ležeče. Količina 4,4 m in sintetična
cena 50 EUR/m za roke izhajata iz geometrije in izvorne stroškovne postavke.
Za pavšale ne izmišljamo količine ali cene na kos. Neznani zneski so prazni,
ne 0. Formula pri neznanem znesku vrne prazno celico. Nepopolni sintetični
seštevek 1120 EUR ni potrjena skupna cena naprave; preverjenih ponudb ni.

**Formule preračuna Excel/LibreOffice ob odprtju.** openpyxl jih zapiše, ne
izračuna predpomnilnika. Pregledovalnik brez računskega pogona lahko zato pokaže
prazne rezultate formul; izvorni zneski in besedilno označen nepopolni seštevek
ostanejo vidni. Datoteka zahteva ponovni izračun ob odprtju.

## Lokalna izdelava brez agentov

```sh
python -m pip install .
python -m src.reporting pot/do/result.json --metadata-dir pot/do/izvornega-artifacta --output-dir packages
# Samostojen že shranjeni popolni rezultat:
python -m src.reporting examples/V01-R01-engineering-result.json --output-dir packages
# Ali zaključen dnevnik, npr. po napaki izdelave dokumentov:
python -m src.reporting .runs/V01-R01.json --output-dir packages
```

Prebere se rezultat ali dnevnik s štirimi sprejetimi predajami. Identiteta,
sintetičen izvor, enote, celovitost tabel, notranje sledi in status validacije
morajo biti skladni. Predčasno ustavljen cikel, manjkajoči agenti, neuspešna
numerična kontrola ali trditev o tehnični odobritvi ne dobijo popolnega paketa.
Generator ne popravi vhodnih števil in ne spreminja statusa, da bi tak paket
lahko nastal. Poverilnice v znanih poljih in prepoznavnih vzorcih se odstranijo;
v izvorne datoteke še vedno ne dodajaj skrivnosti. Besedilo v Excelu ni formula,
modelov tekst v PDF je varno ubežan.

`CycleRunner` paket izdela šele po uspešnem ciklu; `Orchestrator.run` ostaja
nizkonivojski matematični izvajalnik brez samodejnega zapisovanja dokumentov.
Ob napaki izrisa ostane zaključen Handoff v dnevniku, `development_package`
pa kaže `failed`. Cloud job se konča z `document_generation_failed`, brez
lažnega ZIP-a. Popravi odvisnosti/vhod in uporabi lokalni ukaz nad dnevnikom;
agentov oziroma plačljivih klicev ni treba ponovno zaganjati.

## Preverjanje

```sh
python -m pip install '.[ai,test]'
python -m unittest discover -s tests -v
```

Testi preverijo ZIP in vseh šest imen, veljavnost in A4 velikost PDF,
vgrajene pisave, slovenske znake, položaj besedila in prekrivanja, vektorski
graf, številke in enote, formule XLSX, neznane/sintetične stroške, status,
redakcijo poverilnic, neuspešne/nepopolne cikle in lokalni način brez agentov.
CI na Pythonu 3.11–3.13 brezplačno izvede teste in simulacijo ter naloži tudi
simulirani razvojni paket. Ročni plačljivi preizkusi se ne sprožijo samodejno.

Vzorčni paket Naloge 05 je izdelan iz že uspešno zaključenega zagona
[40794650126](https://github.com/mulecvojko-star/razvoj-dvizne-mize-ai-open/actions/runs/40794650126),
commita `d415e1e`, brez novega API-klica. Paket ni certifikat, izračun nosilnosti
vseh delov ali dovoljenje za izdelavo naprave.
