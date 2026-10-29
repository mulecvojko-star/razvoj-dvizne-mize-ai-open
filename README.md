# Razvoj dvižne mize – 4 AI-agenti

Učni Python projekt z zaporedjem **Konstruktor → Hidravlik → Ekonomist → Recenzent**.
Privzeti način je deterministična simulacija brez ključa, omrežja in API-stroškov.
Ločeni način `openai` uporablja uradni Python SDK in OpenAI Responses API s
strukturiranim JSON odgovorom. Vsak zagon izvede največ en izrecno odobren cikel.

Uporabljaj samo sintetične ali javne podatke. Rezultati modelov in simulacije niso
strokovna potrditev dimenzioniranja, varnosti, skladnosti ali stroškov naprave.

## Popravek stroškovne predaje (04B)

[Poročilo 04B](docs/economist-04b.md) loči potrjeno zavrnitev seznama stroškov,
reproducirano težavo binarnega float in neznani dejanski odgovor Ekonomista.
Stroški so normalizirani na cente in preverjeni po kategoriji; zahteva modelu
omeji postavke na dovoljeni katalog. Ob zavrnitvi poročilo poda konkretno
postavko, polje in razlog. To ne dovoljuje izmišljenih preverjenih cen.

## Pripravljenost za plačljivi preizkus

[Poročilo naloge 04A](docs/readiness-V01-R01.md) loči dejansko staro porabo od
ocen novega cikla. Ročni cloud workflow omogoča ločene izhodne meje 2500/2500/3000/3500
za Konstruktorja, Hidravlika, Ekonomista in Recenzenta. Limit poziva ostaja 48000
bajtov. Večja meja izhoda ni zagotovilo zaključka cikla ali trda finančna meja.
`report.json` ohrani varne kode napak in razpoložljivo porabo tudi pri nepopolnem
odgovoru. Ocenjevalnik `python -m src.orchestrator.token_audit --output /tmp/audit.json`
ne kliče modelov in ne potrebuje ključa.

## Preliminarna inženirska varianta

Naloga 04 dodaja determinističen izračun škarjaste geometrije, hoda in sile
cilindra, primerjavo hidravlike ter neodvisne numerične kontrole recenzenta.
Glej [tehnični opis V01-R01](docs/engineering-V01-R01.md) in
[celoten sintetični rezultat](examples/V01-R01-engineering-result.json).
Izračuni niso potrditev varnosti: pregled ostane `changes_required`,
`engineering_verified=false`, nedoločeni podatki pa `null`.

## Zagon iz oblaka ali telefona Android

Za ročni preizkus enega cikla glej [navodila za Android](docs/android-ai-trial.md).
Workflow **En AI preizkus (rocno)** je privzeto simuliran, nima samodejnih sprožilcev
in rezultate shrani kot 7-dnevni artifact. Dejanski način zahteva ločeno odobritev
in skrivnost okolja `ai-trial`. Trda finančna meja ni zagotovljena. Na voljo bo po
združitvi naloge 03 v `main`.

## Zagon simulacije

Potrebuješ Python 3.11+ in Git. Simulacija nima zunanjih izvajalnih odvisnosti.

```sh
git clone https://github.com/mulecvojko-star/razvoj-dvizne-mize-ai-open.git
cd razvoj-dvizne-mize-ai-open
python -m unittest discover -s tests -v
python -m src.orchestrator examples/V01-R01.json --approve-cycle V01-R01
```

Zastavica `--approve-cycle` je nova in obvezna: uporabnik odobri točno določeno
varianto in revizijo. Izhod je JSON, dnevnik pa `.runs/V01-R01.json`. Ponovni
zagon iste revizije v istem dnevniku je zavrnjen. Testi uporabljajo začasne
imenike in simulirane odgovore, tudi kadar je SDK nameščen.

## Konfiguracija OpenAI (zagon lahko povzroči stroške)

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install '.[ai]'
```

Ključ `OPENAI_API_KEY` nastavi v varnem okolju terminala ali prek upravljalnika
skrivnosti. V Bash ga lahko vneseš brez prikaza in brez zapisovanja v zgodovino:

```sh
read -r -s -p 'OPENAI_API_KEY: ' OPENAI_API_KEY
export OPENAI_API_KEY
```

Program ne bere `.env` datotek in ključa ne sprejema kot argument CLI. Ne zapisuj
ga v kodo, JSON, dnevnik, GitHub ali izpis terminala. `.env*` in `.runs/` so
izključeni iz Gita. Model izberi iz modelov, dostopnih tvojemu računu, ki podpirajo
Responses API in Structured Outputs, npr. `gpt-4.1-mini`; razpoložljivost se spreminja.

Naslednji ukaz je namenjen šele uporabnikovi odločitvi za plačljiv zagon:

```sh
export OPENAI_MODEL=gpt-4.1-mini
python -m src.orchestrator examples/V01-R01.json \
  --mode openai --approve-cycle V01-R01 --runs-dir .runs/openai \
  --max-output-tokens 2500
```

| Nastavitev | Pomen |
| --- | --- |
| `--mode simulated` | Privzeto; ne ustvari SDK odjemalca |
| `--mode openai` | Pravi modeli; ključ je obvezen |
| `OPENAI_MODEL` / `--model` | Model; CLI ima prednost; brez privzetega plačljivega modela |
| `--max-output-tokens` | Omejitev na odgovor, privzeto 2500, dovoljeno 256–16000 |
| `--approve-cycle V01-R01` | Odobritev enega cikla; v načinu OpenAI tudi njegovih API-stroškov |
| `--runs-dir` | Trajni lokalni dnevnik, privzeto `.runs` |

SDK je neobvezen (`openai>=2.0,<3`); integracija je lokalno preverjena z verzijo
2.54.0. Adapter uporablja `responses.create`, strogo JSON shemo, `store=False`,
60-sekundno časovno omejitev in `max_retries=0`. Ne uporablja orodij, zunanjega
brskanja, samodejnih predaj SDK ali zank. Dodatni Agents SDK tu ni potreben,
ker zaporedje in pogodbe nadzoruje obstoječi orkestrator.

## Odobritev, revizije in ustavitev

Vsaka varianta začne pri `R01`. Nov zagon zahteva novo vhodno datoteko s praznimi
`results`, zaporedno naslednjo revizijo in novo zastavico odobritve. Primer po
pregledu `V01-R01`: pripravi `examples/V01-R02.json`, popravi vhode in nastavi
`revision` na `R02`, nato izrecno odobri:

```sh
python -m src.orchestrator examples/V01-R02.json --approve-cycle V01-R02
```

Ohrani isti `--runs-dir` za isto razvojno zgodovino. Dnevnik veže novo revizijo
na kontrolno vsoto prejšnjega zapisa. Tudi ustavljeni poskus porabi revizijo, saj
je lahko del API-klicev že izveden in zaračunan. Ni samodejnega nadaljevanja ali
samodejnega ponovnega izvajanja neuspešnega klica. Uporabnik pregleda delne rezultate
in zahteve recenzenta, pripravi nove vhode ter odobri naslednjo revizijo. Program
ne prenaša samodejno zahtev za popravke v nove vhodne podatke.

Stanja dnevnika so `running`, `stopped` in `awaiting_approval`. Zaključeni pregled,
tudi `accepted`, vedno konča cikel; `changes_required` in `blocked` ničesar ne
zaženeta samodejno. Datoteka vsebuje odobreno oznako, čas odobritve, izvorni hash,
način, zadnjo dokončano predajo in odločitev recenzenta.

Za ustavitev pred naslednjim agentom v drugem terminalu ustvari:

```sh
touch .runs/STOP
```

Pri drugem `--runs-dir` uporabi ta imenik. Datoteka ostane aktivna, dokler je ne
odstraniš. Že poslani HTTP zahtevek se s tem ne prekliče; zanj velja časovna omejitev.
`Ctrl+C` zabeleži ustavitev in ohrani že dokončane predaje. Ob trdi prekinitvi lahko
ostaneta stanje `running` in `.lock`; pred ročno odstranitvijo zaklepa preveri, da
noben proces ne teče. Dnevnik in zaklep sta lokalna, nista porazdeljena avtentikacija
ali dokaz identitete uporabnika. Brisanje oziroma menjava dnevnika ponastavi zgodovino.

## Arhitektura in pogodbe

```text
src/
  agents/
    konstruktor.md, hidravlik.md, ekonomist.md, recenzent.md
    simulated.py       deterministični odgovori, ohranjena prvotna polja
    openai_agent.py    adapter Responses API, štiri ločene vloge
  models/
    handoff.py         Handoff: identiteta, vhodi, viri, rezultati, vprašanja
    contracts.py       JSON shema, validacija vhodov in recenzije, SHA-256
  engineering/         deterministična geometrija, hidravlika, stroški in neodvisni pregled
  orchestrator/
    pipeline.py        primitiven enkratni zaporedni izvajalnik
    cycles.py          odobritve, revizije, zaklep in shranjevanje delnih rezultatov
    __main__.py        CLI z izbiro načina
    cloud.py           ročni sintetični oblačni preizkus in preverjanje brez API-ja
```

Vsak agent dobi kopijo celotne predaje. Naslednji vidi vse prejšnje rezultate,
predpostavke in vprašanja. Orkestrator zavrne spremembe identitete, vhodov, virov,
prejšnjih rezultatov, vrstnega reda ali že zbranih vprašanj.

| Polje | Pomen |
| --- | --- |
| `variant`, `revision` | Npr. `V01`, `R01`; pozitivna številka z najmanj dvema števkama |
| `inputs` | Podatki z enotami v imenih; nespremenljivi skozi cikel |
| `input_sources` | Vir vsakega vhodnega polja, npr. `synthetic:učni-primer` ali javni URL |
| `results` | Rezultati agentov po zahtevanem vrstnem redu |
| `open_questions` | Ohranjen seznam vseh dosedanjih odprtih vprašanj |

Upravljani cikel zahteva `data_origin` (`synthetic` ali `public`), pozitivne končne
številke `payload_kg`, `platform_length_mm`, `platform_width_mm`, `min_height_mm`
in `max_height_mm`, pri čemer mora biti največja višina večja od najmanjše.
Logične vrednosti, števila v nizih, NaN, neskončnost in manjkajoči podatki so zavrnjeni
pred klicem modela. CLI ob odsotnosti `input_sources` doda ime in SHA-256 izvorne
datoteke za vsako polje; navedene vire ohrani. Izvor je navedba uporabnika, ne preverba
verodostojnosti javnega vira ali samodejno prepoznavanje zaupnih podatkov.

AI-odgovor vsebuje identiteto, `summary`, seznam `assumptions`, `calculations`, `cost_items`, `outputs`
(`name`, `value`, `unit`, `basis`), `open_questions`, `decision` in `findings`.
Rezultatu adapter lokalno doda `trace`: hash vhodov, celotne prejete predaje in
navodil, ime modela, ID odgovora, čas ter porabo vhodnih/izhodnih tokenov.
Simulacija doda predpostavke in hashe brez modela in porabe tokenov. Shema je
v `src/models/contracts.py`; dodatna polja v modelskem odgovoru niso dovoljena.

Recenzent vrne odločitev `accepted`, `changes_required` ali `blocked`. Vsaka
ugotovitev vsebuje enolični `id`, `severity` (`info`, `minor`, `major`, `critical`),
`status` (`open`, `resolved`), `target_agent`, opis in neprazno zahtevo `required_correction`.
Odprte ugotovitve preprečijo `accepted`. Zahteva za popravke potrebuje vsaj eno
odprto ugotovitev. Tudi sprejet rezultat ostane `engineering_verified=False`.
Napaka API-ja, zavrnitev modela, nepopoln odgovor ali neveljavna pogodba ustavi cikel;
surova sporočila napak ponudnika se ne izpisujejo in ne shranjujejo.

Za programsko uporabo upravljanih ciklov:

```python
from pathlib import Path
from src.models import Handoff
from src.orchestrator.cycles import CycleRunner

# data je preverjen vhodni slovar z vsemi zahtevanimi polji in input_sources.
handoff = Handoff(**data)
result = CycleRunner(Path(".runs")).run(handoff, approved_label=handoff.label)
```

Nizkonivojski `Orchestrator.run` je ohranjen za združljivost s prvotnimi testi in
vgradnjo; ne vodi odobritev ali zgodovine. Za uporabniške zagone uporabljaj CLI ali
`CycleRunner`, ne neposrednega izvajalnika. Odobritev je dejanje klicatelja; model
je ne more izdati prek svojega izhoda.

## API-stroški in omejitve

Simulacija in vsi testi: **0 USD za modele**. V tej nadgradnji ni bilo izvedenih
plačljivih klicev. Uspešen AI-cikel pomeni štiri zahteve; ob napaki se konča prej.
Vsak naslednji model prejme tudi prejšnje rezultate, zato se vhodna poraba povečuje.

Izračun okvirnega stroška: `(vhodni tokeni × vhodna cena + izhodni tokeni × izhodna
cena) / 1.000.000`, pri cenah za milijon tokenov. Če hipotetično predpostavimo
20.000 vhodnih in 6.000 izhodnih tokenov skupaj ter ceni 0,40 in 1,60 USD za milijon,
je cikel približno **0,0176 USD**. To je ilustracija, ne preverjena trenutna cena
ali zgornja meja. Preveri [aktualni cenik](https://openai.com/api/pricing/) za izbrani
model in nastavi projektne omejitve porabe pri ponudniku. Dnevnik vsebuje dejansko
porabo iz odgovorov, ne obračuna USD. Časovne omejitve in neuspešne zahteve lahko
še vedno povzročijo stroške; izhodni limit ni finančni limit za vhodne tokene.

Sistem ne preverja fizikalne pravilnosti, standardov ali resničnosti virov. Model
lahko poda napačen rezultat kljub pravilnemu JSON. Sledljivost s hashi omogoča
primerjavo podatkov, ni kriptografski podpis. V načinu OpenAI se celotna predaja
pošlje ponudniku. `store=False` ni zagotovilo ničelne hrambe po vseh pravilih
ponudnika; uporabi le dovoljene sintetične ali javne podatke.

## Preverjanje

```sh
# Brez SDK: simulacija in pogodbe, testi dejanskega SDK so preskočeni.
python -m unittest discover -s tests -v
# Z nameščenim [ai]: tudi SDK s prestreženim HTTP prenosom, brez omrežnih klicev.
python -m pip install '.[ai]'
python -m unittest discover -s tests -v
```

Prvotnih 9 testov ostaja nespremenjenih. Dodatni testi preverjajo celotno AI-predajo
s simuliranimi odzivi, izvore in hashe, napačne/manjkajoče vhode, revizije, odobritve,
strukturirano recenzijo, ustavitev, delne rezultate, sočasni zagon, CLI brez ključa,
JSON shemo v dejanski zahtevi SDK ter zavrnitev/nepopoln odgovor/časovno napako.
GitHub Actions namesti `[ai]` in preveri teste ter simulirani primer na Pythonu
3.11, 3.12 in 3.13. Skrivnosti v CI niso potrebne.

Referenci integracije: [uradni Python SDK](https://github.com/openai/openai-python)
in [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs).
