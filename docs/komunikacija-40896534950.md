# Zavrnitev komunikacije v zagonu 40896534950

Vir je dejanski [zagon 40896534950](https://github.com/mulecvojko-star/razvoj-dvizne-mize-ai-open/actions/runs/40896534950)
na commitu `898aaaba4a39f129af56e6b698bd80df68f835ae` in njegov artifact
`final-openai-40896534950-1`, ID `12905994418`, SHA-256
`2789c83f6f665abdd92bde454c99314149ff0a5c4b10b177901d252b81e88a79`.
Regresijska fixture vsebuje dejanski odgovor, izvor in opaženo porabo.

Prejšnja napaka je odpravljena: Hidravlik je vrnil vseh pet pravilno poimenovanih
kontrolnih količin, nobenih ničel za neznani pretok/moč ter obvezni vir REV-03.
Nova ustavitev je ponovljena brez API-klica: `validate_response` zavrne
`request_updates`, ker vsebuje REQ-09, REQ-10, REQ-11 in REV-03, medtem ko je seznam
prejetih zahtevkov v R01 prazen. To so ID-ji iz baze, ne dodeljene naloge Recenzenta.
Lokalna kontrolna kopija samo z `request_updates=[]` prestane preostalo validacijo.
Produkcijski program odgovora ne spreminja in nalog ne ustvarja za nazaj.

Popravek:

- JSON shema veže `request_updates.request_id` na dejansko dostavljene naloge
  posameznega prejemnika. Če jih ni, je dovoljeno samo prazno polje.
- Za nerecenzente so `requests` in `findings` prazni; za neekonomiste tudi
  `cost_items`. Identiteta, revizija in dovoljena odločitev so vezane na fazo.
- Konstruktor v prvi reviziji ne more predlagati spremembe brez podprte prejete
  naloge; prihodnji predlog je še vedno neodvisno izračunan in preverjen.
- Poziv izrecno loči `allowed_request_update_ids` od ID-jev virov v bazi.
  Dodatna vprašanja ostanejo v `open_questions`. Nominalno nezadosten izhodiščni
  katalogski kandidat ni potrjena izbira; agent naj izbere zadostnega, če obstaja.
- Lokalni varnostni pregledi ostanejo vključeni. Diagnostika navaja polje,
  `undelivered_request`, dovoljene ID-je in varen sklic na dejanski napačni ID.

Prvotni zagon je porabil dva klica in po njegovem shranjenem ceniku približno
0,0415095 USD. To je zgodovinski zagon uporabnika; ni strošek regresijskih testov.
Novi testi in simulacije so brezplačni, dejanski SDK testi uporabljajo prestrežen HTTP.

Aktualno uporabnikovo navodilo dovoljuje Codexu nove plačljive zagone po popravkih.
Izvedba uporablja nove ročne `workflow_dispatch` zagone, nikoli GitHubovega Re-run,
ter ohrani okolje ai-trial, Secret, omejitve tokenov in onemogočene ponovitve SDK.
Za to popravljalno serijo velja skupno največ 16 zahtev, štiri na vlogo in 3 USD
lokalne ocene. Pred naslednjim zagonom se upošteva že porabljeno in konservativna
rezervacija naslednjega zagona. Ob neznani porabi ali premalo preostalega proračuna
se izvajanje ustavi. Zaščit okolja ali veje se ne obide; to ne pomeni trde finančne
omejitve obračunavanja ponudnika. Dnevnik serije in povezave posameznih zagonov so
shranjeni v delovnem okolju ter navedeni v končnem poročilu.
