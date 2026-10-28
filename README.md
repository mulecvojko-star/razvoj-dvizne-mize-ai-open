# Razvoj dvižne mize – 4 AI-agenti

Učni Python projekt za predajo podatkov med štirimi specializiranimi agenti:
**Konstruktor → Hidravlik → Ekonomist → Recenzent**.

V nalogi 01 so vsi odgovori deterministično simulirani. Program ne kliče
OpenAI API-ja, nima zunanjih izvajalnih odvisnosti, ne potrebuje ključev in
ne povzroča stroškov za AI-modele. Ocene niso tehnični izračuni ali potrditev
varnosti naprave. Vsi podatki v primeru so sintetični.

## Zagon

Potrebuješ Python 3.11 ali novejši in Git. V terminalu izvedi:

```sh
git clone https://github.com/mulecvojko-star/razvoj-dvizne-mize-ai-open.git
cd razvoj-dvizne-mize-ai-open
```

Dokler Pull Request naloge 01 ni združen, preklopi na njegovo vejo:

```sh
git switch naloga-01-zacetna-struktura
```

Iz korenske mape repozitorija zaženi:

```sh
python -m src.orchestrator examples/V01-R01.json
python -m unittest discover -s tests -v
```

Namestitev paketov in konfiguracija okolja nista potrebni. Rezultat prvega ukaza
je JSON s predajo `V01-R01`, rezultati vseh štirih agentov v pravilnem vrstnem
redu in zbranimi odprtimi vprašanji. Recenzent predlaga `R02`, vendar novega
cikla ne zažene. Izhod lahko shraniš z `> rezultat.json`.

## Struktura

```text
src/
  agents/          simulirani agenti in ločena navodila v datotekah .md
  orchestrator/    preverjanje zaporedja, en cikel in ukazna vrstica
  models/          strukturirana predaja Handoff
tests/             testi zaporedja, identitete in ohranjanja predaj
examples/          sintetični vhod V01-R01.json
.github/workflows/ avtomatski testi in primer za Python 3.11–3.13
```

## Pogodba predaje

| Polje | Pomen |
| --- | --- |
| `variant` | Oznaka variante, npr. `V01` |
| `revision` | Revizija, npr. `R01` |
| `inputs` | Skupni vhodni podatki, enote so v imenih polj |
| `results` | Rezultati po imenih agentov, dodani po predpisanem vrstnem redu |
| `open_questions` | Zbrana odprta vprašanja za nadaljnjo obravnavo |

Varianta in revizija imata najmanj dve števki in pozitivno zaporedno številko.
Vsak agent prejme kopijo celotne predaje in doda svoj rezultat ter vprašanja.
Orkestrator preveri vrstni red, ohranitev vhodov, obstoječih rezultatov,
vprašanj in nespremenjeno varianto/revizijo. Ob kršitvi sproži `ValueError`
in ustavi cikel. Začetna predaja mora biti brez rezultatov.

Pri programski uporabi klicatelj določi pričakovano identiteto:

```python
from src.models import Handoff
from src.orchestrator import Orchestrator

handoff = Handoff(variant="V01", revision="R01", inputs={"data_origin": "synthetic"})
result = Orchestrator().run(
    handoff, expected_variant="V01", expected_revision="R01"
)
```

Tako je mogoče zavrniti zastarelo revizijo. Ukazna vrstica izvede identiteto iz
izbrane vhodne datoteke; ne vodi evidence zadnje revizije. Za novo revizijo
pripravi novo predajo (npr. `V01-R02`) s praznimi rezultati in ustreznimi vhodi.
Ni trajne baze, samodejne zanke, zagona pravih AI-agentov ali povezave z modeli.

## Navodila agentov

- [Konstruktor](src/agents/konstruktor.md)
- [Hidravlik](src/agents/hidravlik.md)
- [Ekonomist](src/agents/ekonomist.md)
- [Recenzent](src/agents/recenzent.md)

Navodila določajo prihodnje vloge; trenutna simulacija jih ne pošilja modelu.
GitHub Actions preverja programsko kodo ob `push` in `pull_request`, ne izvaja
razvojnih ciklov s pravimi AI-modeli.

## Javni učni podatki

V repozitorij dodajaj samo sintetične ali javne podatke. Ne dodajaj API-ključev,
zaupnih podatkov ali resničnih službenih projektnih dokumentov. Ključ se v tej
fazi ne nastavlja.
