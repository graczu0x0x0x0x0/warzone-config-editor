# Plan realizacji — Warzone Config Editor

> Status: stos zaakceptowany; **etapy 0–9 ukończone — wersja 1.1.0** (2026-10-17). Odhaczaj `[x]` w miarę postępu.
> Stos: Python 3.12 + PySide6-Essentials, pytest, ruff, uv, PyInstaller.
> Szczegóły i uzasadnienie: [`RAPORT.md`](RAPORT.md). Format pliku: [`FILE_FORMAT.md`](FILE_FORMAT.md).

## Architektura (warstwy)

```
src/wzce/
  core/            # czysty Python, zero importów Qt — w pełni testowalny
    errors.py      # exception hierarchy (WzceError and subclasses)              [done]
    model.py       # Setting, Constraint, ValueType, value validation/formatting [done]
    document.py    # text -> ConfigDocument, byte-exact round-trip, set_value    [done]
    diff.py        # setting-level diff of documents / snapshots                 [done]
    storage.py     # SettingsFileSet: A/B slots, atomic save, read-only, rollback [done]
    backup.py      # timestamped backups with sha256 manifest, restore, prune    [done]
    discovery.py   # finds s.1.0.codNN and account g.codNN files                [done]
    process.py     # cod.exe detection                                           [done]
    paths.py       # %APPDATA%/WarzoneConfigEditor, game players folders         [done]
    undo.py        # undo stack with merging of quick edits                    [done]
    history.py     # persistent history: saves + game changes, snapshots     [done]
    templates.py   # templates, built-in presets, preview plan, store, import/export [done]
    knowledge.py   # knowledge base loader + unknown-key fallback                [done]
    i18n.py        # UI translations with EN fallback, language listeners        [done]
    session.py     # EditorSession: original vs working copy, revert, save, disk change [done]
    hardware.py    # CPU cores/P-cores, VRAM, GPU, refresh rate, RAM (Win32)   [done]
    optimizer.py   # goal + bottleneck + hardware -> values with reasons      [done]
  data/
    settings_db/       # baza wiedzy: _meta.json (grupy, presety) + plik na grupę  [done]
    i18n/en.json, pl.json                                                      [done]
  ui/              # PySide6
    app.py, app_settings.py, theme.py                                         [done]
    main_window.py, setting_card.py, editors.py, changes_panel.py             [done]
    history_dialog.py                                                          [done]
    templates_dialog.py                                                        [done]
    optimizer_dialog.py, plan_table.py (shared preview table)                  [done]
tests/             # pytest, fixtures z examples/
```

## Etapy

### Etap 0 — Fundamenty
- [x] Repozytorium Git, `.gitignore`, `CLAUDE.md`, dokumentacja w `docs/`
- [x] `pyproject.toml` (uv, Python 3.12), ruff, pytest, struktura katalogów
- [x] Sprawdzenie, że PySide6 instaluje się na wybranej wersji Pythona

### Etap 1 — Rdzeń: odczyt i zapis (bez UI)
- [x] Parser: nagłówek, sekcje, opisy, ustawienia `Key@Variant;Type;Default = Value // Constraint`
- [x] Rozpoznawanie typów: bool / int / float / enum / string; zakresy „bez limitu”
- [x] Writer z gwarancją round-trip (test: parse → write == oryginał, bajt w bajt, dla wszystkich próbek)
- [x] Walidacja wartości (zakres, opcje enum, format float 6 miejsc)
- [x] Zapis do obu slotów (txt0 + txt1), atomowo; `.m` bez zmian
- [x] Wykrywanie `cod.exe` i blokada zapisu
- [x] Kopia zapasowa przed zapisem + przywracanie
- [x] Discovery: `%LOCALAPPDATA%` i `Dokumenty`, wszystkie `codNN`
- [x] Testy jednostkowe na plikach z `examples/`
- [x] Tymczasowy raport CLI: `uv run python -m wzce` (tylko odczyt, do czasu GUI)

### Etap 2 — Baza wiedzy i tłumaczenia
- [x] Baza wiedzy `data/settings_db/` (folder: `_meta.json` + plik na kategorię zamiast jednego
      `settings_db.json` — łatwiejsza edycja): 168 wpisów = 147 cod25 + 21 nowych z cod26;
      kategoria/podkategoria, nazwa i pełny opis PL/EN, etykiety opcji, wpływ (FPS / opóźnienie /
      widoczność / VRAM), zalecenia dla 4 presetów, flagi, producent GPU, podpowiedzi kontrolek,
      reguły sprzętowe dla etapu 6. Schemat: [`KNOWLEDGE_BASE.md`](KNOWLEDGE_BASE.md)
- [x] Fallback dla nieznanych kluczy: kategoria z sekcji pliku, nazwa z klucza, opis z komentarza, flaga „new”
- [x] `i18n/en.json`, `pl.json` (~120 tekstów UI) + `Translator` z powiadamianiem o zmianie języka
- [x] Testy spójności: pokrycie wszystkich kluczy, poprawność zaleceń względem plików gry, kompletność tłumaczeń
- [ ] Baza wiedzy dla pliku konta (czułość, FOV — 67 ustawień) → razem z etapem 7

### Etap 3 — Interfejs MVP
- [x] Okno główne: nagłówek (plik, filtry, akcje), nawigacja kategorii z licznikami zmian, karty, pasek statusu
- [x] Kontrolki: przełącznik, suwak+pole (także %), przyciski segmentowe, lista rozwijana, pole tekstowe; blokada kółka myszy
- [x] Karta: opis PL/EN, odznaki wpływu / producenta GPU / „Nowe” / kłódka, zalecenie wybranego presetu + „Użyj zalecanej”, „Przed zmianą”, cofnięcie
- [x] Panel „Oczekujące zmiany” (było → będzie, przejście do ustawienia, cofnięcie), Zapisz / Odrzuć / Wczytaj ponownie
- [x] Wyszukiwarka (PL/EN/klucz), widok „Zmienione”, tryb Zaawansowany, ukrywanie opcji innych producentów GPU
- [x] Ciemny motyw, przełącznik PL/EN bez restartu, zapamiętywanie języka, filtrów, presetu, ostatniego pliku i układu okna
- [x] Wskaźnik „gra uruchomiona” (blokuje zapis), ostrzeżenie o różnicy txt0/txt1, automatyczne przeładowanie, gdy gra zmieni plik
- [x] Pytanie o niezapisane zmiany przy zmianie pliku i zamykaniu; Ctrl+S, Ctrl+F
- [x] Testy GUI (pytest-qt, offscreen) — 18 scenariuszy
- [ ] Opisy w bazie wiedzy dla 6 ustawień tylko z BO6 (cod24) — dziś pokazują się jako „Nowe”

### Etap 4 — Historia i cofanie
- [x] Cofnij/Ponów (Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z) — własny stos w rdzeniu zamiast `QUndoStack`
      (testowalny bez Qt); szybkie zmiany tego samego ustawienia łączą się w jeden krok;
      cofnąć można też „Odrzuć wszystkie” i przywrócenia z historii; stos przeżywa zapis
- [x] Trwała historia (`%APPDATA%\WarzoneConfigEditor\history`): wpisy „Zapis w edytorze” i
      „Zmienione przez grę”, data, diff przed → po, pełny stan po każdym wpisie (do 200 wpisów)
- [x] Okno Historii: „Cofnij te zmiany” (tylko wymienione ustawienia) i „Przywróć cały ten stan”;
      oba trafiają do edytora jako zmiany do zapisania; pomijają wartości zarządzane przez grę
- [x] Wykrywanie zmian gry: przy otwarciu (porównanie z ostatnio widzianym stanem) i w trakcie pracy;
      baner z nazwami zmienionych ustawień, „Pokaż szczegóły” i „Cofnij zmiany gry”;
      zmiany samych pól technicznych (sterownik, okno) trafiają do historii bez banera
- [x] Zapis nadpisujący świeże zmiany gry pyta o zgodę, a nadpisywany stan najpierw trafia do historii
- [x] Testy: 17 rdzenia (stos, historia, zmiany gry) + 11 GUI

### Etap 5 — Szablony i presety
- [x] Zapis szablonu z obecnych ustawień (także niezapisanych): nazwa, opis, wybór kategorii;
      wartości sprzętowe i zarządzane przez grę nigdy nie trafiają do szablonu
- [x] Nakładanie z podglądem: tabela „obecnie → z szablonu” z checkboxami, podsumowanie
      (zmieni się / bez zmian / pominięte z powodem), zastosowanie jako jeden krok Cofnij
- [x] Wbudowane presety z bazy wiedzy: Competitive, Zbalansowany, Jakość, Słaby PC / laptop
- [x] Pomijanie z podaniem powodu: brak w pliku (inny tytuł), zależne od sprzętu, zarządzane przez grę,
      inny producent GPU, wartość nieakceptowana (np. DLAA w cod26)
- [x] Eksport do `.json` (także presetów), import `.json` oraz utworzenie szablonu z cudzego pliku
      `.txt0/.txt1/.txt` (wybrane kategorie, bez danych sprzętowych); usuwanie własnych szablonów
- [x] Szablony w `%APPDATA%\WarzoneConfigEditor\templates`; testy: 22 rdzenia + 5 GUI

### Etap 6 — Optymalizator
- [x] Wykrywanie sprzętu bez uprawnień administratora: procesor i rdzenie (P/E na hybrydowych
      Intelach przez `GetLogicalProcessorInformationEx`), RAM, karta i VRAM (rejestr, dokładnie > 4 GB),
      odświeżanie monitora (bieżące i maksymalne); każda sonda w razie błędu zwraca „nie wykryto”
- [x] Reguły: `RendererWorkerCount` = rdzenie P lub fizyczne; `VideoMemoryScaleMP` z tabeli VRAM i celu;
      `MaxFpsInGame` = odświeżanie − 3 (30–300); upscaler pasujący do producenta karty;
      wąskie gardło CPU/GPU → Reflex boost i GPU Upload Heaps
- [x] Kreator „Optymalizuj”: wykryty sprzęt, cel (4 presety), „co ogranicza FPS?” z podpowiedzią
      o telemetrii, podgląd z kolumną „Dlaczego”, zastosowanie jako jeden krok Cofnij
- [x] Ukrywanie opcji innych producentów GPU (od etapu 3) + pomijanie ich przez optymalizator
- [x] Menu „Narzędzia”: wczytaj ponownie, „Przywróć ustawienia zalecane przez grę” (`RecommendedSet`),
      blokada plików „tylko do odczytu” (z wyjaśnieniem skutków), foldery gry i kopii zapasowych
- [x] Nagłówek przebudowany: minimalna szerokość okna 1278 px zamiast 1743 px (laptopy 1366 px)
- [x] Wspólny widget podglądu zmian (`PlanTable`) dla szablonów i optymalizatora
- [x] Testy: 25 rdzenia (parsowanie CPU, wybór karty, reguły) + 8 GUI

### Etap 7 — Plik konta (czułość, FOV)
- [x] Analiza `.l.b`: to NIE jest suma kontrolna tekstu (sloty tekstu się różnią, `.l.b` identyczne),
      a wartości z tekstu (FOV, czułość) nie występują w żadnym pliku binarnym — szczegóły w
      [`FILE_FORMAT.md`](FILE_FORMAT.md)
- [x] Obsługa `players\<ID>\g.codNN.1.0.l` i `g.codNN.pm.1.0.l` (A/B i pojedyncze pliki cod26),
      te same zasady zapisu co dla pliku komputera (oba sloty, znacznik `.m` i `.l.b` bez zmian)
- [x] Wybór konta: każdy plik konta na liście plików z końcówką identyfikatora (np. „Profil konta …0575”)
- [x] Baza wiedzy: 67 ustawień konta PL/EN, nowa kategoria „Celowanie i FOV” (FOV, czułość, ADS,
      pojazdy, akceleracja/wygładzanie), miks dźwięku, czat głosowy, jasność/HDR, HUD, auto-sprint
- [x] ~~Baner „edycja pliku konta jest eksperymentalna”~~ — usunięty po potwierdzeniu w grze (test #2)
- [x] Testy: pokrycie bazy dla plików konta cod25/cod26 + 4 GUI (zapis FOV i czułości do obu slotów)
- [x] Test w grze #1: gra wczytała wartość z pliku tekstowego (zapisała ją z powrotem jako 119.900002),
      nie nadpisała jej z chmury; menu gry zaokrągla FOV do liczby całkowitej
- [x] Poprawki po teście: FOV zmienia się o pełne stopnie (pole `step` w bazie wiedzy); różnice
      zaokrągleń float32 (119.900000 vs 119.900002) nie są już zgłaszane jako zmiana gry
- [x] Test w grze #2: FOV 119 ustawione w edytorze → gra pokazuje 119 i zapisuje 119.000000;
      edycja plików konta potwierdzona

### Etap 8 — Dystrybucja
- [x] Ikona (`data/icons/app.svg` → `app.png` + wielorozmiarowe `app.ico`, `scripts/build_icon.py`),
      ikona okna i paska zadań (AppUserModelID)
- [x] Wersjonowanie: jedno źródło `src/wzce/__init__.py` (1.0.0) → `pyproject.toml` (hatch),
      metadane .exe, `--version`, okno „O programie”
- [x] Build `.exe`: `scripts/build_exe.py` (PyInstaller, jeden plik 37 MB lub `--onedir` + zip),
      automatyczny samotest `--smoke-test` zbudowanego pliku, suma SHA-256
- [x] README PL/EN ze zrzutami (`docs/img/`), CHANGELOG
- [ ] Pomysły na później: podpis cyfrowy .exe (mniej ostrzeżeń SmartScreen), lista urządzeń audio
      Windows zamiast identyfikatorów, licencja projektu

### Etap 9 — Twój sprzęt i kontrola systemu (wersja 1.1.0)
Propozycja i analiza: [`RAPORT_SPRZET.md`](RAPORT_SPRZET.md).
- [x] 9a Zbieranie danych bez administratora: `core/system_info.py` (PowerShell→JSON, rejestr,
      powercfg, nvidia-smi, instalacja gry); parsery jako czyste funkcje z testami na fixturach
- [x] Analiza RAM: kanały z etykiet slotów, prędkość/CL znamionowe z numeru części
      (G.Skill, Kingston FURY, Corsair, TeamGroup, ogólne), heurystyka EXPO/XMP
- [x] 9b Pasek „Twój sprzęt” (w tle, zwijany, zapamiętywany) + okno „Sprzęt i system”
      ze specyfikacją i „Kopiuj specyfikację”
- [x] 9c Kontrola systemu: 15 sprawdzeń (`core/system_checks.py`) z ważnością, wyjaśnieniem,
      instrukcją i akcją (ustawienia Windows / strona sterownika / ustawienie w edytorze)
- [x] 9d Optymalizator: ostrzeżenia systemowe w kreatorze, ReBAR wyłączony → GPU Upload Heaps off
- [x] Testy: 29 rdzenia (parsowanie, EXPO, sprawdzenia „mój PC” i „PC z problemami”) + 9 GUI
- [ ] Później: HDR Windows (DisplayConfig), szczegóły PCIe/ReBAR dla AMD/Intel, więcej marek RAM

## Otwarte pytania / ryzyka
- Czy gra czyta slot z `.m`, czy zawsze oba? (zapis obu identycznie omija problem)
- Czy chmura (`ConfigCloudStorageEnabled`, SteamCloud) nadpisuje edycję? — test w etapie 1/7
- Znaczenie liczb `TypeId;DefaultId` — rozszyfrowanie dałoby „reset do domyślnej” dla każdej opcji
- Czy Battle.net ma inną strukturę folderu konta niż Steam
