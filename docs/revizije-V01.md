# Omejen razvojni cikel V01-R01 → V01-R02

Naloga 06 podpira dve zaporedni **simulirani** reviziji s sintetičnimi podatki.
Odobritev zaporedja obsega samo ti dve brezplačni reviziji. Ne pomeni odobritve
API-klicev ali tehnične potrditve konstrukcije. Vsaka revizija izvede Konstruktorja,
Hidravlika, Ekonomista in Recenzenta; nato se program ustavi. R03 ni dovoljena.

## Zagon lokalno

```sh
python -m pip install '.[ai]'
python -m unittest discover -s tests -v
python -m src.orchestrator.revisions examples/V01-R01.json \
  --approve-sequence V01:R01-R02 --output-dir revision-artifacts
```

Namestitev dodatka `[ai]` omogoča tudi teste SDK s prestreženim prenosom; simulacija
sama potrebuje samo `pip install .`. Ključ ni potreben in noben agent ne kliče API-ja.
Izhodna mapa mora biti nova: obstoječega `sequence.json` program ne prepiše.
Za eno revizijo uporabi `--max-revisions 1 --approve-sequence V01:R01-R01`;
takrat skupni paket R01-R02 ni izdelan. Privzeta vrednost je 2, dovoljen razpon 1–2.
Prihodnje povečanje zahteva pregledano spremembo `HARD_REVISION_LIMIT` in politike;
sam vhod uporabnika ali modela ne more dovoliti tretje revizije.

## Zagon na telefonu Android

1. Na GitHubu odpri repozitorij, **Actions → Dve reviziji V01 (samo simulacija)**.
2. Izberi **Run workflow**, vejo `main`, `max_revisions: 2`.
3. V polje `approval` vnesi `V01:R01-R02` in zaženi workflow.
4. Po uspešnem zaključku odpri zagon in razdelek **Artifacts**.
5. Prenesi `revizije-V01-<run_id>-<attempt>`. V njem je
   `V01_R01-R02_Razvojni_cikel.zip` ter spremljajoči dnevniki.

Workflow je izključno ročen, deluje samo na `main`, nima dostopa do skrivnosti,
ima dovoljenje `contents: read` in sedemdnevno hrambo. Potrebna je prijava v GitHub;
po potrebi v brskalniku vključi namizni prikaz. Obstoječi ročni AI-preizkus ostaja ločen.

## Podatkovna politika A/B/C

- **A – fiksne zahteve:** 300 kg, ploščad 1200 × 800 mm, višini 350 in 1000 mm,
  zahtevani dvig 650 mm ter vsi drugi vhodni pogoji razen izrecno dovoljenih B.
  Ohranita se izvor in zgoščena sled zahtev. Recenzent jih ne sme spremeniti.
- **B – dovoljeni geometrijski parametri:** `arm_length_mm`, `structure_offset_mm`,
  `cylinder_base_x_mm`, `rod_pin_fraction`. Predlog potrebuje sledljivo nalogo
  Konstruktorja, razlog in neodvisno preverljiv prehod konkretne kontrole iz
  neuspešne v uspešno. Če že ponovni izračun nespremenjene geometrije odpravi
  numerično napako, sprememba geometrije ni dovoljena. Drugi posegi zahtevajo
  uporabniško odločitev. Trenutni konservativni načrtovalnik ne izmišljuje optimizacij.
- **C – rezultati:** sile, hod, hidravlične dimenzije in ocene izračunajo obstoječe
  deterministične funkcije. Besedilo agenta jih ne sme poljubno zamenjati.

Vsaka revizija začne s praznimi rezultati ter znova izvede in validira izračune.
Predaja R02 vsebuje nespremenljiv `revision_context`: hash R01, hash A, naloge,
spremembe in obseg odobritve. Vsak agent zabeleži prejete naloge in opravljene
ponovne preveritve. Stari JSON brez tega polja ostaja združljiv.

## Naloge in dokazi

Naloga ima stabilen ID, opis, odgovornega agenta, pomembnost, povezavo na podatek,
predlagani popravek, status `open` / `resolved` / `unresolved` ter sled izvora.
Enake ugotovitve lokalne validacije in Recenzenta se združijo z ohranitvijo obeh
virov. Manjkajočega lastnika program ne ugiba iz besedila: `null` pomeni ročni
pregled. Nadomestne povezave na JSON-poti so izrecno označene kot sklepane.

Izginotje ugotovitve ali modelova trditev `resolved` ni dokaz popravka. Zaprtje
zahteva neodvisno ponovno preverjanje konkretne prvotno neuspešne kontrole,
povezano s hashom izvornega rezultata. Poročilo ločuje dokazane popravke,
nespremenjene nerešene naloge, nove ugotovitve in odločitve uporabnika.
Strukturne preveritve zunaj podprtega računskega modela ostanejo nerešene.

## Rezultat priloženega sintetičnega primera

| Količina | R01 | R02 |
|---|---:|---:|
| Nosilnost [kg] | 300 | 300 |
| Zahtevani dvig [mm] | 650 | 650 |
| Največja sila cilindra [N] | 64.136,45 | 64.136,45 |
| Hod cilindra [mm] | 143,08 | 143,08 |
| Nepopolni sintetični delni stroški [EUR] | 1.120 | 1.120 |
| Dokazano odpravljene ugotovitve | — | 0 |
| Nerešene ugotovitve | 3 | 3 |

Geometrija ostane enaka: iz obstoječih podatkov ni utemeljenega popravka.
Nerešeni ostajajo napetosti/uklon/spoji/stabilnost (Konstruktor), vgradnja cilindra,
pretok in varnost hidravlike (Hidravlik) ter preverljive ponudbe in neznani stroški
(Ekonomist). **Izboljšanje ni dokazano.** Obe reviziji ohranita
`changes_required` in `engineering_verified=false`. Programsko uspešno zaporedje
ne pomeni tehnično potrjene konstrukcije. Vseh osem agentnih korakov je simuliranih;
število zunanjih API-klicev je nič.

## Datoteke in ustavitev

Skupni `V01_R01-R02_Razvojni_cikel.zip` vsebuje:

- `V01-R01_Razvojni_paket.zip` in `V01-R02_Razvojni_paket.zip` iz Naloge 05;
- `V01_R01-R02_Primerjava.pdf` (A4, slovenska pisava, enote in dejanski statusi);
- `Ugotovitve_in_statusi.json` in `Primerjava.json`;
- `Sledljivost_cikla.json`;
- `V01-R01_Izvorni_podatki.json` in `V01-R02_Izvorni_podatki.json`.

Posamezna razvojna paketa še vedno vsebujeta štiri PDF, Excel s formulami in izvorni
JSON iz Naloge 05. Primerjava stroškov je samo primerjava razpoložljivih postavk;
neznane vrednosti niso nič in delni seštevek ni potrjena cena naprave.

`sequence.json` hrani vmesno stanje, odobritev, fiksne zahteve, hashe, naloge in dnevnik
sprememb. Datoteka `STOP` v izhodni mapi ali `cycles/STOP` ustavi izvajanje.
Pri napaki ostanejo že izdelani posamezni paketi, delne predaje in diagnostika.
Celoten skupni ZIP se objavi atomsko šele po dveh uspešnih revizijah in uspešni
izdelavi dokumentov. Skrivnosti se ne zapisujejo; dokumentni izvoz uporablja
obstoječe odstranjevanje skrivnosti. Hashi so sledljivost, ne digitalni podpis.

## Prihodnji plačljivi način: načrt, ne vključena funkcionalnost

`--mode openai` je za večrevizijsko zaporedje onemogočen pred izdelavo odjemalca.
Tudi agent in transport zavrneta predajo z `revision_context` pred API-zahtevo.
Obstoječi enociklični način z modelom `gpt-5.4-mini`, omejitvami tokenov, varovanjem
ključa, največ štirimi zahtevami in brez ponovitev ostaja nespremenjen.

Za prihodnjo implementacijo je predvideno:

1. Ločeno, izrecno odobren R01: največ štiri zahteve; pregled shranjenih rezultatov.
2. Ločena odobritev R02 s hashom potrjenega R01, odobrenimi nalogami in dovoljenimi
   spremembami: ponovno največ štiri zahteve, brez samodejnega nadaljevanja.
3. Če se R01 ponovno uporabi iz preverjenega artefakta, lahko nov preizkus porabi
   največ štiri zahteve samo za R02. Dve novi plačljivi reviziji bi bili dve ločeno
   odobreni izvajanji, nikoli en preizkus z osmimi zahtevami.
4. Vsako izvajanje potrebuje lastni števec, omejitve tokenov po agentih in velikosti
   vhodov, evidenco dejanske porabe, zaustavitev ob napaki ter brez ponovitev.
   Omejitve tokenov in projektni proračun niso trda finančna omejitev.

Ta načrt ne omogoča plačljivega zagona. Implementacija, integracijski pregled in
izrecna odobritev uporabnika so potrebni pred prvo plačljivo večrevizijsko uporabo.
