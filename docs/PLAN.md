# Plan realizacji — Warzone Config Editor

> Status: stos zaakceptowany; **etapy 0–1 ukończone** (2026-10-17). Odhaczaj `[x]` w miarę postępu.
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
    history.py     # trwała historia zapisów (snapshoty + diff)
    templates.py   # szablony: zapis/odczyt/nakładanie częściowe, import/export
    knowledge.py   # ładowanie bazy wiedzy (opisy PL/EN, grupy, wpływ, zalecenia)
    hardware.py    # CPU/VRAM/GPU/monitor → rekomendacje
  data/
    settings_db.json   # baza wiedzy o każdym ustawieniu
    presets/*.json     # wbudowane presety
    i18n/en.json, pl.json
  ui/              # PySide6
    main_window.py, category_nav.py, setting_card.py, widgets/ (toggle, slider, segmented…)
    changes_panel.py, history_dialog.py, templates_dialog.py, optimizer_wizard.py
    i18n.py, theme.qss
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
- [ ] `settings_db.json`: dla każdego z 147 (+ cod26) ustawień: grupa, podgrupa, nazwa PL/EN,
      pełny opis PL/EN, wpływ (FPS / widoczność / opóźnienie / VRAM), zalecenia per preset,
      flagi: `hardware_specific`, `read_only`, `advanced`, nadpisanie kontrolki
- [ ] Fallback dla nieznanych kluczy: kontrolka z ograniczenia w pliku + opis z komentarza + odznaka „nowe”
- [ ] `i18n/en.json`, `pl.json` dla całego interfejsu; przełączanie bez restartu

### Etap 3 — Interfejs MVP
- [ ] Okno główne: pasek narzędzi, nawigacja kategorii, lista kart, pasek statusu
- [ ] Kontrolki: toggle, suwak+pole, przyciski segmentowe, lista rozwijana, pole tekstowe, pole tylko-do-odczytu
- [ ] Panel „Oczekujące zmiany” (było → będzie), Zapisz / Odrzuć
- [ ] Wyszukiwarka, filtr „tylko zmienione”, tryb Prosty/Zaawansowany
- [ ] Ciemny motyw, przełącznik PL/EN, zapamiętywanie ustawień okna
- [ ] Wskaźnik „gra uruchomiona” i stan plików (txt0/txt1 zgodne?)

### Etap 4 — Historia i cofanie
- [ ] Cofnij/Ponów w sesji (`QUndoStack`, Ctrl+Z / Ctrl+Y)
- [ ] Trwała historia zapisów z opisem, datą i diffem; przywracanie dowolnej wersji
- [ ] Wykrywanie zmian dokonanych przez grę od ostatniego otwarcia („gra zmieniła 4 ustawienia”)

### Etap 5 — Szablony i presety
- [ ] Zapis szablonu: całość lub wybrane kategorie; pomijanie danych sprzętowych
- [ ] Nakładanie szablonu z podglądem różnic (wybór, które zmiany przyjąć)
- [ ] Wbudowane presety: Competitive, Zbalansowany, Jakość, Słaby PC, Streaming
- [ ] Eksport/import `.json`; import wybranych kategorii z cudzego pliku `.txt0`

### Etap 6 — Optymalizator
- [ ] Odczyt sprzętu (rdzenie fizyczne/P-cores, VRAM, producent GPU, odświeżanie)
- [ ] Kreator: cel (FPS / balans / jakość), wąskie gardło CPU/GPU → propozycja zmian
- [ ] Ukrywanie opcji innych producentów GPU
- [ ] Przyciski: „Zalecane przez grę” (`RecommendedSet`), atrybut „tylko do odczytu”

### Etap 7 — Plik konta (czułość, FOV)
- [ ] Obsługa `players\<ID>\g.cod25.1.0.l.txt0/1` i `g.cod25.pm.1.0.l.txt0/1` (ten sam parser)
- [ ] Wybór konta, gdy jest kilka folderów
- [ ] Sprawdzenie, czy gra respektuje edycję tekstu, czy nadpisuje z binarnego `.b0/.b1` / chmury
      (uwaga: każdy `g.cod25.1.0.l.txtN` ma binarny towarzysz `.l.bN` — możliwa suma kontrolna)

### Etap 8 — Dystrybucja
- [ ] Ikona, nazwa, wersjonowanie
- [ ] Build `.exe` (PyInstaller; ewentualnie Nuitka przy problemach z antywirusem)
- [ ] README PL/EN z instrukcją, CHANGELOG

## Otwarte pytania / ryzyka
- Czy gra czyta slot z `.m`, czy zawsze oba? (zapis obu identycznie omija problem)
- Czy chmura (`ConfigCloudStorageEnabled`, SteamCloud) nadpisuje edycję? — test w etapie 1/7
- Znaczenie liczb `TypeId;DefaultId` — rozszyfrowanie dałoby „reset do domyślnej” dla każdej opcji
- Czy Battle.net ma inną strukturę folderu konta niż Steam
