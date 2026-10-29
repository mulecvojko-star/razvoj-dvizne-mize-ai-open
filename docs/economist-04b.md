# Naloga 04B – zavrnjena stroškovna predaja Ekonomista

## Dokazano iz zagona in kode

Pregledan je [zagon 40790622780](https://github.com/mulecvojko-star/razvoj-dvizne-mize-ai-open/actions/runs/40790622780)
na commitu `ae8e8e5`, artifact `openai-40790622780-1`.

- `report.json` potrjuje tri API-zahteve in tri `completed_response`.
- Ekonomist ima 911 izhodnih tokenov pri meji 3000 in 0 reasoning tokenov.
  To ni bila ustavitev zaradi izhodne meje. JSON je dosegel poslovno validacijo.
- Shranjeni sta samo sprejeti predaji Konstruktorja in Hidravlika. Cikel je
  pravilno `stopped`, tehnično `not_completed`, `engineering_verified=false`.
- Sporočilo napake izvira iz `src/engineering/contracts.py::validate_claims`:
  primerjave **celotnih seznamov** `model["cost_items"] != expected["cost_items"]`.
  Pred njo sta bila preverjena JSON shema in numerični vmesni seštevek.
  `src/engineering/review.py` ni sprožil te zavrnitve: Recenzent še ni bil poklican.
- V artifactu ni `result.json` ali zavrnjenega odgovora Ekonomista; dnevnik
  vsebuje samo zadnjo sprejeto predajo in splošno sporočilo. Poskusi vsebujejo
  metapodatke/usage, ne odgovora. Surovi odgovori se tudi ne izpisujejo v log.

**Natančna problematična postavka in polje iz tega zagona nista dokazljiva.**
Za njuno določitev potrebujemo dejanski zavrnjeni Ekonomistov JSON odgovor,
ki v pregledanem artifactu in repozitoriju ni shranjen. Novih API-klicev za
njegovo pridobivanje nismo izvajali.

## Dokazljivo neskladje pri denarnih zneskih

V shranjeni konstrukcijski predaji je dolžina roke 1100 mm. Stara referenca je
računala sintetično ceno rok z binarnim float:

```python
4 * 1100 / 1000 * 50  # 220.00000000000003
```

Stara točna primerjava zavrne seznam z običajnim zneskom `220` ali `220.0`,
čeprav je to ista cena v EUR na cente. To je **reproducirana napaka validatorja**,
ne dokaz, da je prav ta razlika nastala v konkretnem AI-odgovoru.
Spremenjen vrstni red postavk ali drugačen `source`, kategorija ali cena so
bili prav tako možni vzroki istega splošnega sporočila; ostajajo hipoteze.

Poziv je zahteval kopiranje, shema pa je dovoljevala poljubna besedila kategorij,
vrste cen in virov. Poslovni validator je hkrati zahteval enak seznam, enak vrstni
red ter enake float vrednosti. To je omogočalo strukturno veljaven odgovor, ki
ni ustrezal dejanski poslovni pogodbi. Še posebej ni bilo jasno, da je `source`
dobesedna oznaka lokalne reference in ne prostor za dodatno razlago izvora.

## Popravek in ohranjene zaščite

1. Dovoljene sintetične/neznane postavke so v skupnem lokalnem katalogu
   `src/engineering/costs.py`; vsebina in cene ostajajo enake. Cena rok je
   izračunana z Decimal in zaokrožena na 0.01 EUR (`ROUND_HALF_UP`).
2. Zneski se primerjajo na cente. Dovoljen je le binarni šum do 1e−9 EUR;
   `220.00000000000003` je isto kot `220`, `220.001` in `220.01` pa se zavrneta.
   Ne pretvarjamo številskih nizov, logičnih vrednosti ali `null` v denar.
3. Postavke se preverjajo po enolični `category`, ne po vrstnem redu. Vsaka mora
   biti prisotna natanko enkrat; manjkajoče, dodatne ali podvojene se zavrnejo.
4. Ekonomistov dejanski Responses API zahtevek dobi ožjo JSON shemo: šest
   postavk, vsaka z dovoljenim parom kategorije/vrste in točnim zneskom ter
   besedilom vira (enum/anyOf). Te ne spreminjamo za druge vloge. Velikost
   dejanske sheme je vključena v obstoječo omejitev poziva.
5. Navodila izrecno zahtevajo samo štiri polja, znane kategorije, JSON številke
   za EUR in `null` za neznane cene. Razlage, DDV in dodatne neznanke sodijo
   v `summary`, `outputs` ali `open_questions`; ne v spremenjen katalog.
6. `source` ostaja preverjen dobesedno. Neznani zneski ostajajo `null`, ne 0.
   `verified` ni dovoljen v tem sintetičnem preizkusu. Nobene napačne postavke
   ne popravljamo ali samodejno zamenjamo s pričakovano. `verified_prices=[]`,
   `total_EUR=null` in odprta naloga za Ekonomista ostajajo ohranjeni.
7. Recenzent poleg vsote in sledljivosti preveri postavke proti istemu dovoljenemu
   katalogu ter navede pot/polje zavrnitve. To ni preverba resničnih dobaviteljskih
   cen. Različne dejanske cene zahtevajo nov postopek s preverljivimi dokazi.

## Diagnostika prihodnjih napak

`runs/V01-R01.json → error.details` in `report.json → validation_details`
vsebujeta strukturirane razloge, na primer:

```json
{
  "path": "cost_items[2].source",
  "index": 2,
  "category": "cylinder",
  "field": "source",
  "reason": "source_mismatch"
}
```

Dodana je tudi pričakovana vrednost. Pri varnih numeričnih/enum vrednostih se
lahko zabeleži prejeta vrednost; pri neznanem besedilu vira samo SHA-256 in
dolžina, ne surovi modelov tekst. Neznane kategorije in dodatni ključi se ne
izpisujejo kot poljubno besedilo. Razlogi ločijo `amount_mismatch`,
`price_kind_mismatch`, `source_mismatch`, `missing_field`, `missing_category`,
`duplicate_category`, `unknown_category`, `unexpected_fields` in napačno obliko
seznama/objekta. Neveljavna stroškovna polja se pregledajo pred splošno JSON
shemo, zato tudi manjkajoči znesek dobi uporabno postavko/polje.

Diagnostika ne spremeni neuspeha v uspeh: zadnji dobri predaji ostaneta,
Recenzent se po napaki Ekonomista ne kliče in `result.json` se ne ustvari.

## Preverjanje brez plačljivih klicev

Na začetnem main je bilo uspešnih 62 testov. Z dodanimi regresijami je uspešnih
**72/72**, vključno z obstoječim štiriagentnim SDK-preizkusom s prestreženim HTTP.
Brez zunanjih paketov uspe 62 testov, 10 testov SDK se preskoči.

Novi testi pokrivajo pravilne/reorganizirane stroške, float/cente, manjkajoče in
napačne postavke, izmišljene preverjene cene, neznane zneske, natančno diagnostiko,
veljavnost ožje sheme, odvisnost cene od dolžine rok in ustavitev po tretjem
simuliranem odgovoru. Reprodukcija napačnega vira je izrecno **sintetična**, ne
ponovitev izgubljenega odgovora iz zagona 40790622780.

Lokalna simulacija in meritev velikosti pozivov sta uspešni. Za kratke sintetične
odgovore so pozivi približno 14.2/19.0/25.5/26.2 kB, pod obstoječim limitom.
Daljši resnični odgovori lahko mejo še vedno presežejo; ne povečujemo je samodejno.

Model, izhodne meje 2500/2500/3000/3500, skupna rezervna meja, 48000 bajtov,
SDK brez ponovitev, največ štiri zahteve, ročni workflow, odobritev, ključ in
varnostne nastavitve niso spremenjeni. Ni bilo novega plačljivega AI-preizkusa.
Prihodnji dejanski zagon nove sheme ostaja predmet uporabnikove ločene odobritve.
