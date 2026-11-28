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
  ZIGMon běží na stejném počítači). Deset akcí nových ve verzi 1.3 potřebuje **ZIGMon 5.59.4**
  (ostatní fungují se starším jako dosud).
- Ostatní modely Stream Decku fungují také (jen tlačítka); plugin je navržený pro XL a +.

## 1. Stažení a instalace

1. V ZIGMonu jako administrátor: **Nastavení → Messages → Stream Deck**.
2. Zapněte **Povolit ovládání ze Stream Decku**.
3. Klikněte na **Stáhnout ZIGMon for Stream Deck 1.3.0**. Pokud chcete, porovnejte SHA-256
   zobrazený tamtéž se souborem (`Get-FileHash ZIGMon.streamDeckPlugin` v PowerShellu).
4. Stažený `.streamDeckPlugin` otevřete dvojklikem. Stream Deck se zeptá na instalaci,
   potvrďte. V seznamu akcí přibude kategorie **ZIGMon for Stream Deck**.

## 2. Spárování počítače se ZIGMonem

1. Přetáhněte libovolnou akci ZIGMonu na tlačítko (nebo na ovladač Stream Decku +)
   a kliknutím otevřete její nastavení.
2. Napište adresu dashboardu, např. `https://zigmon.example.net`, a stiskněte **Connect**.
3. Objeví se kód, např. **K7Q-4PX** - velký v nastavení **a na všech tlačítkách ZIGMonu**.
4. V ZIGMonu → **Nastavení → Messages → Stream Deck** se objeví žádost se jménem počítače, jeho Stream
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
| **Thermostat** | Oblouk: aktuální teplota uprostřed, požadovaná na oblouku, plamen při topení, režim a předvolba. Stisk: další režim, další předvolba, boost, **ukázat podrobnosti** nebo **nastavit jeden režim** (podle volby). | Otočení = požadovaná teplota (0,1 / 0,5 / 1 ° na cvak), stisk = další režim, dotyk = boost. |
| **Light** | Žárovka svítí podle jasu, procenta a ukazatel. Stisk přepne. | Otočení = jas (1-20 % na cvak), stisk = zap/vyp, lišta: posuvník. |
| **Blinds** | Okno se žaluzií v její poloze, Otevřeno/Zavřeno/procenta, Otevírá se…/Zavírá se…. Stisk: otevřít/zavřít (podle polohy), stop, otevřít nebo zavřít. | Otočení = poloha, stisk = stop/otevřít/zavřít, dotyk = stop. |
| **Scene** | Spustí scénu, sekvenci nebo skupinu akcí. Zelená fajfka = hotovo, červený křížek = nepovedlo se. | Stisk nebo dotyk = spustit. |
| **ZIGMon status** | Zdraví ZIGMonu: otevřené výstrahy, blokované adresy, proxy, Zigbee brána, zdraví - zeleně, oranžově nebo červeně. | Lišta: totéž se stavem. |
| **House power** *(1.3)* | Příkon domu teď, dnešní kWh, graf za 1 h / 6 h / 24 h / 7 dní. | Otočení = rozsah grafu. |
| **Network security** *(1.3)* | Nevyřízené výstrahy a blokované adresy; červený štít při výstraze. Podržený stisk = potvrdit poslední. | Stisk (podržený) = potvrdit. |
| **Heating everywhere** *(1.3)* | Topí n/m místností, společný režim nebo Mixed, min–max °C. Stisk = další režim nebo jeden režim všem. | Otočení / stisk = režim. |
| **Away / Home** *(1.3)* | Pryč nebo doma, zapnutá světla, topící místnosti. Stisk = přepnout a vypnout vybrané. | Stisk = přepnout. |
| **Windows & doors** *(1.3)* | Kolik je otevřených a která; červeně, když jde teplo ven. | Lišta: počet, jména, pruh čidel. |
| **Batteries** *(1.3)* | Kolik baterií je slabých, nejslabší jménem a v %. | Lišta: totéž se stavem. |
| **Zigbee network** *(1.3)* | Online / offline, které vypadlo naposledy. | Lišta: totéž s pruhem. |
| **Timer** *(1.3)* | Vypínač zapnutý na N minut s živým odpočtem; další stisk = vypnout. | Otočení = minuty, stisk = spustit / zrušit. |
| **Room** *(1.3)* | Teplota, vlhkost, co je zapnuté, topení. | Otočení = položky místnosti, stisk = přepnout vybranou. |
| **SMS** *(1.3)* | Ukázat poslední / napsat novou v desktopové aplikaci, nebo stav SMS se ztlumením (podržení). | Stisk = totéž. |
| **Computed** *(1.3)* | Hodnota spočítaná ZIGMonem přes dům - celkový příkon, svítící světla, nejchladnější místnost... - ukázaná jako Reading; vybraná skládačkou Co / Jak / Kde nebo jednou z Popular. | Lišta: jako u Reading. |

Otáčení ovladačem posune hodnotu na liště okamžitě; cvaky se sečtou a do ZIGMonu odejdou
jako jedna změna (ZIGMon ji udrží v rozsahu a kroku položky).

### Topení po místnostech (od 1.1)

Akce **Thermostat** umí i místnost z karty Topení (položka *Heating in …*), stejně jako ji
ukazuje dashboard:

- **cílová teplota** (→ 35,0 °C), **naměřená teplota** z hlavního teploměru místnosti (ten,
  který je u místnosti v ZIGMonu nastavený, např. Temp-Loznice) a **režim** slovy dashboardu:
  Comfort, Eco, Night, Max, Off, Plan, By hand - a když je teplota nastavená ručně,
  **By hand until 14:30** (do dalšího kroku plánu, nebo po dobu `manual_hold_s`);
- **stisk** může nastavit jeden konkrétní režim (Comfort, Eco, Night, Max, Off, Plan nebo
  By hand), nebo **Next mode** - dokola všemi režimy včetně Plan a By hand; od 1.3 volbou
  **Go round only these** jen vybranými (např. Comfort, Max, Off) v obvyklém pořadí - totéž
  umí Next preset i klávesa Topení všude (i její ovladač);
- **otočení ovladačem** nastaví místnost ručně přesně jako posuvník *Set … by hand* v
  dashboardu (stejnou cestou v ZIGMonu, platí i oprávnění *climate* a podržení);
- volba **Show details (3 s)**: stisk na 3 sekundy ukáže kartu s režimem, cílovou a naměřenou
  teplotou a jménem teploměru - nic se nepřepne. Totéž je trvale vidět volbami níže.
- **od 1.2** se při **Next mode** režim na tlačítku přepne hned, ale do ZIGMonu se pošle jen
  ten, na kterém se zastavíte (1,2 s po posledním stisku). Dřív se nastavil každý režim cestou,
  takže cesta na Max vedla přes Off a ventily v místnosti se zavřely. S podržením pro
  potvrzení se dál posílá každý potvrzený stisk.

### Grafy (od 1.1)

Měření (**Reading**) a topení (**Thermostat**) kreslí graf z **historie, kterou připraví
ZIGMon** - stejné, ze které kreslí karta Historie: hotovou řadu (zhuštěnou asi na 48 bodů)
za zvolené období **1 h, 6 h, 24 h nebo 7 dní**. Graf je tak vidět hned po spuštění,
plugin mezi tím jen přikresluje živé hodnoty a řadu si každých pár minut (a při změně
období) vyžádá znovu. Volitelně: **min / max** u grafu a u topení **cílová teplota
čárkovaně**. Starší ZIGMon (5.59.0) historii neposílá - pak graf roste jen z hodnot, které
plugin sám uviděl.

### Vzhled tlačítek (od 1.1)

V nastavení každé akce je oddíl **Look**:

- **60 vzhledů** se živými náhledy z aktuálního stavu položky: *Classic* (jako v 1.0 - beze
  změny pro dříve nastavená tlačítka), *Minimal* (velká ikona), *Big value* (hodnota co
  největší), *Solid fill* (celé tlačítko se rozsvítí barvou), *Neon* (zářící obrys),
  *Ring gauge* (prstenec, který se plní), *Two-tone* (barevný pruh nad tmavým),
  *Glass* (matné sklo se zářením), *Bold label* (velký nápis), *Status dot* (kontrolka a
  čisté písmo), *Light* (světlé tlačítko s tmavým písmem) a *High contrast* (černobílé,
  silné čáry). K nim deset čistých, které ukazují jen to podstatné velkým písmem a nanejvýš
  jeden malý řádek: *Huge* (hodnota přes celé tlačítko), *Pill* (stav ve velké pilulce),
  *Orb* (koule, která svítí), *Tile* (dlaždice jako ikona aplikace a jedno slovo), *Gauge*
  (silný oblouk s číslem uprostřed), *Bars* (velké číslo nad sloupci), *Wave* (tlačítko se
  plní jako vodou), *Aurora* (barevný přechod, bílé písmo), *Outline* (silný okraj, když je
  zapnuto) a *Mono* (jedna barva, obří ikona). A dvacet dalších stejně čistých, každý jiného
  tvaru: *Diagonal* (barevný roh), *Hex* (šestiúhelník), *Stripe* (boční pruh, který se plní),
  *Switch* (přepínač), *LCD* (retro displej), *Dial* (knoflík s věncem rysek), *Ticket*
  (vstupenka s barevným ústřižkem), *Bubble* (bublina), *Frame* (rohové závorky), *Shadow*
  (karta s barevným stínem), *Line* (hodnota na jedné čáře), *Tube* (trubice teploměru),
  *Stamp* (obří bledá ikona), *Pastel* (jemná barva, tmavé písmo), *Carbon* (karbon a světelný
  pruh), *Grid* (mřížka kontrolek), *Tab* (složka se jménem na oušku), *Rise* (vycházející
  slunce), *Spot* (reflektor) a *Button* (skutečné tlačítko, zamáčknuté, když je zapnuto).
  A osmnáct vzhledů, kde má přednost **jméno**: je velké a celé (radši na dva řádky a menší,
  než aby se uřízlo - podle volby délky jména) a hned u něj **stav** - Zap/Vyp, teplota
  s jednotkou, příkon ve wattech, jas, poloha, režim, odpočet nebo počet -, takže je obojí
  čitelné najednou i na malých tlačítkách XL: *Name bar* (jméno na barevném pruhu, stav pod
  ním), *Caption* (jméno uprostřed, stav v pilulce), *LED* (jméno, kontrolka a stav), *Two rows*
  (jméno a stav oddělené tenkou čarou), *Plate* (rytý štítek s okénkem stavu), *Ticker* (jméno
  nad pruhem se stavem), *Card* (jméno nad dlaždicí s ikonou a stavem), *Halves* (jméno nahoře,
  stav na barevné spodní půlce), *Stacked* (jméno, stav, malá ikona), *Corner* (velké jméno,
  stav v rohovém štítku), *Lined* (jméno podtržené barvou, když je zapnuto), *Terminal* (konzole:
  jméno a pod ním `> stav`), *Marquee* (jméno ve věnci žárovek), *Widget* (widget jako v telefonu,
  jméno dole), *Sign* (dopravní cedule se jménem), *Note* (kartička, stav zvýrazněný
  zvýrazňovačem), *Pass* (visačka na šňůrce, velké jméno) a *Glow* (jméno samo září, když je
  zapnuto).
  Nad nimi je dvojice náhledů **zapnuto / vypnuto**.
- **Barvy** ve dvou záložkách: **On colour** (barva zapnutého tlačítka; *Auto* = podle druhu
  položky) a **Off colour** (barva vypnutého; *Auto* = šedá, jak ji kreslí daný vzhled). Každá je
  jednou z 24 pojmenovaných barev (prvních deset jako v 1.1, k nim indigo, nebeská, azurová,
  mátová, limetková, zlatá, broskvová, korálová, růžová, purpurová, levandulová, hnědá, břidlicová
  a bílá) nebo vlastní: dlaždice *Custom* otevře výběr - čtverec sytosti a jasu, pruh odstínu a
  pole `#RRGGBB`, které se kontroluje už při psaní. Tlačítko, dvojice zapnuto / vypnuto i náhledy
  vzhledů se mění, jak táhnete. Vypnuté tlačítko se kreslí barvou Off všude, kde by vzhled použil
  šedou (okraj, ikona, stav, dlaždice - podle vzhledu, i v Classic a na dotykové liště). Položky
  bez zapnuto / vypnuto (měření, scéna, stav) mají barvu On jako svou a barvu Off v klidu.
  Nastavení si pamatuje jméno barvy nebo přesně `#RRGGBB`; cokoli jiného zahodí a žádná barva
  nikdy nepřichází ze ZIGMonu.
- **Popisek**: vlastní text místo jména položky (nejvýš 40 znaků) - u všech akcí.
- **Dlouhá jména**: *Shrink to fit* (zmenšit, případně na dva řádky), *Two lines* (dva řádky,
  zlom i u pomlček - „Light-Loznice-" / „Main") nebo *One line* (jeden řádek se třemi
  tečkami, jako v 1.0).
- **Co je na tlačítku vidět** - každé zvlášť: ikona, jméno, místnost, stav / hodnota, druhá
  hodnota (W, jas %, cílová teplota, pohyb žaluzie, trend), režim / předvolba, graf (historie,
  ukazatel úrovně, okno žaluzie), baterie. Tlačítka *Everything* a *Icon only* je nastaví
  najednou. Každý vzhled tyto volby respektuje; offline, zámek (nepovoleno), ruka i kroužek
  podržení zůstávají čitelné ve všech.

Na **Stream Decku +** se vzhled, barva a volby promítnou i do dotykové lišty, kam to rozvržení
dovolí: podklad lišty, barvy písma, dlaždice ikony, skryté části zůstanou prázdné.

### Potvrzení podržením

Když administrátor u funkce zaškrtne **Potvrdit podržením** (systémové akce ho mají vždy),
krátký stisk nic neudělá, jen napíše **Hold to confirm**. Držte tlačítko (nebo ovladač):
plní se kroužek a po 1,5 s se akce provede - pustit můžete, jakmile se objeví *Confirmed*.

**Od 1.1 i na vlastní přání**: v nastavení každé akce, která něco dělá (všechny kromě
Reading a ZIGMon status), je přepínač s rukou **Hold to confirm (1.5 s)**. Zapnutý = stisk
tlačítka, stisk ovladače i dotyk lišty vyžadují stejné podržení s kroužkem; otáčení
ovladačem zůstává volné. Když podržení vyžaduje ZIGMon, přepínač je zapnutý a zamčený
(*ZIGMon requires it for this item*). Ruka je na tlačítku vždy, když se podržení uplatní.

### By hand (1.2, ZIGMon 5.59.3)

Tlačítko **Control** u zásuvky, světla nebo relé má přepínač **By hand**, stejný jako
tlačítka v ZIGMonu. Když tímto tlačítkem zařízení zapnete, ZIGMon ho převezme ručně a pravidla
a plány ho nechají být. Když ho jím vypnete, převezmou ho zpátky. Malá postavička na tlačítku
ukazuje, že je zařízení převzaté, ať už tímto tlačítkem, jiným, nebo tlačítkem v ZIGMonu.
Starší ZIGMon přepínač ignoruje.

### Deset nových akcí (1.3, ZIGMon 5.59.4)

Deset dalších akcí ukazuje, co ZIGMon 5.59.4 shrnuje za celý dům, a umí s tím pracovat. Každá
funguje na tlačítkách i na ovladačích Stream Decku + (s vlastním rozvržením dotykové lišty), má
vlastní kresbu v Classic i všech 60 vzhledů, barvy pro zapnuto / vypnuto, popisek, dlouhá jména
a volbu, co tlačítko ukazuje - přesně jako akce výše. V jejich nastavení je karta **Now**
s tím, co se na tlačítko nevejde (všechna otevřená okna, celý text poslední výstrahy, položky
místnosti...).

Potřebují **ZIGMon 5.59.4 nebo novější**: plugin se na ně ptá jen ZIGMonu, který je nabízí,
a se starším tlačítka napíšou **Needs ZIGMon 5.59.4 or newer** a nic nedělají. Souhrny domu se
nevybírají: stačí akci položit na tlačítko a ukáže je (pokud je ZIGMon tomuto decku dovolí vidět).

#### House power - příkon domu (1.3, ZIGMon 5.59.4)

Příkon domu teď velkým písmem (**452 W**, **1.84 kW**), pod ním dnešní **kWh** a graf za
**1 h, 6 h, 24 h nebo 7 dní** (ze ZIGMonu: minutová maxima pro 1 h, hodinové průměry měřených
zásuvek pro delší). Svítí, když něco odebírá. Stisk obnoví. Na ovladači **otočení = rozsah grafu**;
lišta ukazuje číslo nad grafem. Karta **Now** ho rozdělí na zásuvky a světla.

#### Network security - zabezpečení sítě (1.3, ZIGMon 5.59.4)

Nevyřízené výstrahy (**2 alerts**, za každou tečka) a blokované adresy (**14 blocked · 37 in
24 h**); štít **zčervená** při výstraze, a když žádná není, napíše zeleně **Quiet**. Karta **Now**
ukáže **text poslední výstrahy** (adresy a čísla ZIGMon skryje) a kdy přišla. Stisk **podržený
1,5 s potvrdí poslední výstrahu** - jako *viděno* v dashboardu; starší zůstanou. Potřebuje
oprávnění **System** pro tento deck (pro vše, nebo jménem pro *Network security*) a **vždy se
drží**; bez něj tlačítko dál vše ukazuje a po stisku napíše *needs System in ZIGMon*. Když žádná
výstraha nečeká, napíše *All clear*.

#### Heating everywhere - topení všude (1.3, ZIGMon 5.59.4)

Kolik vytápěných místností právě chce topit (**1/4**, za každou místnost dílek), jejich **společný
režim** - nebo **Mixed** - a nejnižší a nejvyšší teplota v místnostech (**18.5–21.0°**). Stisk:
**další režim** pro všechny místnosti (ukáže se hned a odejde 1,2 s po posledním stisku, jako
u termostatu; z Mixed začíná na Plan) nebo **jeden režim pro všechny** (Plan, Comfort, Eco,
Night, Max, Off nebo By hand). Otočení ovladačem režim posouvá stejně. Pod oprávněním *climate*
a jeho podržením.

#### Away / Home - pryč / doma (1.3, ZIGMon 5.59.4)

**Away** nebo **Home** (přepínač nepřítomnosti v topení; *by the dates*, když platí data
nepřítomnosti) se **zapnutými světly** a **místnostmi, které topí**. Stisk přepne. V nastavení můžete
navíc zaškrtnout **vypínače a světla, která se při odchodu vypnou**: odejdou po přepnutí na Away,
každé jako vlastní příkaz pod vlastním oprávněním - co tento deck vypínat nesmí, se přeskočí
(tlačítko řekne kolik), a co vyžaduje podržení, způsobí, že ho při odchodu vyžaduje i tlačítko
Away. Návrat domů nic zpátky nezapíná.

#### Windows & doors - okna a dveře (1.3, ZIGMon 5.59.4)

Kolik je **otevřených** a která - první jedno dvě na tlačítku, všechna na kartě **Now** - nebo
zeleně **Closed**. Za každé čidlo dílek. **Červeně, s plamenem na dlaždici, když je otevřené okno
v místnosti, která topí** (teplo jde ven oknem). Stisk obnoví.

#### Batteries - baterie (1.3, ZIGMon 5.59.4)

Kolik baterií je **slabých** (pod 20 %) a nejslabší jménem s procenty a baterkou nakreslenou podle
stavu - oranžově, červeně, když je některá pod 10 %; jinak zeleně **All OK**.

#### Zigbee network - síť Zigbee (1.3, ZIGMon 5.59.4)

Kolik zařízení Zigbee je **online**, nebo kolik je **offline** (oranžově), s tím, které **vypadlo**
naposledy a kdy, a pruhem online proti offline.

#### Timer - časovač (1.3, ZIGMon 5.59.4)

Na vypínači (zásuvka, světlo, relé): stisk ho **zapne na 5, 10, 15, 30, 60 nebo 120 minut** - nebo
na libovolný počet 1-720, který napíšete - a ZIGMon ho po nich **vypne** (i když počítač spí; je to
vlastní časovač ZIGMonu a přežije i restart). Během běhu ukazuje tlačítko **živé odpočítávání**
v ubývajícím kruhu; **další stisk vypne**, a tím časovač zruší. Na ovladači **otočení = minuty**
(5, 10, 15, 20... až 12 h), **stisk = spustit** (nebo zrušit). By hand a podržení fungují jako
u Control. Tlačítka **Control** na vypínači dostala také volbu stisku **Timer** se stejnými minutami
a odpočet ukazují u stavu.

#### Room - místnost (1.3, ZIGMon 5.59.4)

Místnost na jeden pohled: velká **teplota**, **vlhkost**, kolik jejích vypínačů je zapnutých
(**1/3**) a **topení** - režim a cíl (*Comfort → 21°*, oranžově, když chce topit). Stisk tlačítka
obnoví. Na ovladači Stream Decku + **otočení = procházení položek místnosti** (těch, které ZIGMon
tomuto decku dovolí vidět, v pořadí ZIGMonu); lišta ukáže vybranou se stavem a řadou teček
a **stisk ji přepne nebo spustí** podle jejích vlastních pravidel - vlastní oprávnění, vlastní
podržení.

#### SMS (1.3, ZIGMon 5.59.4)

Jedna akce, tři režimy:

- **Show latest** - kolik zpráv dnes přišlo, kdo poslal poslední (jméno kontaktu nebo `…123`)
  a kdy, s odznakem **nepřečtených**. Stisk ukáže poslední SMS s možností odpovědět
  v **desktopové aplikaci ZIGMon propojené s tímto Stream Deckem**.
- **Write new** - stisk otevře v té aplikaci novou zprávu, adresovanou číslům a skupinám kontaktů,
  které přidáte v nastavení (`+420 777 123 456` nebo `group:Rodina`, nejvýš 20), nebo nikomu.
  Deck seznam kontaktů nemá: čísla skupiny si dohledá ZIGMon sám.
- **Status** - odesílatel poslední SMS (skrytý) a dnešní počet, červeně *modem offline*, když brána
  nejde, a **Muted until 15:47**, dokud jsou výstrahy ztlumené. Stisk **podržený 1,5 s ztlumí
  všechny výstrahy** na 15 min - 4 h (podle volby) a během ztlumení ho zruší. Pod **System**, vždy
  s podržením.

*Show latest* a *Write new* potřebují oprávnění **sms** a ZIGMon je předá desktopové aplikaci
propojené s touto instalací Stream Decku (ZIGMon → Nastavení → Messages → Stream Deck). Když žádná
neběží, tlačítko napíše **No desktop app running** - *link one in ZIGMon*.

### Computed - spočítané hodnoty (1.3, ZIGMon 5.59.4)

Hodnota, kterou **ZIGMon spočítá přes celý dům**, ukázaná přesně jako Reading: velká hodnota
s jednotkou, trend, graf za 1 h / 6 h / 24 h / 7 dní, vaše žluté a červené meze, počet desetinných
míst i vlastní popisek, ve všech vzhledech a barvách a se stejnými poctivými stupnicemi. Například
celkový příkon všeho, příkon jen světel, kolik světel svítí, průměrná teplota uvnitř, nejchladnější
místnost, otevřená okna, zařízení offline, vybité baterie nebo dnešní spotřeba.

Místo seznamu stovek položek má nastavení **skládačku**:

1. **What (co)** - Power (příkon), Energy today (spotřeba dnes), Energy total (spotřeba celkem),
   Temperature, Rooms' temperature (teplota místností, jedna za místnost, uvnitř: nejchladnější nebo
   nejteplejší místnost), Humidity, Pressure, Light level (osvětlení), CO₂, Battery, Low battery
   (baterie na varovné hranici ZIGMonu nebo pod ní), Signal, On / off, Open (otevřeno) nebo Online.
2. **How (jak)** - Sum (součet), Average (průměr), Min, Max, Count (počet), On, Off, % on nebo
   Spread (rozpětí: nejvyšší mínus nejnižší), jen ty, které pro danou veličinu dávají smysl:
   součet teplot není.
3. **Where (kde)** - All (vše), Inside (uvnitř) nebo Outside (venku); nebo jeden druh (světla,
   zásuvky, vypínače, stmívače, termostaty, čidla, žaluzie) a/nebo jedna místnost.

Vybrat jde jen to, co ZIGMon ve vašem domě opravdu počítá; ostatní je zašedlé (bez barometru žádný
tlak, s jedním venkovním teploměrem žádné „nejchladnější venku“). Každá volba posune ty ostatní
na nejbližší hodnotu, která existuje, a nastavení ukáže její název a hodnotu teď. Řada **Popular**
nad tím vybere jedním klepnutím: celkový příkon, příkon světel, příkon zásuvek, svítící světla,
průměr uvnitř, nejchladnější místnost, otevřená okna, zařízení offline, vybité baterie, dnešní
spotřebu. *Now* jmenuje místnost nebo zařízení s krajní hodnotou (nejchladnější místnost, zařízení
s nejslabší baterií) a kolik členů hodnotu mělo.

Stisk obnoví. Hodnoty potřebují **ZIGMon 5.59.4** se spočítanými hodnotami (jeho hello říká
`calc`); u staršího tlačítko napíše **Needs ZIGMon 5.59.4 or newer**. Správce je povoluje pod
**view**: s *every thing* všechny, s *only these* každou jmenovitě (ve skupině *Computed*). Povolená
hodnota se vždy počítá ze všech svých členů, i těch, které tento deck jednotlivě vidět nesmí.

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
| **Needs ZIGMon 5.59.4 or newer** | Jedna z akcí 1.3 se starším ZIGMonem. |
| **No desktop app running** | Tlačítko SMS: neběží žádná desktopová aplikace ZIGMon propojená s tímto Stream Deckem. |
| číslo v oválku | Nepřečtené SMS. |

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
