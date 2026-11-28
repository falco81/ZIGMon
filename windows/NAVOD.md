# ZIGMon Notifier – návod

Malá aplikace pro Windows 10/11. Sedí vedle hodin na hlavním panelu, hlídá
čidla ZIGMonu, která si vyberete, a když se některé spustí (pohyb, otevřené
dveře, voda, kouř, plyn, CO, sabotáž, vibrace, stisk tlačítka – nebo
**podmínka**, kterou správce v ZIGMonu nastavil na libovolném zařízení, třeba
„teplota ≥ 25 °C“ nebo „hlavice přepnuta na eco“), ukáže vpravo dole na
zvoleném monitoru nad vším ostatním upozornění se zvoleným zvukem.

Od verze 1.4.0 (se ZIGMonem 5.59.4) umí i **SMS**: příchozí SMS ukáže
v okénku s tlačítkem Odpovědět, v okně **Messages** jsou konverzace a nové SMS
se píší kontaktům uloženým v ZIGMonu, a klávesa na **Stream Decku** umí ukázat
poslední SMS nebo otevřít novou zprávu. Viz „SMS a Stream Deck“ níže.

## Instalace

1. **Stáhněte aplikaci ze svého ZIGMonu:** Settings → Messages → Desktop app →
   **Download ZIGMon Notifier** (vedle tlačítka je i otisk SHA-256 souboru).
   Uložte `ZigmonNotifier.exe` do složky, kam smíte zapisovat, třeba
   `%LOCALAPPDATA%\Programs\ZIGMon Notifier\` (kvůli aktualizacím ne do
   Program Files).
2. Aplikace potřebuje **.NET 10 Desktop Runtime** od Microsoftu (zdarma, jednou
   na počítač). Když chybí, Windows to při prvním spuštění řekne a nabídne
   stažení; ručně: https://dotnet.microsoft.com/download/dotnet/10.0 →
   „.NET Desktop Runtime 10“ pro Windows x64.
3. Spusťte `ZigmonNotifier.exe`. Je to jeden soubor, nic se neinstaluje a
   nepotřebuje práva správce.
4. Windows může poprvé varovat před nepodepsaným programem: „Další informace“ →
   „Přesto spustit“.

## Aktualizace

Nové verze přicházejí s aktualizacemi ZIGMonu a aplikace si je **sama stáhne ze
serveru, ke kterému je připojená** (po připojení a pak každých 6 hodin). Každou
aktualizaci nejdřív ověří: manifest musí být podepsaný **klíčem vydání ZIGMonu**
(Ed25519, klíč je zabudovaný v aplikaci) a stažený soubor musí mít přesně
podepsanou velikost a SHA-256. Nikdy nepřejde na starší verzi. Starý soubor
přejmenuje na `ZigmonNotifier.exe.old`, nový spustí a starý smaže; když se
cokoli nepovede, vrátí starou verzi zpět.

V menu (pravé tlačítko) je oddíl s aktualizacemi: **Update automatically**
(zapnuto; vypnuté = nová verze se jen ukáže a nainstaluje se kliknutím),
**Check for updates now** a řádek se stavem („Up to date – 1.2.0“,
„Updating to 1.3.0…“, „Update failed: …“).

## Nastavení

1. V ZIGMonu správce vytvoří klíč: **Settings → Messages → Desktop app**
   (pojmenujte ho třeba „Kancelář“, případně vyberte čidla). Klíč `zmn_…` se
   ukáže **jen jednou** – zkopírujte ho.
2. Při prvním spuštění se otevře okno **Connection** (později: pravé tlačítko na
   ikoně → Connection…). Zadejte adresu dashboardu (`https://…`), vložte klíč a
   klikněte **Test connection**. Zelená karta ukáže dům, verzi a jméno klíče.
   Pak **Save and connect**.
3. Pravé tlačítko → **Watched sensors…** (nebo dvojklik na ikonu): zapněte
   čidla, která mají upozorňovat. „Also when it clears“ upozorní i na návrat do
   klidu (dveře zavřeny, sucho, bez pohybu) nebo na to, že podmínka už neplatí.
   Každé sledované čidlo může mít **vlastní zvuk** (rozbalovací seznam pod ním,
   vedle tlačítko pro přehrání); „Default sound“ = zvuk z Alert settings.
4. **Podmínky** (ZIGMon 5.58 a novější) se zakládají v ZIGMonu u klíče:
   Settings → Messages → Desktop app → klíč → **Conditions** → Add condition
   (libovolné zařízení a atribut; > ≥ < ≤ = ≠, mezi, mimo, obsahuje, zapnuto/
   vypnuto, změna; s hysterezí). V aplikaci se pak objeví mezi čidly s ikonou
   budíku, podmínkou slovy a aktuální hodnotou – stačí je zapnout.

## Nastavení upozornění

Pravé tlačítko → **Alert settings…** (vše se ukládá hned a aplikace si to pamatuje):

* **Zvuk** – zapnout/vypnout; výchozí zvuk: Chime, Doorbell, Bell, Beeps, Pulse,
  Alarm, Siren, Klaxon nebo **vlastní soubor .wav** (nekomprimovaný, do 20 MB;
  když ho nejde přečíst, zahraje výchozí zvonek).
* **Jak dlouho hraje** – jednou, 5 s, 15 s, 30 s, 1 min, 5 min, nebo dokud
  upozornění nezavřete (nejdéle 30 minut). Dismiss, Mute, Open ZIGMon i Esc
  zvuk hned zastaví, stejně jako zavření posledního upozornění.
* **Hlasitost** – 0–100 % hlasitosti Windows, tlačítko Test.
* **Samo se zavře po** – nikdy, 10 s, 30 s, 1 min, 5 min, 15 min (čas běží
  znovu, když se čidlo spustí znovu nebo je nad upozorněním myš).
* **Zobrazovat na** – hlavní monitor, monitor s kurzorem myši, nebo konkrétní
  monitor (podle čísla displeje ve Windows; když je odpojený, použije se hlavní,
  dokud se nevrátí). „Show me“ tam ukáže zkušební upozornění.
* **Vytáhnout dopředu a převzít klávesnici.**

## Používání

* Tečka na ikoně: **zelená** připojeno, **šedá** připojuje se, **červená**
  problém (najeďte myší pro důvod), **oranžová** upozornění pozastavena.
* Pravé tlačítko: stav, výběr čidel, připojení, pozastavení (15 min / 1 h / do
  odvolání), zvuk, „vytáhnout dopředu a převzít klávesnici“, Alert settings…,
  spouštění s Windows, zkušební upozornění, otevřít ZIGMon, ukončit.
* Upozornění: **Open ZIGMon**, **Mute 1 h** (jen toto čidlo na hodinu),
  **Dismiss** (nebo Esc). Najednou nejvýš čtyři; opakované spuštění téhož čidla
  jen zvýší počítadlo (×2, ×3 …).
* **Zkušební upozornění ze ZIGMonu** (od verze 1.3.0): v ZIGMonu Settings →
  Messages → Desktop app má každý klíč tlačítko **Test alert**. Počítač s tímto
  klíčem hned ukáže upozornění „Test alert“ – i když nesleduje žádné čidlo, je
  pozastavený nebo ztlumený. Starší verze aplikace se nejdřív sama aktualizuje.

## SMS a Stream Deck (od verze 1.4.0)

Potřebuje ZIGMon 5.59.4 nebo novější a svolení správce pro daný klíč:
Settings → Messages → Desktop app → klíč → **SMS** (číst, posílat, kontakty;
vše je ve výchozím stavu vypnuté). Se starším ZIGMonem se nic z toho neukáže.

* **Okénko s SMS.** Příchozí SMS se ukáže jako karta mezi upozorněními na
  zvoleném monitoru: avatar s iniciálami, jméno nebo číslo, čas a text (dlouhý
  se posouvá). **Reply** otevře přímo v kartě pole pro odpověď s počítadlem
  znaků a dílů SMS (160 / 153 znaků na díl; s diakritikou nebo emoji jde zpráva
  jako Unicode, 70 / 67 na díl – počítá se stejně jako v ZIGMonu). **Send**
  (nebo Ctrl+Enter), **Copy**, **Dismiss** (nebo Esc) a tlačítko, které otevře
  celou konverzaci. Další SMS od stejného člověka se přidají do téže karty.
  Bez oprávnění posílat tlačítko Reply chybí. Když jsou upozornění pozastavená,
  okénko nevyskočí (v Messages SMS najdete).
* **Messages** (pravé tlačítko → Messages…; jen když to ZIGMon dovolí): vlevo
  konverzace podle kontaktu nebo čísla, nejnovější nahoře, nepřečtené s
  tečkou; vpravo vybraná konverzace v bublinách (vaše vpravo, neodeslaná
  červeně) a pole pro psaní s počítadlem. **New** (Ctrl+N nebo pravé tlačítko
  → Write an SMS…) píše komukoli: pole Komu se „štítky“ a našeptávačem podle
  jmen, čísel a skupin z kontaktů (kontakt s více čísly se nabídne pro každé
  číslo), oblíbení jako rychlé štítky, a jde napsat i libovolné číslo. Po
  odeslání se ukáže výsledek slovy – i hlášení ZIGMonu, např. o denním limitu.
  F5 načte seznam znovu.
* **Stream Deck.** Instalace Stream Decku se v ZIGMonu propojí s jednou nebo
  více aplikacemi (Settings → Messages → Stream Deck). Klávesa **poslední SMS**
  ukáže na tomto počítači poslední příchozí SMS (i už viděnou), klávesa **napsat
  SMS** otevře novou zprávu rovnou adresovanou lidem z klávesy – kurzor je v
  textu a okno vepředu, stačí napsat text a odeslat.
* **Přepínače** (Alert settings → Messages (SMS), uložené v tomto počítači):
  okénka s SMS zapnout/vypnout, zvuk SMS (Chime, Doorbell, Bell nebo Beeps,
  jednou) a zda vůbec reagovat na SMS klávesy Stream Decku.
* Text SMS, čísla ani kontakty se nikam neukládají ani nelogují; aplikace je
  drží jen v paměti, dokud běží.

## Bezpečnost

* Klíč umí **jen číst** stav vybraných čidel – nic nezmění. Správce ho může v
  ZIGMonu kdykoli zrušit.
* Klíč je uložen **šifrovaně** (Windows DPAPI, jen pro váš účet na tomto
  počítači) v `%APPDATA%\ZIGMon Notifier\settings.json`; celý už se nikde
  nezobrazí.
* Posílá se jen v hlavičce přes **HTTPS**; obyčejné http je povolené jen pro
  localhost. Přesměrování se nesledují.
* Vlastní (self-signed) certifikát aplikace sama nepřijme: ukáže jeho otisk
  SHA-256 a důvěřovat mu můžete až po porovnání s certifikátem na serveru. Pak
  platí jen ten jeden certifikát; když se změní, aplikace se zastaví a zeptá se.
* Žádná telemetrie, žádné logy. Aktualizace jen z vašeho ZIGMonu a jen
  podepsané klíčem vydání ZIGMonu.
