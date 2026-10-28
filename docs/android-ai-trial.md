# En AI-preizkus prek telefona Android

Za zagon ni treba nameščati Pythona ali terminala na telefon. Uporabi GitHub v
Chromu in svoj račun z dovoljenjem za ročni zagon Actions v tem repozitoriju.
Ta postopek bo na voljo **po pregledu in združitvi PR naloge 03 v `main`**.
Workflow se ne izvaja ob commitu, Pull Requestu ali po urniku.

## 1. Najprej brezplačna simulacija

1. Na telefonu odpri [Actions](https://github.com/mulecvojko-star/razvoj-dvizne-mize-ai-open/actions).
2. Izberi **En AI preizkus (rocno)** in nato **Run workflow**.
   Če gumba ni, v Chromu odpri meni ⋮ → **Spletno mesto za namizne računalnike**
   (Desktop site). Preveri prijavo, dovoljenja in ali je workflow že na `main`.
3. Izberi vejo **main**, način **simulated**, model pusti nespremenjen.
   Privzete izhodne meje so 2500/2500/3000/3500 tokenov za štiri agente;
   poziv je omejen na 48000 bajtov na agenta.
   V simulaciji se model in API ne uporabljata.
4. V polje **approval** vnesi točno `ODOBRIM SIMULACIJO V01-R01`.
   Nikoli ne vnašaj API-ključa v ta obrazec.
5. Pritisni **Run workflow**. Odpri novi zagon in počakaj na zaključek.
6. V **Summary → Artifacts** prenesi ZIP `simulated-<run_id>-1`.
   Android ga običajno shrani v Prenosi (Downloads); odpri ga z aplikacijo Datoteke.

Pričakovani rezultat: `report.json` kaže `api_requests_started: 0`,
`result.json` vsebuje štiri rezultate, dnevnik pa stanje `awaiting_approval`.
Preflight ne potrebuje niti ne preverja ključa. Simulacija ne dobi skrivnosti.
GitHub Actions ima lastne pogoje in kvote; nič modelskih stroškov ne pomeni
jamstva, da bo vsaka uporaba infrastrukture GitHub vedno brezplačna.

## 2. Varna priprava ključa za prihodnji AI-zagon

Ta korak opravi lastnik repozitorija neposredno v upravljalniku skrivnosti.
Ključa ne pošiljaj v pogovor, issue, komentar, vhod workflowa ali datoteko v Gitu.
Ta naloga ključa ne ustvari in ne spremeni skrivnosti v tvojem računu.

Priporočena nastavitev:

1. V OpenAI uporabi ločen projekt za ta učni preizkus. Uporabi projektni ključ
   z najmanjšimi dovoljenji, ki omogočajo Responses API; kjer vmesnik omogoča
   omejitve modelov in hitrosti, dovoli samo izbrane modele in nizke omejitve.
   Preveri obračunavanje in [aktualni cenik](https://openai.com/api/pricing/).
2. V GitHub odpri **Settings → Environments → New environment** in ustvari
   okolje **ai-trial**:
   [nastavitve okolij](https://github.com/mulecvojko-star/razvoj-dvizne-mize-ai-open/settings/environments).
3. V okolju nastavi **Deployment branches and tags → Selected branches and tags**
   samo na vejo **main**. Če so na voljo zaščite **Required reviewers**, dodaj
   zaupanja vrednega pregledovalca. To ustvari dodatno ročno odobritev pred
   razkritjem skrivnosti opravilu. Zaščito je treba dejansko nastaviti v GitHubu;
   sama navedba `environment: ai-trial` v YAML je ne ustvari.
4. V **Environment secrets → Add secret** nastavi ime **OPENAI_API_KEY** in
   vrednost vnesi neposredno v varno GitHubovo polje za skrivnost.
   Na telefonu po potrebi uporabi Desktop site. Po uporabi izprazni odložišče.
5. Ključ shrani samo kot skrivnost tega okolja, ne kot splošno repository secret
   z istim imenom. GitHub sicer pri izrazu secrets.OPENAI_API_KEY lahko uporabi
   tudi skrivnost repozitorija, zato je obseg nastavitev pomemben.

Skrivnost je v workflowu povezana samo s korakom **En izrecno odobren AI-cikel**.
Preflight, simulacija in namestitev paketov je ne dobijo kot okoljsko spremenljivko.
Workflow ima `contents: read`, checkout ne ohrani poverilnic, zunanje Actions so
pripete na pregledane commit SHA. Ne zapisuje commitov ali modelskih odgovorov
v dnevnike. Vsi, ki lahko spremenijo zaupanja vredno kodo na `main` ali njene
workflows, lahko vplivajo na uporabo ključa; pred združitvijo preglej spremembe
in zaščiti `main`. GitHubovo maskiranje ni nadomestilo za skrbno ravnanje s ključem.

## 3. Prvi dejanski AI-preizkus — šele po tvoji odločitvi

Pripravljena integracija še ne dokazuje, da ima račun veljaven ključ, dobroimetje,
dovoljenja ali dostop do modela. Tega brez zahteve ponudniku nismo preverjali.
Pred začetkom preglej simulacijski artifact, omejitve in nastavitev skrivnosti.

1. Odpri isti workflow in **Run workflow** z vejo **main**.
2. Izberi **openai** in model **gpt-4.1-mini**, **gpt-4.1-nano** ali **gpt-5.4-mini**. Za vse tri je
   pripravljena uporaba Responses API in Structured Outputs; dostopnost v tvojem
   računu ostaja nepreverjena. Privzeti model je `gpt-4.1-mini`.
3. Preglej štiri ločene meje izhoda: Konstruktor 2500, Hidravlik 2500,
   Ekonomist 3000, Recenzent 3500. Dovoljene so vrednosti 256–4000; vrednost 0
   uporabi skupno rezervno `max_output_tokens` (privzeto 1500). Poziv omejuje
   `max_prompt_bytes` (16000, 32000 ali 48000; privzeto 48000).
4. Samo če odobriš plačljive API-klice za ta en cikel, vnesi
   **`ODOBRIM AI V01-R01`** in pritisni **Run workflow**.
5. Če je okolje zaščiteno, odpri zagon in opravi še **Review deployments**.
6. Po koncu prenesi artifact **openai-<run_id>-1**. Celotne odgovore glej v
   `result.json`, stanje in porabo v `report.json`, nastavitve v `manifest.json`,
   delne predaje pa v `runs/V01-R01.json`.

Po napaki **ne uporabi Re-run jobs**: ponovni poskusi istega zagona so zavrnjeni,
ker bi uporabili prejšnjo odobritev. Preglej artifact in za nov izoliran preizkus
odpri nov **Run workflow** ter ponovno izrecno vnesi odobritev. Vsak dispatch je
samostojen poskus istega sintetičnega `V01-R01`, označen z novim `run_id`; to ni
samodejni razvoj `R02`. Trajne medsebojne zgodovine revizij med cloud zagoni ni.
Za prihodnji razvoj drugih revizij je potrebna ločena nadgradnja postopka.

Zagon lahko ustaviš z **Cancel workflow**. To ne zagotavlja preklica že poslane
zahteve ali odprave njenih stroškov. Workflow poskusi naložiti razpoložljive delne
rezultate tudi ob napaki; ob prisilni prekinitvi, izgubi runnerja ali neuspešnem
nalaganju artifact morda ne bo na voljo. Pregled vedno zahteva človeka, tudi ko
model vrne `accepted`.

## Združljivost modela GPT-5.4 Mini

Po [uradni dokumentaciji modela](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
(preverjeno 2026-10-28) `gpt-5.4-mini` podpira Responses API in Structured Outputs.
Obstoječi `text.format` z `type=json_schema`, `strict=True`, zahtevana polja in
`additionalProperties=False` ne potrebujejo sprememb. Uporabljeni `instructions`,
`input`, `max_output_tokens` in `store=False` ostanejo enaki; dodatni parametri ali
nadgradnja SDK za to zahtevo niso potrebni. Privzeti model ostaja `gpt-4.1-mini`.

Model podpira reasoning, privzeti `reasoning.effort` je `none`; program ga ne
spreminja. [Omejitev izhodnih tokenov](https://developers.openai.com/api/docs/guides/token-counting)
vključuje tudi morebitne reasoning in nevidne oblikovne tokene, zato ni jamstvo
za enako število tokenov vidnega JSON. Prenizka meja lahko povzroči `incomplete`;
obstoječi adapter tak odgovor zavrne in ustavi cikel brez ponovitve.

Združljivost oblike zahtev je preverjena s simuliranimi odgovori prek dejanskega
SDK 2.54.0 in lokalno prestreženega HTTP-prenosa. Dostop računa do modela, kvote,
obračunavanje in kakovost resničnih odgovorov niso preverjeni. Model se lahko
cenovno razlikuje od modelov GPT-4.1; pred odobritvijo preveri aktualni cenik.

## Omejitve porabe in finančna meja

| Omejitev | Kaj zagotavlja |
| --- | --- |
| Največ 4 zahteve | En klic na agenta, brez ponavljanja ali novih ciklov |
| Štiri meje izhodnih tokenov | API-meja na zahtevo; privzeto 2500/2500/3000/3500, skupaj največ 11500 |
| `max_prompt_bytes` | Pred vsako zahtevo preveri vsoto UTF-8 bajtov navodil, JSON predaje in JSON sheme |
| SDK timeout 60 s | Časovna omejitev prenosa; ni finančna omejitev |
| Workflow timeout 10 min | Omeji trajanje AI-opravila, vključno z namestitvijo in nalaganjem |
| Concurrency | En aktiven workflow preizkusa; novi ročni zagoni lahko čakajo v vrsti |

Bajti niso tokeni in omejitev poziva ne vključuje vseh HTTP ovojnic. Presežena
velikost ustavi proces pred naslednjim API-klicem; zlasti daljši odgovori lahko
povzročijo ustavitev pred recenzentom. Prenizek izhodni limit lahko prekine JSON
in povzroči plačano, a neuspešno zahtevo. Prejšnji odgovori so del novih vhodov,
zato se vhodna poraba povečuje.

**Workflow ne uveljavlja trde finančne meje v EUR ali USD.** Projektni proračuni
pri ponudniku so lahko samo opozorila. Preveri, ali tvoja nastavitev dejansko
ustavi porabo; tudi omejeno dobroimetje in izklop samodejnega polnjenja nista
jamstvo takojšnjega obračunskega izklopa. Za ta preizkus uporabi ločen projekt,
nizke omejitve in po potrebi ključ po zaključku prekliči.

Ocena po aktualnem ceniku je `(vhodni tokeni × cena vhoda + izhodni tokeni × cena
izhoda) / 1.000.000`, kadar sta ceni podani za milijon tokenov. `report.json`
sešteva porabo vseh razpoložljivih odgovorov, tudi nepopolnih. Poskusi brez usage
so posebej označeni; neuspeh ali časovna omejitev ima lahko dodatne neznane stroške.
Poročilo ni račun. Glej [preverjanje pripravljenosti 04A](readiness-V01-R01.md).

## Artifacti, podatki in ponovljivost

Workflow uporablja samo pregledani primer `examples/V01-R01.json`; ne omogoča
nalaganja lastnih dokumentov, poljubne vhodne poti ali zunanjih virov. Pred spremembo primera preveri, da vsebuje samo sintetične podatke.
Izvorna datoteka, njena kontrolna vsota, commit, model, SDK, Python, uporabnik in
ID zagona so zabeleženi za sledljivost. SDK je za ta workflow pripet na 2.54.0.
Postopek je ponovljiv, odgovori dejanskih modelov pa niso deterministični.

Artifacti se hranijo **7 dni** in se ne shranjujejo kot javni commiti.
**V javnem repozitoriju artifact ni zaupna shramba**: prijavljeni uporabniki z
ustreznim dostopom ga lahko prenesejo. Tudi povzetek in dnevniki zagona so vidni
v skladu z dostopom do repozitorija. Vanj sodijo samo sintetični podatki.
`store=False` velja za zahtevo API-ja, ne pomeni jamstva ničelne hrambe pri ponudniku.

## Lokalno preverjanje brez plačljivih klicev

```sh
python -m unittest discover -s tests -v
TRIAL_APPROVAL='ODOBRIM SIMULACIJO V01-R01' \
  python -m src.orchestrator.cloud --output-dir /tmp/trial-simulation
TRIAL_MODE=openai TRIAL_APPROVAL='ODOBRIM AI V01-R01' \
  python -m src.orchestrator.cloud --preflight --output-dir /tmp/trial-preflight
```

`--preflight` vedno deluje brez ključa in nikoli ne ustvari SDK odjemalca.
V okolju GitHub Actions dodatno zahteva nov dogodek `workflow_dispatch`, `main`
in prvi poskus. Lokalno preverjanje ni preverba poverilnic ali dostopnosti modela.
Izhodne imenike izberi sveže: že obstoječi manifest prepreči ponovno izvajanje
istega lokalnega poskusa. `cloud-artifacts/` je izključen iz Gita.
