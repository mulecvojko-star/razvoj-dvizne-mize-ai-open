# Preliminarna škarjasta varianta V01-R01

Ta varianta je matematično sledljiv **preliminaren koncept**, ne proizvodni načrt
ali potrditev varnosti. Vsi vhodi in stroškovne ocene so sintetični. Modeli niso
bili klicani. Celoten primer je v [strukturiranem rezultatu](../examples/V01-R01-engineering-result.json).

## Geometrija in predpostavke

Vhodi: 300 kg, ploščad 1200 × 800 mm, višini 350 in 1000 mm, dvig 650 mm.
Dve vzporedni škarjasti ravnini sta pri y=100 in 700 mm; en cilinder je na
sredini y=400 mm in poganja ravnini prek toge prečke. Širina ne določa profilov
ali stabilnosti. Vsaka ravnina ima dve idealni roki dolžine L=1100 mm.

Koordinati sta x vzdolž ploščadi in z navzgor, spodnji sklep A je izhodišče.
Odmik podnožja in ploščadi skupaj je 100 mm; zato je višina škarij h=H−100.
Sklepi v ravnini so A=(0,0), B=(s,0), C=(s,h), D=(0,h). Roki AC in BD se
križata pri (s/2,h/2). A je pritrjen na podnožje, B drsi; D je pripet na
ploščad, C drsi vzdolž ploščadi. Zgornja ploščad se premika navpično.

Spodnje vpetje cilindra je E=(a,0), a=250 mm, zgornje P=(fs,fh), f=0.5,
na roki AC (v tem primeru v sredinskem sklepu). Cilinder se ob dvigu podaljšuje.
Masa premičnih delov 100 kg je konzervativno zgoščena na ploščadi; upoštevamo
centrično kvazistatično obremenitev, faktor obremenitve k=1.3 in mehanski
izkoristek eta=0.85. To so sintetične predpostavke, ne standardno predpisani
faktorji. Izvor vsake predpostavke (`input` ali `synthetic_default`) je shranjen.

Parametre lahko izrecno poda uporabnik kot dodatne vhode `arm_length_mm`,
`structure_offset_mm`, `cylinder_base_x_mm`, `rod_pin_fraction`, `moving_mass_kg`,
`load_factor`, `mechanical_efficiency`. Ohranjeni so kontrolni seštevki vhodov.
Čas dviga `lift_time_s` je neobvezen in nima privzete vrednosti.

## Preverljive enačbe

- Razpon: `s = sqrt(L² − h²)`; kot roke: `theta = asin(h/L)`.
- Dolžina med sornikoma cilindra: `l = sqrt((fs−a)² + (fh)²)`.
- Enakovredno: `l² = f²L² + a² − 2af*s`.
- Geometrijski prenos: `dl/dH = af*h/(l*s)`, ker `dh/dH=1`.
- Projektna navpična sila: `W = (payload + moving_mass)*9.81*k = 5101.2 N`.
- Virtualno delo z modelom trenja: `F_cyl = W/(eta * dl/dH)`.
- Hod: `l(Hmax) − l(Hmin)`; en cilinder prevzame celotno silo, ne polovice.

Velja `0 < Hmin−offset < Hmax−offset < L <= dolžina ploščadi` in pozitivna
nesingularna vpetja. Model zavrne tudi vpetje zunaj najmanjšega razpona ter
zahtevani hod, ki je večji ali enak spodnji razdalji med sornikoma (običajen
neteleskopski cilinder). To je le nujni pogoj vgradljivosti; dejanska zaprta
dolžina vsebuje dodatke za glavi, ušesi, bat in tesnila in še ni preverjena.

Največja sila je analitično v spodnji legi, ne zgolj največja med 11 vzorci.
Če zapišemo `F²` sorazmerno `(c−2af*s)*s²/(L²−s²)`, `c=f²L²+a²`, ima njegov
odvod po s predznak izraza `2cL²−2af*s*(3L²−s²)`. Ta je nenegativen za
`0<s<L`, ker `s*(3L²−s²)<=2L³` in `c>=2afL`. Ker s z dvigom pada, pada tudi F.

| H [mm] | Razpon s [mm] | Kot [°] | Cilinder l [mm] | Sila [kN] |
| --- | --- | --- | --- | --- |
| 350 | 1071.21 | 13.14 | 311.76 | 64.14 |
| 1000 | 632.46 | 54.90 | 454.85 | 15.35 |

Celotna tabela 11 položajev s korakom višine 65 mm, koordinatami sklepov in
vpetij ter silami je v JSON rezultatu. Zahtevani hod je **143.08 mm**.
Numerična validacija AI-kontrolnih količin dopušča zaokroževanje z relativno
toleranco 1e−4 in absolutno 0.01 v navedeni enoti. Celotna lokalna tabela se
preverja strožje; podatek z drugo enoto se zavrne, ne pretvori samodejno.

## Hidravlična in ekonomska predaja

Pri iztegu idealnega cilindra velja `1 bar = 0.1 N/mm²`, `A=Fmax/p` in
`D=sqrt(4A/pi)`. Največja zahtevana sila je približno **64.14 kN**.

| Tlak [bar] | Teoretični premer [mm] |
| --- | --- |
| 160 | 71.44 |
| 200 | 63.90 |
| 250 | 57.15 |
| 315 | 50.92 |

To ni izbira standardnega cilindra. Niso zajeti protitlak, tlačne izgube,
uklon batnice, bočne sile ali dejanska vgradna dolžina. Pri podanem času t
in konstantni hitrosti ploščadi velja `v_H=dvig/t`, `v_cyl=(dl/dH)*v_H`,
`Q=A*v_cyl*60/1e6 [L/min]` za A v mm² in hitrost v mm/s. Referenca uporablja
teoretični premer pri 200 bar, `P=200*Q/600 [kW]` pa je moč pri nastavljeni
meji tlaka; pri spremenljivi potrebni sili to ni dejanska moč med celotnim
ciklom. Brez časa sta pretok in moč `null`. Moč na gredi ostane `null`, ker
ni podatkov o izkoristku črpalke/pogona.

Ekonomist poveže postavke z geometrijo in hidravlično predajo prek SHA-256.
Štiri roke × 1.1 m × sintetičnih 50 EUR/m = 220 EUR; dodani sintetični pavšali
so podnožje/ploščad 300 EUR, cilinder 350 EUR in sestava 250 EUR.
**1120 EUR je samo nepopoln sintetični vmesni seštevek**, brez DDV in ponudb.
Agregat ter varnost/preverjanje so `unknown` z `amount_EUR=null`, ne nič.
`verified_prices=[]` in `total_EUR=null`. AI ne sme dodati izmišljenih ponudb.

## Neodvisni pregled in programska pogodba

`src/engineering/calculations.py` izdela lokalne numerične predaje.
`src/engineering/review.py` ne kliče tega izračuna: preveri dolžine, koordinate,
robne lege, parametre, odvod dolžine s centralno končno diferenco, virtualno
delo, sile in premere, pretoke (če je čas podan), izvore cen ter sledi predaj.
To je neodvisen numerični pregled v okviru istega fizikalnega modela; ne
zagotavlja neodvisnosti od skupnih modelskih predpostavk ali pravilnosti naprave.

AI dobi pregledano lokalno referenco in mora v `calculations` vrniti zahtevane
`quantity`, numerični `value` in `unit`; poljubno besedilo ni dokaz izračuna.
`cost_items` ločijo `verified`, `synthetic`, `unknown` in vir. V tem sintetičnem
preizkusu so dovoljene samo priložene sintetične/neznane postavke. Shema je
razširjena tudi s `findings.target_agent`. Neveljavna struktura, manjkajoče
količine, napačne enote ali številke ustavijo cikel pred naslednjim agentom.
Geometrija se preveri pred prvim modelskim klicem. Varni opisi inženirskih
napak se shranijo v dnevnik; nepopoln odgovor API ni uspešna predaja.

Lokalni `engineering` vsebuje celotno numerično tabelo, enote, predpostavke in
vhodni hash. AI poda razlago in numerične kontrolne količine, ne določa prosto
nove geometrije. To je ena izbrana preliminarna varianta, ne optimizator konstrukcij.
Nizkonivojska prvotna simulacija minimalnih predaj brez zahtev ostaja na voljo,
vendar ima `technical_status=not_evaluated`; upravljani cikli zahtevajo vse vhode.

Pravilen račun pomeni `calculation_check_passed=true`, ne tehnične odobritve.
Recenzent vedno ohrani odprte naloge za konstruktorja, hidravlika in ekonomista.
Odločitev je `changes_required`, ob napačni/nepopolni predaji pa `blocked`.
`engineering_verified` je vedno `false`. Stanje opravila `awaiting_approval`
pomeni zaključek računalniškega cikla, ne odobritve naprave. Nova revizija še
vedno zahteva uporabnikovo odobritev; samodejnega vračanja agentov ni.

Pred izvedbo ostajajo preverbe profilov, napetosti, uklona, spojev, stabilnosti,
tolerance, kolizije, servisni položaji, agregat in ventili, analiza tveganja ter
ustreznost veljavnim predpisom. Te naloge niso opravljene s tem preliminarnim računom.

## Ponovitev brez API-ključa

```sh
python -m unittest discover -s tests -v
python -m src.orchestrator examples/V01-R01.json --approve-cycle V01-R01
```

Za vsak upravljani poskus uporabi ustrezno zgodovino/novo revizijo; isti lokalni
cikel se ne prepisuje. Ročni workflow, gpt-5.4-mini, skrivnosti in zaščite ostajajo
kot prej. Daljša engineering predaja porabi več vhodnih tokenov; ob doseženi
omejitvi poziva ali nepopolnem odgovoru se postopek ustavi brez ponovitve.
V tem PR ni bilo nobenega plačljivega preizkusa.
