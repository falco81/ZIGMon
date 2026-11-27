# ZIGMon Notifier – návod

Malá aplikace pro Windows 10/11. Sedí vedle hodin na hlavním panelu, hlídá
čidla ZIGMonu, která si vyberete, a když se některé spustí (pohyb, otevřené
dveře, voda, kouř, plyn, CO, sabotáž, vibrace, stisk tlačítka), ukáže vpravo
dole nad vším ostatním upozornění a tiše cinkne.

## Instalace

1. Rozbalte `ZigmonNotifier-1.0.0-win-x64.zip` kamkoli (třeba do
   `%LOCALAPPDATA%\Programs\ZIGMon Notifier\`).
2. Spusťte `ZigmonNotifier.exe`. Je to jeden soubor, nic se neinstaluje a
   nepotřebuje práva správce.
3. Windows může poprvé varovat před nepodepsaným programem: „Další informace“ →
   „Přesto spustit“.

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
   klidu (dveře zavřeny, sucho, bez pohybu).

## Používání

* Tečka na ikoně: **zelená** připojeno, **šedá** připojuje se, **červená**
  problém (najeďte myší pro důvod), **oranžová** upozornění pozastavena.
* Pravé tlačítko: stav, výběr čidel, připojení, pozastavení (15 min / 1 h / do
  odvolání), zvuk, „vytáhnout dopředu a převzít klávesnici“, automatické
  zavření po minutě, spouštění s Windows, zkušební upozornění, otevřít ZIGMon,
  ukončit.
* Upozornění: **Open ZIGMon**, **Mute 1 h** (jen toto čidlo na hodinu),
  **Dismiss** (nebo Esc). Najednou nejvýš čtyři; opakované spuštění téhož čidla
  jen zvýší počítadlo (×2, ×3 …).

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
* Žádná telemetrie, žádné automatické aktualizace, žádné logy.
