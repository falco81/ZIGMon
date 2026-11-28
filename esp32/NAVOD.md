# ZIGMon ESP32 Gateway – návod

ESP32 ve vaší Wi-Fi, které se spáruje se ZIGMonem; ZIGMon zjistí, co umí, a ovládá to.
Funkce jsou **moduly**; první je **Yeelock** – otevírá zámky šuplíků a skříněk Xiaomi Yeelock
přes Bluetooth LE, více zámků na jedno ESP.

- **Bezpečně:** jen HTTPS s certifikátem, který si ESP vyrobí samo (ZIGMon si ověří a zapamatuje
  jeho otisk); každý požadavek ZIGMonu i každá odpověď jsou podepsané (HMAC-SHA256, bez
  možnosti přehrání); webové rozhraní chrání heslo (PBKDF2), relace, CSRF a blokování po
  chybných pokusech.
- **Modulárně, s autodetekcí:** ZIGMon se brány zeptá, co má, a zobrazí to – nový modul
  nevyžaduje změnu v ZIGMonu.
- **Vše na desce:** webové rozhraní pro mobil i počítač, sériová konzole (CLI), nastavení ve
  flash paměti (NVS).

Protokol: [`PROTOCOL.md`](PROTOCOL.md). Anglicky: [`README.md`](README.md).

> Protokol Yeelocku je neoficiální (reverse engineering komunity, viz poděkování na konci).
> Než se na bránu spolehnete, vyzkoušejte zámky – a mějte náhradní klíč.

## 1. Hardware

| | |
|---|---|
| **Hlavní cíl** | deska **ESP32-S3-N16R8**: 16 MB flash, 8 MB PSRAM (octal), BLE 5 |
| Funguje i | klasické ESP32 (WROOM/WROVER), ESP32-C3 (cokoli s BLE a aspoň 4 MB flash) |
| Napájení | USB 5 V trvale; umístění do ~5–10 m od zámků |

ESP32-S3 i C3 mají **jen BLE 5 (žádný klasický Bluetooth)** – bráně to stačí, Yeelock je BLE
zařízení a NimBLE je čistě BLE. PSRAM firmware využije pro velké buffery (historie událostí a
logu, JSON); bez PSRAM použije vnitřní RAM.

## 2. Arduino IDE: deska a knihovny

1. Arduino IDE 2.x: *Soubor > Předvolby > Další URL správce desek*:
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
2. *Nástroje > Deska > Správce desek*: nainstalujte **esp32 by Espressif Systems** verze **3.x**
   (3.0.0 nebo novější). Jádro 2.x podporované není.
3. *Nástroje > Spravovat knihovny*, přesně tyto:

   | Název ve Správci knihoven | Verze | Proč |
   |---|---|---|
   | **NimBLE-Arduino** od h2zero | **1.4.3** (jakákoli 1.4.x) | BLE. **Ne 2.x** – má jiné API. |
   | **ArduinoJson** od Benoit Blanchon | **7.4.2** (jakákoli 7.x) | JSON s limity a filtry |

   Ostatní je součástí jádra (WiFi, Preferences, ESPmDNS, mbedTLS, esp_https_server,
   esp_http_client, balík kořenových certifikátů).
4. Menu *Nástroje* pro **ESP32-S3-N16R8**:

   | Položka | Hodnota |
   |---|---|
   | Board | **ESP32S3 Dev Module** |
   | Flash Size | **16MB (128Mb)** |
   | PSRAM | **OPI PSRAM** |
   | Partition Scheme | **16M Flash (3MB APP/9.9MB FATFS)** (nebo jiné 16MB schéma s aplikací ≥ 3 MB) |
   | USB CDC On Boot | **Enabled** pro konzoli na nativním USB, **Disabled** pro konzoli na UART portu (viz níže) |
   | Upload Speed | **921600** |
   | CPU Frequency | 240 MHz |

   Jiné desky: klasické ESP32 = „ESP32 Dev Module“, ESP32-C3 = „ESP32C3 Dev Module“, Partition
   Scheme **„Huge APP (3MB No OTA/1MB SPIFFS)“** nebo **„Minimal SPIFFS“** – firmware má
   1,6–1,9 MB, víc než výchozí 1,2 MB.

**Dva USB porty na desce S3.** Většina desek N16R8 má dva konektory USB-C:

- **„USB“** – nativní USB čipu S3 (GPIO 19/20). Konzole se tu objeví jen s *USB CDC On Boot:
  Enabled*. Nahrávat jde i sem (když to nejde: podržte BOOT, stiskněte RESET, pusťte BOOT,
  nahrajte znovu).
- **„COM“ / „UART“** – převodník USB-sériová linka na UART0. Konzole je tu s *USB CDC On Boot:
  Disabled*. Nejjednodušší volba: nahrávání i konzole na jednom portu, bez tlačítka BOOT.

Zvolte jeden port a podle něj nastavte *USB CDC On Boot*; při špatném nastavení deska běží, ale
sériový monitor mlčí.

## 3. Nahrání

1. Otevřete `esp32/ZigmonGateway/ZigmonGateway.ino` (ostatní `.h`/`.cpp` se otevřou jako záložky;
   složka `web/` obsahuje zdroje webového rozhraní, už zabalené ve `web_assets.h`).
2. Nastavte desku podle tabulky, port a **Nahrát**.
3. *Nástroje > Sériový monitor*, **115200** baudů, konec řádku **„Nový řádek“** (nebo „NL i CR“).
   Při prvním startu si brána vyrobí klíč a certifikát (pár sekund) a ukáže výzvu `zgw>`.

## 4. Wi-Fi přes sériovou konzoli

```
zgw> wifi scan
zgw> wifi set "Moje Wi-Fi" mojeheslo
zgw> status
```

Název sítě s mezerami dejte do uvozovek. Heslo se při psaní zobrazuje jako `*` a nikdy se
nevypisuje. `status` ukáže IP adresu a jméno `zigmon-gw-xxxxxx.local`. Pevná adresa:
`wifi static 192.168.1.50 255.255.255.0 192.168.1.1 [dns]`; zpět na DHCP: `wifi dhcp`.

## 5. Heslo správce

Dokud není nastavené heslo, webové rozhraní nic nedovolí. Buď v konzoli:

```
zgw> password
New admin password: ************
Repeat it: ************
```

nebo na úvodní stránce webu, která je otevřená jen **10 minut po startu** (nebo po příkazu
`webinit`). 8–64 znaků; uloží se jen jako PBKDF2-HMAC-SHA256 (10 000 kol, náhodná sůl).

## 6. Webové rozhraní

1. Otevřete `https://zigmon-gw-xxxxxx.local/` (nebo `https://<IP>/`); `http://` přesměruje.
2. Prohlížeč upozorní na nedůvěryhodný certifikát – brána si ho vyrobila sama. Než ho přijmete,
   **porovnejte otisk**: příkaz `fingerprint` v konzoli a otisk SHA-256 v detailu certifikátu v
   prohlížeči (klik na varování / zámek > certifikát). Shodují-li se, přijměte.
3. Přihlaste se. Po 5 chybných heslech je přihlášení zablokované 60 s, pak dvojnásobně až na hodinu.

Stránky: **Přehled** (Wi-Fi, čas, ZIGMon, moduly, poslední akce), **Wi-Fi** (hledání sítí,
pevná IP), **ZIGMon** (párování, otisk, zrušení), stránka každého **modulu** a **Systém**
(jména, heslo, log, restart, tovární nastavení).

## 7. Přidání zámků

Každý zámek potřebuje **sériové číslo** (S/N – na štítku a v BLE jménu `EL_<SN>`) a svůj
**`ble_sign_key`** – tajný klíč, který aplikace Yeelock dostane z cloudu Yeelocku, když zámek
přidáte do účtu. Kdo zná klíč a je v dosahu BLE, zámek otevře – zacházejte s ním jako s
fyzickým klíčem. Na stránce **Yeelock** nabízí *Přidat zámek* tři cesty:

- **Účet – import z mého účtu Yeelock.** Zadejte předvolbu země (např. `420`, bez `+`), telefonní
  číslo (bez předvolby) a heslo k Yeelocku. Brána se **jednou, přímo z ESP** přihlásí na
  `api.yeeloc.com` přes ověřené HTTPS (balík certifikátů jádra, žádná nezabezpečená varianta),
  ukáže vaše zámky s „v dosahu“ / „mimo dosah“ a uloží jen ty, které zaškrtnete. Heslo a
  přístupový token jsou jen v RAM po dobu dvou požadavků a pak se smažou; stažené klíče se z RAM
  smažou nejpozději po 10 minutách. Max. 5 pokusů za 10 minut. V konzoli:
  `yeelock fetch 420 123456789` (heslo se zeptá bez zobrazení), pak `yeelock import <SN>... | all`.
- **Hledat:** BLE sken ukáže zámky `EL_*` v okolí se sílou signálu, označí už přidané a ty,
  které jsou ve vašem účtu. Vyberte zámek, doplní se S/N, klíč vložte.
- **Ručně:** jméno, S/N a klíč v hexu (8–32 bajtů; mezery nebo `:` nevadí). V konzoli:
  `yeelock add "Šuplík" <SN> <klíč>`.

Ruční cesta se nespojuje s žádným cloudem. Kdo chce klíč získat na PC, může použít nástroj, ze
kterého firmware čerpá znalost protokolu: [aso824/yeehack](https://github.com/aso824/yeehack) –
`python3 yeehack.py fetch`; klíč z PC i ověří (`yeehack.py do unlock <SN> <klíč>`).

**Každý nový zámek (i nový klíč) se hned ověří:** brána se připojí, přečte baterii a pošle jen
synchronizaci času. Nikdy kvůli testu neodemyká. Špatný klíč se ukáže jako červený pruh
*„Wrong sign key“* na kartě zámku (zámek odpověděl `TX_SIGN_INVALID`); „reachable, key OK“
znamená, že je vše v pořádku. Tlačítko *Check* ověření zopakuje.

Karta zámku ukazuje stav (podle hlášení zámku `UNLOCK_CMP` / `LOCK_CMP`), baterii, signál,
poslední akci a výsledek a tlačítka **Open** (odemkne a zámek se sám znovu zamkne), **Unlock**,
**Lock** a **Refresh** (baterie). Open a Unlock chtějí potvrzení. Nastavení: doba skenu,
časový limit spojení, interval kontroly baterie.

Pro příkazy Yeelocku musí brána znát čas: nastaví ho NTP (s internetem), jinak ZIGMon prvním
podepsaným požadavkem, nebo tlačítko *Use this browser's time* na Přehledu.

## 8. Spárování se ZIGMonem

1. Web > **ZIGMon** > **Pair with ZIGMon** (nebo v konzoli `pair`): **6místný kód**, platí
   10 minut, jen jednou.
2. V ZIGMonu: **Nastavení > Zařízení > ESP32 brány > Přidat** – adresa brány a kód.
3. ZIGMon ukáže otisk certifikátu – ověřte, že je stejný jako na stránce ZIGMon brány (nebo
   `fingerprint` v konzoli), a potvrďte.
4. ZIGMon najde moduly a jejich entity (zámky) a ovládá je. Open a Unlock jsou citlivé akce –
   ZIGMon se zeptá na potvrzení (na Stream Decku podržením).

Chybný kód se tím spotřebuje; po pěti chybných kódech je párování zablokované 15 minut.
**Unpair** (nebo `unpair`) klíč ZIGMonu zapomene.

## 9. Sériová konzole (CLI)

115200 baudů, jeden příkaz na řádek; funguje Backspace, uvozovky `"..."` / `'...'` a `\`,
šipky se ignorují, Ctrl-C zahodí řádek. `help` vypíše vše.

| Příkaz | Co dělá |
|---|---|
| `help [příkaz]` | všechny příkazy |
| `status` | firmware, doba běhu, Wi-Fi, čas, párování, moduly |
| `wifi scan` / `wifi set <ssid> [heslo]` / `wifi forget` | Wi-Fi |
| `wifi static <ip> <maska> <brána> [dns]` / `wifi dhcp` | adresa |
| `hostname <jméno>` | mDNS `<jméno>.local` |
| `password` | heslo správce (dvakrát, zobrazuje `*`) |
| `webinit` | znovu otevře úvodní stránku hesla na 10 minut |
| `fingerprint` | otisk certifikátu SHA-256 |
| `pair` / `unpair` | kód pro párování / zapomenout ZIGMon |
| `time [unix]` | ukáže nebo nastaví čas (UTC) |
| `modules` | moduly, verze, entity |
| `yeelock list` | zámky s baterií a posledním výsledkem |
| `yeelock add <jméno> <SN> <klíč>` / `yeelock key <id> <klíč>` / `yeelock del <id>` | správa zámků |
| `yeelock scan` | zámky `EL_*` v okolí (výsledek v logu) |
| `yeelock check <id>` | test dosahu a klíče (nikdy neodemkne) |
| `yeelock do <id> open\|unlock\|lock\|battery` | provést akci |
| `yeelock fetch <předvolba> <telefon>` / `yeelock import <SN>...\|all` | import z účtu Yeelock |
| `log [error\|warn\|info\|debug]` | úroveň logu, poslední řádky |
| `reboot` | restart |
| `factory-reset` | smazat vše (ptá se dvakrát) |

## 10. Tovární nastavení

```
zgw> factory-reset
zgw> factory-reset YES        (do 30 s)
```

nebo *Systém > Factory reset* na webu (napsat `FACTORY RESET` a heslo). Smaže celé NVS: Wi-Fi,
heslo, párování se ZIGMonem, nastavení všech modulů (všechny zámky a klíče) i certifikát a
restartuje se jako nová. V ZIGMonu bránu odeberte a spárujte znovu.

## 11. Řešení problémů

| Příznak | Příčina / řešení |
|---|---|
| Sériový monitor mlčí | Jiný USB port, než odpovídá *USB CDC On Boot* (kap. 2); rychlost 115200. |
| „Sketch too big“ | Schéma oddílů s aplikací 3 MB (kap. 2). |
| Chyby kompilace NimBLE | Je nainstalované NimBLE-Arduino 2.x – nainstalujte 1.4.3. |
| `httpd_req_async_handler_begin` neznámé | Velmi staré jádro: na začátek `gw_config.h` `#define GW_HTTPD_ASYNC 0`. |
| `esp_crt_bundle.h` chybí | Jádro bez balíku certifikátů: `#define GW_YEELOCK_CLOUD 0` v `yeelock_cloud.h` (ruční cesta zůstane). |
| Prohlížeč hlásí 431 | Moc cookies pro adresu brány: otevřete ji přes IP nebo v anonymním okně. |
| Web chce nejdřív heslo | 10 minut uplynulo: `password` nebo `webinit` v konzoli. |
| Zámek „not found“ | Mimo dosah nebo špatné S/N; probuďte zámek dotykem a dejte *Hledat*. |
| „could not connect“ | K zámku je připojený telefon s aplikací Yeelock – zavřete ji. |
| „Wrong sign key“ | Klíč nepatří k zámku (nebo byl zámek znovu přidán do účtu a klíč se změnil): naimportujte ho znovu. |
| „clock is not set“ | Bez NTP: spárujte ZIGMon (nastaví čas) nebo *Use this browser's time*. |
| ZIGMon hlásí změněný certifikát | Brána prošla továrním nastavením: spárujte znovu a porovnejte nový otisk. |

## 12. Bezpečnost

- Žádné tajemství se nikde nevypisuje celé – nanejvýš „set (..xy)“.
- NVS není ve výchozím stavu šifrované: kdo má desku v ruce, může klíče z flash přečíst. Bránu
  umístěte mimo dosah cizích, případně zapněte šifrování flash a NVS (ESP-IDF).
- Bránu nevystavujte do internetu (žádné přesměrování portů).

## 13. Jak napsat nový modul

Modul je jedna třída implementující `gw::Module` (`core_module.h`) v jednom novém souboru
`mod_<id>.cpp` a jeden řádek registrace v `ZigmonGateway.ino` (`registerModules()`). Popisuje
entity (`describe`), jejich stav (`stateOf`), přijímá příkazy (`command` – pomalou práci předá
jobu a odpoví 202), popisuje nastavení schématem (`settingsSchema` – web z něj sám vykreslí
formuláře, karty položek, sken, kontrolu i import) a může mít vlastní příkazy v konzoli.
Úplný příklad (relé na GPIO) a pravidla jsou v [`README.md`, kapitola 13](README.md#13-writing-a-new-module).

**Piny na ESP32-S3-N16R8:** **nepoužívejte GPIO 35, 36, 37** (obsazuje je octal PSRAM), ani
26–32 (flash), 19/20 (nativní USB), 43/44 (UART0 – konzole na portu COM); 0, 3, 45, 46 jsou
strapping piny. Volné: 1, 2, 4–18, 21, 38–42, 47, 48 (48 je na mnoha deskách RGB LED).

## 14. Vývoj a testy

```
esp32/tests/run.sh                 # stačí g++ (a python3, node pro kontrolu webu)
python3 tools/esp32-embed-web.py   # po úpravě web/: přegeneruje web_assets.h
python3 esp32/tests/webmock.py 8099   # web s falešnými daty na http://127.0.0.1:8099/
```

## 15. Poděkování

Znalost protokolu Yeelock (pakety, kódy notifikací, GATT charakteristiky, cloudové endpointy)
pochází z **[aso824/yeehack](https://github.com/aso824/yeehack)** (Apache-2.0) a z původního
reverse engineeringu **[cnrd/yeelock](https://github.com/cnrd/yeelock)**. Firmware je nezávislá
implementace v C++; viz [`NOTICE`](NOTICE).
