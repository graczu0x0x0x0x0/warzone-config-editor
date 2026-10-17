# Zmiany · Changelog

Format oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/), wersje według
[Semantic Versioning](https://semver.org/lang/pl/). Wersja programu jest zdefiniowana w jednym
miejscu: `src/wzce/__init__.py`.

## [1.0.0] — 2026-10-17

Pierwsze wydanie. · First release.

### Dodano

- **Edycja plików ustawień** Call of Duty: Black Ops 7 / Warzone (`cod25`), Black Ops 6 (`cod24`)
  i nowszych tytułów (`cod26`): plik komputera `s.1.0.codNN` oraz pliki konta `g.codNN.1.0.l`
  i `g.codNN.pm.1.0.l` (czułość, FOV, miks dźwięku). Zapis bajt w bajt — zmienia się tylko
  edytowana linia.
- **Baza wiedzy** z opisami PL/EN ponad 230 ustawień, kategoriami, wpływem na FPS / opóźnienie /
  widoczność / VRAM i zaleceniami dla presetów Competitive, Zbalansowany, Jakość, Słaby PC.
- **Interfejs graficzny** (PySide6): ciemny motyw, kategorie z licznikami zmian, karty ustawień
  z dopasowanymi kontrolkami, wyszukiwarka, tryb zaawansowany, ukrywanie opcji innych producentów
  kart, panel „oczekujące zmiany”, przełączanie PL/EN bez restartu.
- **Cofnij/Ponów** oraz **trwała historia** zapisów z porównaniem „przed → po” i przywracaniem.
- **Wykrywanie zmian zrobionych przez grę** z banerem i opcją „Cofnij zmiany gry”.
- **Szablony**: wbudowane presety, własne szablony z wybranych kategorii, podgląd z wyborem zmian,
  eksport/import `.json`, szablon z cudzego pliku ustawień — zawsze bez danych sprzętowych.
- **Optymalizator**: wykrywanie procesora (rdzenie P/E), karty i VRAM, odświeżania monitora;
  zalecenia z uzasadnieniem dla celu i wąskiego gardła (CPU/GPU).
- **Narzędzia**: blokada plików „tylko do odczytu”, „przywróć ustawienia zalecane przez grę”,
  foldery gry i kopii zapasowych, okno „O programie”.
- Plik **.exe** (PyInstaller) z ikoną i metadanymi wersji; samotest `--smoke-test`, raport `--report`.

### Bezpieczeństwo

- Zapis zablokowany, gdy działa `cod.exe`; kopia zapasowa przed każdym zapisem (50 ostatnich).
- Oba sloty `txt0`/`txt1` zapisywane identycznie i atomowo, z wycofaniem przy błędzie; znacznik
  `.m`, pliki binarne (`.b`, `.l.b`, `.kb`, `.cdb`) i SteamCloud nigdy nie są zmieniane.
- Zapis nadpisujący świeże zmiany gry wymaga potwierdzenia, a nadpisywany stan trafia do historii.

### Ustalenia techniczne

- Pliki `txt0`/`txt1` + `.m` to zapis „ping-pong” (A/B) — potwierdzone obserwacją.
- Pliki `.l.b` nie są sumą kontrolną tekstu; edycja pliku konta działa w grze (testy FOV 119,9 i 119).
- Gra zapisuje liczby przez float32 (119,9 → 119.900002); takie różnice nie są traktowane jako zmiany.

### Znane ograniczenia

- Tylko Windows. Plik .exe nie jest podpisany — Windows SmartScreen/antywirus mogą ostrzegać.
- Wybór urządzeń audio odbywa się przez identyfikator tekstowy (bez listy urządzeń Windows).
- Część ustawień z drugim wariantem (`@1`) ma nieudokumentowane znaczenie — opisane jako takie.
