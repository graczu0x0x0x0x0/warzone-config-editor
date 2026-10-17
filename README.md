# Warzone Config Editor

Graficzny edytor plików ustawień **Call of Duty: Black Ops 7 / Warzone** (PC)
· Graphical editor for **Call of Duty: Black Ops 7 / Warzone** PC settings files.

> Status: MVP z interfejsem graficznym · GUI MVP.

## Uruchomienie · Running

```
uv sync
uv run wzce
```

Wymaga [uv](https://docs.astral.sh/uv/) i Windows. Zamknij grę przed zapisem — program sam to sprawdza.
Requires uv and Windows. Close the game before saving — the editor checks it.

- [Raport z researchu i propozycje](docs/RAPORT.md) (PL)
- [Plan realizacji](docs/PLAN.md) (PL)
- [File format spec](docs/FILE_FORMAT.md) (EN)

Pliki gry · Game files: `%LOCALAPPDATA%\Activision\Call of Duty\players\s.1.0.cod25.txt0` / `.txt1`

Narzędzie nie modyfikuje gry ani jej procesu — zmienia wyłącznie tekstowe pliki ustawień,
zawsze z kopią zapasową. Nie jest powiązane z Activision.
