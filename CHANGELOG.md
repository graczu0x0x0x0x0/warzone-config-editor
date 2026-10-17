# Zmiany · Changelog

Format oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/), wersje według
[Semantic Versioning](https://semver.org/lang/pl/). Wersja programu jest zdefiniowana w jednym
miejscu: `src/wzce/__init__.py`.

## [Nieopublikowane]

### Dodano

- Odczyt ustawień Windows ważnych dla gier (etap 10a, na razie bez interfejsu): wymagania
  anty-cheatu Ricochet (UEFI, Secure Boot, dysk GPT, TPM 2.0 z wersją firmware, certyfikaty
  Secure Boot 2023), wirtualizacja i zabezpieczenia (hypervisor, SVM/VT-x, VBS/HVCI, WSL/Hyper-V,
  antywirus), opcje DirectX (Auto HDR, VRR, preferencja GPU dla gry), MPO, Game DVR, tryb
  zasilania i parametry procesora, plik stronicowania, TRIM, akceleracja myszy, łącze sieciowe
  i programy działające w tle. Wszystko tylko do odczytu, bez uprawnień administratora.
- **Kontrola ustawień Windows** (etap 10b) — w oknie „Sprzęt i system” → „Kontrola systemu”
  doszło ok. 30 sprawdzeń z wyjaśnieniem i instrukcją: wymagania anty-cheatu (Secure Boot,
  UEFI/GPT, TPM 2.0 i jego firmware, UAC, programy do przemapowania sterowania), wirtualizacja
  (WSL/Hyper-V przy wyłączonym SVM), antywirus, sterownik WinRing0, karta graficzna dla gry,
  Auto HDR, wyłączone MPO, Xbox Game Bar, limity procesora, sterownik AMD 3D V-Cache
  i parkowanie rdzeni (X3D z dwoma CCD), mikrokod Intel 13./14. gen., wersja Windows (poprawki
  dla Ryzenów i Core Ultra 200S), regresja sterownika NVIDIA po KB5066835, oczekujący restart,
  plik stronicowania, miejsce na C:, TRIM, nakładki w tle, akceleracja myszy, Wi-Fi.
- `wzce --system-report` — pełny wynik sondy sprzętu i systemu jako JSON (diagnostyka).

### Zmieniono

- Plan zasilania: na Ryzenach X3D z dwoma CCD zalecany jest plan zrównoważony (wymóg sterownika
  AMD), a przy planie zrównoważonym ważny jest tryb zasilania „Najlepsza wydajność”.
- Wskazówki naprawy są pokazywane także przy pozycjach informacyjnych.
- Raport [`docs/RAPORT_WINDOWS.md`](docs/RAPORT_WINDOWS.md): research optymalizacji Windows 11
  pod gry (co działa, co jest mitem) i plan zakładki „Optymalizacja Windows”.

## [1.2.0] — 2026-10-17

### Dodano

- **Udostępnij ustawienia (Markdown / JSON)** — w menu *Narzędzia*. Eksport czytelnego
  podsumowania aktualnych ustawień: domyślnie Wyświetlanie, Wydajność, Upscaling i AA oraz
  Jakość grafiki (dowolne kategorie do wyboru; dla pliku konta — celowanie, FOV, dźwięk).
  - Polskie lub angielskie nazwy i wartości („Pełny ekran”, „75 %”) wraz z oryginalnym kluczem z pliku.
  - Opcjonalnie krótki opis sprzętu (procesor, karta z VRAM, RAM z prędkością i EXPO/XMP, monitor).
  - Markdown w formie list (czytelny na Discordzie, Reddicie, GitHubie) lub JSON z surowymi
    wartościami dla narzędzi; podgląd na żywo, „Kopiuj do schowka”, „Zapisz do pliku…”.
  - Tylko podstawowe ustawienia (opcjonalnie także zaawansowane); pomijane są opcje kart innych
    producentów.
  - Prywatność: bez identyfikatorów urządzeń audio, pozycji okna, wykrytego sprzętu, wersji
    sterowników, ścieżek plików i identyfikatorów konta. Nic nie jest wysyłane.

### Zmieniono

- Wartości liczbowe są wyświetlane bez szumu zaokrągleń gry (np. 0.750001 → 0.75).

## [1.1.2] — 2026-10-17

### Zmieniono

- Przy nazwie każdego ustawienia widać w nawiasie, mniejszą czcionką, jego oryginalną nazwę
  z pliku gry (np. „Tryb DLSS (DLSSModeMP@0)”) — łatwiej porównać z poradnikami i samym plikiem.
  Nazwę można zaznaczyć i skopiować. Wcześniej była tylko w prawym dolnym rogu karty.

## [1.1.1] — 2026-10-17

### Poprawiono

- Po zapisie (a także po cofnięciu, ponownym wczytaniu czy zmianie języka) lista ustawień nie
  przeskakuje już na samą górę — zostaje w miejscu, w którym była. Lista wraca na górę tylko
  przy przejściu do innej kategorii, innego pliku albo zmianie wyszukiwania/filtrów.

## [1.1.0] — 2026-10-17

### Dodano

- **Pasek „Twój sprzęt”** pod nagłówkiem: procesor (rdzenie/wątki), RAM (pojemność, typ, prędkość,
  ostrzeżenie o wyłączonym EXPO/XMP), karta i VRAM, monitor z odświeżaniem, dysk z grą.
  Dane wczytują się w tle (2–4 s), pasek można zwinąć.
- **Okno „Sprzęt i system”** z pełną specyfikacją: pamięć podręczna i 3D V-Cache, każda kość RAM
  (producent, numer części, napięcie, prędkość i CL znamionowe z numeru części), kanały i sloty,
  złącze PCIe, Resizable BAR, limit mocy i temperatura karty (NVIDIA), monitor z EDID, folder i dysk
  gry z wolnym miejscem, Windows, płyta główna, BIOS, plan zasilania, HAGS, tryb gry, nagrywanie
  w tle, integralność pamięci. Przycisk **„Kopiuj specyfikację”** (tekst na Discord/forum).
- **Kontrola systemu** — 15 sprawdzeń ze statusem, ważnością, wyjaśnieniem i instrukcją: EXPO/XMP,
  pamięć jednokanałowa, ilość RAM, dysk z grą (HDD / SATA przy dostępnym NVMe), wolne miejsce,
  odświeżanie monitora, sterownik starszy niż zalecany przez grę, linie PCIe, Resizable BAR
  (także w połączeniu z GPU Upload Heaps), plan zasilania, HAGS, tryb gry, nagrywanie w tle,
  HVCI, grafika zintegrowana. Przyciski otwierają odpowiednie ustawienia Windows lub ustawienie
  w edytorze. Kontrola niczego nie zmienia.
- **Optymalizator** pokazuje najważniejsze problemy systemowe i wyłącza GPU Upload Heaps, gdy
  Resizable BAR jest wyłączony.
- Tytuł `cod26` rozpoznawany jako *Modern Warfare 4 (beta)* (na podstawie zainstalowanej bety).

### Ustalenia techniczne

- Dane zbierane bez uprawnień administratora: jedno wywołanie PowerShell (CIM/WMI, wynik JSON),
  rejestr, `powercfg`, `nvidia-smi`, manifesty Steam / wpisy deinstalacji. Każda sonda może się
  nie udać bez wpływu na pozostałe.
- EXPO/XMP nie ma flagi w Windows — stan wynika z prędkości i napięcia JEDEC w porównaniu
  z prędkością znamionową odczytaną z numeru części kości.
- Dokładnych timingów RAM, temperatury CPU i stanu G-Sync nie da się odczytać bez sterownika
  jądra — program celowo tego nie robi.

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
