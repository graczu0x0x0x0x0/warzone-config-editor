# Raport: zakładka „Optymalizacja Windows 11” — co pokazać, co zmieniać, czego nie ruszać

> **Status:** etapy 10a (odczyt, `core/windows_info.py`), 10b (ocena, `core/windows_checks.py`)
> i 10c (zakładka „Optymalizacja Windows”) wdrożone; 10d–10e czekają — patrz `PLAN.md`.

*Data: 2026-10-17. Dane w §2 odczytałem z Twojego PC bez uprawnień administratora (rejestr, WMI/CIM,
`powercfg`, `tpmtool`/TBS). Nic nie zostało zmienione. Źródła są w §9. Liczby pochodzą z testów
redakcji sprzętowych. Tam, gdzie pomiarów nie ma, piszę to wprost.*

---

## 1. Najważniejsze wnioski

1. **Większość popularnych „tweaków Windows pod gry” nie daje nic albo szkodzi.** Na Windows 11
   24H2/25H2 realnie mierzalne są tylko:
   - wirtualizacja zabezpieczeń (VBS/HVCI, ok. 3–6% FPS przy ograniczeniu przez procesor, w CoD ok. 3%),
   - aktualne poprawki systemu i sterowników,
   - kilka ustawień zależnych od sprzętu (Ryzen X3D z dwoma CCD, Intel 13/14 gen.).
   Zakładka powinna więc **porządkować wiedzę i mówić „tego nie ruszaj”**, a nie obiecywać +30% FPS.
2. **Wymagania anti-cheatu Ricochet to dziś najważniejsza rzecz do sprawdzenia.** Bez TPM 2.0 i
   Secure Boot BO7/Warzone odcina tryby rankingowe i część playlist (od sezonu 4, czerwiec 2026).
   Program wykrywa to bez administratora i może wskazać dokładną przyczynę: CSM, MBR, wyłączony
   fTPM albo zła wersja firmware TPM.
3. **Część obecnych sprawdzeń trzeba poprawić.** Kontrola systemu w wersji 1.2.0 ostrzega przed planem
   „Zrównoważony”. Dla Ryzenów X3D z dwoma CCD (7900X3D/7950X3D/9900X3D/9950X3D) to błąd: optymalizator
   AMD 3D V-Cache **wymaga** planu zrównoważonego i Xbox Game Bar.
4. **Program może bezpiecznie zmieniać tylko ustawienia użytkownika (HKCU).** Ustawienia systemowe
   (HKLM, restart) wymagają UAC, kopii i cofania. Zabezpieczeń (VBS, Defender, Secure Boot) program
   **nigdy** nie powinien wyłączać sam. Może je tylko pokazać, wyjaśnić koszt i otworzyć właściwą stronę.

---

## 2. Stan Twojego komputera (odczyt 2026-10-17)

| Obszar | Wykryto | Ocena |
|---|---|---|
| Windows | 11 Pro **25H2**, build 26200.9711 | ✅ zawiera poprawkę AMD branch prediction (+~10% na Zen 5) |
| Tryb rozruchu | UEFI, **Secure Boot włączony** | ✅ wymóg Ricochet |
| Certyfikaty Secure Boot 2023 | `UEFICA2023Status = Updated` | ✅ (stare certyfikaty Microsoft wygasają w czerwcu i 19.10.2026) |
| TPM | **TPM 2.0** (AMD fTPM / Pluton), firmware 6.32.0.6 | ✅ nie jest to wadliwa seria 3.x.0.x |
| Wirtualizacja CPU (SVM) | **wyłączona w BIOS** (brak hypervisora, `VirtualizationFirmwareEnabled = False`) | ℹ️ zob. niżej |
| VBS / HVCI | VBS „włączone, ale nie działa”, integralność pamięci wyłączona | ✅ dla FPS (najszybszy wariant) |
| Funkcje Windows | Platforma maszyny wirtualnej + WSL **zainstalowane**, Hyper-V wyłączone | ⚠️ zainstalowane, ale bez SVM nie wystartują |
| RAM | 2 × 32 GB, **6200 MT/s** | ✅ profil EXPO/ręczny działa (w poprzednim raporcie było 4800) |
| HAGS | włączone | ✅ wymagane przez DLSS Frame Generation |
| Tryb gry | włączony (domyślnie) | ✅ |
| Nagrywanie w tle (Game DVR) | wyłączone | ✅ |
| Auto HDR (globalnie) | **włączone** | ℹ️ CoD ma własne HDR, więc Auto HDR nic tu nie wnosi |
| Optymalizacje gier w oknie | włączone | ✅ bez wpływu na CoD (DX12) |
| **MPO (multiplane overlay)** | **wyłączone tweakiem** (`OverlayTestMode = 5`) | ⚠️ stary tweak na migotanie. Na 24H2+ bywa ignorowany lub psuje wideo. Warto przywrócić, jeśli nie było problemów |
| Pełny ekran (FSO) dla `cod.exe` | wyłączone przez flagę zgodności | ℹ️ bez efektu w grach DX12 |
| Plan zasilania | „Wysoka wydajność” (+ zainstalowany „Bitsum Highest Performance” z Process Lasso) | ✅ dla 9800X3D (jeden CCD) |
| Minimalny stan procesora (AC) | **0%** w planie „Wysoka wydajność” (domyślnie 100%) | ℹ️ ktoś to zmienił. Wpływ na FPS niezmierzony |
| Parkowanie rdzeni | wyłączone (CPMINCORES = 100) | ✅ dla jednego CCD |
| Precyzja wskaźnika myszy | wyłączona | ✅ (gra i tak używa raw input) |
| Programy w tle | Discord, Steam, NVIDIA App + nakładka, **MSI Afterburner + RTSS**, Logitech G HUB, aplikacja Xbox, Epic | ℹ️ 3 nakładki naraz (Steam, NVIDIA, RTSS) |
| Antywirus | **Norton 360** aktywny, Defender w trybie pasywnym | ℹ️ wykluczenia ustawia się w Nortonie, nie w Defenderze |
| Plik stronicowania | ręcznie, 128 GB na C: | ℹ️ działa, ale zajmuje 128 GB. Wyłączenie byłoby szkodliwe (CoD crashuje) |
| Sieć | Ethernet, 1 Gb/s (karta 2.5G) | ✅ |
| Sterownik NVIDIA | 617.42 (≥ 581.94, poprawka regresji KB5066835) | ✅ |
| Oczekujący restart | brak (jest tylko `PendingFileRenameOperations`, zwykle nieszkodliwe) | ✅ |

**Wniosek dla Twojego PC:** system jest dobrze ustawiony. Do decyzji zostają drobiazgi:
1. **MPO:** przywrócić domyślne, jeśli tweak nie był potrzebny.
2. **SVM i WSL:** albo włączyć SVM, jeśli używasz WSL2/Dockera (koszt w grze jest wtedy niewielki,
   o ile HVCI zostaje wyłączone), albo odinstalować WSL i platformę VM, jeśli ich nie używasz.
3. **Auto HDR:** wyłączyć.
4. **Nakładki:** ograniczyć do jednej (np. tylko RTSS albo tylko NVIDIA).

---

## 3. Co już jest w programie (wersja 1.2.0)

Okno **„Sprzęt i system”** ma dwie zakładki: **Specyfikacja** i **Kontrola systemu**. Kontrola ma 15
sprawdzeń. Z Windows są tam już: plan zasilania, HAGS, tryb gry, nagrywanie w tle, HVCI i odświeżanie
monitora. Dane zbiera `core/system_info.py` (bez administratora, w tle), a ocenia `core/system_checks.py`.
Akcje to linki `ms-settings:`, strony WWW albo przejście do ustawienia gry.

**Nowa zakładka powinna to rozbudować, a nie dublować.** Sprawdzenia „windowsowe” przechodzą do
nowej zakładki, a sprzętowe (RAM, dysk, PCIe, ReBAR, sterownik) zostają w „Kontroli systemu”.

---

## 4. Proponowana zawartość zakładki — pełna lista

Legenda:
- **Wpływ:** 🟢 zmierzony · 🟡 zależy od sprzętu/sytuacji · ⚪ brak efektu / mit
- **Odczyt bez administratora:** ✅ tak · 🟡 częściowo · ❌ nie
- **Zmiana:**
  - **A** = program zmienia sam (HKCU, bez administratora, odwracalne)
  - **B** = program zmienia po zgodzie UAC (HKLM, często restart)
  - **L** = tylko link lub instrukcja (decyzja i zmiana po stronie użytkownika, często w BIOS)

### 4.1 Wymagania gry i anti-cheat (Ricochet) — sekcja na górze

| Pozycja | Odczyt | Rekomendacja | Zmiana |
|---|---|---|---|
| **Secure Boot** | ✅ rejestr `SecureBoot\State\UEFISecureBootEnabled` | Musi być włączony | L: BIOS → Boot/Security → CSM: Disabled, Secure Boot: Enabled, „Install default keys” |
| **Tryb UEFI** (nie Legacy/CSM) | ✅ `GetFirmwareType()` | Wymagany | L: BIOS |
| **Dysk systemowy GPT** | 🟡 `MSFT_Disk.PartitionStyle` (do sprawdzenia bez administratora) | Wymagany. MBR → `mbr2gpt` | L: instrukcja `mbr2gpt /validate` → `/convert` (administrator, BitLocker wyłączony) |
| **TPM 2.0** | ✅ `Tbsi_GetDeviceInfo` (tbs.dll) lub urządzenie PnP `MSFT0101` | Wymagany | L: BIOS → AMD fTPM / Intel PTT |
| **Wersja firmware TPM** | ✅ rejestr `Services\TPM\WMI` (wartości nieudokumentowane) | AMD fTPM **3.x.0.x** i Intel 302/303.12.x nie przechodzą atestacji → aktualizacja BIOS | L: strona producenta płyty |
| **Certyfikaty Secure Boot 2023** | ✅ `SecureBoot\Servicing\UEFICA2023Status` | „Updated”. Jeśli nie: Windows Update + BIOS | L: `ms-settings:windowsupdate` |
| **UAC nie na „Nigdy nie powiadamiaj”** | ✅ `ConsentPromptBehaviorAdmin` / `EnableLUA` | Gra wymaga zaakceptowania UAC dla `CODBrokerInstaller.exe` i `enrollaik.exe` | L |
| Odnośnik do **Secure Attestation Wizard** Activision | — | Oficjalne narzędzie diagnostyczne | L: link do support.activision.com |

Ważne: **nie znalazłem żadnego oficjalnego wymogu ani zakazu** dotyczącego HVCI, Hyper-V, WSL czy
VMware w Ricochet. Program nie może twierdzić, że coś „blokuje anti-cheat”, jeśli nie ma na to źródła.

### 4.2 Wirtualizacja i zabezpieczenia

| Pozycja | Wpływ | Odczyt | Rekomendacja | Zmiana |
|---|---|---|---|---|
| **Integralność pamięci (HVCI)** | 🟢 ComputerBase: −6% średnio i −8% w 1% low przy ograniczeniu przez CPU. **Warzone 2: −3,4%**. Tom's Hardware: ~5% (RTX 4090) | ✅ `Win32_DeviceGuard` | Decyzja użytkownika: bezpieczeństwo kontra kilka % | L: `windowsdefender://coreisolation` (restart) |
| **VBS** (bez HVCI) | 🟡 mniejszy koszt. Działa tylko, gdy działa hypervisor | ✅ | Informacja | L |
| **Platforma maszyny wirtualnej, WSL2, Hyper-V, Piaskownica, Platforma hypervisora** | 🟡 każda z nich uruchamia hypervisor, więc koszt podobny do VBS | ✅ `Win32_OptionalFeature` | „Jeśli nie używasz WSL/Dockera/maszyn wirtualnych, możesz je wyłączyć” (to zalecenie samego Microsoftu dla graczy) | L: `optionalfeatures.exe` lub B (DISM, restart) |
| **Hypervisor działa?** | — | ✅ `Win32_ComputerSystem.HypervisorPresent` | Pokazuje, czy powyższe naprawdę działa | — |
| **SVM / VT-x w BIOS** | ⚪ sam przełącznik nie kosztuje FPS (brak wiarygodnych pomiarów, które by to pokazały) | ✅ tylko gdy nie działa hypervisor | Zostawić włączone. Wyłączenie blokuje WSL2 i VBS | L: BIOS „SVM Mode” / „Intel Virtualization Technology” |
| **Lista zablokowanych sterowników** | ⚪ | ✅ rejestr `CI\Config` | Włączona. Blokuje m.in. stare sterowniki WinRing0 | L |
| **Antywirus** (Defender / inny) | 🟡 skanowanie w czasie zapisu shaderów może dawać przycięcia. Brak dobrych pomiarów | ✅ `SecurityCenter2`, `MSFT_MpComputerStatus` | Nigdy nie wyłączać. Ewentualnie wykluczyć **tylko folder gry** | L (Defender: B, wymaga administratora; inny AV: instrukcja) |
| **Smart App Control** | ⚪ | ✅ | Nie ruszać (wyłączenie może być nieodwracalne) | — |

### 4.3 Grafika i wyświetlanie

| Pozycja | Wpływ | Odczyt | Rekomendacja | Zmiana |
|---|---|---|---|---|
| **HAGS** | 🟡 FPS w granicach błędu, ale **wymagane przez DLSS Frame Generation** (BO7 ma DLSS 4 MFG) | ✅ | Włączone. Wyłączać tylko przy diagnozie przycięć | B (HKLM, restart) albo L |
| **Odświeżanie monitora = maksimum** | 🟢 oczywisty efekt | ✅ (już jest) | Maksimum | L |
| **HDR Windows włączony?** | 🟡 | ✅ `DisplayConfigGetDeviceInfo` | Spójność z ustawieniem HDR w grze | L |
| **Auto HDR** | ⚪/🟡 kosztuje „trochę mocy GPU”. CoD ma natywne HDR | ✅ `DirectXUserGlobalSettings` | Wyłączone (gra rankingowa) | **A** |
| **Optymalizacje gier w oknie** | ⚪ dla CoD (DX12 i tak używa flip model) | ✅ | Domyślne (włączone) | A |
| **VRR Windows** | ⚪ dla CoD (dotyczy gier DX11 bez natywnego VRR) | ✅ | Domyślne | A |
| **Preferencja GPU dla `cod.exe`** | 🟢 krytyczne na laptopach / PC z iGPU | ✅ `UserGpuPreferences` | „Wysoka wydajność”, gdy jest iGPU | **A** (tylko `GpuPreference=2;`, inne pary bez zmian) |
| **MPO** | 🟡 tylko na migotanie / czarne ekrany. Na 24H2+ klucz bywa ignorowany | ✅ `Dwm\OverlayTestMode` | Domyślne. Ostrzec, jeśli wyłączone tweakiem | B (przywrócenie = usunięcie wartości, restart) |
| **„Wyłącz optymalizacje pełnoekranowe”** dla `cod.exe` | ⚪ w DX12 | ✅ `AppCompatFlags\Layers` | Informacja „bez efektu” | A (usunięcie tylko tego jednego tokenu) |
| **Pamięć podręczna shaderów** | 🟡 czyszczenie = przycięcia przy pierwszych meczach | 🟡 rozmiar folderów | Nie czyścić bez potrzeby. W NVIDIA: „Domyślne sterownika” lub większe | L |
| **Ustawienia sterownika NVIDIA** (Low Latency, tryb zasilania, V-Sync) | 🟡 | ❌ brak publicznego API (NVAPI/DRS = osobny projekt) | Przepis Blur Busters: G-SYNC + V-Sync w sterowniku + Reflex w grze | L: instrukcja |

### 4.4 Tryb gry, Xbox, powiadomienia

| Pozycja | Wpływ | Odczyt | Rekomendacja | Zmiana |
|---|---|---|---|---|
| **Tryb gry** | 🟡 pomaga 1% low, gdy w tle coś działa. W kilku grach CPU-bound minimalnie gorzej | ✅ | Włączony (domyślnie) | **A** |
| **Nagrywanie w tle** („Nagrywaj, co się stało”) | 🟢 ok. 4–7% podczas nagrywania (stare testy Win10) | ✅ | Wyłączone | **A** |
| **Przechwytywanie Game DVR** (ogólnie) | 🟡 | ✅ | Wyłączone, jeśli nie nagrywasz Game Barem | A |
| **Xbox Game Bar zainstalowany** | 🟢 dla X3D z dwoma CCD (wykrywanie gry) | ✅ pakiet Appx | **Nie odinstalowywać** (wiele „debloaterów” go usuwa) | L |
| **„Nie przeszkadzać” automatycznie w grach** | 🟡 brak pomiarów, ale wyskakujące powiadomienia psują pełny ekran | 🟡 brak stabilnego klucza na 24H2+ | Włączone | L: `ms-settings:quietmomentsgame` |
| **Tryb Xbox** (pełnoekranowe doświadczenie, 2026) | ⚪ pomiary: mniej RAM, brak zysku FPS | ✅ | Informacja, bez obietnic | — |

### 4.5 Zasilanie i procesor

| Pozycja | Wpływ | Odczyt | Rekomendacja | Zmiana |
|---|---|---|---|---|
| **Plan zasilania** | 🟡 brak rzetelnych pomiarów na Win11 dla nowoczesnych CPU | ✅ GUID | **Zależnie od CPU:** dwa CCD X3D → **Zrównoważony** (obowiązkowo). Pozostałe: Zrównoważony + tryb „Najlepsza wydajność” albo Wysoka wydajność | **A** (`powercfg /setactive` działa bez administratora, uprawnienia sprawdzone, sam zapis jeszcze nie) |
| **Tryb zasilania** (nakładka Win11) | 🟡 | ✅ `PowerGetEffectiveOverlayScheme` | „Najlepsza wydajność”. Działa tylko przy planie zrównoważonym (UI musi to wyjaśnić) | A |
| **Minimalny stan procesora / parkowanie rdzeni** | ⚪/🟡 | ✅ `powercfg /qh` | **Nie wyłączać parkowania na X3D z dwoma CCD** (psuje sterowanie CCD). Pozostałe: domyślne | L (pokazać wartości niestandardowe) |
| **Łańcuch X3D z dwoma CCD**: sterownik chipsetu AMD + usługa 3D V-Cache + Game Bar + plan zrównoważony | 🟢 bez tego gra trafia na CCD bez V-Cache | 🟡 usługa i sterownik do zweryfikowania | Wszystko obecne | L |
| **Intel 13./14. gen.: mikrokod ≥ 0x12B** | 🟢 stabilność (degradacja Vmin) | ✅ rejestr `CentralProcessor\0\Update Revision` | Aktualizacja BIOS + profil „Intel Default Settings” | L |
| **Intel Core Ultra 200S: build ≥ 26100.2161 + BIOS** | 🟢 Intel: 6–30% przy brakującej poprawce | ✅ | Aktualny Windows + BIOS | L |
| **AMD Zen 3/4/5: Windows 24H2+** (branch prediction) | 🟢 ok. +10% średnio (HUB, 40 gier) | ✅ build | 24H2/25H2 | L |
| **Wiek BIOS** | 🟡 stary BIOS = stary AGESA, stary fTPM, brak certyfikatów 2023 | ✅ `Win32_BIOS` | Sugerować aktualizację, gdy BIOS ma ponad 12–18 miesięcy | L |

### 4.6 Aktualizacje i stabilność

| Pozycja | Odczyt | Rekomendacja |
|---|---|---|
| Wersja Windows (24H2/25H2, Windows 10 = koniec wsparcia) | ✅ | 25H2 nie jest szybszy od 24H2 (to ta sama gałąź), ale oba są OK |
| **Regresja KB5066835** (październik 2025, build ≥ .6899) + sterownik NVIDIA < 581.94 | ✅ | 🟢 DF: −33–50% FPS w niektórych grach → zaktualizuj sterownik |
| Oczekujący restart po aktualizacji | ✅ rejestr | Zrestartuj przed graniem |
| Plik stronicowania | ✅ `Win32_ComputerSystem.AutomaticManagedPagefile` | Zarządzany przez system. **Wyłączony lub mały = ostrzeżenie** (crashe CoD „memory error”) |
| Wolne miejsce na C: | ✅ | Bufor na plik stronicowania i cache shaderów |

### 4.7 Programy w tle

| Pozycja | Odczyt | Rekomendacja |
|---|---|---|
| **Nakładki działające naraz** (Steam, Discord, NVIDIA, RTSS, Overwolf, Medal, Xbox) | ✅ lista procesów (`psutil`) | Jedna nakładka. Każda podpina się pod renderowanie gry |
| **Limiter FPS w RTSS** przy Reflex | ✅ proces | Lepszy jest limit w grze lub Reflex (mniejsze opóźnienie) |
| **Narzędzia RGB / wentylatorów z WinRing0** (stare Afterburner, OpenRGB, FanCtrl, HWiNFO…) | 🟡 sterowniki w systemie | Defender oznacza WinRing0 jako HackTool, więc aktualizacja |
| **Programy przechwytujące wejście** (reWASD, Cronus/XIM) | ✅ proces / usługa | Ricochet je wykrywa: ostrzeżenie o ryzyku bana |
| Programy startowe | ✅ `Run` + `StartupApproved` | Lista z linkiem `ms-settings:startupapps` (bez zmian z programu) |

### 4.8 Mysz, sieć, dysk

| Pozycja | Wpływ | Odczyt | Rekomendacja | Zmiana |
|---|---|---|---|---|
| **Precyzja wskaźnika** (akceleracja) | ⚪ w grze (raw input), ale ma znaczenie w menu i na pulpicie | ✅ | Wyłączona (spójność ruchu) | **A** (`SystemParametersInfo`, działa od razu) |
| **Ethernet vs Wi-Fi** | 🟢 stabilność pingu | ✅ | Kabel | L |
| **TRIM** | 🟡 | ✅ `fsutil behavior query` | Włączony | L |
| Dysk z grą: NVMe/SATA/HDD | — | ✅ (już jest) | — | — |

### 4.9 Mity — osobna sekcja „Nie warto / szkodzi”

Pokazywać jako wiedzę i wykrywać, jeśli ktoś to już ustawił. Wtedy proponować **przywrócenie domyślnych**.

| Tweak | Dlaczego nie |
|---|---|
| HPET / `bcdedit useplatformclock`, `disabledynamictick` | Brak efektu albo większe opóźnienie. Jeśli ustawione, sugerować usunięcie |
| Programy do „timer resolution” | Od Win10 2004 rozdzielczość timera jest per proces, a od Win11 ukryte okna jej nie gwarantują. Gra ustawia ją sama |
| Nagle / `TcpNoDelay` / `TcpAckFrequency` | Dotyczą TCP. Rozgrywka CoD idzie po UDP |
| Wyłączanie parkowania rdzeni | Na Win11 brak pomiarów. Na X3D z dwoma CCD szkodzi |
| Wyłączanie SysMain, indeksowania, szybkiego uruchamiania | Brak pomiarów w grach (SysMain ma znaczenie tylko przy HDD lub małym RAM) |
| Wyłączanie pliku stronicowania | Crashe CoD „out of memory” |
| Uśpienie selektywne USB | Aktywna mysz się nie usypia. Twierdzenia o „2–5 ms” są niezmierzone |
| Wymuszony natywny sterownik NVMe (`nvmedisk.sys`) | Eksperyment: psuje Samsung Magician, może wywołać odzyskiwanie BitLockera, Microsoft go zablokował |
| „Ultimate Performance” jako magiczny plan | Brak pomiarów. Na X3D z dwoma CCD szkodzi |
| „Debloatery” usuwające Xbox Game Bar | Psują tryb gry i sterowanie X3D |
| Wyłączanie Defendera / Smart App Control | Ryzyko bezpieczeństwa bez zmierzonego zysku |

### 4.10 Lista kontrolna BIOS (ręczna, tylko instrukcje)

Ustawień BIOS nie da się odczytać z Windows bez sterownika jądra. Dlatego lista kontrolna, a przy
pozycjach, które jednak da się wykryć pośrednio, status:

- EXPO/XMP (✅ heurystyka już jest)
- Resizable BAR + Above 4G (✅ NVIDIA)
- CSM wyłączony i Secure Boot (✅)
- fTPM/PTT (✅)
- SVM/VT-x (✅, gdy nie działa hypervisor)
- PBO / Curve Optimizer, C-states, CPPC: ❌ niewykrywalne. Zalecenie: „Auto”, chyba że wiesz, co robisz
- Intel 13/14 gen.: profil „Intel Default Settings” (❌ niewykrywalne) + mikrokod (✅)

Do tego nazwy opcji dla Gigabyte, ASUS, MSI i ASRock (jak dziś przy EXPO).

---

## 5. Zmiany wykonywane przez program — zasady bezpieczeństwa

Trzy poziomy, od najbezpieczniejszego:

1. **Tylko informacja i link (L).** Domyślne dla wszystkiego, co dotyczy bezpieczeństwa, BIOS i AV.
2. **Zmiana bez administratora (A):** wartości HKCU i `powercfg` dla planu bieżącego użytkownika.
   - Przed zmianą: **kopia każdej wartości** (typ, dane lub „nie istniała”) w JSON w katalogu
     danych programu, jak dziś kopie plików gry.
   - Przycisk **„Przywróć”** dla pojedynczej zmiany i „Przywróć wszystko”.
   - Wartości wielokluczowe (`DirectXUserGlobalSettings`, `AppCompatFlags`) edytujemy tylko w
     obrębie jednego klucza i zachowujemy resztę napisu.
   - Wpis w historii programu (jak zapis pliku gry).
3. **Zmiana z UAC (B):** HKLM, funkcje Windows. Zwykle wymaga restartu.
   - Wykonuje ją ten sam program uruchomiony z parametrem `--elevated-action <id>`. Lista
     dozwolonych akcji jest zamknięta i bez dowolnych poleceń PowerShell. Program **nigdy** nie
     działa w całości jako administrator.
   - Przed zmianą: kopia jak wyżej. Opcjonalnie punkt przywracania systemu (to wymaga administratora
     i włączonej ochrony systemu; niepowodzenie = ostrzeżenie, nie blokada).
   - Na liście „Wymaga restartu” pokazujemy, co czeka na restart.
   - **Wyłączania HVCI/VBS, Defendera i Secure Boot nie robimy nigdy**, nawet na prośbę. Program
     daje tylko link do odpowiedniej strony Windows.

Reguły z `CLAUDE.md` (nie zapisujemy, gdy działa gra, wszystko przez kopie) stosujemy analogicznie:
zmian systemowych nie wykonujemy, gdy `cod.exe` działa.

Proponuję zacząć od **poziomów L + A**. Poziom B ma sens dopiero, gdy pierwsze dwa się sprawdzą.
Pozycji B jest niewiele (HAGS, MPO, funkcje VM) i Windows ma dla nich własne strony ustawień.

---

## 6. Interfejs — propozycja

- W oknie **„Sprzęt i system”** trzecia zakładka **„Windows”** (EN: *Windows*), także osobny
  przycisk / pozycja menu „Optymalizacja Windows”, który otwiera okno od razu na tej zakładce.
- Na górze **podsumowanie:** „Wymagania gry: spełnione ✓ · Do poprawy: 2 · Do decyzji: 3”.
- Sekcje jak w §4 (wymagania gry, zabezpieczenia, grafika, tryb gry, zasilanie, aktualizacje,
  programy w tle, mysz/sieć, mity, BIOS), zwijane. Każdy wiersz zawiera:
  - status (✓ / ⚠ / ℹ / –),
  - nazwę,
  - **obecną wartość** („Włączone”, „Wysoka wydajność”, „TPM 2.0, firmware 6.32”),
  - zalecaną wartość z krótkim „dlaczego”,
  - znaczek wpływu (🟢 zmierzony / 🟡 zależy / ⚪ mit),
  - przyciski: **„Zmień”** (poziom A), **„Otwórz ustawienia”** albo **„Instrukcja”** (L),
    **„Przywróć”**, jeśli program to zmienił.
- Filtr „Pokaż tylko do poprawy”.
- Przycisk „Odśwież” (ponowny odczyt w tle). Po zmianie odświeżamy tylko ten wiersz.
- Teksty w `i18n` (PL/EN), w tym samym układzie co `checks.*`, np. `win.<id>.title/now/why/fix`.

Architektura (zgodnie z obecną):
- `core/windows_info.py`: odczyt w tle, czyste parsery, bez Qt.
- `core/windows_checks.py`: ocena (dzisiejsze sprawdzenia windowsowe przechodzą tu z `system_checks.py`).
- `core/windows_tweaks.py`: zmiany poziomu A z kopią i przywracaniem. Testy na fałszywym rejestrze
  (wstrzykiwany interfejs), więc **żaden test nie dotyka prawdziwego rejestru**.
- `ui/windows_panel.py`.

---

## 7. Plan etapów (do akceptacji)

| Etap | Zakres | Nakład | Zmienia system? |
|---|---|---|---|
| **10a** | Odczyt: Secure Boot, UEFI, GPT, TPM (wersja + firmware), certyfikaty 2023, UAC, hypervisor, funkcje VM, SVM, AV, Auto HDR, preferencja GPU, MPO, FSO, tryb zasilania, parametry planu, plik stronicowania, oczekujący restart, procesy w tle, mikrokod, łącze sieciowe. Parsery + testy na fixturach | średni | nie |
| **10b** | Ocena: `windows_checks.py` z regułami zależnymi od CPU (X3D z 1 lub 2 CCD, Intel 13/14, Arrow Lake), kompatybilność z Ricochet, sekcja mitów. **Poprawka obecnego sprawdzenia planu zasilania dla X3D z dwoma CCD** | średni | nie |
| **10c** | Zakładka „Windows” w oknie „Sprzęt i system”: sekcje, wartości obecne i zalecane, linki `ms-settings:` / instrukcje BIOS, filtr, PL/EN, testy GUI | średni | nie |
| **10d** | Zmiany poziomu A z kopią i przywracaniem (tryb gry, Game DVR, Auto HDR, preferencja GPU `cod.exe`, precyzja wskaźnika, plan i tryb zasilania, usunięcie tokenu FSO) + wpisy w historii. **Test w praktyce na Twoim PC** (za Twoją zgodą) | średni | tak, HKCU |
| 10e (opcjonalnie) | Poziom B przez UAC: HAGS, przywrócenie MPO, wyłączenie nieużywanych funkcji VM | średni | tak, HKLM + restart |
| później | Ustawienia sterownika NVIDIA przez NVAPI/DRS (Low Latency, shader cache) | duży | — |

Etapy 10a–10c są **tylko do odczytu**, więc mogą wyjść jako wersja 1.3.0. Etap 10d to wersja 1.4.0,
po teście u Ciebie.

---

## 8. Ryzyka i otwarte pytania

- **Nieudokumentowane klucze rejestru** (tryb gry, Game DVR, `DirectXUserGlobalSettings`,
  `TPM\WMI`) mogą zmienić się w kolejnej wersji Windows. Odczyt musi mieć stan „nieznane”, a zapis
  musi sprawdzać, czy klucz ma oczekiwany format.
- **Ricochet zmienia wymagania co sezon.** Teksty powinny mówić, skąd informacja i z kiedy, i kierować
  do Secure Attestation Wizard.
- **Odpowiedzialność za porady dotyczące bezpieczeństwa:** VBS/HVCI zawsze jako „kompromis”, z
  linkiem, bez przycisku „wyłącz”.
- **Antywirus:** program zmieniający rejestr może zostać uznany za podejrzany (heurystyki AV,
  SmartScreen). Poziom A to zwykłe wartości HKCU, więc ryzyko jest niskie. Poziom B (UAC)
  zwiększa to ryzyko.
- **Do zweryfikowania przed 10a:**
  - odczyt GPT bez administratora,
  - nazwa usługi AMD 3D V-Cache,
  - czy zapis planu i trybu zasilania działa bez administratora (uprawnienia na to wskazują),
  - czy MPO (`OverlayTestMode`) jest jeszcze honorowane na 25H2.

---

## 9. Źródła

**Wymagania gry / Ricochet**
- Activision — TPM i Secure Boot: https://support.activision.com/articles/trusted-platform-module-and-secure-boot
- Ricochet, beta BO7: https://www.callofduty.com/blog/2025/09/call-of-duty-black-ops-7-beta-ricochet-anti-cheat-update
- Ricochet, sezon 4: https://www.callofduty.com/blog/2026/06/call-of-duty-black-ops-7-warzone-ricochet-anti-cheat-season-04
- TechPowerUp — BO7 i BF6 wymagają Secure Boot + TPM: https://www.techpowerup.com/339706/call-of-duty-black-ops-7-and-battlefield-6-confirmed-to-require-secure-boot-and-tpm-2-0
- Porty CoD (UDP): https://support.activision.com/articles/ports-used-for-call-of-duty-games

**VBS / HVCI**
- ComputerBase: https://www.computerbase.de/2023-03/windows-11-vbs-hvci-spiele-benchmarks/
- Tom's Hardware: https://www.tomshardware.com/news/windows-11-gaming-benchmarks-performance-vbs-hvci-security
- PCGH: https://www.pcgameshardware.de/Windows-Software-277633/News/Win11-VBS-kostet-bis-zu-10-Prozent-Leistung-bei-RTX-4090-1415466/
- Microsoft — HVCI: https://learn.microsoft.com/en-us/windows/security/hardware-security/enable-virtualization-based-protection-of-code-integrity
- Lista zablokowanych sterowników: https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/design/microsoft-recommended-driver-block-rules

**Poprawki CPU i regresje Windows**
- AMD branch prediction (PCGH): https://www.pcgameshardware.de/Ryzen-9-9950X-CPU-280539/News/KB5041587-als-Soforthilfe-gegen-Leistungsprobleme-1454581/
- Intel 0x12B: https://www.theregister.com/2024/09/26/intel_0x12b_raptor_lake/
- Regresja KB5066835 i poprawka NVIDIA: https://www.neowin.net/news/nvidia-blames-microsofts-windows-11-kb5066835-for-performance-issues-hotfix-driver-out/
- 25H2 vs 24H2: https://www.guru3d.com/story/windows-11-25h2-benchmarks-show-no-performance-gains-over-24h2
- Ryzen X3D z dwoma CCD (recenzja 9950X3D): https://www.notebookcheck.net/AMD-Ryzen-9-9950X3D-Review-Ryzen-7-9800X3D-levels-of-gaming-performance-and-power-efficiency-for-50-markup-over-the-Ryzen-9-9950X.976049.0.html

**HAGS, tryb gry, nagrywanie**
- GamersNexus — HAGS: https://gamersnexus.net/guides/3599-windows-10-hardware-accelerated-gpu-scheduling-benchmarks
- PCGH — HAGS: https://www.pcgameshardware.de/Windows-Software-277633/Specials/HAGS-Benchmark-Test-1352947/
- Xbox — Game DVR: https://news.xbox.com/en-us/2016/10/14/tips-on-windows-10-and-game-dvr-optimization

**Wyświetlanie i opóźnienia**
- Microsoft — gry w oknie: https://support.microsoft.com/en-us/topic/3f006843-2c7e-4ed0-9a5e-f9389e535952
- Microsoft — optymalizacje pełnoekranowe: https://devblogs.microsoft.com/directx/demystifying-full-screen-optimizations/
- NVIDIA — MPO: https://nvidia.custhelp.com/app/answers/detail/a_id/5157
- Blur Busters — G-SYNC: https://www.blurbusters.com/gsync/gsync101-input-lag-tests-and-settings/14/
- Microsoft — `timeBeginPeriod`: https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod

**Secure Boot i TPM**
- Certyfikaty Secure Boot 2026: https://directaccess.richardhicks.com/2025/12/04/windows-secure-boot-uefi-certificates-expiring-june-2026/
- AMD fTPM (AGESA): https://www.guru3d.com/story/amd-agesa-v2-1-2-7-microcode-to-fix-ftpm-stutters/

**Programy w tle i Linux**
- WinRing0: https://www.pcworld.com/article/2912435/if-windows-defender-flags-winring0-on-your-gaming-pc-pay-attention.html
- Ricochet na Linuksie: https://www.gamingonlinux.com/anticheat/vendor/ricochet-anti-cheat

**Interfejsy Windows**
- Adresy `ms-settings:`: https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings-app
- `SystemParametersInfo`: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-systemparametersinfow
- `GetFirmwareType`: https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfirmwaretype
