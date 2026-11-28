# ZIGMon Notifier – návod

Malá aplikace pro Windows 10/11. Sedí vedle hodin na hlavním panelu, hlídá
čidla ZIGMonu, která si vyberete, a když se některé spustí (pohyb, otevřené
dveře, voda, kouř, plyn, CO, sabotáž, vibrace, stisk tlačítka – nebo
**podmínka**, kterou správce v ZIGMonu nastavil na libovolném zařízení, třeba
„teplota ≥ 25 °C“ nebo „hlavice přepnuta na eco“), ukáže vpravo dole na
zvoleném monitoru nad vším ostatním upozornění se zvoleným zvukem.

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
