# Zaključni preizkus 07–09: Wordova baza in dejanski agenti

Sistem nadgradi Naloge 04–06: uporablja iste izračune geometrije in hidravlike,
neodvisno recenzijo, osnovno JSON-pogodbo, Responses transport in A4 dokumente.
Stari enociklični workflow z največ štirimi klici in simulacija Naloge 06 ostajata
nespremenjena. Zaključni preizkus je ločen vhod z ločeno odobritvijo.

## Baza in ugotovljena skladnost

`knowledge_base/Testna_baza_znanja_V01.docx` se bere neposredno kot DOCX XML,
brez AI-klica, zunanjih storitev ali vektorske baze. Ohranijo se vsi odstavki,
vse tabele, celice, naslovi poglavij ter viri dokument/odstavek/tabela/vrstica/stolpec.
Izluščenih je 51 zapisov REQ/GEO/CON/HYD/COST/REV/TEST; pravila brez ID so ohranjena
v besedilu in tabeli pravil agentov. Vsak vir vsebuje SHA-256 dokumenta.

Zahteve 300 kg, ploščad 1200 × 800 mm, višini 350–1000 mm in dvig 650 mm se ujemajo
s programskim primerom. Zaokrožena referenca 143,08 mm / 64,14 kN se ujema z izračunom.
Dve razliki sta izrecno dokumentirani v `preflight.json` in končnem poročilu:

- **REQ-07 omejuje razvoj na R01 in največ R02.** Zato ta baza dovoljuje največ
  dve zaključeni reviziji oziroma največ osem zahtev, čeprav ima ločena nova
  politika absolutno mejo 16 zahtev in štiri na vlogo. Omejitve se ne sproščajo
  samodejno samo zaradi razpoložljivega proračuna.
- **COST cenik se razlikuje od zgodovinskih pavšalov programa.** Novi zaključni
  preizkus uporablja izključno COST-01…12. Izračunani zneski iz preteklih nalog
  ostajajo nespremenjeni; novi scenarijski stroški niso njihova tiha zamenjava.

Manjkajoč, poškodovan dokument, podvojeni/manjkajoči ID-ji ali nepodprt zapis
ustavijo zagon. Neskladje fiksnih zahtev se zapiše kot blokirajoče, brez prepisa
programskih zahtev. Neznani podatki ostanejo neznani. GEO je spremenljiv samo
z obrazložitvijo in ponovno kontrolo; sila, hod in stroški so izpeljani rezultati.

## Delovanje agentov

Vsak agent dobi izvleček celotne baze, sledljive zapise, dosedanje predaje,
prejete zahtevke in deterministično referenco. V JSON vrne osnovni rezultat,
uporabljene `source_ids`, predlog geometrije oziroma izbor komponent ter odgovore
na naloge. Recenzent doda zahtevke z lastnikom, razlogom, virom in ciljem popravka.

Orkestrator shranjuje komunikacijo z obveznimi polji `sender`, `recipient`,
`revision`, `request`, `reason`, `data_sources`, `status`. Agent ne kliče drugih
agentov, orodij ali novega cikla. Viri v izhodu se validirajo proti dejanskim ID-jem;
poročilo razlikuje posredovano bazo od virov, ki jih je agent deklariral kot uporabljene.
To ni dokaz notranjega razmišljanja modela.

Konstruktor lahko za sledljivo nalogo `reduce_peak_force` predlaga spremembo enega
od štirih obstoječih geometrijskih parametrov B. Program zahteva veljaven izračun
in dokazano zmanjšanje največje idealizirane sile. Zabeleži tudi spremembo hoda;
zmanjšanje sile ne pomeni splošno boljše ali varne konstrukcije. Število ravnin,
cilindrov in koncept CON-01 ostajajo v podprtem računskem modelu. Nepodprte spremembe
zahtevajo ročni pregled. Predlog vsebuje predhodne modelove izračune; novi rezultati
so označeni kot ponovno deterministično izračunani, brez pripisa AI-ju.

Hidravlik izbira samo HYD-01…04 in HYD-05/06 ter dovoljene tlake. Program neodvisno
računa idealno silo `p × 0,1 × pi × D²/4`, preveri tlačne omejitve cilindra in agregata
ter primerja katalog. Ustreznost idealne sile ne dokazuje hoda, vgradnje, uklona,
izkoristka ali varnosti. Nazivni pretok agregata ne nadomesti manjkajočega časa dviga.

Ekonomist uporablja scenarijske količine po en sklop, cene COST in točno podano
kosovnico. COST-10/11/12 ostanejo `null`. Skupna investicijska vrednost ni določena.
Kataloške alternative so primerjane; za CON-02/03 ni podprte geometrije in količin,
zato celotnih konceptnih cen ni mogoče določiti. Nobena cena ni preverjena ponudba.

Recenzent ohrani `changes_required` in `engineering_verified=false`. Numerične
kontrole uporabi obstoječa neodvisna recenzija, s katalogom stroškov iz dejanske KB.
Lokalnih tveganj agent ne more zapreti z besedilom. Samodejno se lahko zapre samo
`KB-CAPACITY`, ko je prejšnji izbor dokazano odpovedal kontroli idealne sile/tlaka,
novi pa jo prestane. Strukturni, vgradni, cenovni in varnostni zahtevki ostanejo
odprti/nerešeni oziroma nepotrjeni. Neznan lastnik pomeni ročni pregled.

Če ni utemeljene naslednje spremembe, se izvajanje zaključi po R01. Če naslednji
Konstruktor ne poda utemeljenega popravka in ni numerične kataloške napake, je njegov
poskus zabeležen kot `proposal_only`; to ni nova zaključena revizija. Nobena tretja
revizija ali avtomatska ponovitev ni dovoljena. `STOP` v izhodni mapi ustavi izvajanje.

## Brezplačno preverjanje in ponovni izvoz

```sh
python -m pip install '.[ai,test]'
python -m unittest discover -s tests -v
FINAL_APPROVAL='ODOBRIM KONCNO SIMULACIJO V01' python -m src.final_trial --preflight
FINAL_APPROVAL='ODOBRIM KONCNO SIMULACIJO V01' python -m src.final_trial
python -m src.final_trial --report-only final-artifacts/trial.json --output-dir ponovni-izvoz
```

Za nov zagon uporabi novo `--output-dir`: obstoječega `trial.json` ni mogoče
prepisati. Ponovni dokumentni izvoz ne potrebuje ključa, odobritve ali AI-klica.
Neveljaven ali nedokončan cikel ne ustvari lažno popolnega paketa. Diagnostika,
poraba, nevalidiran redigiran odgovor in delne predaje ostanejo v JSON.

Simulacija namenoma preizkusi nezadostni idealni izbor C63 pri 200 bar ter popravek
na C70 pri 200 bar. Geometrija se ne spremeni; delni sintetični znesek se poveča
iz 1.390 na 1.425 EUR. Odpravljena je samo omejena nominalna kataloška napaka,
ne vgradnja ali varnost. Dejanski model lahko že prvič predlaga nominalno ustrezen
cilinder; v tem primeru je ena zaključena revizija pravilen izid, ne napaka.

## Cena, tokeni in omejitve

Preverjeno 29. 10. 2026 na uradni strani modela:
<https://developers.openai.com/api/docs/models/gpt-5.4-mini>

Standardni besedilni API: **0,75 USD/milijon vhodnih** in **4,50 USD/milijon
izhodnih tokenov**. Predpostavka je standardna storitev brez regionalnega pribitka,
davkov ali popusta za predpomnilnik. V kodi sta vir in datum; veljavnost izračuna
je omejena do 5. 11. 2026. Po tem je plačljivi zagon blokiran do ponovnega pregleda
cenika in pregledane posodobitve. Neznan cenik ne povzroči izmišljene cene.
Simulacija lahko deluje tudi brez veljavnega cenika.

Privzete izhodne omejitve po vlogah: **3500 / 3500 / 4000 / 4500**.
Workflow omogoča skupno zamenjavo 256–6000; 0 ohrani meje po vlogah. Reasoning je
vključen v izhodno porabo; novi preizkus izrecno zahteva `reasoning.effort=none`,
kar model po uradni dokumentaciji podpira. Responses API in Structured Outputs
ostajata uporabljena; dostopnost modela v računu je pred prvim odobrenim klicem neznana.

Celoten poziv (navodila, vhod in JSON shema) je omejen na **96.000 UTF-8 bajtov**.
Konservativna lokalna ocena vhodnih tokenov je število bajtov + 2048 za okvir
zahteve; preveri se proti nastavljeni meji, privzeto 100.000. To ni podatek
ponudnikovega tokenizerja ali nativni parameter `max_input_tokens` Responses API.
Dejanska poraba je znana šele iz odgovora. Prevelik vhod se zavrne pred klicem.

Za dve reviziji so konservativne predzagonske ocene največ 800.000 vhodnih in
31.000 izhodnih tokenov oziroma **0,7395 USD** po standardnem ceniku. To je
konservativna rezervacija, ne napoved dejanske porabe. Absolutna meja novega
preizkusa ostaja 16 klicev, posamezna vloga največ štiri; REQ-07 dodatno omeji
konkretni zagon na največ osem. Stari enociklični preizkus ostane omejen na štiri.

Pred vsakim plačljivim klicem se trajno zapiše rezervacija največjega odobrenega
vhodnega/izhodnega obsega po ceniku. Če dosedanji obračunani zneski plus rezervacija
presežejo prag (privzeto **3 USD**, nastavljivo navzdol), se klic ne izvede. SDK ima
`max_retries=0`; napaka, nepopoln odgovor, neveljaven JSON, manjkajoča poraba ali
neprepoznan odzivni model ustavijo nadaljevanje. Neznana poraba se ne prikaže kot nič;
rezervirana izpostavljenost ostane ločeno zapisana.

`09_API_poraba.json` vsebuje klice, revizije, model, vhodne/izhodne/reasoning tokene,
rezervacije, oceno dejanske porabe po ceniku in seštevke po agentu. Reasoning ni
obračunan dvakrat. **Lokalni prag ni trda omejitev računa pri ponudniku**;
projektni proračun OpenAI prav tako ni nujno trda finančna meja.

## Ločena odobritev dejanskega preizkusa na Androidu

Programske spremembe in simulacija ne pomenijo odobritve plačljivega izvajanja.
Plačljivi zagon ni bil sprožen kot del priprave. Ključ ostaja samo v obstoječem
GitHub Secret `OPENAI_API_KEY`, ne v vnosu workflowa ali pogovoru. Okolje `ai-trial`
in njegove zaščite se ne spreminjajo. Trenutno okolje uporablja omejitev vej;
če GitHub zahteva še pregled deploymenta, ga mora odobriti pooblaščeni pregledovalec.

1. Odpri **Actions → Zakljucni AI preizkus V01 (rocno) → Run workflow**.
2. Izberi **main**, `mode=openai`, `model=gpt-5.4-mini`, `budget_usd=3` in privzete
   omejitve tokenov. Če želiš najprej samo brezplačen paket, izberi `simulated`.
3. Za plačljivo izvajanje vpiši točno **ODOBRIM KONCNI AI V01 DO 16 KLICEV**.
   Za brezplačno izvajanje uporabi **ODOBRIM KONCNO SIMULACIJO V01**.
4. Pritisk **Run workflow** s plačljivo izbiro in izrecnim nizom pomeni ločeno
   odobritev tega plačljivega zagona. Preflight brez ključa najprej objavi oceno.
   Po potrebi odpri **Review deployments** za okolje `ai-trial`; zaščite ne obidi.
5. Ob napaki ne izberi **Re-run jobs**: ponovni poskusi so blokirani. Najprej
   preglej diagnostiko, nato je potreben nov, izrecno odobren ročni zagon.
6. Po zaključku prenesi artefakt `final-openai-<run_id>-1`. Znotraj je
   **V01_Koncni_AI_razvojni_paket.zip**. Prijava v GitHub je potrebna, hramba je 7 dni.

Če model ni dostopen, ključ manjka ali cenik ni veljaven, se zagon ustavi;
program ne izbere drugega modela in ne sprošča omejitev. Ključa ne prilepi v pogovor.

## Končni paket

ZIP vsebuje točno deset zahtevanih datotek: razvojni povzetek, Konstruktorja,
Hidravlika, Excel Ekonomista, Recenzenta, primerjavo revizij, komunikacijo, vire in
predpostavke ter izvorne podatke in API-porabo. PDF uporablja obstoječo A4 predlogo
s pisavo DejaVu; Excel vsebuje formule, primerjave in ločene neznane stroške.
Paket je artifact, brez javnega commita rezultatov. Označen je z dejansko izvedenimi
revizijami in načinom izvajanja; simulacijski paket ni poročilo dejanskega AI-preizkusa.

## Diagnostika Hidravlika po prvem plačljivem poskusu

[Analiza zagona 40890068418](hidravlik-40890068418.md) dokumentira konkretni zavrnjeni
odgovor in regresijsko preverjanje. Zaključna JSON shema zdaj omeji kontrolne oznake,
enote in število izračunov na `required_calculations`; poziv navede tudi obvezne
`required_source_ids`. Neznanke ostajajo `null` v lokalni predaji, ne numerične ničle.
Ob inženirski napaki preglej `trial.json.validation_error.details` in
`partial_revision.unvalidated_response`. Samodejnih popravkov odgovora ali ponovitev
API-klicev ni.
