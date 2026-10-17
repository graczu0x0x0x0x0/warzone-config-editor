# Plan realizacji — Warzone Config Editor

> Status: stos zaakceptowany; **etapy 0–3 ukończone** (2026-10-17). Odhaczaj `[x]` w miarę postępu.
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
    knowledge.py   # knowledge base loader + unknown-key fallback                [done]
    i18n.py        # UI translations with EN fallback, language listeners        [done]
    session.py     # EditorSession: original vs working copy, revert, save, disk change [done]
    hardware.py    # GPU vendor from the file [done]; CPU/VRAM/monitor -> stage 6
  data/
    settings_db/       # baza wiedzy: _meta.json (grupy, presety) + plik na grupę  [done]
    i18n/en.json, pl.json                                                      [done]
  ui/              # PySide6
    app.py, app_settings.py, theme.py                                         [done]
    main_window.py, setting_card.py, editors.py, changes_panel.py             [done]
    history_dialog.py, templates_dialog.py, optimizer_wizard.py               (stages 4-6)
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
- [ ] Cofnij/Ponów w sesji (`QUndoStack`, Ctrl+Z / Ctrl+Y)
- [ ] Trwała historia zapisów z opisem, datą i diffem; przywracanie dowolnej wersji
- [ ] Wykrywanie zmian dokonanych przez grę od ostatniego otwarcia („gra zmieniła 4 ustawienia”)

### Etap 5 — Szablony i presety
- [ ] Zapis szablonu: całość lub wybrane kategorie; pomijanie danych sprzętowych
- [ ] Nakładanie szablonu z podglądem różnic (wybór, które zmiany przyjąć)
- [ ] Wbudowane presety (zalecenia już są w bazie wiedzy): Competitive, Zbalansowany, Jakość, Słaby PC
- [ ] Presety pomijają ustawienia innych producentów GPU i zgłaszają różnice między tytułami
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
