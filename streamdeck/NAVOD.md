# ZIGMon pro Stream Deck

Ovládejte dům se ZIGMonem z **Elgato Stream Deck XL** (32 tlačítek) nebo **Stream Deck +**
(8 tlačítek, 4 otočné ovladače a dotyková lišta) a vidějte jeho stav živě: zásuvky, světla
a stmívače, topení, žaluzie, scény, měření i zdraví samotného ZIGMonu. Každé tlačítko je
nakreslené v barvách ZIGMon dashboardu a překreslí se v okamžiku, kdy se v domě něco změní.

Nic nejde ovládat, dokud to ZIGMon nedovolí: ovládání ze Stream Decku se zapíná v ZIGMonu,
každý počítač se v něm páruje a schvaluje, každý Stream Deck na něm se schvaluje zvlášť
a administrátor povoluje funkce jednu po druhé.

*English: [README.md](README.md).*

## Co je potřeba

- Windows 10 nebo 11 s aplikací Stream Deck **7.1 nebo novější**.
- ZIGMon **5.59 nebo novější**, dostupný z počítače přes **https** (čisté http jen když
  ZIGMon běží na stejném počítači).
- Ostatní modely Stream Decku fungují také (jen tlačítka); plugin je navržený pro XL a +.

## 1. Stažení a instalace

1. V ZIGMonu jako administrátor: **Nastavení → Stream Deck**.
2. Zapněte **Povolit ovládání ze Stream Decku**.
3. Klikněte na **Stáhnout ZIGMon for Stream Deck 1.0.0**. Pokud chcete, porovnejte SHA-256
   zobrazený tamtéž se souborem (`Get-FileHash ZIGMon.streamDeckPlugin` v PowerShellu).
4. Stažený `.streamDeckPlugin` otevřete dvojklikem. Stream Deck se zeptá na instalaci,
   potvrďte. V seznamu akcí přibude kategorie **ZIGMon for Stream Deck**.

## 2. Spárování počítače se ZIGMonem

1. Přetáhněte libovolnou akci ZIGMonu na tlačítko (nebo na ovladač Stream Decku +)
   a kliknutím otevřete její nastavení.
2. Napište adresu dashboardu, např. `https://zigmon.example.net`, a stiskněte **Connect**.
3. Objeví se kód, např. **K7Q-4PX** - velký v nastavení **a na všech tlačítkách ZIGMonu**.
4. V ZIGMonu → **Nastavení → Stream Deck** se objeví žádost se jménem počítače, jeho Stream
   Decky (nakreslené v měřítku), adresou, odkud přišla, a stejným kódem. Ověřte, že kód
   souhlasí, vyberte, co smí tento počítač dělat, a **Schvalte** (PINem) - nebo **Zamítněte**.
5. Tlačítka do pár sekund ožijí. Nastavení teď ukazuje dům, verzi ZIGMonu, vaše Stream Decky
   (schválené nebo čekající) a souhrn toho, co je povoleno.

Kód platí 15 minut. Jedno spárování platí pro všechny Stream Decky na tomto účtu Windows;
Stream Deck připojený později ukazuje na tlačítkách **Approve deck**, dokud ho administrátor
neschválí u instalace v ZIGMonu.

### Certifikát podepsaný sám sebou

Když Windows certifikátu ZIGMonu nevěří, nastavení ukáže **Check the certificate** s otiskem
SHA-256, pro koho je a do kdy platí. Porovnejte otisk s tím, který ukazuje ZIGMon, a pak
**Trust this certificate**. Od té chvíle plugin pro tu adresu přijímá **jen tento
certifikát** - i kdyby Windows věřily jinému. Když se změní, plugin se zastaví a řekne to
(obnovený certifikát? porovnejte a důvěřujte novému; jinak může být někdo mezi vámi). Před
přijetím certifikátu se neodešle nic - ani žádost o spárování.

## 3. Akce

Všechny fungují na tlačítkách každého Stream Decku; ty s ovladačem i na ovladačích
Stream Decku +, kde kreslí vlastní rozvržení dotykové lišty. V nastavení každé z nich vyberete
položku ze seznamu s hledáním, seskupeného podle místností; položky, které ZIGMon tomuto decku
ovládat nedovolí, mají zámek, a živý náhled ukazuje, jak bude tlačítko vypadat.

| Akce | Tlačítko | Ovladač (Stream Deck +) |
|---|---|---|
| **Control** | Cokoli, co ZIGMon dovolí: zásuvka, světlo, relé, ventil, pravidlo... Ikona, jméno, místnost, Zap/Vyp se zářením v barvě položky, hodnota (např. 42 W). Stisk přepne (nebo zapne / vypne / spustí / otevře / zavře - podle volby). | Stisk = jako tlačítko, otočení = hlavní hodnota (jas, teplota, poloha), lišta: ikona, jméno, hodnota, posuvník nebo stav. |
| **Reading** | Měření velkým písmem s jednotkou, šipkou trendu, grafem posledních hodnot, oranžově/červeně mimo vámi nastavené meze. Stisk obnoví. | Lišta: hodnota nad grafem přes celou šířku. |
| **Thermostat** | Oblouk: aktuální teplota uprostřed, požadovaná na oblouku, plamen při topení, režim a předvolba. Stisk: další režim, další předvolba nebo boost (podle volby). | Otočení = požadovaná teplota (0,1 / 0,5 / 1 ° na cvak), stisk = další režim, dotyk = boost. |
| **Light** | Žárovka svítí podle jasu, procenta a ukazatel. Stisk přepne. | Otočení = jas (1-20 % na cvak), stisk = zap/vyp, lišta: posuvník. |
| **Blinds** | Okno se žaluzií v její poloze, Otevřeno/Zavřeno/procenta, Otevírá se…/Zavírá se…. Stisk: otevřít/zavřít (podle polohy), stop, otevřít nebo zavřít. | Otočení = poloha, stisk = stop/otevřít/zavřít, dotyk = stop. |
| **Scene** | Spustí scénu, sekvenci nebo skupinu akcí. Zelená fajfka = hotovo, červený křížek = nepovedlo se. | Stisk nebo dotyk = spustit. |
| **ZIGMon status** | Zdraví ZIGMonu: otevřené výstrahy, blokované adresy, proxy, Zigbee brána, zdraví - zeleně, oranžově nebo červeně. | Lišta: totéž se stavem. |

Otáčení ovladačem posune hodnotu na liště okamžitě; cvaky se sečtou a do ZIGMonu odejdou
jako jedna změna (ZIGMon ji udrží v rozsahu a kroku položky).

### Potvrzení podržením

Když administrátor u funkce zaškrtne **Potvrdit podržením** (systémové akce ho mají vždy),
krátký stisk nic neudělá, jen napíše **Hold to confirm**. Držte tlačítko (nebo ovladač):
plní se kroužek a po 1,5 s se akce provede - pustit můžete, jakmile se objeví *Confirmed*.

### Co tlačítka říkají

| Tlačítko | Význam |
|---|---|
| **Connect** | Ještě nespárováno - otevřete nastavení tlačítka. |
| velký kód | Párování: schvalte ho v ZIGMonu. |
| **Approve deck** | Tento Stream Deck ještě není v ZIGMonu schválený. |
| **Switched off** | Ovládání ze Stream Decku je v ZIGMonu vypnuté. |
| **ZIGMon offline** | Žádná odpověď; plugin to zkouší znovu (1 s, 2 s, ... až minuta). |
| **Certificate** | Certifikát serveru potřebuje rozhodnutí - viz výše. |
| **Disconnected** | Instalace byla v ZIGMonu odvolána - spárujte znovu. |
| zámek | Položka je vidět, ale tomuto decku není povolena. |
| ruka | Potvrzení podržením. |

## Bezpečnost

- **Nic bez souhlasu ZIGMonu**: ZIGMon kontroluje každý příkaz - zapnuto, klíč, instalace,
  schválený deck, povolená položka pro svou schopnost, podržení, hodnota. Plugin jen kreslí,
  co ZIGMon hlásí, a žádá; sám nic nerozhoduje.
- **Klíč** (`zsd_...`) přijde jednou při schválení a ukládá se jen zašifrovaný přes Windows
  **DPAPI** pro aktuálního uživatele (PowerShell ProtectedData; klíč jde přes stdin, nikdy na
  příkazovou řádku). ZIGMon si drží jen jeho SHA-256. Posílá se jen v hlavičce, nikdy v adrese,
  a nikdy se nezapisuje do logu.
- **Jen https** (http jen na `localhost`), **přesměrování se nenásledují**, odpovědi mají
  omezenou velikost a kontroluje se každé pole; vše zobrazené na tlačítku je escapované.
- **Certifikáty**: ty, kterým věří Windows (a jméno musí sedět), nebo přesně ten, který jste
  si připnuli.
- **Odvolání** v ZIGMonu zastaví počítač při jeho dalším požadavku; **Disconnect**
  v nastavení zapomene klíč na tomto počítači.

## Aktualizace

Když má ZIGMon novější plugin, nastavení každé akce ukáže **Update to x.y.z**. Kliknutí
stáhne balíček ze ZIGMonu, ověří, že jeho manifest je **podepsaný release klíčem ZIGMonu**
(Ed25519; klíče jsou zabudované v pluginu) a že velikost a SHA-256 souboru odpovídají
podepsanému manifestu, uloží ho jako `%TEMP%\ZIGMon-x.y.z.streamDeckPlugin` a otevře ho -
Stream Deck se pak zeptá na instalaci. Co nesedí, se neotevře.

## Když něco nejde

- *There is no deck API at that address*: ZIGMon je starší než 5.59 nebo adresa není adresa
  dashboardu.
- *Too many requests*: párování je omezené na 10 pokusů za hodinu z jedné adresy a příkazy
  na 10 za sekundu; chvíli počkejte.
- *The saved key could not be read*: nastavení bylo přeneseno z jiného účtu nebo počítače -
  spárujte znovu.
- Log pluginu: `%APPDATA%\Elgato\StreamDeck\Plugins\com.zigmon.streamdeck.sdPlugin\logs`.

## Sestavení (pro vývojáře)

`streamdeck/build.sh` na Linuxu (Node.js 20+, python3) nainstaluje přesné závislosti, zabuduje
release klíče z `deploy/release-keys/`, nakreslí rozvržení a ikony, spustí testy, sbalí plugin,
vyzkouší ho se skutečným SDK proti falešné aplikaci Stream Deck, pak `streamdeck validate`
a `streamdeck pack` a zapíše `dist/com.zigmon.streamdeck.streamDeckPlugin` a `dist/plugin.json`
(podepisuje `tools/make-release.sh`). Stejné zdroje dávají stejné bajty.
