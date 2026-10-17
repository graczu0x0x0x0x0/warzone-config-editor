# Raport: specyfikacja komputera w programie — co da się wykryć i co z tego zrobić

> **Status:** etapy 9a–9d wdrożone w wersji 1.1.0 (pasek „Twój sprzęt”, okno „Sprzęt i system”,
> kontrola systemu, powiązanie z optymalizatorem). Punkty „później” — patrz `PLAN.md`.

*Data: 2026-10-17 · Wszystkie dane poniżej odczytałem z Twojego PC bez uprawnień administratora
(WMI/CIM, rejestr, `nvidia-smi`, EDID monitora, manifesty Steam). Nic nie zostało zmienione.*

---

## 1. Najważniejsze: co już znalazłem na Twoim komputerze

| Obszar | Wykryto | Ocena |
|---|---|---|
| Procesor | AMD Ryzen 7 9800X3D, 8 rdzeni / 16 wątków, L3 96 MB (3D V-Cache), AM5 | ✅ |
| **RAM** | **2 × 32 GB DDR5 Patriot „6400 Series”, kanały A+B (dual channel), pracuje na 4800 MT/s przy 1,10 V** | ⚠️ **EXPO wyłączone** |
| Płyta / BIOS | Gigabyte X870E AORUS ELITE WIFI7, BIOS F12 (21.05.2026) | ✅ |
| Karta | NVIDIA GeForce RTX 5090, 32 GB, sterownik 617.42, limit mocy 600 W | ✅ |
| Złącze karty | PCIe 5.0 x16 (maksimum dla tej karty) | ✅ |
| Resizable BAR | włączony (BAR1 = 32 768 MB = cały VRAM) | ✅ |
| Druga karta | zintegrowane AMD Radeon Graphics (w procesorze) | ℹ️ |
| Monitor | MSI MAG 321U X24 (2024), 3840×2160 @ 240 Hz — maksimum | ✅ |
| **Dysk z grą** | **G: — WD SATA SSD 1 TB**; w komputerze są też 2 dyski NVMe (Samsung 980, Lexar NM800 PRO) | ⚠️ |
| Windows | 11 Pro 25H2 (build 26200), plan zasilania „Wysoka wydajność”, HAGS włączony | ✅ |
| Zabezpieczenia | VBS (wirtualizacja zabezpieczeń) działa, integralność pamięci (HVCI) wyłączona | ℹ️ |
| Sterownik vs gra | 617.42, a gra zaleca minimum 591.59 (z pliku ustawień gry) | ✅ |

### Co z tego wynika

1. **Włącz EXPO w BIOS — to najważniejsza rzecz w tym raporcie.** Kości 6400 MT/s pracują jako
   4800 MT/s z napięciem bazowym 1,10 V. Ryzen 9800X3D ma 96 MB pamięci podręcznej, więc mniej
   zależy od RAM niż inne procesory. Warzone jest jednak mocno ograniczany przez procesor, a szybszy
   RAM poprawia zwłaszcza 1% low (płynność w walkach). W BIOS Gigabyte szukaj pozycji
   *Extreme Memory Profile (X.M.P.) / EXPO* → *Profile1*. Dla 9800X3D typowy „złoty środek” to
   6000 MT/s z UCLK=MEMCLK (1:1). Profil 6400 może wymusić tryb 1:2 — wtedy warto ręcznie ustawić 6000.
2. **Przenieś grę na NVMe (opcjonalne).** SATA SSD wystarcza do grania, ale Warzone dużo doczytuje
   (strumieniowanie świata i tekstur, kompilacja shaderów). NVMe skraca wczytywanie i ogranicza
   doczytywanie tekstur. Battle.net/Steam mają funkcję przeniesienia gry.
3. VBS: integralność pamięci jest wyłączona, więc koszt jest niewielki. Nie ruszałbym tego bez potrzeby,
   to kompromis bezpieczeństwa.

---

## 2. Co da się wykryć — szczegółowo, z oceną wykonalności

Legenda: ✅ działa bez uprawnień administratora · 🟡 częściowo / tylko dla niektórych producentów /
heurystyka · ❌ niemożliwe bez sterownika jądra (tego robić nie będziemy)

### Procesor

| Informacja | Źródło | Stan |
|---|---|---|
| Model, rdzenie, wątki | WMI `Win32_Processor` / już mamy | ✅ |
| Rdzenie P / E (Intel 12–14 gen., Core Ultra) | już mamy (`GetLogicalProcessorInformationEx`) | ✅ |
| Pamięć podręczna L2 / L3 + oznaczenie „3D V-Cache” (X3D) | `Win32_Processor` (L3 96 MB) | ✅ |
| Gniazdo (AM5, LGA1700…) | `Win32_Processor.SocketDesignation` | ✅ |
| Taktowanie bazowe | `MaxClockSpeed` (Windows często podaje bazowe, nie boost) | 🟡 |
| Bieżące taktowanie na żywo | licznik wydajności „Processor Information” | 🟡 (opcjonalnie) |
| Temperatura procesora | wymaga sterownika (jak HWiNFO) | ❌ |

### Pamięć RAM

| Informacja | Źródło | Stan |
|---|---|---|
| Łącznie GB, liczba kości, GB na kość | `Win32_PhysicalMemory` | ✅ |
| Producent, numer części (Part Number) | `Win32_PhysicalMemory` | ✅ (u Ciebie ogólne „6400 Series”) |
| Typ DDR4 / DDR5 | `SMBIOSMemoryType` (34 = DDR5) | ✅ |
| Prędkość pracy (MT/s) | `ConfiguredClockSpeed` | ✅ |
| Napięcie | `ConfiguredVoltage` | ✅ |
| Dual / single channel, zajęte sloty | `BankLabel` (CHANNEL A/B) + `Win32_PhysicalMemoryArray` | ✅ |
| **EXPO / XMP włączone?** | brak bezpośredniej flagi; **heurystyka**: prędkość na poziomie JEDEC (DDR5 ≤ 5600, DDR4 ≤ 3200) i napięcie bazowe (DDR5 1,1 V / DDR4 1,2 V), a kości mają wyższą znamionową prędkość (z numeru części) | 🟡 wysoka trafność — u Ciebie jednoznaczne |
| **Opóźnienie CL** | dokładne timingi są tylko w SPD, a ich odczyt wymaga sterownika SMBus | ❌ |
| CL **znamionowe** z numeru części | dekodowanie oznaczeń popularnych marek, np. G.Skill `F5-6000J3038F16G` → 6000 CL30, Kingston `KF560C30…` → 6000 CL30, Corsair `…6000C30` → 6000 CL30 | 🟡 (dla znanych marek; u Ciebie numer nie zawiera CL) |

### Karta graficzna

| Informacja | Źródło | Stan |
|---|---|---|
| Model, producent, VRAM | już mamy (rejestr) | ✅ |
| Wersja i data sterownika | `Win32_VideoController` / `nvidia-smi` | ✅ |
| **Porównanie ze sterownikiem zalecanym przez grę** | plik gry: `DisplayDriverVersionRecommended` | ✅ — gotowe dane |
| Złącze PCIe (gen. i szerokość, np. 5.0 x16) | `nvidia-smi` | 🟡 tylko NVIDIA |
| Resizable BAR | `nvidia-smi` (rozmiar BAR1 ≥ VRAM) | 🟡 tylko NVIDIA |
| Limit mocy, maks. taktowania, temperatura na żywo | `nvidia-smi` | 🟡 tylko NVIDIA |
| Dodatkowa karta zintegrowana (laptopy, iGPU) | `Win32_VideoController` | ✅ |
| Szczegóły kart AMD / Intel (PCIe, ReBAR) | wymagałyby SDK producenta (ADLX / Intel) | ❌ na razie |

### Monitor

| Informacja | Źródło | Stan |
|---|---|---|
| Nazwa, producent, rok (EDID) | `WmiMonitorID` | ✅ |
| Rozdzielczość, bieżące i maksymalne odświeżanie | już mamy | ✅ |
| **Monitor ustawiony poniżej maksymalnego odświeżania** (częsty błąd: 60 Hz na monitorze 144 Hz) | porównanie bieżące / maks. | ✅ |
| HDR włączony w Windows | API `DisplayConfig` (zaawansowany kolor) | 🟡 do zrobienia |
| G-Sync / FreeSync aktywne | brak wiarygodnego publicznego API | ❌ |

### Dysk i instalacja gry

| Informacja | Źródło | Stan |
|---|---|---|
| Na którym dysku jest gra | manifesty Steam (`appmanifest_1938090.acf`) / Battle.net | ✅ (Steam sprawdzony) |
| Typ dysku: NVMe / SATA SSD / HDD | `Get-PhysicalDisk` | ✅ |
| Wolne miejsce (aktualizacje, cache shaderów) | system plików | ✅ |

### Windows i ustawienia systemowe istotne dla gier

| Informacja | Źródło | Stan |
|---|---|---|
| Wersja / build Windows | `Win32_OperatingSystem` | ✅ |
| Plan zasilania | `powercfg` | ✅ |
| HAGS (sprzętowe planowanie GPU — potrzebne do DLSS Frame Generation) | rejestr | ✅ |
| Tryb gry (Game Mode) | rejestr | ✅ |
| Optymalizacje gier w oknie, Auto HDR | rejestr `DirectXUserGlobalSettings` | ✅ |
| Nagrywanie w tle (Xbox Game Bar / Game DVR) | rejestr | ✅ |
| VBS / integralność pamięci (HVCI) | `Win32_DeviceGuard` | ✅ |
| Kompresja pamięci | wymaga administratora | ❌ (pomijamy) |

### Płyta główna

| Informacja | Źródło | Stan |
|---|---|---|
| Producent, model płyty | `Win32_BaseBoard` | ✅ |
| Wersja i data BIOS | `Win32_BIOS` | ✅ |
| Ustawienia BIOS (EXPO, PBO, ReBAR w BIOS) | niedostępne z Windows (poza heurystykami wyżej) | ❌ |

### Czego nie da się zrobić rozsądnie

Dokładnych timingów RAM (CL-tRCD-tRP), temperatur procesora, częstotliwości odpytywania myszy,
stanu G-Sync/FreeSync ani ustawień BIOS nie da się odczytać bez sterownika jądra albo sprzętu
konkretnego producenta. Programy, które to pokazują (CPU-Z, HWiNFO), instalują własny sterownik.
Edytor nie powinien tego robić — to ryzyko i potencjalny konflikt z anty-cheatem.

---

## 3. Propozycja: jak to pokazać w programie

### A. Pasek „Twój sprzęt” na górze strony

Jedna zwarta linia pod nagłówkiem, z ikonami i krótkimi etykietami:

```
🖥 Ryzen 7 9800X3D · 8C/16T · 96 MB L3   ▸ 64 GB DDR5 · 4800 MT/s ⚠ EXPO   ▸ RTX 5090 · 32 GB · 617.42
▸ MAG 321U X24 · 4K · 240 Hz   ▸ Gra: G: SATA SSD ⚠   ▸ Windows 11 25H2   [Szczegóły]  [Kontrola systemu: 2 ⚠]
```

- Ostrzeżenia (⚠) są klikalne i prowadzą do „Kontroli systemu”.
- Pasek można zwinąć (zapamiętywane w ustawieniach), żeby nie zabierał miejsca.
- Dane wczytują się w tle przy starcie (1–2 s), więc program nie czeka na nie z uruchomieniem.

### B. Okno „Szczegóły sprzętu”

Pełna tabela z sekcjami jak w punkcie 2. Do tego przycisk **„Kopiuj specyfikację”**: tekst
gotowy do wklejenia na Discord lub forum, np. przy prośbie o pomoc z ustawieniami.
Specyfikacja jest kopiowana do schowka tylko na Twoje kliknięcie — nic nie wysyłamy.

### C. „Kontrola systemu” — lista sprawdzeń ze światłami (to daje największą wartość)

| Sprawdzenie | Kiedy ostrzeżenie | Waga | Co doradzamy |
|---|---|---|---|
| **EXPO / XMP** | RAM na prędkości i napięciu JEDEC, a kości są szybsze | 🔴 wysoka | włącz profil w BIOS (z instrukcją dla producenta płyty) |
| **Single channel RAM** | 1 kość albo obie w tym samym kanale | 🔴 wysoka | przełóż kości do slotów A2/B2 |
| Za mało RAM | < 16 GB | 🟠 | Warzone zaleca 16 GB+ |
| **Gra na HDD** | dysk z grą to HDD | 🔴 | przenieś na SSD |
| Gra na SATA, a jest NVMe | tak jak u Ciebie | 🟡 niska | przeniesienie opcjonalne |
| Mało miejsca na dysku z grą | < 50 GB wolnego | 🟠 | aktualizacje mogą się nie zmieścić |
| **Monitor poniżej maks. odświeżania** | np. 60 Hz na monitorze 144 Hz | 🔴 | ustaw w Windows → Ekran → Zaawansowane |
| Sterownik starszy niż zalecany przez grę | porównanie z plikiem gry | 🟠 | zaktualizuj sterownik |
| Karta w złym slocie / zbyt wolny link | PCIe x8/x4 lub niższa generacja niż maks. (NVIDIA) | 🟠 | sprawdź slot / kabel riser |
| ReBAR wyłączony, a `GPUUploadHeaps = true` | NVIDIA | 🟠 | włącz ReBAR w BIOS albo wyłącz to ustawienie w grze (powiązanie z edytorem) |
| Plan zasilania „Zrównoważony” / „Oszczędzanie” | powercfg | 🟡 | ustaw „Wysoka wydajność” |
| HAGS wyłączony | rejestr | 🟡 | wymagany dla DLSS Frame Generation |
| Tryb gry wyłączony | rejestr | 🟡 | włącz |
| Nagrywanie w tle włączone | Game DVR | 🟡 | wyłącz, jeśli nie używasz |
| Integralność pamięci (HVCI) włączona | DeviceGuard | 🟡 | kilka % FPS; decyzja należy do Ciebie (bezpieczeństwo) |
| Dwie karty (iGPU + dedykowana) | WMI | ℹ️ | upewnij się, że gra używa właściwej (`GPUName`) |

Kontrola **niczego nie zmienia w systemie**. Pokazuje stan, wyjaśnienie i instrukcję, a tam, gdzie
to możliwe, przycisk otwierający właściwe okno Windows (np. ustawienia ekranu, zasilania, grafiki).

### D. Powiązanie z optymalizatorem

- Optymalizator może korzystać z nowych danych: przy pojedynczym kanale RAM albo braku EXPO
  ostrzeże, że ograniczenie przez procesor będzie silniejsze, i zaproponuje cel CPU-bound.
- ReBAR wyłączony → automatycznie `GPUUploadHeaps = false`.
- Karta zintegrowana + dedykowana → sprawdzenie i zalecenie `GPUName`.

---

## 4. Inne pomysły (poza sprzętem)

1. **„Tryb przed meczem”** — skrót, który przed uruchomieniem gry sprawdza: gra zamknięta,
   pliki niezablokowane / zablokowane, brak niezapisanych zmian. Potem przycisk „Uruchom grę”
   (`steam://rungameid/1938090` lub Battle.net).
2. **Porównanie ze znajomym** — wczytanie cudzego szablonu lub pliku i widok obok siebie:
   „u mnie / u niego” z różnicami.
3. **Profil na grę** — szybkie przełączanie zestawów (np. „Warzone competitive”, „Zombies jakość”)
   jednym kliknięciem, na bazie istniejących szablonów.
4. **Lista urządzeń audio Windows** zamiast identyfikatorów GUID w ustawieniach dźwięku
   (z planu jako „na później”).

---

## 5. Wykonalność i plan

| Etap | Zakres | Nakład |
|---|---|---|
| 9a | Zbieranie danych: WMI/CIM, rejestr, EDID, manifesty Steam/Battle.net, `nvidia-smi` (w tle, z limitem czasu); testy na danych przykładowych | średni |
| 9b | Pasek „Twój sprzęt” + okno szczegółów + „Kopiuj specyfikację” (PL/EN) | średni |
| 9c | „Kontrola systemu” — 16 sprawdzeń z wyjaśnieniami, testy każdego warunku | średni |
| 9d | Powiązanie z optymalizatorem (ReBAR, kanały RAM, iGPU) | mały |
| później | HDR Windows (DisplayConfig), dekoder numerów części RAM (CL znamionowe), AMD/Intel PCIe | opcjonalnie |

**Sposób techniczny:** bez nowych bibliotek. Zapytania WMI przez jedno wywołanie PowerShell
z wynikiem w JSON albo przez COM. `nvidia-smi` tylko, jeśli jest zainstalowany (instaluje go
sterownik NVIDIA). Każda sonda ma limit czasu i w razie problemu pokazuje „nie wykryto” — tak jak
obecne wykrywanie sprzętu. Wszystko tylko do odczytu, bez uprawnień administratora, nic nie
opuszcza komputera.
