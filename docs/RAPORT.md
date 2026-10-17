# Raport: pliki konfiguracyjne Warzone / Black Ops 7 i propozycja edytora

> **Status (wersja 1.2.0):** to raport z researchu przed rozpoczęciem prac — opisuje stan
> wiedzy i propozycje z 2026-10-17. Wszystkie etapy są wdrożone (patrz [`PLAN.md`](PLAN.md)
> i [`CHANGELOG.md`](../CHANGELOG.md)). Różnice względem propozycji: plik konta został
> obsłużony w etapie 7 (nie 2), preset „Streaming” nie powstał (są 4: Competitive,
> Zbalansowany, Jakość, Słaby PC), a aktualny opis formatu jest w [`FILE_FORMAT.md`](FILE_FORMAT.md).

*Data: 2026-10-17 · Źródła: analiza plików z `examples/`, Twój folder `players`, research w sieci (lista na końcu).*

---

## 1. Najważniejsze wnioski (TL;DR)

1. **`s.1.0.cod25.txt0` i `.txt1` to ten sam plik w dwóch kopiach (sloty A/B).** Gra zapisuje
   je naprzemiennie, a mały plik **`s.1.0.cod25.m`** (2 bajty: `00 00` lub `01 01`) wskazuje,
   który slot jest aktualny. Chroni to przed uszkodzeniem ustawień, gdy gra padnie w trakcie zapisu.
   Twoje pliki różnią się tylko jedną linią (`WindowMaximized`).
2. **Edytor musi zapisywać identyczną treść do obu plików** i robić to tylko przy zamkniętej grze
   — przy wyjściu gra nadpisuje oba pliki swoją wersją.
3. **W tych plikach NIE ma czułości myszy, FOV ani bindów.** Są w osobnych plikach konta:
   `players\<SteamID>\g.cod25.1.0.l.txt0/1` (tekst: czułość, mnożniki ADS, FOV, HDR, audio mix)
   oraz w plikach binarnych (`.b0/.b1`, `keybinds.cod25.kb`), których nie ruszamy.
4. Format jest **tekstowy i samoopisujący**: każde ustawienie ma komentarz z opisem,
   a dla liczb i list także zakres (`// 0 to 200`) albo opcje (`// one of Off, Low, High`).
   Edytor może więc **automatycznie zbudować kontrolkę dla każdej opcji**, także takiej,
   którą doda przyszła aktualizacja.
5. W Twoim folderze jest już plik **`s.1.0.cod26.txt`** (kolejna odsłona CoD/Warzone, 163 ustawienia,
   jeden plik zamiast dwóch). Edytor nie powinien mieć wpisanego na sztywno „cod25”.

---

## 2. Gdzie są pliki i co jest w którym

Folder: `%LOCALAPPDATA%\Activision\Call of Duty\players\`

| Plik | Format | Co zawiera | Edytujemy? |
|---|---|---|---|
| `s.1.0.cod25.txt0` / `.txt1` | tekst | **Komputer:** grafika, wyświetlanie, upscaling, limity FPS, audio (urządzenia i głośność), system (VRAM, wątki CPU) — 147 ustawień | **Tak (MVP)** |
| `s.1.0.cod25.m` | 2 bajty | znacznik aktywnego slotu | nie (tylko odczyt) |
| `<SteamID>\g.cod25.1.0.l.txt0/1` | tekst | **Konto:** czułość myszy, ADS, FOV, FOV 3. osoby, HDR, granice HUD, audio mix, dostępność — 67 ustawień | **Tak (etap 2)** |
| `<SteamID>\g.cod25.pm.1.0.l.txt0/1` | tekst | FOV (mały plik) | etap 2 |
| `<SteamID>\g.cod25.1.0.b0/b1`, `keybinds.cod25.kb`, `*.cdb` | binarne | profil, bindy, presety z gry | **Nie** |
| `<SteamID>\SteamCloud\…` | mieszane | kopia w chmurze Steam | nie |
| `s.1.0.cod26.txt` | tekst | następny tytuł (`cod26`) | etap 3 |

Starszy Black Ops 6 (`cod24`) trzymał pliki w `Dokumenty\Call of Duty\players\` — u Ciebie też tam są.

---

## 3. Budowa pliku

```
1                                        ← wersja formatu (pierwsza linia)

//
// Graphics                              ← nagłówek sekcji (kategoria)

// Shadow Quality Level                  ← opis ustawienia (po angielsku, od twórców)
ShadowQuality@0;3981;58629 = Very_Low // one of Very_Low, Low, Medium, High, Very_High
│             │ │    │       │           └ ograniczenie: zakres "A to B" lub lista "one of …"
│             │ │    │       └ wartość
│             │ │    └ prawdopodobnie hash wartości domyślnej
│             │ └ prawdopodobnie hash typu/zakresu
│             └ wariant (ta sama nazwa może mieć @0 i @1, np. DepthOfField bool + enum)
└ nazwa ustawienia (może zawierać spacje, np. "Handheld Fov")
```

**Typy wartości** (rozpoznawane automatycznie):

| Typ | Rozpoznanie | Przykład | Proponowana kontrolka |
|---|---|---|---|
| bool | `true`/`false`, brak zakresu | `VSync… = false` | przełącznik (toggle) |
| float | `A to B` z częścią dziesiętną | `0.000000 to 1.000000` | suwak + pole liczby (0–1 pokazane jako 0–100%) |
| int | `A to B` bez części dziesiętnej | `30 to 300` | suwak + pole liczby |
| int/float „bez limitu” | zakres > ~100 000 | `0 to 2147483647` | samo pole liczby |
| enum | `one of …` | `Off, Low, High` | ≤4 opcje: przyciski segmentowe; więcej: lista rozwijana |
| tekst | brak zakresu | GUID urządzenia audio, nazwa GPU | pole tekstowe / wybór urządzenia |

**Pułapki, o które edytor musi zadbać:** końce linii LF (nie CRLF), puste wartości (`SoundInputDevice =`),
opcje enum ze spacjami i znakami `+ % : .` (`Enabled + boost`, `wide 19.5:9`), floaty zawsze z 6 miejscami
po przecinku, nie zmieniać liczb po `@`, ostatnie 3 ustawienia są za sekcją System bez własnego nagłówka.
Pełna specyfikacja techniczna: [`FILE_FORMAT.md`](FILE_FORMAT.md).

---

## 4. Dlaczego są dwa pliki

W sieci **nikt tego oficjalnie nie wyjaśnia** — poradniki (np. JordanTBH) mówią tylko, że od BO6 są
„wiele plików” i trzeba „skopiować txt0 do txt1”. Analiza Twojego folderu daje jednak jasny obraz:

- każdy zapisywany plik ma trzy elementy: `…0`, `…1` i `….m` (także binarne profile `b0/b1`);
- `.m` ma zawsze wartość `00 00` albo `01 01`;
- tam, gdzie daty plików się różnią, nowszy jest zawsze ten slot, który wskazuje `.m`.

To klasyczny **zapis „ping-pong” (A/B)**: gra zapisuje nieaktywny slot, a potem przestawia znacznik.
Jeśli zapis się przerwie (crash, prąd), druga kopia jest wciąż poprawna. Pewność: wysoka, ale nie
potwierdzona przez Activision.

**Wnioski dla edytora:** zapisuj oba pliki identycznie, nie ruszaj `.m`, sprawdzaj czy `cod.exe`
nie działa, rób kopię zapasową przed zapisem.

### Ustawienia, które się resetują
Gracze często zgłaszają, że gra po aktualizacji przywraca ustawienia. Popularny trik to atrybut
**„Tylko do odczytu”** na obu plikach — działa u części osób, u innych nie, a dodatkowo blokuje zapis
zmian z menu gry. Czynniki resetu widoczne w samym pliku:
- `RecommendedSet = false` → gra przy starcie ustawi „zalecane” (przydatne jako przycisk „reset”),
- `DisableHWChangeDetection = false` → nowy sterownik/GPU może wywołać ponowne wykrycie sprzętu,
- `ConfigCloudStorageEnabled = true` → synchronizacja z chmurą może nadpisać lokalne zmiany.

---

## 5. Kategorie i najważniejsze ustawienia

Gra dzieli plik na 7 sekcji: **Audio (15), Display (20), Gameplay (17), Graphics (64), Interface (7),
Mouse and Gamepad (8), System (13)** + 3 ostatnie ustawienia leżące za sekcją System bez własnego nagłówka. Sekcja Graphics jest za duża, by była czytelna — w edytorze
proponuję podgrupy (bez zmiany pliku):

| Kategoria w edytorze | Podgrupy |
|---|---|
| Wyświetlanie | Tryb i rozdzielczość · Okno · Synchronizacja i opóźnienia (VSync, Reflex, Anti-Lag) · HDR i kolory |
| Wydajność | Limity FPS · Rozdzielczość renderowania/dynamiczna · Pamięć i CPU (VRAM, wątki) |
| Upscaling i AA | DLSS · FSR/CAS · XeSS · NIS · Generowanie klatek |
| Jakość grafiki | Tekstury i modele · Cienie · Oświetlenie i odbicia · Efekty (cząsteczki, woda, pogoda) · Ray tracing |
| Rozgrywka | Krew i efekty · Kursor mapy · Zwłoki |
| Audio | Głośności · Urządzenia · Mikrofon i komunikacja |
| Interfejs | HUD, licznik FPS, intro i filmy |
| Sterowanie | Gamepad, menu, pojazdy, kółko myszy |
| Oszczędzanie energii | Sustainability*, Eco/bateria |
| System (zaawansowane) | wykrywanie sprzętu, chmura, pola „DO NOT MODIFY” (tylko podgląd) |

### Ustawienia o największym wpływie (z researchu)

> Źródła często się różnią — edytor będzie pokazywał zalecenie **z uzasadnieniem i wpływem**
> (FPS / widoczność / opóźnienie / VRAM), a nie „jedyną słuszną” wartość.

| Ustawienie (klucz) | Twoja wartość | Zalecenie competitive | Uwagi |
|---|---|---|---|
| `DisplayMode` | Fullscreen | **Fullscreen** (exclusive) | najniższe opóźnienie |
| `VSync`, `VSyncInMenu` | disabled | **disabled** | VSync dodaje opóźnienie |
| `NvidiaReflex` | Enabled + boost | **Enabled** gdy limituje GPU, **Enabled + boost** gdy CPU | AMD: `AmdAntilag2 = true` |
| `GPUUploadHeaps` | true | **true** przy limicie GPU (ReBAR on), **false** przy limicie CPU | sprzeczne opinie — testować |
| `RendererWorkerCount` | 9 | liczba **rdzeni fizycznych** (lub −1); na Intel 12–14 gen tylko P-cores | `-1` = automat; wpływ głównie na 1% low / stuttering |
| `VideoMemoryScaleMP` | 0.50 | **0.60–0.80** (8 GB VRAM: niżej) | za wysoko → stutter; 0.5 jest bardzo zachowawcze dla RTX 5090 |
| `ResolutionMultiplier` | 100 | **100** | poniżej 100 rozmywa obraz |
| `DynamicSceneResolution` | false | **false** | zmienna ostrość przeszkadza w celowaniu |
| `ShaderQuality` | Low | **Medium** | Low psuje oświetlenie na niektórych mapach („ciemne dziury”) |
| `ShadowQuality` | Very_Low | Low/Medium | cienie zdradzają pozycję przeciwnika; opinie podzielone |
| `SSRQuality` | Off | **Off** | odbicia potrafią „chować” wrogów w oknach/wodzie |
| `DxrMode` (RT) | Off | **Off** | duży koszt FPS, zero korzyści competitive |
| `EnableVelocityBasedBlur` | **true** | **false** | rozmycie ruchu — warto wyłączyć! |
| `DepthOfField@0/@1` | false / Off | **false / Off** | rozmycie przy ADS |
| `TextureFilter` | aniso 2x | aniso 8x–16x | prawie bez kosztu FPS na mocnym GPU |
| `AATechniquePreferredMP` / `DLSS*` | DLSS Balanced | DLAA lub DLSS Quality, model TRANSFORMER | przy RTX 5090 DLAA jest realne |
| `DLSSFrameGeneration` | false | **false** w competitive | dodaje opóźnienie |
| `CapFps` / `MaxFpsInGame` | false / 250 | **true**, ~3 FPS poniżej odświeżania lub stabilny limit | stabilniejsze frame-time’y |
| `MaxFpsOutOfFocus` | 30 | 30 | oszczędza GPU w tle |
| `HDR` | On | Off w MP (wg części poradników) | zależy od monitora — preferencja |
| `SkipIntro`, `SkipSeasonIntroVideo` | false | **true** | szybszy start gry |
| `MouseUsesRawInput` | true | **true** | surowe wejście myszy |
| `EnableOfflineGameUpdater` | true | true | wstępna kompilacja shaderów = mniej stutteringu |

Z pliku konta (etap 2): FOV **100–110** (Warzone część graczy 110–120 — powyżej 110 efekt „rybiego oka”),
`ADSFovScaling`, `MouseAcceleration = 0`, `MouseSmoothing = false`, `MouseFilter = 0`.

**Ostrzeżenie o „gotowych configach” z internetu:** niektóre poradniki każą usunąć pliki i wgrać pobrane
z Google Drive. Edytor pozwoli zamiast tego **zaimportować tylko wybrane kategorie** z cudzego pliku,
bez danych sprzętowych (GPU, monitor, GUID-y urządzeń audio).

**Anti-cheat:** edycja tych plików to zmiana ustawień, nie modyfikacja gry; poradniki od lat ją zalecają
i nie znalazłem doniesień o banach. Edytor nie dotyka procesu gry ani plików binarnych. Nie jest to jednak
oficjalnie wspierane przez Activision.

---

## 6. Propozycje funkcji (ponad to, o co prosiłeś)

**Bezpieczeństwo danych**
- Automatyczna kopia zapasowa (txt0+txt1+.m) przed każdym zapisem, z przywracaniem jednym kliknięciem.
- Blokada zapisu, gdy `cod.exe` działa (wskaźnik „Gra uruchomiona” w pasku).
- Zapis atomowy obu slotów + walidacja zakresów i opcji enum przed zapisem.
- Gwarancja „round-trip”: niezmienione linie zostają bajt w bajt.

**Praca z ustawieniami**
- Panel **„Oczekujące zmiany”** (diff: było → będzie) przed zapisem.
- Cofnij/Ponów (Ctrl+Z / Ctrl+Y) w sesji + **trwała historia zapisów** z podglądem różnic i przywracaniem dowolnej wersji.
- **Szablony**: zapis całości lub wybranych kategorii, nakładanie częściowe (np. tylko „Upscaling”),
  podgląd zmian przed zastosowaniem, eksport/import `.json` do dzielenia się ze znajomymi.
- **Wbudowane presety**: Competitive (max FPS + widoczność), Zbalansowany, Jakość, Słaby PC/laptop, Streaming.
- Wyszukiwarka (po nazwie, opisie PL/EN, kluczu), filtr „tylko zmienione”, „ulubione”.
- Przy każdej opcji: odznaki wpływu (FPS / widoczność / opóźnienie / VRAM), wartość zalecana, przycisk reset.
- Przycisk „Przywróć zalecane przez grę” (`RecommendedSet = false`).
- Przełącznik „Tylko do odczytu” dla obu plików (z ostrzeżeniem o skutkach).
- Porównanie dwóch plików / szablonów obok siebie.

**Inteligentne podpowiedzi**
- Wykrywanie sprzętu: rdzenie CPU (→ `RendererWorkerCount`), VRAM (→ `VideoMemoryScaleMP`),
  producent GPU (ukrywa opcje NVIDIA/AMD/Intel, które Cię nie dotyczą), odświeżanie monitora (→ limit FPS).
- Kreator „Optymalizuj” z pytaniami: cel (FPS / jakość / balans), wąskie gardło CPU czy GPU.
- Oznaczanie **nowych ustawień** po aktualizacji gry (porównanie z poprzednią wersją pliku).

**Wygoda**
- Automatyczne wykrywanie plików (`cod24`/`cod25`/`cod26`, foldery kont Steam/Battle.net).
- Edytor pliku konta (czułość, FOV) — etap 2.
- Wybór urządzeń audio z listy Windows zamiast ręcznego GUID-a (później).
- Przycisk „Uruchom grę” i opcjonalne czyszczenie cache shaderów (z ostrzeżeniem).

---

## 7. Technologia — propozycja

Na Twoim komputerze są: Python 3.14 (+3.12, 3.11), Node 24, .NET 10, Git. Brak Rusta.

| Opcja | Plusy | Minusy |
|---|---|---|
| **Python 3.12 + PySide6 (Qt 6)** ⭐ | najszybszy rozwój i testy (pytest), bogate kontrolki (suwaki, toggle, drzewa, diff), natywne Undo (`QUndoStack`), ciemny motyw, łatwa praca dla mnie | `.exe` przez PyInstaller ~60–90 MB, czasem fałszywe alarmy antywirusa (łagodzi Nuitka) |
| C# .NET 10 + WPF | natywny Windows, mały plik przy zainstalowanym .NET, brak problemów z AV | więcej kodu, wolniejsze iteracje, ładny wygląd wymaga biblioteki (np. WPF-UI) |
| Electron + React | najładniejszy UI „webowy” | ciężki (~150 MB), dwa języki (JS + Node) |
| Tauri | mały, nowoczesny | wymaga instalacji Rusta |

**Rekomendacja: Python 3.12 + PySide6.** Rdzeń (parser, zapis, historia, szablony) jako czysta biblioteka
Pythona bez zależności od UI, w pełni pokryta testami na Twoich plikach; UI jako osobna warstwa.
Tłumaczenia w plikach JSON (`en.json`, `pl.json`) i baza wiedzy o ustawieniach w JSON z opisami PL/EN —
przełączanie języka bez restartu. Dane programu w `%APPDATA%\WarzoneConfigEditor\` (szablony, historia, kopie).

## 8. Proponowany UX

Ciemny motyw w stylu „gamingowym”, jedno okno:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Warzone Config Editor   [cod25 ▾]  ● Gra zamknięta    🔍 Szukaj…   PL|EN  ⚙  │
│ [↶ Cofnij] [↷ Ponów]  [Szablony ▾] [Historia]  [Optymalizuj]   [💾 Zapisz (3)]│
├───────────────┬──────────────────────────────────────────────┬───────────────┤
│ Wyświetlanie  │ Upscaling i AA › DLSS                         │ Zmiany (3)    │
│ Wydajność     │ ┌──────────────────────────────────────────┐ │ ShaderQuality │
│▶Upscaling i AA│ │ Tryb DLSS                     ⚡FPS 👁    │ │  Low → Medium │
│ Jakość grafiki│ │ Wybór między DLSS, DLAA …  (opis PL)     │ │ VelocityBlur  │
│ Rozgrywka     │ │ [ DLSS | DLAA | DLSS-D ]   zalecane: DLAA│ │  true → false │
│ Audio         │ │ DLSSModeMP@0 · domyślnie ?        ↺ reset│ │ TextureFilter │
│ Interfejs     │ └──────────────────────────────────────────┘ │  2x → 16x     │
│ Sterowanie    │ ┌──────────────────────────────────────────┐ │               │
│ Energia       │ │ Ostrość DLSS          ━━━━━━━━●━━  100 % │ │ [Odrzuć]      │
│ System        │ └──────────────────────────────────────────┘ │               │
├───────────────┴──────────────────────────────────────────────┴───────────────┤
│ Plik: …\players\s.1.0.cod25.txt0 + txt1 · ostatnia kopia: 12:04 · 147 opcji    │
└──────────────────────────────────────────────────────────────────────────────┘
```

- Lewo: kategorie z licznikiem zmienionych opcji. Środek: karty ustawień (nazwa, opis, kontrolka,
  odznaki wpływu, zalecenie, techniczny klucz drobną czcionką, reset). Prawo: panel zmian do zapisu.
- Zmienione karty mają kolorowy pasek z boku; opcje „DO NOT MODIFY” są zablokowane z kłódką.
- Tryb „Prosty / Zaawansowany” — prosty ukrywa pola systemowe i techniczne.

---

## Źródła

- [JordanTBH.TV — Black Ops 7 Configuration File Instructions](https://jordantbh.tv/title/blackops7/settings/configuration/)
- [Steam Community — Graphics Settings keep resetting](https://steamcommunity.com/app/1938090/discussions/0/3470612993464904191/)
- [Steam Community — Why do my settings get reset](https://steamcommunity.com/app/1938090/discussions/0/6589423683861782520/)
- [Dexerto — Best Black Ops 7 PC settings](https://www.dexerto.com/wikis/black-ops-7-guides-walkthrough-tips/best-pc-settings-black-ops-7/)
- [Hone — Best CoD BO7 settings for FPS](https://hone.gg/blog/cod-bo7-settings-for-fps/)
- [Hone — How to remove stutter in BO7](https://hone.gg/blog/remove-stutter-in-call-of-duty-black-ops-7/)
- [HDOpti — BO7 settings to maximise FPS and minimise stutters](https://hdopti.com/articles/black-ops-7-best-settings-for-fps)
- [HDOpti — Warzone Season 4 FPS boost](https://hdopti.com/articles/black-ops-7-best-settings-warzone-season-4-fps-boost)
- [DTG Reviews — BO7 best settings after Season 05 (2026)](https://www.dtgre.com/2026/07/black-ops-7-best-settings-season-05.html)
- [Gfinity — Black Ops 7 best PC settings](https://www.gfinityesports.com/article/black-ops-7-best-pc-settings-fps-fov-graphics-for-visibility)
- [Timesaver — BO7 graphics settings guide](https://timesaver.gg/blog/bo7-graphics-settings-guide)
- [ValoSettings — BO7 PC graphics settings](https://www.valosettings.com/news/best-pc-graphics-settings-in-black-ops-7-for-maximum-fps-and-visibility/)
- [Overgear — Black Ops 7 best settings](https://overgear.com/guides/call-of-duty/black-ops-7-best-settings/)
- [Dexerto FR — ukryte ustawienie w pliku BO6](https://www.dexerto.fr/call-of-duty/parametre-cache-warzone-black-ops-6-ameliore-visibilite-pc-1595902/)
- [Twisted Voxel — How to boost FPS in BO7](https://twistedvoxel.com/how-to-boost-fps-in-call-of-duty-black-ops-7-pc/)
