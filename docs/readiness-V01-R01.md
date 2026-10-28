# Naloga 04A – pripravljenost V01-R01 za plačljivi preizkus

**Sklep:** sistem je po tej spremembi pripravljen za omejen, ročno odobren
preizkus `gpt-5.4-mini`, ne pa dokazano zanesljiv za zaključek vsakega cikla.
V nalogi 04A ni bil sprožen noben plačljiv API-klic. Ključ in zaščite ostajajo
nespremenjeni. Pregled izhaja iz `main` na commitu `53d7669`.

## 1. Priporočene omejitve

| Agent | Ocena vidnega izhoda z novo pogodbo | Ocena meje 1500 | Priporočena meja |
| --- | --- | --- | --- |
| Konstruktor | približno 1000–1600 tokenov | tesno, brez zanesljive rezerve | 2500 |
| Hidravlik | približno 940–1510 | tesno | 2500 |
| Ekonomist | približno 1410–2260 | posebej tvegano zaradi cost_items in virov | 3000 |
| Recenzent | približno 960–1540, več pri dodatnih ugotovitvah | tesno | 3500 |

To so planske ocene iz lokalne rekonstrukcije, ne izmerjeni novi modelski
izhodi. Zelo kratek JSON bi bil lahko manjši; nobena shema ne omeji dolžine
vsega prostega besedila, zato ni jamstva, da bo odgovor vedno končan znotraj
priporočene meje. Skupaj je dovoljenih največ **11.500 izhodnih tokenov**, če
vse štiri zahteve porabijo celotno svojo mejo; to ni pričakovana poraba.

`max_output_tokens` zajema tudi morebitne reasoning in nevidne oblikovne tokene.
Dokumentirani privzeti `reasoning.effort` za GPT-5.4 Mini je `none`; program ga
ne spreminja. To ni dokaz ničelne nevidne porabe. Zgodovinski zapis ni shranil
razčlenitve reasoning tokenov; novi adapter jo shrani, ko jo ponudnik vrne.
Referenci: [model](https://developers.openai.com/api/docs/models/gpt-5.4-mini),
[pomen izhodnih tokenov](https://developers.openai.com/api/docs/guides/token-counting).

Workflow ohrani skupno rezervno mejo `max_output_tokens=1500`. Štiri nova polja
`constructor_max_output_tokens`, `hydraulics_max_output_tokens`,
`economics_max_output_tokens`, `reviewer_max_output_tokens` imajo zgornje
priporočene privzete vrednosti. Dovoljene so vrednosti 256–4000; **0 uporabi
skupno rezervno mejo**. Neveljavna konfiguracija se zavrne pred odjemalcem.
Manifest zabeleži vse štiri dejanske meje in njihov seštevek. SDK ohrani
`max_retries=0`; meje se med ciklom ne povečujejo samodejno.

## 2. Izmerjeni bajti in ocenjeni tokeni

Prebrani so bili vsi štirje pozivi, skupna navodila, referenčni engineering
objekti, celotne predaje in izhodna JSON shema. Konstruktor ima 7 obveznih
numeričnih kontrolnih količin, hidravlik 5 (več, ko je podan čas), ekonomist
1 in šest stroškovnih postavk, recenzent pa najmanj tri lokalne ugotovitve z
odgovornimi agenti. Velika numerična tabela se lokalno pripne rezultatu in je
modelu dostopna v referenci/predajah; modelu je ni treba ponovno izpisati.

[Strojno poročilo](token-audit-V01-R01.json) je ustvarjeno brez odjemalca in
brez zunanjega token-count API-ja. Bajti so izmerjeni nad istimi komponentami,
ki jih šteje BoundedTransport: navodila + JSON predaje + JSON sheme. Tokeni so
**hevrističen planski razpon UTF-8 bajti / 4 do bajti / 2.5**, ne rezultat
preverjenega modelskega tokenizatorja in ne zagotovljena spodnja/zgornja meja.
Starejše opazovane zahteve so imele približno 3.3 bajta/token; rekonstruirani
starejši izhodi približno 3.6 bajta/token. Ovojnica in interni dodatki API-ja
niso vključeni. Ne uporabljaj teh števil za obračun.

Za bolj realističen obseg prostega besedila je lokalna rekonstrukcija uporabila
samo besedilna polja starega sintetičnega AI-artifacta, nato pa dodala novo
shemo, numerične količine, stroške in ugotovitve iz lokalne reference. To ni
ponovni modelski preizkus. Surovi zgodovinski odgovori niso dodani v repozitorij.

| Agent | Izmerjen poziv [bajtov] | Ocenjeni vhodni tokeni |
| --- | --- | --- |
| Konstruktor | 14.192 | 3547–5678 |
| Hidravlik | 22.056 | 5513–8823 |
| Ekonomist | 28.093 | 7022–11.238 |
| Recenzent | približno 37.606 | 9401–15.044 |

Skupaj: približno **25.500–40.800 vhodnih** in **4300–6900 vidnih izhodnih**
tokenov pri tem obsegu besedila, pred dodatki API-ja in morebitnimi nevidnimi
izhodi. Za načrtovanje upoštevaj še rezervo; to ni zgornja meja. Z zelo jedrnatimi
sintetičnimi odgovori je lokalni razpon nižji: približno 20.300–32.500 vhodnih
in 1400–2300 vidnih izhodnih tokenov. Dejanski novi odgovori ostajajo neznani.

Limit `max_prompt_bytes=48000` ostane nespremenjen. Rekonstrukcija ga ne preseže,
vendar ima recenzent samo približno 10 kB rezerve. Če predhodni odgovori postanejo
daljši, lahko limit ustavi naslednjo zahtevo, tudi če ima ta dovolj izhodnih
tokenov. Dodan test tak primer izrecno preveri. Program poziva ne skrajša ali
prekorači samodejno. Predzadnje predaje vsebujejo tudi stare rezultate, zato
višji izhodni limiti lahko povečajo naslednje vhode in možnost ustavitve.

## 3. Dejanski zgodovinski podatki, ločeni od ocen

Pregledan je [uspešen stari AI-zagon 40781898486](https://github.com/mulecvojko-star/razvoj-dvizne-mize-ai-open/actions/runs/40781898486)
na commitu `3eaea55` (pred nalogo 04), artifact `openai-40781898486-1`, model
`gpt-5.4-mini-2026-03-17`, omejitev 1500 in štiri zahteve:

| Agent | Vrnjeni vhodni tokeni | Vrnjeni izhodni tokeni |
| --- | --- | --- |
| Konstruktor | 1142 | 933 |
| Hidravlik | 2629 | 933 |
| Ekonomist | 4168 | 1293 |
| Recenzent | 6083 | 1063 |
| Skupaj | **14.022** | **4222** |

To so dejanski podatki usage starega zapisa, ne stroškovni račun in ne dokaz
porabe novega engineering cikla. [Sedanja simulacija 40787220741](https://github.com/mulecvojko-star/razvoj-dvizne-mize-ai-open/actions/runs/40787220741)
na `53d7669` kaže 0 API-zahtev, `changes_required`, `engineering_verified=false`;
simulacija ne meri potrebnih modelskih tokenov. Noben nov plačljiv klic ni bil
potreben za branje teh že obstoječih zapisov.

Cenika v tej nalogi nismo preverjali, zato ne podajamo zneska EUR/USD.
Neznani so tudi dostop računa do modela danes, stanje dobroimetja, kvote,
morebitna cena cachiranih tokenov in dejanska poraba prihodnjega cikla.
**Projektni proračun OpenAI ni trda finančna omejitev.** Tudi nastavljene meje
izhoda ne omejijo same zase skupnih stroškov vhodov, neuspešnih zahtev ali drugih
uporabnikov projekta.

## 4. Zanesljivost in napake

- Nepopoln odgovor ob izhodni meji: `failure_code=max_output_tokens`, brez
  ponovitve, brez naslednjega agenta. Razpoložljivi usage se zdaj ohrani.
- Drugi nepopolni odgovori, zavrnitev in neveljaven JSON imajo ločene varne kode
  `incomplete_response`, `empty_or_refused`, `invalid_json`.
- Manjkajoče količine, napačne enote, številke ali stroški ne prestanejo sheme
  oziroma matematične validacije. Ostanejo samo zadnje uspešno preverjene predaje.
- API timeout, avtentikacija, omejitev hitrosti in druge napake ustavijo cikel
  po eni zahtevi; SDK je brez samodejnih ponovitev. Tudi HTTP 500 se ne ponovi.
- Omejitev poziva da `prompt_bytes_limit`, peta zahteva `request_limit`;
  blokada se zgodi pred pošiljanjem. Ročni ponovni zagon potrebuje novo odobritev.
- Poročilo kaže `stopped`, `technical_status=not_completed` in vedno
  `engineering_verified=false`. `completed_response` v attempts pomeni samo
  prejet dokončan API-odgovor, ne njegove matematične pravilnosti.
- `report.json` vsebuje porabo vsake razpoložljivega odgovora, tudi nepopolnega
  ali neveljavnega JSON. Manjkajoči usage je `null` v poskusu in je preštet v
  `requests_with_unknown_usage`. Vsota znanih tokenov ni nujno celoten obračun;
  odsotnost usage ni dokaz ničelnega stroška. Surova sporočila napak se ne shranijo.

Še vedno lahko spodletijo dostop/model, kvote, omrežje, 60-sekundni SDK timeout,
10-minutna omejitev opravila, predolg poziv ali odgovor, natančno kopiranje
cost_items/source, numerična validacija ali nalaganje artifacta. Pri zavrnitvi
ali izgubi povezave lahko nastanejo stroški brez celotnega rezultata. Tudi
uspešen cikel vrne `changes_required`, ne odobritve naprave.

## 5. Preverjanje in naslednji korak

Na začetnem main je uspešnih vseh 52 testov. S spremembo je uspešnih **62/62**
na Pythonu 3.12.14; brez zunanjih paketov 52 uspešnih in 10 testov SDK preskočenih.
Novi testi uporabljajo dejanski SDK s httpx.MockTransport: preverijo štiri
različne meje, token exhaustion z reasoning usage, HTTP 400/401/429/500,
timeout, zavrnitev, nepopoln odgovor, JSON, matematične napake, predaje,
limit poziva in odsotnost usage. Validacija workflowa z actionlint je uspešna.

```sh
python -m unittest discover -s tests -v
python -m src.orchestrator.token_audit --output /tmp/token-estimate.json
# Neobvezno, če imaš že prenesen stari sintetični artifact ZIP:
python -m src.orchestrator.token_audit --historical-artifact /pot/do/artifact.zip \
  --output /tmp/token-estimate-with-history.json
```

Po pregledu in združitvi PR naj uporabnik najprej ročno izvede simulacijo, preveri
manifest in nato **ločeno odobri** morebitni plačljivi cikel. Ohranjenih je največ
štiri API-zahteve, workflow_dispatch, veja main, blokada Re-run, okolje ai-trial
in sintetični primer. Ta priprava ni odobritev plačljivega zagona.
